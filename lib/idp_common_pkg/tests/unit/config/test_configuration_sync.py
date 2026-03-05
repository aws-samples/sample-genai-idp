# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for configuration synchronization behavior.

In the current full-config design, versions are independent snapshots.
sync_custom_with_new_default is a legacy compatibility no-op that returns
old_custom unchanged.  These tests verify that contract.
"""

from unittest.mock import patch

import boto3
import pytest
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import (
    AssessmentConfig,
    ExtractionConfig,
    IDPConfig,
)
from moto import mock_aws


class TestSyncCustomWithNewDefault:
    """Test sync_custom_with_new_default returns old_custom unchanged.

    In the full-config design each version is an independent snapshot,
    so sync is intentionally a no-op.
    """

    def test_returns_old_custom_unchanged(self):
        """sync_custom_with_new_default returns old_custom as-is."""
        manager = ConfigurationManager(table_name="test-table")

        old_default = IDPConfig(extraction=ExtractionConfig(temperature=0.0, top_p=0.1))
        old_custom = IDPConfig(extraction=ExtractionConfig(temperature=0.8, top_p=0.1))
        new_default = IDPConfig(
            extraction=ExtractionConfig(temperature=0.5, top_p=0.2, max_tokens=5000)
        )

        result = manager.sync_custom_with_new_default(
            old_default, new_default, old_custom
        )

        assert result is old_custom
        assert result.extraction.temperature == 0.8
        assert result.extraction.top_p == 0.1

    def test_user_customizations_preserved(self):
        """All user customizations in old_custom are retained."""
        manager = ConfigurationManager(table_name="test-table")

        old_default = IDPConfig(
            extraction=ExtractionConfig(temperature=0.0, model="nova-pro-v1:0"),
            assessment=AssessmentConfig(enabled=True, temperature=0.0),
        )
        old_custom = IDPConfig(
            extraction=ExtractionConfig(temperature=0.9, model="nova-pro-v1:0"),
            assessment=AssessmentConfig(enabled=False, temperature=0.0),
        )
        new_default = IDPConfig(
            extraction=ExtractionConfig(temperature=0.5, model="nova-premier-v1:0"),
            assessment=AssessmentConfig(enabled=True, temperature=0.5),
        )

        result = manager.sync_custom_with_new_default(
            old_default, new_default, old_custom
        )

        assert result.extraction.temperature == 0.9
        assert not result.assessment.enabled
        assert result.extraction.model == "nova-pro-v1:0"

    def test_classes_preserved(self):
        """User-added classes in old_custom are preserved."""
        manager = ConfigurationManager(table_name="test-table")

        old_default = IDPConfig(extraction=ExtractionConfig(temperature=0.0))
        old_custom = IDPConfig(
            extraction=ExtractionConfig(temperature=0.8),
            classes=[{"$id": "Invoice", "properties": {}}],
        )
        new_default = IDPConfig(extraction=ExtractionConfig(temperature=0.5))

        result = manager.sync_custom_with_new_default(
            old_default, new_default, old_custom
        )

        assert len(result.classes) == 1
        assert result.classes[0]["$id"] == "Invoice"


@pytest.mark.unit
class TestConfigurationManagerSync:
    """Integration tests for configuration sync behavior."""

    @mock_aws
    @pytest.mark.skip(
        reason="Test mock setup needs update - sync logic requires unmocked get_configuration calls"
    )
    def test_save_default_triggers_sync(self):
        """Saving Default should automatically sync Custom."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = "test-config-table"

        dynamodb.create_table(  # type: ignore[attr-defined]
            TableName=table_name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        manager = ConfigurationManager(table_name=table_name)

        old_default = IDPConfig(extraction=ExtractionConfig(temperature=0.0))
        old_custom = IDPConfig(extraction=ExtractionConfig(temperature=0.8))

        with (
            patch.object(manager, "get_configuration") as mock_get,
            patch.object(manager, "get_raw_configuration") as mock_get_raw,
            patch.object(manager, "_write_record") as mock_write,
        ):
            mock_get.side_effect = [old_default, old_custom]
            mock_get_raw.return_value = None

            new_default = IDPConfig(extraction=ExtractionConfig(temperature=0.5))
            manager.save_configuration("Default", new_default)

            assert mock_write.call_count == 2

            custom_call = mock_write.call_args_list[0]
            saved_custom = custom_call[0][0].config

            assert saved_custom.extraction.temperature == 0.8

    @mock_aws
    def test_save_custom_does_not_trigger_sync(self):
        """Saving Custom should NOT trigger any sync."""
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = "test-config-table"

        dynamodb.create_table(  # type: ignore[attr-defined]
            TableName=table_name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        manager = ConfigurationManager(table_name=table_name)

        custom = IDPConfig(extraction=ExtractionConfig(temperature=0.8))

        with patch.object(manager, "_write_record") as mock_write:
            manager.save_configuration("Custom", custom)

        assert mock_write.call_count == 1
