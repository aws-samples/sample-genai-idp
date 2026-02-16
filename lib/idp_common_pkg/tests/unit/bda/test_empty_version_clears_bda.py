# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from unittest.mock import Mock, patch

import pytest
from idp_common.bda.bda_blueprint_service import BdaBlueprintService


@pytest.mark.unit
class TestEmptyVersionClearsBda:
    """Test that empty versions (default copies) clear BDA blueprints."""

    @pytest.fixture
    def service(self):
        """Create BdaBlueprintService instance for testing."""
        with patch("idp_common.bda.bda_blueprint_service.ConfigurationManager"):
            service = BdaBlueprintService(dataAutomationProjectArn="test-project-arn")
            service.blueprint_name_prefix = "test-stack"
            return service

    @pytest.fixture
    def existing_blueprints(self):
        """Mock existing blueprints in BDA."""
        return [
            {
                "blueprintArn": "arn:aws:bedrock:us-east-1:123456789012:blueprint/test-stack-Invoice-abc123",
                "blueprintName": "test-stack-Invoice-abc123",
                "blueprintVersion": "1",
            },
            {
                "blueprintArn": "arn:aws:bedrock:us-east-1:123456789012:blueprint/test-stack-Receipt-def456",
                "blueprintName": "test-stack-Receipt-def456",
                "blueprintVersion": "1",
            },
        ]

    @patch("idp_common.bda.bda_blueprint_service.BDABlueprintCreator")
    def test_empty_version_clears_bda_blueprints(
        self, mock_blueprint_creator, service, existing_blueprints
    ):
        """Test that a version with no classes clears all BDA blueprints."""
        # Mock configuration with empty classes
        mock_config = Mock()
        mock_config.classes = []  # Empty version
        service.config_manager.get_configuration.return_value = mock_config

        # Mock existing blueprints in BDA
        service._retrieve_all_blueprints = Mock(return_value=existing_blueprints)

        # Mock blueprint creator methods
        mock_creator_instance = Mock()
        mock_blueprint_creator.return_value = mock_creator_instance
        service.blueprint_creator = mock_creator_instance

        # Mock project blueprint list
        mock_creator_instance.list_blueprints.return_value = {
            "blueprints": existing_blueprints
        }

        # Execute sync with empty version
        service.create_blueprints_from_custom_configuration(
            version="empty-version", sync_direction="idp_to_bda"
        )

        # Verify _synchronize_deletes was called and would delete blueprints
        # Since we can't easily mock the internal _synchronize_deletes call,
        # we verify the expected behavior through the mocked methods

        # Should have retrieved existing blueprints
        service._retrieve_all_blueprints.assert_called_once_with("test-project-arn")

        # Should have called list_blueprints for deletion process
        mock_creator_instance.list_blueprints.assert_called()

        # Should have called update_project_with_custom_configurations to remove blueprints
        mock_creator_instance.update_project_with_custom_configurations.assert_called()

        # Should have called delete_blueprint for each existing blueprint
        assert mock_creator_instance.delete_blueprint.call_count == len(
            existing_blueprints
        )

        # Verify delete_blueprint was called with correct ARNs
        expected_calls = [
            (
                existing_blueprints[0]["blueprintArn"],
                existing_blueprints[0]["blueprintVersion"],
            ),
            (
                existing_blueprints[1]["blueprintArn"],
                existing_blueprints[1]["blueprintVersion"],
            ),
        ]

        actual_calls = [
            call.args for call in mock_creator_instance.delete_blueprint.call_args_list
        ]
        assert set(actual_calls) == set(expected_calls)

    @patch("idp_common.bda.bda_blueprint_service.BDABlueprintCreator")
    def test_empty_version_no_existing_blueprints(
        self, mock_blueprint_creator, service
    ):
        """Test that empty version with no existing blueprints doesn't fail."""
        # Mock configuration with empty classes
        mock_config = Mock()
        mock_config.classes = []
        service.config_manager.get_configuration.return_value = mock_config

        # Mock no existing blueprints
        service._retrieve_all_blueprints = Mock(return_value=[])

        # Mock blueprint creator
        mock_creator_instance = Mock()
        mock_blueprint_creator.return_value = mock_creator_instance
        service.blueprint_creator = mock_creator_instance

        # Execute sync
        service.create_blueprints_from_custom_configuration(
            version="empty-version", sync_direction="idp_to_bda"
        )

        # Should not fail and should not call delete methods
        mock_creator_instance.delete_blueprint.assert_not_called()
        mock_creator_instance.update_project_with_custom_configurations.assert_not_called()

    @patch("idp_common.bda.bda_blueprint_service.BDABlueprintCreator")
    def test_version_with_classes_preserves_matching_blueprints(
        self, mock_blueprint_creator, service, existing_blueprints
    ):
        """Test that version with classes only deletes non-matching blueprints."""
        # Mock configuration with one class (should preserve one blueprint, delete the other)
        mock_config = Mock()
        mock_config.classes = [{"$id": "Invoice", "x-aws-idp-document-type": "Invoice"}]
        service.config_manager.get_configuration.return_value = mock_config

        # Mock existing blueprints
        service._retrieve_all_blueprints = Mock(return_value=existing_blueprints)

        # Mock successful processing of the Invoice class
        service._process_classes_parallel = Mock(
            return_value=(
                [{"status": "success", "class": "Invoice"}],  # status
                [
                    "arn:aws:bedrock:us-east-1:123456789012:blueprint/test-stack-Invoice-abc123"
                ],  # updated
                False,  # modified
            )
        )

        # Mock blueprint creator
        mock_creator_instance = Mock()
        mock_blueprint_creator.return_value = mock_creator_instance
        service.blueprint_creator = mock_creator_instance

        # Mock project blueprint list
        mock_creator_instance.list_blueprints.return_value = {
            "blueprints": existing_blueprints
        }

        # Execute sync
        service.create_blueprints_from_custom_configuration(
            version="version-with-invoice", sync_direction="idp_to_bda"
        )

        # Should only delete the Receipt blueprint (not matching current classes)
        # Invoice blueprint should be preserved because it was "updated"
        mock_creator_instance.delete_blueprint.assert_called_once_with(
            "arn:aws:bedrock:us-east-1:123456789012:blueprint/test-stack-Receipt-def456",
            "1",
        )
