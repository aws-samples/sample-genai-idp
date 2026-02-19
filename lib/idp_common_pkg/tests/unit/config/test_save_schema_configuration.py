from unittest.mock import Mock, patch

import pytest
from idp_common.config.configuration_manager import ConfigurationManager


@pytest.mark.unit
def test_save_schema_configuration():
    """Test saving Schema configuration."""
    mock_table = Mock()

    # Mock get_item to return no existing record
    mock_table.get_item.return_value = {}

    schema_config = {
        "notes": "test schema",
        "classes": [],
        "classification": {
            "model": "test-model",
            "temperature": 0.1,
            "top_k": 1,
            "top_p": 0.1,
            "max_tokens": 100,
            "system_prompt": "test",
            "task_prompt": "test",
        },
        "extraction": {
            "model": "test-model",
            "temperature": 0.1,
            "top_k": 1,
            "top_p": 0.1,
            "max_tokens": 100,
            "system_prompt": "test",
            "task_prompt": "test",
        },
    }

    with patch("idp_common.config.configuration_manager.boto3.resource") as mock_boto3:
        mock_boto3.return_value.Table.return_value = mock_table

        manager = ConfigurationManager(table_name="test-table")
        manager.save_configuration("Schema", schema_config)

        # Verify table.put_item was called
        mock_table.put_item.assert_called_once()

        # Get the item that was saved (compressed format)
        call_args = mock_table.put_item.call_args
        saved_item = call_args[1]["Item"]

        # Decompress to inspect the full item
        decompressed_item = ConfigurationManager._decompress_item(saved_item)

        # Verify the saved item structure
        assert decompressed_item["Configuration"] == "Schema"
        assert "notes" in decompressed_item
        assert "classes" in decompressed_item
        assert "classification" in decompressed_item
        assert "extraction" in decompressed_item
