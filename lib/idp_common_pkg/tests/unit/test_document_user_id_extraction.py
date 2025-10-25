# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for user_id extraction from S3 object keys.

This test module ensures that user_id is automatically extracted from
user-scoped S3 object keys and properly set on Document objects.

Regression test for bug: "UserId is required for document updates but was not provided"
"""

import pytest
from idp_common.models import Document, extract_user_id_from_object_key, Status


@pytest.mark.unit
class TestExtractUserIdFromObjectKey:
    """Tests for the extract_user_id_from_object_key utility function."""

    def test_extracts_user_id_from_valid_path(self):
        """Should extract user_id from user-scoped path."""
        object_key = "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf"
        user_id = extract_user_id_from_object_key(object_key)

        assert user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"

    def test_returns_none_for_non_user_scoped_path(self):
        """Should return None for paths not starting with 'users/'."""
        object_key = "documents/invoice7.pdf"
        user_id = extract_user_id_from_object_key(object_key)

        assert user_id is None

    def test_returns_none_for_empty_string(self):
        """Should return None for empty string."""
        user_id = extract_user_id_from_object_key("")

        assert user_id is None

    def test_returns_none_for_none_input(self):
        """Should return None for None input."""
        user_id = extract_user_id_from_object_key(None)

        assert user_id is None

    def test_returns_none_for_invalid_structure(self):
        """Should return None for invalid user-scoped structure."""
        object_key = "users/invalid"  # Missing filename
        user_id = extract_user_id_from_object_key(object_key)

        assert user_id is None

    def test_handles_nested_paths(self):
        """Should extract user_id from nested path structures."""
        object_key = "users/93c46832-90d1-7096-708c-e7d4f19e6695/subfolder/invoice7.pdf"
        user_id = extract_user_id_from_object_key(object_key)

        assert user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"

    def test_warns_on_non_uuid_format(self, caplog):
        """Should extract but warn if user_id doesn't match UUID format."""
        object_key = "users/not-a-uuid/invoice7.pdf"
        user_id = extract_user_id_from_object_key(object_key)

        # Should still extract the value
        assert user_id == "not-a-uuid"
        # But should log a warning
        assert "doesn't match UUID pattern" in caplog.text

    @pytest.mark.parametrize("object_key,expected_user_id", [
        ("users/12345678-1234-1234-1234-123456789abc/file.pdf", "12345678-1234-1234-1234-123456789abc"),
        ("users/ABCDEF12-3456-7890-ABCD-EF1234567890/file.pdf", "ABCDEF12-3456-7890-ABCD-EF1234567890"),
        ("users/a1b2c3d4-e5f6-7890-abcd-ef1234567890/dir/file.pdf", "a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    ])
    def test_various_uuid_formats(self, object_key, expected_user_id):
        """Should handle various UUID formats (upper, lower, mixed case)."""
        user_id = extract_user_id_from_object_key(object_key)

        assert user_id == expected_user_id


@pytest.mark.unit
class TestDocumentUserIdExtraction:
    """Tests for automatic user_id extraction in Document class."""

    def test_from_dict_extracts_user_id_from_input_key(self):
        """Should automatically extract user_id from input_key if not provided."""
        doc_data = {
            "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            "status": "OCR",
        }

        doc = Document.from_dict(doc_data)

        assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
        assert doc.input_key == "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf"

    def test_from_dict_preserves_explicit_user_id(self):
        """Should use explicit user_id if provided, not extract from path."""
        doc_data = {
            "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            "user_id": "explicit-user-id-123",
            "status": "OCR",
        }

        doc = Document.from_dict(doc_data)

        # Should use the explicitly provided user_id
        assert doc.user_id == "explicit-user-id-123"

    def test_from_dict_sets_none_for_non_user_scoped_path(self):
        """Should set user_id to None for non-user-scoped paths."""
        doc_data = {
            "input_key": "documents/invoice7.pdf",
            "status": "OCR",
        }

        doc = Document.from_dict(doc_data)

        assert doc.user_id is None

    def test_from_s3_event_extracts_user_id(self):
        """Should extract user_id when creating Document from S3 event."""
        event = {
            "detail": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf"}
            },
            "time": "2025-10-24T15:00:00Z"
        }

        doc = Document.from_s3_event(event, output_bucket="output-bucket")

        assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
        assert doc.input_key == "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf"

    def test_to_dict_preserves_user_id(self):
        """Should preserve user_id when converting to dict."""
        doc = Document(
            input_key="users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            user_id="93c46832-90d1-7096-708c-e7d4f19e6695",
            status=Status.OCR,
        )

        doc_dict = doc.to_dict()

        assert doc_dict["user_id"] == "93c46832-90d1-7096-708c-e7d4f19e6695"

    def test_json_serialization_round_trip_preserves_user_id(self):
        """Should preserve user_id through JSON serialization/deserialization."""
        original_doc = Document(
            input_key="users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            user_id="93c46832-90d1-7096-708c-e7d4f19e6695",
            status=Status.OCR,
            num_pages=1,
        )

        # Serialize to JSON
        json_str = original_doc.to_json()

        # Deserialize from JSON
        restored_doc = Document.from_json(json_str)

        assert restored_doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
        assert restored_doc.input_key == original_doc.input_key


@pytest.mark.unit
class TestDocumentUserIdForAppSync:
    """
    Tests ensuring user_id is properly set for AppSync mutations.

    Regression test for error:
    "UserId is required for document updates but was not provided for ObjectKey: users/..."
    """

    def test_document_loaded_from_event_has_user_id_for_appsync(self):
        """
        Should ensure Documents loaded from Lambda events have user_id populated.

        This simulates the flow in OCR Lambda where:
        1. Document is loaded from event
        2. Document is updated via AppSync (requires user_id)
        """
        # Simulate document data coming from Step Functions event
        event_document_data = {
            "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            "input_bucket": "input-bucket",
            "output_bucket": "output-bucket",
            "status": "QUEUED",
            "num_pages": 0,
        }

        # Load document (as done in Lambda handlers)
        doc = Document.from_dict(event_document_data)

        # Verify user_id is populated
        assert doc.user_id is not None, "user_id should be extracted from input_key"
        assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"

        # Verify it's ready for AppSync update
        # (AppSync service will use this user_id to create the UserId field)
        assert doc.input_key == event_document_data["input_key"]

    def test_appsync_update_input_includes_user_id(self):
        """
        Should verify that AppSync update input includes UserId field.

        This is the critical check that prevents the original error.
        """
        from unittest.mock import Mock
        from idp_common.appsync.service import DocumentAppSyncService

        # Create document with user-scoped path
        doc = Document.from_dict({
            "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf",
            "status": "OCR",
            "num_pages": 1,
        })

        # Create AppSync service with mocked client
        mock_client = Mock()
        service = DocumentAppSyncService(appsync_client=mock_client)

        # Generate update input (as done in document_service.update_document)
        update_input = service._document_to_update_input(doc)

        # Critical assertion: UserId must be present
        assert "UserId" in update_input, "UserId is required for user-scoped documents"
        assert update_input["UserId"] == "93c46832-90d1-7096-708c-e7d4f19e6695"
        assert update_input["ObjectKey"] == doc.input_key

    def test_non_user_scoped_document_does_not_include_user_id(self):
        """Should not include UserId for non-user-scoped documents."""
        from unittest.mock import Mock
        from idp_common.appsync.service import DocumentAppSyncService

        # Create document with non-user-scoped path
        doc = Document.from_dict({
            "input_key": "documents/invoice7.pdf",
            "status": "OCR",
        })

        # Create AppSync service with mocked client
        mock_client = Mock()
        service = DocumentAppSyncService(appsync_client=mock_client)
        update_input = service._document_to_update_input(doc)

        # UserId should not be included for non-user-scoped documents
        assert "UserId" not in update_input or update_input.get("UserId") is None
