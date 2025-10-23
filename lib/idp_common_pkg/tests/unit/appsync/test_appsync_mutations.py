# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the AppSync mutations module.
"""

import re

import pytest
from idp_common.appsync.mutations import CREATE_DOCUMENT, UPDATE_DOCUMENT


@pytest.mark.unit
class TestAppSyncMutations:
    """Tests for the AppSync mutations."""

    def test_create_document_mutation_format(self):
        """Test that CREATE_DOCUMENT mutation has the correct format."""
        # Verify it's a GraphQL mutation
        assert CREATE_DOCUMENT.strip().startswith("mutation CreateDocument")

        # Verify it has the required input parameter
        assert "$input: CreateDocumentInput!" in CREATE_DOCUMENT

        # Verify it calls the createDocument mutation
        assert "createDocument(input: $input)" in CREATE_DOCUMENT

        # Verify it selects the ObjectKey field
        assert "ObjectKey" in CREATE_DOCUMENT

    def test_update_document_mutation_format(self):
        """Test that UPDATE_DOCUMENT mutation has the correct format."""
        # Verify it's a GraphQL mutation
        assert UPDATE_DOCUMENT.strip().startswith("mutation UpdateDocument")

        # Verify it has the required input parameter
        assert "$input: UpdateDocumentInput!" in UPDATE_DOCUMENT

        # Verify it calls the updateDocument mutation
        assert "updateDocument(input: $input)" in UPDATE_DOCUMENT

    def test_update_document_mutation_fields(self):
        """Test that UPDATE_DOCUMENT mutation selects all required fields."""
        required_fields = [
            "ObjectKey",
            "ObjectStatus",
            "InitialEventTime",
            "QueuedTime",
            "WorkflowStartTime",
            "CompletionTime",
            "WorkflowExecutionArn",
            "WorkflowStatus",
            "PageCount",
            "Sections",
            "Pages",
            "Metering",
            "EvaluationReportUri",
            "EvaluationStatus",
            "SummaryReportUri",
            "ExpiresAfter",
        ]

        for field in required_fields:
            assert (
                field in UPDATE_DOCUMENT
            ), f"Field {field} not found in UPDATE_DOCUMENT mutation"

    def test_update_document_sections_fields(self):
        """Test that UPDATE_DOCUMENT mutation selects all required section fields."""
        # Extract the Sections part of the query using regex
        sections_pattern = r"Sections\s*{([^}]*)}"
        match = re.search(sections_pattern, UPDATE_DOCUMENT)
        assert match, "Sections block not found in UPDATE_DOCUMENT mutation"

        sections_block = match.group(1)
        required_section_fields = ["Id", "PageIds", "Class", "OutputJSONUri"]

        for field in required_section_fields:
            assert (
                field in sections_block
            ), f"Section field {field} not found in UPDATE_DOCUMENT mutation"

    def test_update_document_pages_fields(self):
        """Test that UPDATE_DOCUMENT mutation selects all required page fields."""
        # Extract the Pages part of the query using regex
        pages_pattern = r"Pages\s*{([^}]*)}"
        match = re.search(pages_pattern, UPDATE_DOCUMENT)
        assert match, "Pages block not found in UPDATE_DOCUMENT mutation"

        pages_block = match.group(1)
        required_page_fields = ["Id", "Class", "ImageUri", "TextUri"]

        for field in required_page_fields:
            assert (
                field in pages_block
            ), f"Page field {field} not found in UPDATE_DOCUMENT mutation"
