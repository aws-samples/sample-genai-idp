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


@pytest.mark.unit
class TestConfigurationManagerResolveActiveVersion:
    """Test resolve_active_version — the version a new document is pinned to.

    Callers use this to STAMP document.config_version at queue time instead of
    leaving it None and letting each downstream consumer resolve it for itself.
    Every independent re-resolution was a place the answer could disagree or
    silently fail, which is what issue #599 was.
    """

    @patch("idp_common.config.configuration_manager.boto3")
    def test_returns_the_active_version(self, mock_boto3):
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.return_value = {
            "Items": [
                {"Configuration": "Config#default", "IsActive": False},
                {"Configuration": "Config#claims-pack-v0.4.0", "IsActive": True},
            ]
        }

        manager = ConfigurationManager(table_name="test-table")
        assert manager.resolve_active_version() == "claims-pack-v0.4.0"

    @patch("idp_common.config.configuration_manager.boto3")
    def test_finds_an_active_version_beyond_the_first_scan_page(self, mock_boto3):
        """Built on list_config_versions, which paginates — so an active row that
        sorts late is still found. An unpaginated resolver reported 'nothing
        active' here and silently pinned the default (issue #599)."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.side_effect = [
            {
                "Items": [{"Configuration": "Config#v1", "IsActive": False}],
                "LastEvaluatedKey": {"Configuration": "Config#v1"},
            },
            {"Items": [{"Configuration": "Config#v2", "IsActive": True}]},
        ]

        manager = ConfigurationManager(table_name="test-table")
        assert manager.resolve_active_version() == "v2"
        assert mock_table.scan.call_count == 2

    @patch("idp_common.config.configuration_manager.boto3")
    def test_no_active_version_returns_default(self, mock_boto3):
        """A NORMAL state, not an error: a freshly deployed stack writes
        Config#default with no IsActive attribute at all."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.return_value = {"Items": [{"Configuration": "Config#default"}]}

        manager = ConfigurationManager(table_name="test-table")
        assert manager.resolve_active_version() == "default"

    @patch("idp_common.config.configuration_manager.boto3")
    def test_empty_table_returns_default(self, mock_boto3):
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.return_value = {"Items": []}

        manager = ConfigurationManager(table_name="test-table")
        assert manager.resolve_active_version() == "default"

    @patch("idp_common.config.configuration_manager.boto3")
    def test_scan_failure_returns_default_rather_than_raising(self, mock_boto3):
        """Never fail a document over this — the default is always readable."""
        mock_table = Mock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_table.scan.side_effect = RuntimeError("throttled")

        manager = ConfigurationManager(table_name="test-table")
        assert manager.resolve_active_version() == "default"
