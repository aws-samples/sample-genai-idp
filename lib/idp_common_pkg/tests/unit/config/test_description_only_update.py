# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from unittest.mock import Mock

import pytest
from idp_common.config.configuration_manager import ConfigurationManager


@pytest.mark.unit
def test_description_only_update():
    """Test that description-only updates work correctly."""

    # Mock the DynamoDB table
    mock_table = Mock()

    # Mock existing version record
    existing_record = {
        "Configuration": "Config#test-version",
        "CreatedAt": "2024-01-01T00:00:00Z",
        "UpdatedAt": "2024-01-01T00:00:00Z",
        "IsActive": False,
        "Description": "old description",
        "some_config": "value",
    }

    # Mock table.get_item to return existing record
    mock_table.get_item.return_value = {"Item": existing_record}

    # Mock table.put_item to capture what gets saved
    saved_item = None

    def capture_put_item(Item):
        nonlocal saved_item
        saved_item = Item
        return {}

    mock_table.put_item.side_effect = capture_put_item

    # Create ConfigurationManager with mocked table
    manager = ConfigurationManager(table_name="test-table")
    manager.table = mock_table

    # Test description-only update (empty config)
    result = manager.handle_update_custom_configuration(
        custom_config="{}",  # Empty config
        version="test-version",
        description="new description",
    )

    # Debug: Print what was saved
    print(f"Saved item: {saved_item}")
    print(
        f"Description in saved item: {saved_item.get('Description') if saved_item else 'None'}"
    )

    # Verify the operation succeeded
    assert result is True

    # Verify the saved item has the new description
    assert saved_item is not None
    assert saved_item["Description"] == "new description"
    assert "UpdatedAt" in saved_item

    # Verify get_item was called to fetch existing record
    assert mock_table.get_item.call_count >= 1

    # Verify put_item was called to save the update
    mock_table.put_item.assert_called_once()


@pytest.mark.unit
def test_description_only_update_with_rule_classes():
    """Test description update when rule_classes is included but unchanged."""

    # Mock the DynamoDB table
    mock_table = Mock()

    # Mock existing version record with rule_classes
    existing_record = {
        "Configuration": "Config#test-version",
        "CreatedAt": "2024-01-01T00:00:00Z",
        "UpdatedAt": "2024-01-01T00:00:00Z",
        "IsActive": False,
        "Description": "old description",
        "rule_classes": [],
    }

    # Mock table.get_item to return existing record
    mock_table.get_item.return_value = {"Item": existing_record}

    # Mock table.put_item to capture what gets saved
    saved_item = None

    def capture_put_item(Item):
        nonlocal saved_item
        saved_item = Item
        return {}

    mock_table.put_item.side_effect = capture_put_item

    # Create ConfigurationManager with mocked table
    manager = ConfigurationManager(table_name="test-table")
    manager.table = mock_table

    # Test description update with unchanged rule_classes
    result = manager.handle_update_custom_configuration(
        custom_config='{"rule_classes": []}',  # Same as existing
        version="test-version",
        description="updated description",
    )

    # Verify the operation succeeded
    assert result is True

    # Verify the saved item has the new description
    assert saved_item is not None
    assert saved_item["Description"] == "updated description"
    assert "UpdatedAt" in saved_item

    # In full-config mode, rule_classes is preserved in the saved config
    # (no longer stripped by auto-cleanup since we save complete configs)
    # Config data is compressed, so decompress to verify field presence
    decompressed_item = ConfigurationManager._decompress_item(saved_item)
    assert "rule_classes" in decompressed_item  # Full config preserves all fields


@pytest.mark.unit
def test_description_none_handling():
    """Test that None description is handled correctly."""

    # Mock the DynamoDB table
    mock_table = Mock()

    # Mock existing version record
    existing_record = {
        "Configuration": "Config#test-version",
        "CreatedAt": "2024-01-01T00:00:00Z",
        "UpdatedAt": "2024-01-01T00:00:00Z",
        "IsActive": False,
        "Description": "existing description",
    }

    # Mock table.get_item to return existing record
    mock_table.get_item.return_value = {"Item": existing_record}

    # Mock table.put_item to capture what gets saved
    saved_item = None

    def capture_put_item(Item):
        nonlocal saved_item
        saved_item = Item
        return {}

    mock_table.put_item.side_effect = capture_put_item

    # Create ConfigurationManager with mocked table
    manager = ConfigurationManager(table_name="test-table")
    manager.table = mock_table

    # Test with None description (should not update description)
    result = manager.handle_update_custom_configuration(
        custom_config='{"some_field": "value"}',
        version="test-version",
        description=None,
    )

    # Verify the operation succeeded
    assert result is True

    # Verify the saved item preserves existing description when None passed
    assert saved_item is not None
    assert (
        saved_item["Description"] == "existing description"
    )  # Should preserve existing when None
    assert "UpdatedAt" in saved_item
