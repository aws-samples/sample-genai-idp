# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the summarization models module.
"""

import pytest

from idp_common.summarization.models import DocumentSummarizationResult, DocumentSummary


@pytest.mark.unit
class TestDocumentSummary:
    """Tests for the DocumentSummary class."""

    def test_init(self):
        """Test initialization with content."""
        content = {"key1": "value1", "key2": "value2"}
        summary = DocumentSummary(content=content)

        assert summary.content == content
        assert summary.metadata == {}

    def test_init_with_metadata(self):
        """Test initialization with content and metadata."""
        content = {"key1": "value1", "key2": "value2"}
        metadata = {"model": "test-model", "tokens": 100}
        summary = DocumentSummary(content=content, metadata=metadata)

        assert summary.content == content
        assert summary.metadata == metadata

    def test_getitem(self):
        """Test dictionary-like access to summary fields."""
        content = {"key1": "value1", "key2": "value2"}
        summary = DocumentSummary(content=content)

        assert summary["key1"] == "value1"
        assert summary["key2"] == "value2"
        assert summary["non_existent"] is None

    def test_get(self):
        """Test get method with default value."""
        content = {"key1": "value1", "key2": "value2"}
        summary = DocumentSummary(content=content)

        assert summary.get("key1") == "value1"
        assert summary.get("non_existent") is None
        assert summary.get("non_existent", "default") == "default"

    def test_keys(self):
        """Test keys method."""
        content = {"key1": "value1", "key2": "value2"}
        summary = DocumentSummary(content=content)

        keys = summary.keys()
        assert isinstance(keys, list)
        assert "key1" in keys
        assert "key2" in keys
        assert len(keys) == 2

    def test_to_dict(self):
        """Test to_dict method."""
        content = {"key1": "value1", "key2": "value2"}
        metadata = {"model": "test-model", "tokens": 100}
        summary = DocumentSummary(content=content, metadata=metadata)

        result = summary.to_dict()
        assert result == {"key1": "value1", "key2": "value2", "metadata": metadata}


@pytest.mark.unit
class TestDocumentSummarizationResult:
    """Tests for the DocumentSummarizationResult class."""

    def test_init(self):
        """Test initialization with required fields."""
        document_id = "doc-123"
        summary = DocumentSummary(content={"key1": "value1"})

        result = DocumentSummarizationResult(document_id=document_id, summary=summary)

        assert result.document_id == document_id
        assert result.summary == summary
        assert result.execution_time == 0.0
        assert result.output_uri is None

    def test_init_with_optional_fields(self):
        """Test initialization with all fields."""
        document_id = "doc-123"
        summary = DocumentSummary(content={"key1": "value1"})
        execution_time = 1.5
        output_uri = "s3://bucket/key"

        result = DocumentSummarizationResult(
            document_id=document_id,
            summary=summary,
            execution_time=execution_time,
            output_uri=output_uri,
        )

        assert result.document_id == document_id
        assert result.summary == summary
        assert result.execution_time == execution_time
        assert result.output_uri == output_uri

    def test_to_dict(self):
        """Test to_dict method."""
        document_id = "doc-123"
        summary = DocumentSummary(
            content={"key1": "value1", "key2": "value2"},
            metadata={"model": "test-model"},
        )
        execution_time = 1.5
        output_uri = "s3://bucket/key"

        result = DocumentSummarizationResult(
            document_id=document_id,
            summary=summary,
            execution_time=execution_time,
            output_uri=output_uri,
        )

        expected = {
            "document_id": document_id,
            "execution_time": execution_time,
            "output_uri": output_uri,
            "key1": "value1",
            "key2": "value2",
            "metadata": {"model": "test-model"},
        }

        assert result.to_dict() == expected

    def test_to_markdown_simple(self):
        """Test to_markdown method with simple content."""
        document_id = "doc-123"
        summary = DocumentSummary(
            content={
                "summary": "This is a summary",
                "key_points": "These are key points",
            }
        )

        result = DocumentSummarizationResult(document_id=document_id, summary=summary)

        markdown = result.to_markdown()

        assert "# Document Summary: doc-123" in markdown
        assert "## Summary" in markdown
        assert "This is a summary" in markdown
        assert "## Key Points" in markdown
        assert "These are key points" in markdown

    def test_to_markdown_with_list(self):
        """Test to_markdown method with list content."""
        document_id = "doc-123"
        summary = DocumentSummary(
            content={"key_points": ["Point 1", "Point 2", "Point 3"]}
        )

        result = DocumentSummarizationResult(document_id=document_id, summary=summary)

        markdown = result.to_markdown()

        assert "# Document Summary: doc-123" in markdown
        assert "## Key Points" in markdown
        assert "- Point 1" in markdown
        assert "- Point 2" in markdown
        assert "- Point 3" in markdown

    def test_to_markdown_with_nested_dict(self):
        """Test to_markdown method with nested dictionary content."""
        document_id = "doc-123"
        summary = DocumentSummary(
            content={
                "sections": {
                    "introduction": "This is the introduction",
                    "conclusion": "This is the conclusion",
                }
            }
        )

        result = DocumentSummarizationResult(document_id=document_id, summary=summary)

        markdown = result.to_markdown()

        assert "# Document Summary: doc-123" in markdown
        assert "## Sections" in markdown
        assert "### Introduction" in markdown
        assert "This is the introduction" in markdown
        assert "### Conclusion" in markdown
        assert "This is the conclusion" in markdown

    def test_to_markdown_with_metadata(self):
        """Test to_markdown method with metadata."""
        document_id = "doc-123"
        summary = DocumentSummary(
            content={"summary": "This is a summary"},
            metadata={"model": "test-model", "tokens": 100, "execution_time": 1.5},
        )

        result = DocumentSummarizationResult(
            document_id=document_id, summary=summary, execution_time=1.5
        )

        markdown = result.to_markdown()

        assert "# Document Summary: doc-123" in markdown
        assert "## Summary" in markdown
        assert "This is a summary" in markdown
        assert "## Metadata" in markdown
        assert "| Key | Value |" in markdown
        assert "| model | test-model |" in markdown
        assert "| tokens | 100 |" in markdown
        assert "Execution time: 1.50 seconds" in markdown
