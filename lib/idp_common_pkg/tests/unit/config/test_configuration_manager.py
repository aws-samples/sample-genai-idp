"""Tests for ConfigurationManager activate_version functionality."""

from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager


@pytest.mark.unit
class TestConfigurationManagerActivateVersion:
    """Test activate_version method."""

    @patch("idp_common.config.configuration_manager.boto3")
    def test_activate_version_success(self, mock_boto3):
        """Test successful version activation."""
        # Setup mocks
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table

        manager = ConfigurationManager(table_name="test-table")

        # Mock get_raw_configuration to return existing config
        manager.get_raw_configuration = Mock(return_value={"notes": "test"})

        # Mock list_config_versions to return active version
        manager.list_config_versions = Mock(
            return_value=[{"versionName": "other-version", "isActive": True}]
        )

        # Execute
        manager.activate_version("test-version")

        # Verify DynamoDB operations
        assert mock_table.get_item.called
        assert mock_table.update_item.call_count == 2  # Deactivate old + activate new

    @patch("idp_common.config.configuration_manager.boto3")
    def test_activate_version_not_found(self, mock_boto3):
        """Test activation of non-existent version."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.get_item.return_value = {"Item": None}

        manager = ConfigurationManager(table_name="test-table")

        with pytest.raises(ValueError, match="Config version test-version not found"):
            manager.activate_version("test-version")
