# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for configuration synchronization behavior when Default is updated.

This tests the critical behavior: when Default config is updated, Custom should
get all new default values EXCEPT for fields the user has customized.
"""

from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import (
    ConfidenceConfig,
    ExtractionConfig,
    IDPConfig,
    ImageConfig,
)


class TestSyncCustomWithNewDefault:
    """Test sync_custom_with_new_default method.

    In the full-config design, configuration versions are independent snapshots
    that do NOT auto-merge with Default when Default changes. The method is kept
    only for backward compatibility and returns ``old_custom`` unchanged. These
    tests assert that no-op contract (they previously asserted an auto-merge
    behavior that was intentionally removed).
    """

    def test_returns_custom_unchanged_when_default_updated(self):
        """A Default update must NOT bleed new values into the custom snapshot."""
        manager = ConfigurationManager(table_name="test-table")

        old_default = IDPConfig(extraction=ExtractionConfig(temperature=0.0, top_p=0.1))
        old_custom = IDPConfig(
            extraction=ExtractionConfig(temperature=0.8, top_p=0.1, top_k=10.0)
        )
        new_default = IDPConfig(
            extraction=ExtractionConfig(temperature=0.5, top_p=0.2, top_k=20.0)
        )

        new_custom = manager.sync_custom_with_new_default(
            old_default, new_default, old_custom
        )

        # The custom snapshot is returned verbatim — no field takes the new default.
        assert new_custom is old_custom
        assert new_custom.extraction.temperature == 0.8
        assert new_custom.extraction.top_p == 0.1
        assert new_custom.extraction.top_k == 10.0

    def test_preserves_user_customizations_and_added_classes(self):
        """User customizations at every level, incl. added classes, survive intact."""
        manager = ConfigurationManager(table_name="test-table")

        old_default = IDPConfig(
            extraction=ExtractionConfig(
                model="us.amazon.nova-pro-v1:0",
                temperature=0.0,
                confidence=ConfidenceConfig(enabled=True, temperature=0.0),
                image=ImageConfig(dpi=300, target_width=None),
            ),
            classes=[],
        )
        old_custom = IDPConfig(
            extraction=ExtractionConfig(
                model="us.amazon.nova-pro-v1:0",
                temperature=0.8,
                confidence=ConfidenceConfig(enabled=False, temperature=0.0),
                image=ImageConfig(dpi=600, target_width=None),
            ),
            classes=[{"$id": "Invoice", "properties": {}}],
        )
        new_default = IDPConfig(
            extraction=ExtractionConfig(
                model="us.amazon.nova-premier-v1:0",
                temperature=0.5,
                confidence=ConfidenceConfig(enabled=True, temperature=0.5),
                image=ImageConfig(dpi=450, target_width=1024),
            ),
            classes=[],
        )

        new_custom = manager.sync_custom_with_new_default(
            old_default, new_default, old_custom
        )

        # Everything from the custom snapshot is preserved; nothing from new_default.
        assert new_custom.extraction.temperature == 0.8
        assert new_custom.extraction.model == "us.amazon.nova-pro-v1:0"
        assert not new_custom.extraction.confidence.enabled
        assert new_custom.extraction.image.dpi == 600
        assert new_custom.extraction.image.target_width is None
        assert new_custom.classes == [{"$id": "Invoice", "properties": {}}]


@pytest.mark.unit
class TestConfigurationManagerSync:
    """Integration tests for configuration sync behavior."""

    @mock_aws
    @pytest.mark.skip(
        reason="Test mock setup needs update - sync logic requires unmocked get_configuration calls"
    )
    def test_save_default_triggers_sync(self):
        """Saving Default should automatically sync Custom."""
        # Create mock DynamoDB table
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = "test-config-table"

        dynamodb.create_table(  # type: ignore[attr-defined]
            TableName=table_name,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        manager = ConfigurationManager(table_name=table_name)

        # Mock get_configuration to return old configs
        old_default = IDPConfig(extraction=ExtractionConfig(temperature=0.0))
        old_custom = IDPConfig(extraction=ExtractionConfig(temperature=0.8))

        with (
            patch.object(manager, "get_configuration") as mock_get,
            patch.object(manager, "get_raw_configuration") as mock_get_raw,
            patch.object(manager, "_write_record") as mock_write,
        ):
            mock_get.side_effect = [old_default, old_custom]
            mock_get_raw.return_value = None  # No raw config needed for this test

            # Save new default
            new_default = IDPConfig(extraction=ExtractionConfig(temperature=0.5))
            manager.save_configuration("Default", new_default)

            # Should have written BOTH Default and synced Custom
            assert mock_write.call_count == 2

            # First call is for Custom (synced), second is for Default
            # Get the Custom config that was saved
            custom_call = mock_write.call_args_list[0]
            saved_custom = custom_call[0][0].config

            # User's temperature should be preserved
            assert saved_custom.extraction.temperature == 0.8

    @mock_aws
    def test_save_custom_does_not_trigger_sync(self):
        """Saving Custom should NOT trigger any sync."""
        # Create mock DynamoDB table
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

        # Should have written only once (just Custom, no sync)
        assert mock_write.call_count == 1
