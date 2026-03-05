# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for use-case-context handling in processresults Lambda handlers.

These tests verify the use_case_context extraction and get_config routing
logic introduced by the multi-use-case feature in both Pattern-1 and Pattern-2
processresults handlers, without requiring the full Lambda runtime.

Covers:
- Pattern-1: use_case_context extraction from single and list events
- Pattern-1: event_for_uc bug fix (passes correct event to handle_skip_bda)
- Pattern-2: use_case_context type validation and fallback
- Pattern-2: fallback to document-level BU/UC when use_case_context is empty
- Both: backward compatibility when use_case_context is absent
"""

import boto3
import pytest
from idp_common.config import get_config
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.constants import CONFIG_TYPE_DEFAULT
from idp_common.config.models import IDPConfig
from idp_common.models import Document
from moto import mock_aws

# ===== Helpers =====


def _create_config_table(table_name="test-config-table"):
    """Create a mocked DynamoDB configuration table."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "Configuration", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "Configuration", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return table


def _seed_global_default(table, config_dict=None):
    """Seed a Global Default configuration via ConfigurationManager.

    Uses save_configuration (the real write path) so the DynamoDB item
    matches what production code expects (Config#default key format).
    """
    config = IDPConfig(**(config_dict or {}))
    mgr = ConfigurationManager(table_name=table.table_name)
    mgr.save_configuration("Config", config, version="default")
    return config


# ===== Pattern-1: use_case_context extraction logic =====


@pytest.mark.unit
class TestPattern1UseCaseContextExtraction:
    """Test the use_case_context extraction logic from Pattern-1 handler.

    Pattern-1 handler extracts use_case_context from the event (which may
    be a list or dict), then calls get_config with the BU/UC values.
    """

    def _extract_use_case_context(self, event):
        """Replicate the use_case_context extraction logic from Pattern-1 handler."""
        if isinstance(event, list) and not event:
            raise ValueError("No BDA responses provided")
        event_for_uc = event[0] if isinstance(event, list) else event
        uc = (
            event_for_uc.get("use_case_context")
            if isinstance(event_for_uc, dict)
            else None
        )
        if not isinstance(uc, dict):
            uc = {}
        return event_for_uc, uc

    def test_dict_event_with_use_case_context(self):
        event = {
            "use_case_context": {
                "business_unit_id": "retail",
                "use_case_id": "mortgage",
            },
            "output_bucket": "test-bucket",
        }
        event_for_uc, uc = self._extract_use_case_context(event)
        assert uc["business_unit_id"] == "retail"
        assert uc["use_case_id"] == "mortgage"
        assert event_for_uc is event

    def test_dict_event_without_use_case_context(self):
        event = {"output_bucket": "test-bucket"}
        event_for_uc, uc = self._extract_use_case_context(event)
        assert uc == {}
        assert event_for_uc is event

    def test_list_event_extracts_from_first_element(self):
        event = [
            {"use_case_context": {"business_unit_id": "bu1", "use_case_id": "uc1"}},
            {"use_case_context": {"business_unit_id": "bu2", "use_case_id": "uc2"}},
        ]
        event_for_uc, uc = self._extract_use_case_context(event)
        assert uc["business_unit_id"] == "bu1"
        assert uc["use_case_id"] == "uc1"
        assert event_for_uc is event[0]

    def test_list_event_without_use_case_context(self):
        event = [{"output_bucket": "test-bucket"}]
        event_for_uc, uc = self._extract_use_case_context(event)
        assert uc == {}

    def test_empty_list_raises_error(self):
        with pytest.raises(ValueError, match="No BDA responses provided"):
            self._extract_use_case_context([])

    def test_non_dict_use_case_context_falls_back_to_empty(self):
        """When use_case_context is a string or other non-dict, should fall back to {}."""
        event = {"use_case_context": "invalid-string"}
        _, uc = self._extract_use_case_context(event)
        assert uc == {}

    def test_none_use_case_context_falls_back_to_empty(self):
        event = {"use_case_context": None}
        _, uc = self._extract_use_case_context(event)
        assert uc == {}


@pytest.mark.unit
class TestPattern1SkipBdaBugFix:
    """Test the event_for_uc bug fix in Pattern-1 handler.

    The PR fixes a bug where `handle_skip_bda(event, config)` was called
    with the full event (which could be a list), instead of `event_for_uc`
    (which is always a dict).
    """

    def test_skip_bda_receives_dict_not_list(self):
        """Verify event_for_uc (dict) is passed to skip_bda, not event (list)."""
        event = [
            {"skip_bda": True, "document": {"id": "test"}, "output_bucket": "out"},
            {"skip_bda": False},
        ]
        # Replicate the fixed logic
        event_for_uc = event[0] if isinstance(event, list) else event
        skip_bda = (
            event_for_uc.get("skip_bda") if isinstance(event_for_uc, dict) else False
        )

        assert skip_bda is True
        assert isinstance(event_for_uc, dict)
        # The fix: handle_skip_bda receives event_for_uc (dict), not event (list)
        assert event_for_uc.get("document") == {"id": "test"}

    def test_skip_bda_single_event(self):
        """Single dict event should also work correctly."""
        event = {"skip_bda": True, "document": {"id": "test"}}
        event_for_uc = event[0] if isinstance(event, list) else event
        skip_bda = event_for_uc.get("skip_bda")
        assert skip_bda is True
        assert event_for_uc is event


# ===== Pattern-2: use_case_context validation and fallback =====


@pytest.mark.unit
class TestPattern2UseCaseContextValidation:
    """Test the improved use_case_context validation in Pattern-2 handler.

    Pattern-2 handler validates that use_case_context is a dict, logs a
    warning for non-dict values, and falls back to an empty dict.
    """

    def _validate_use_case_context(self, event):
        """Replicate the use_case_context validation logic from Pattern-2 handler."""
        use_case_context = event.get("use_case_context")
        if not isinstance(use_case_context, dict):
            if use_case_context is not None:
                # In the real handler, this logs a warning
                pass
            use_case_context = {}
        return use_case_context

    def test_valid_dict_context(self):
        event = {"use_case_context": {"business_unit_id": "bu", "use_case_id": "uc"}}
        ctx = self._validate_use_case_context(event)
        assert ctx == {"business_unit_id": "bu", "use_case_id": "uc"}

    def test_missing_context_returns_empty_dict(self):
        event = {}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}

    def test_none_context_returns_empty_dict(self):
        event = {"use_case_context": None}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}

    def test_string_context_returns_empty_dict(self):
        event = {"use_case_context": "some-string"}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}

    def test_list_context_returns_empty_dict(self):
        event = {"use_case_context": ["bu", "uc"]}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}

    def test_integer_context_returns_empty_dict(self):
        event = {"use_case_context": 42}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}

    def test_empty_dict_context_is_valid(self):
        event = {"use_case_context": {}}
        ctx = self._validate_use_case_context(event)
        assert ctx == {}


@pytest.mark.unit
class TestPattern2DocumentFallback:
    """Test Pattern-2's fallback to document-level BU/UC.

    When use_case_context is empty but the document was parsed from a
    bu/uc/ S3 key, Pattern-2 falls back to document.business_unit_id
    and document.use_case_id.
    """

    def _resolve_bu_uc(self, use_case_context, document):
        """Replicate the BU/UC resolution logic from Pattern-2 handler."""
        resolved_bu = (
            use_case_context.get("business_unit_id") or document.business_unit_id
        )
        resolved_uc = use_case_context.get("use_case_id") or document.use_case_id
        return resolved_bu, resolved_uc

    def test_context_takes_precedence_over_document(self):
        ctx = {"business_unit_id": "ctx-bu", "use_case_id": "ctx-uc"}
        doc = Document(id="test", business_unit_id="doc-bu", use_case_id="doc-uc")
        bu, uc = self._resolve_bu_uc(ctx, doc)
        assert bu == "ctx-bu"
        assert uc == "ctx-uc"

    def test_falls_back_to_document_when_context_empty(self):
        ctx = {}
        doc = Document(id="test", business_unit_id="doc-bu", use_case_id="doc-uc")
        bu, uc = self._resolve_bu_uc(ctx, doc)
        assert bu == "doc-bu"
        assert uc == "doc-uc"

    def test_both_empty_returns_none(self):
        ctx = {}
        doc = Document(id="test")
        bu, uc = self._resolve_bu_uc(ctx, doc)
        assert bu is None
        assert uc is None

    def test_partial_context_partial_document(self):
        """Context has BU but not UC; document has UC but not BU."""
        ctx = {"business_unit_id": "ctx-bu"}
        doc = Document(id="test", use_case_id="doc-uc")
        bu, uc = self._resolve_bu_uc(ctx, doc)
        assert bu == "ctx-bu"
        assert uc == "doc-uc"


# ===== End-to-end: use_case_context → get_config routing =====


@pytest.mark.unit
@mock_aws
class TestUseCaseContextToConfigRouting:
    """Test that use_case_context values correctly route to the right config.

    This verifies the full chain: event → extract context → get_config → merged config,
    using mocked DynamoDB (via moto) for realistic config resolution.
    """

    def test_no_context_uses_global_config(self, monkeypatch):
        """When use_case_context is empty, get_config returns global config."""
        table = _create_config_table()
        _seed_global_default(table, {"extraction": {"temperature": 0.1}})
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "test-config-table")

        # Simulate Pattern-1/2 calling get_config with None BU/UC
        config = get_config(as_model=True, business_unit_id=None, use_case_id=None)
        assert config.extraction.temperature == 0.1

    def test_context_routes_to_use_case_config(self, monkeypatch):
        """When use_case_context has BU/UC, get_config returns use-case-scoped config."""
        table = _create_config_table()
        _seed_global_default(table, {"extraction": {"temperature": 0.1}})
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "test-config-table")

        mgr = ConfigurationManager(table_name="test-config-table")
        mgr.save_use_case_configuration(
            "retail",
            "mortgage",
            CONFIG_TYPE_DEFAULT,
            {"extraction": {"temperature": 0.8}},
        )

        config = get_config(
            as_model=True, business_unit_id="retail", use_case_id="mortgage"
        )
        assert config.extraction.temperature == 0.8

    def test_unknown_use_case_falls_back_to_global(self, monkeypatch):
        """When BU/UC has no specific config, get_config returns global config."""
        table = _create_config_table()
        _seed_global_default(table, {"extraction": {"temperature": 0.2}})
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "test-config-table")

        config = get_config(
            as_model=True, business_unit_id="unknown-bu", use_case_id="unknown-uc"
        )
        assert config.extraction.temperature == 0.2

    def test_hitl_override_per_use_case(self, monkeypatch):
        """Use-case config can override HITL settings independently."""
        table = _create_config_table()
        _seed_global_default(table, {"assessment": {"hitl_enabled": False}})
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "test-config-table")

        mgr = ConfigurationManager(table_name="test-config-table")
        mgr.save_use_case_configuration(
            "bu",
            "uc",
            CONFIG_TYPE_DEFAULT,
            {"assessment": {"hitl_enabled": True}},
        )

        # Global: HITL disabled
        global_config = get_config(
            as_model=True, business_unit_id=None, use_case_id=None
        )
        assert global_config.assessment.hitl_enabled is False

        # Use-case: HITL enabled
        uc_config = get_config(as_model=True, business_unit_id="bu", use_case_id="uc")
        assert uc_config.assessment.hitl_enabled is True

    def test_confidence_threshold_override_per_use_case(self, monkeypatch):
        """Use-case config can override confidence threshold."""
        table = _create_config_table()
        _seed_global_default(
            table, {"assessment": {"default_confidence_threshold": 0.8}}
        )
        monkeypatch.setenv("CONFIGURATION_TABLE_NAME", "test-config-table")

        mgr = ConfigurationManager(table_name="test-config-table")
        mgr.save_use_case_configuration(
            "bu",
            "uc",
            CONFIG_TYPE_DEFAULT,
            {"assessment": {"default_confidence_threshold": 0.5}},
        )

        global_config = get_config(
            as_model=True, business_unit_id=None, use_case_id=None
        )
        assert global_config.assessment.default_confidence_threshold == 0.8

        uc_config = get_config(as_model=True, business_unit_id="bu", use_case_id="uc")
        assert uc_config.assessment.default_confidence_threshold == 0.5
