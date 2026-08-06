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


@pytest.mark.unit
class TestConfigurationManagerListConfigVersions:
    """Test list_config_versions pagination."""

    @patch("idp_common.config.configuration_manager.boto3")
    def test_list_config_versions_single_page(self, mock_boto3):
        """All versions on a single page are returned."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.return_value = {
            "Items": [
                {"Configuration": "config#v1", "IsActive": True},
                {"Configuration": "config#v2", "IsActive": False},
            ]
        }

        manager = ConfigurationManager(table_name="test-table")
        versions = manager.list_config_versions()

        assert mock_table.scan.call_count == 1
        assert [v["versionName"] for v in versions] == ["v1", "v2"]

    @patch("idp_common.config.configuration_manager.boto3")
    def test_list_config_versions_paginates(self, mock_boto3):
        """Versions beyond the first scan page are still returned."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        # First page returns a LastEvaluatedKey, second page does not.
        mock_table.scan.side_effect = [
            {
                "Items": [{"Configuration": "config#v1", "IsActive": False}],
                "LastEvaluatedKey": {"Configuration": "config#v1"},
            },
            {
                "Items": [{"Configuration": "config#v2", "IsActive": True}],
            },
        ]

        manager = ConfigurationManager(table_name="test-table")
        versions = manager.list_config_versions()

        assert mock_table.scan.call_count == 2
        # Second scan must continue from the prior page's LastEvaluatedKey.
        _, second_call_kwargs = mock_table.scan.call_args_list[1]
        assert second_call_kwargs["ExclusiveStartKey"] == {"Configuration": "config#v1"}
        assert [v["versionName"] for v in versions] == ["v1", "v2"]
