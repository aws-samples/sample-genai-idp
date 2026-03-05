# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
End-to-end tests for multi-use-case document handling.

These tests exercise the full multi-use-case lifecycle:
1. Use case registration via ConfigurationManager (same path as UpdateConfiguration Lambda)
2. Per-use-case config storage and 5-layer merge
3. Document routing based on S3 key prefix (bu/uc/filename)
4. Config resolution in processresults handler context
5. CloudFormation UseCaseConfigs parameter processing logic
6. Backward compatibility: no use cases = existing single-config behavior

Uses moto for DynamoDB mocking to test realistic AWS interactions.
"""

import json

import boto3
import pytest
from idp_common.config import get_config
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.constants import (
    CONFIG_TYPE_CUSTOM,
    CONFIG_TYPE_DEFAULT,
    DEFAULT_BUSINESS_UNIT_ID,
    DEFAULT_USE_CASE_ID,
)
from idp_common.config.models import IDPConfig
from idp_common.models import Document
from moto import mock_aws

TABLE_NAME = "test-multi-uc-config"


# ===== Fixtures =====


@pytest.fixture
def config_table():
    """Create a mocked DynamoDB configuration table with global defaults seeded."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "Configuration", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "Configuration", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Seed global default config via ConfigurationManager (the real write path)
        # so the DynamoDB item matches what production code expects (Config#default).
        global_config = IDPConfig(
            notes="Global default config",
            extraction={"temperature": 0.0, "model": "us.amazon.nova-2-lite-v1:0"},
            classification={"model": "us.amazon.nova-2-lite-v1:0"},
            assessment={
                "default_confidence_threshold": 0.85,
                "hitl_enabled": False,
            },
        )
        mgr = ConfigurationManager(table_name=TABLE_NAME)
        mgr.save_configuration("Config", global_config, version="default")

        yield table


@pytest.fixture
def manager(config_table):
    """Create a ConfigurationManager backed by the mocked table."""
    return ConfigurationManager(table_name=TABLE_NAME)


# ===== Test: Full multi-use-case lifecycle =====


@pytest.mark.unit
class TestMultiUseCaseLifecycle:
    """Test the complete lifecycle of registering, configuring, and routing use cases."""

    def test_register_multiple_use_cases(self, manager):
        """Register two use cases and verify they appear in the registry."""
        manager.register_use_case(
            "retail-banking",
            "mortgage-processing",
            "Mortgage Processing",
            "Handles mortgage document packages",
        )
        manager.register_use_case(
            "insurance",
            "claims-processing",
            "Claims Processing",
            "Processes insurance claims",
        )

        use_cases = manager.list_use_cases()
        assert len(use_cases) == 2
        bu_uc_pairs = {(uc["businessUnitId"], uc["useCaseId"]) for uc in use_cases}
        assert ("retail-banking", "mortgage-processing") in bu_uc_pairs
        assert ("insurance", "claims-processing") in bu_uc_pairs

    def test_save_and_retrieve_use_case_config(self, manager):
        """Save per-use-case config and verify it's retrievable."""
        manager.register_use_case("retail-banking", "mortgage-processing", "Mortgage")

        uc_config = {
            "extraction": {"temperature": 0.0, "top_p": 0.0},
            "assessment": {
                "default_confidence_threshold": 0.95,
                "hitl_enabled": True,
            },
        }
        manager.save_use_case_configuration(
            "retail-banking", "mortgage-processing", CONFIG_TYPE_DEFAULT, uc_config
        )

        retrieved = manager.get_use_case_configuration(
            "retail-banking", "mortgage-processing"
        )
        assert retrieved is not None
        assert retrieved.assessment.default_confidence_threshold == 0.95
        assert retrieved.assessment.hitl_enabled is True

    def test_five_layer_merge(self, manager, monkeypatch):
        """Test the 5-layer config merge: Global Default → UC Default → UC Custom."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Register use case with Default config
        manager.register_use_case("bu1", "uc1", "Use Case 1")
        manager.save_use_case_configuration(
            "bu1",
            "uc1",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.5}},
        )

        # Add UC Custom override on top
        manager.save_use_case_configuration(
            "bu1",
            "uc1",
            CONFIG_TYPE_CUSTOM,
            {"assessment": {"hitl_enabled": True}},
        )

        config = get_config(as_model=True, business_unit_id="bu1", use_case_id="uc1")

        # UC Custom overrides assessment
        assert config.assessment.hitl_enabled is True
        # UC Default overrides extraction temperature
        assert config.extraction.temperature == 0.5
        # Global default model is inherited
        assert config.extraction.model == "us.amazon.nova-2-lite-v1:0"

    def test_global_config_unchanged_when_use_cases_exist(self, manager, monkeypatch):
        """Adding use cases should not affect the global default config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Get global config before registering use cases
        global_before = get_config(
            as_model=True, business_unit_id=None, use_case_id=None
        )

        # Register a use case with different settings
        manager.register_use_case("bu1", "uc1", "Use Case 1")
        manager.save_use_case_configuration(
            "bu1",
            "uc1",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.9}},
        )

        # Global config should be unchanged
        global_after = get_config(
            as_model=True, business_unit_id=None, use_case_id=None
        )
        assert (
            global_after.extraction.temperature == global_before.extraction.temperature
        )
        assert (
            global_after.assessment.default_confidence_threshold
            == global_before.assessment.default_confidence_threshold
        )


# ===== Test: Document routing via S3 key prefix =====


@pytest.mark.unit
class TestDocumentRoutingFromS3Key:
    """Test that documents uploaded with bu/uc/ prefix are routed to the correct config."""

    def _make_s3_event(self, key):
        """Create a minimal S3 EventBridge event for testing.

        Document.from_s3_event expects EventBridge format (detail.bucket/object),
        not the S3 notification format (Records[].s3).
        """
        return {
            "detail": {
                "bucket": {"name": "test-input-bucket"},
                "object": {"key": key},
            },
            "time": "2026-01-01T00:00:00Z",
        }

    def test_document_from_bu_uc_key(self):
        """S3 key with bu/uc/filename sets business_unit_id and use_case_id."""
        doc = Document.from_s3_event(
            self._make_s3_event("retail-banking/mortgage-processing/loan-app.pdf"),
            output_bucket="test-output-bucket",
        )
        assert doc.business_unit_id == "retail-banking"
        assert doc.use_case_id == "mortgage-processing"

    def test_document_from_plain_key(self):
        """S3 key without bu/uc prefix has None for business_unit_id and use_case_id."""
        doc = Document.from_s3_event(
            self._make_s3_event("invoice.pdf"),
            output_bucket="test-output-bucket",
        )
        assert doc.business_unit_id is None
        assert doc.use_case_id is None

    def test_document_from_single_prefix_key(self):
        """S3 key with only one prefix level (not bu/uc) has None for both.

        from_s3_event requires at least 3 path segments ({bu}/{uc}/{filename})
        to extract routing info.  With only 2 segments the key is treated as
        non-routed, so both identifiers must be None.
        """
        doc = Document.from_s3_event(
            self._make_s3_event("some-folder/invoice.pdf"),
            output_bucket="test-output-bucket",
        )
        assert doc is not None
        assert doc.business_unit_id is None
        assert doc.use_case_id is None

    def test_document_routing_to_config(self, manager, monkeypatch):
        """Full flow: S3 event → Document → config lookup with correct BU/UC."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Register use case with specific config
        manager.register_use_case("retail-banking", "mortgage-processing", "Mortgage")
        manager.save_use_case_configuration(
            "retail-banking",
            "mortgage-processing",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.2}},
        )

        # Parse document from S3 event
        event = self._make_s3_event(
            "retail-banking/mortgage-processing/bank-statement.pdf"
        )
        doc = Document.from_s3_event(event, output_bucket="test-output-bucket")

        # Get config using document's BU/UC
        config = get_config(
            as_model=True,
            business_unit_id=doc.business_unit_id,
            use_case_id=doc.use_case_id,
        )
        assert config.extraction.temperature == 0.2

    def test_unregistered_bu_uc_falls_back_to_global(self, manager, monkeypatch):
        """Documents with unregistered bu/uc should get global default config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        event = self._make_s3_event("unknown-bu/unknown-uc/document.pdf")
        doc = Document.from_s3_event(event, output_bucket="test-output-bucket")

        config = get_config(
            as_model=True,
            business_unit_id=doc.business_unit_id,
            use_case_id=doc.use_case_id,
        )
        # Should get global default (temperature=0.0 from fixture)
        assert config.extraction.temperature == 0.0


# ===== Test: UseCaseConfigs CloudFormation parameter processing =====


@pytest.mark.unit
class TestUseCaseConfigsCfnProcessing:
    """Test the UseCaseConfigs processing logic used by the UpdateConfiguration Lambda.

    This replicates the validation and persistence logic from
    src/lambda/update_configuration/index.py without importing the Lambda handler.
    """

    def _process_use_case_configs(self, manager, use_case_configs_json):
        """Replicate the UseCaseConfigs processing from UpdateConfiguration Lambda."""
        if isinstance(use_case_configs_json, str):
            use_case_configs = json.loads(use_case_configs_json)
        else:
            use_case_configs = use_case_configs_json

        if not isinstance(use_case_configs, list):
            raise ValueError("UseCaseConfigs must be a JSON array of objects")

        errors = []
        for entry in use_case_configs:
            try:
                # Use shared validation from ConfigurationManager
                bu_id, uc_id = ConfigurationManager.validate_use_case_config_entry(
                    entry
                )

                uc_name = entry.get("name", f"{bu_id}/{uc_id}")
                uc_desc = entry.get("description", "")
                uc_config = entry.get("config", {})

                if not isinstance(uc_config, dict):
                    raise ValueError(f"Config for {bu_id}/{uc_id} must be a dict")

                # Persist
                manager.save_use_case_configuration(
                    bu_id, uc_id, CONFIG_TYPE_DEFAULT, uc_config
                )
                manager.register_use_case(bu_id, uc_id, uc_name, uc_desc)

            except Exception as e:
                errors.append(str(e))

        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

    def test_process_valid_use_case_configs(self, manager):
        """Valid UseCaseConfigs JSON is processed and persisted correctly."""
        configs = [
            {
                "businessUnitId": "retail",
                "useCaseId": "mortgage",
                "name": "Mortgage",
                "config": {"extraction": {"temperature": 0.3}},
            },
            {
                "businessUnitId": "insurance",
                "useCaseId": "claims",
                "name": "Claims",
                "config": {"assessment": {"hitl_enabled": True}},
            },
        ]

        self._process_use_case_configs(manager, json.dumps(configs))

        use_cases = manager.list_use_cases()
        assert len(use_cases) == 2

        # Verify configs were saved
        mortgage_config = manager.get_use_case_configuration("retail", "mortgage")
        assert mortgage_config is not None
        assert mortgage_config.extraction.temperature == 0.3

    def test_process_use_case_configs_from_json_string(self, manager):
        """UseCaseConfigs can be passed as a JSON string (CloudFormation parameter)."""
        configs_str = json.dumps(
            [
                {
                    "businessUnitId": "bu1",
                    "useCaseId": "uc1",
                    "config": {"extraction": {"temperature": 0.7}},
                }
            ]
        )

        self._process_use_case_configs(manager, configs_str)

        use_cases = manager.list_use_cases()
        assert len(use_cases) == 1
        assert use_cases[0]["businessUnitId"] == "bu1"

    def test_reject_missing_required_fields(self, manager):
        """Entries missing businessUnitId or useCaseId are rejected."""
        configs = [{"name": "Missing IDs"}]

        with pytest.raises(
            ValueError, match="Validation failed.*missing required keys"
        ):
            self._process_use_case_configs(manager, configs)

    def test_reject_reserved_default_id(self, manager):
        """Entries using 'DEFAULT' as an ID are rejected."""
        configs = [{"businessUnitId": "DEFAULT", "useCaseId": "uc1"}]

        with pytest.raises(ValueError, match="reserved"):
            self._process_use_case_configs(manager, configs)

    def test_reject_hash_in_id(self, manager):
        """Entries with '#' in IDs are rejected (used as DynamoDB key separator)."""
        configs = [{"businessUnitId": "bu#1", "useCaseId": "uc1"}]

        with pytest.raises(ValueError, match="#"):
            self._process_use_case_configs(manager, configs)

    def test_reject_slash_in_id(self, manager):
        """Entries with '/' in IDs are rejected (used as S3 key separator)."""
        configs = [{"businessUnitId": "bu/1", "useCaseId": "uc1"}]

        with pytest.raises(ValueError, match="/"):
            self._process_use_case_configs(manager, configs)

    def test_empty_config_is_valid(self, manager):
        """Entries with no config override are valid (inherit global defaults)."""
        configs = [{"businessUnitId": "bu1", "useCaseId": "uc1"}]

        self._process_use_case_configs(manager, configs)

        use_cases = manager.list_use_cases()
        assert len(use_cases) == 1

    def test_process_sample_use_cases_json(self, manager, monkeypatch):
        """Process the actual use_cases.json from config_library and verify routing."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Load the sample use_cases.json
        from pathlib import Path

        sample_path = (
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "config_library"
            / "pattern-2"
            / "multi-use-case-sample"
            / "use_cases.json"
        )

        if not sample_path.exists():
            pytest.skip("use_cases.json sample not found")

        with open(sample_path, encoding="utf-8") as f:
            configs = json.load(f)

        self._process_use_case_configs(manager, configs)

        use_cases = manager.list_use_cases()
        assert len(use_cases) == 2

        # Verify mortgage use case has higher confidence threshold
        mortgage_config = get_config(
            as_model=True,
            business_unit_id="retail-banking",
            use_case_id="mortgage-processing",
        )
        assert mortgage_config.assessment.default_confidence_threshold == 0.95
        assert mortgage_config.assessment.hitl_enabled is True

        # Verify claims use case has lower confidence threshold
        claims_config = get_config(
            as_model=True,
            business_unit_id="insurance",
            use_case_id="claims-processing",
        )
        assert claims_config.assessment.default_confidence_threshold == 0.8
        assert claims_config.assessment.hitl_enabled is False

        # Verify global default is unaffected
        global_config = get_config(
            as_model=True, business_unit_id=None, use_case_id=None
        )
        assert global_config.assessment.default_confidence_threshold == 0.85


# ===== Test: Handler-level use_case_context → config resolution =====


@pytest.mark.unit
class TestHandlerUseCaseContextFlow:
    """Test the full handler flow: event → extract context → resolve BU/UC → get_config.

    This simulates what happens in Pattern-1 and Pattern-2 processresults handlers
    when they receive an event with use_case_context.
    """

    def _simulate_handler_config_lookup(self, event, document, monkeypatch):
        """Simulate the config lookup logic from processresults handlers."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Extract use_case_context (Pattern-2 style)
        use_case_context = event.get("use_case_context")
        if not isinstance(use_case_context, dict):
            use_case_context = {}

        # Resolve BU/UC with document fallback
        bu = use_case_context.get("business_unit_id") or document.business_unit_id
        uc = use_case_context.get("use_case_id") or document.use_case_id

        return get_config(as_model=True, business_unit_id=bu, use_case_id=uc)

    def test_event_context_routes_to_use_case_config(self, manager, monkeypatch):
        """Event with use_case_context routes to the correct use-case config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        manager.register_use_case("retail", "mortgage", "Mortgage")
        manager.save_use_case_configuration(
            "retail",
            "mortgage",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.3}},
        )

        event = {
            "use_case_context": {
                "business_unit_id": "retail",
                "use_case_id": "mortgage",
            },
            "document": {"id": "doc-1"},
        }
        doc = Document(id="doc-1")

        config = self._simulate_handler_config_lookup(event, doc, monkeypatch)
        assert config.extraction.temperature == 0.3

    def test_document_fallback_when_no_event_context(self, manager, monkeypatch):
        """When event has no use_case_context, falls back to document BU/UC."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        manager.register_use_case("insurance", "claims", "Claims")
        manager.save_use_case_configuration(
            "insurance",
            "claims",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.7}},
        )

        event = {"document": {"id": "doc-1"}}  # No use_case_context
        doc = Document(id="doc-1", business_unit_id="insurance", use_case_id="claims")

        config = self._simulate_handler_config_lookup(event, doc, monkeypatch)
        assert config.extraction.temperature == 0.7

    def test_no_context_no_document_bu_uc_uses_global(self, manager, monkeypatch):
        """When neither event nor document has BU/UC, uses global config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        event = {"document": {"id": "doc-1"}}
        doc = Document(id="doc-1")

        config = self._simulate_handler_config_lookup(event, doc, monkeypatch)
        # Should get global default (temperature=0.0 from fixture)
        assert config.extraction.temperature == 0.0
        assert config.assessment.default_confidence_threshold == 0.85

    def test_different_use_cases_get_different_configs(self, manager, monkeypatch):
        """Two documents with different use cases get different configs."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Set up two use cases with different settings
        manager.register_use_case("bu1", "uc1", "UC 1")
        manager.save_use_case_configuration(
            "bu1", "uc1", CONFIG_TYPE_DEFAULT, {"extraction": {"temperature": 0.1}}
        )
        manager.register_use_case("bu2", "uc2", "UC 2")
        manager.save_use_case_configuration(
            "bu2", "uc2", CONFIG_TYPE_DEFAULT, {"extraction": {"temperature": 0.9}}
        )

        event1 = {"use_case_context": {"business_unit_id": "bu1", "use_case_id": "uc1"}}
        event2 = {"use_case_context": {"business_unit_id": "bu2", "use_case_id": "uc2"}}
        doc = Document(id="doc-1")

        config1 = self._simulate_handler_config_lookup(event1, doc, monkeypatch)
        config2 = self._simulate_handler_config_lookup(event2, doc, monkeypatch)

        assert config1.extraction.temperature == 0.1
        assert config2.extraction.temperature == 0.9


# ===== Test: Backward compatibility =====


@pytest.mark.unit
class TestBackwardCompatibility:
    """Verify that existing single-config behavior is preserved when no use cases exist."""

    def test_no_use_cases_registered_returns_global(self, manager, monkeypatch):
        """When no use cases are registered, get_config returns global default."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        config = get_config(as_model=True, business_unit_id=None, use_case_id=None)
        assert config.extraction.temperature == 0.0
        assert config.assessment.default_confidence_threshold == 0.85

    def test_empty_use_case_registry(self, manager):
        """list_use_cases returns empty list when no use cases registered."""
        use_cases = manager.list_use_cases()
        assert use_cases == []

    def test_default_bu_uc_returns_global_config(self, manager, monkeypatch):
        """Using DEFAULT_BUSINESS_UNIT_ID and DEFAULT_USE_CASE_ID returns global config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        config = get_config(
            as_model=True,
            business_unit_id=DEFAULT_BUSINESS_UNIT_ID,
            use_case_id=DEFAULT_USE_CASE_ID,
        )
        assert config.extraction.temperature == 0.0

    def test_plain_s3_key_document_uses_global(self, manager, monkeypatch):
        """Document from plain S3 key (no bu/uc prefix) uses global config."""
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", TABLE_NAME)

        # Register a use case to ensure it doesn't interfere
        manager.register_use_case("bu1", "uc1", "UC 1")
        manager.save_use_case_configuration(
            "bu1", "uc1", CONFIG_TYPE_DEFAULT, {"extraction": {"temperature": 0.9}}
        )

        # Document without BU/UC
        doc = Document(id="doc-1")
        config = get_config(
            as_model=True,
            business_unit_id=doc.business_unit_id,
            use_case_id=doc.use_case_id,
        )
        assert config.extraction.temperature == 0.0  # Global default
