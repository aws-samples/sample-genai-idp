# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Pydantic models.
"""

from datetime import datetime

import pytest
from idp_sdk.models import (
    BatchDeletionResult,
    BatchResult,
    BatchStatus,
    ConfigCreateResult,
    ConfigValidationResult,
    DocumentDeletionResult,
    DocumentState,
    DocumentStatus,
    Pattern,
    RerunStep,
)


@pytest.mark.unit
class TestEnums:
    """Test enum values."""

    def test_pattern_enum(self):
        """Pattern enum has correct values."""
        assert Pattern.PATTERN_1.value == "pattern-1"
        assert Pattern.PATTERN_2.value == "pattern-2"
        assert Pattern.PATTERN_3.value == "pattern-3"

    def test_rerun_step_enum(self):
        """RerunStep enum has correct values."""
        assert RerunStep.CLASSIFICATION.value == "classification"
        assert RerunStep.EXTRACTION.value == "extraction"

    def test_document_state_enum(self):
        """DocumentState enum has correct values."""
        assert DocumentState.QUEUED.value == "QUEUED"
        assert DocumentState.COMPLETED.value == "COMPLETED"
        assert DocumentState.FAILED.value == "FAILED"


@pytest.mark.unit
class TestBatchModels:
    """Test batch-related models."""

    def test_batch_result_creation(self):
        """BatchResult can be created with required fields."""
        result = BatchResult(
            batch_id="test-batch",
            document_ids=["doc1", "doc2"],
            queued=2,
            uploaded=2,
            failed=0,
            source="./test/",
            output_prefix="test",
            timestamp=datetime.now(),
        )

        assert result.batch_id == "test-batch"
        assert len(result.document_ids) == 2
        assert result.documents_queued == 2

    def test_batch_status_creation(self):
        """BatchStatus can be created."""
        status = BatchStatus(
            batch_id="test-batch",
            documents=[],
            total=10,
            completed=5,
            failed=1,
            in_progress=2,
            queued=2,
            success_rate=0.5,
            all_complete=False,
        )

        assert status.batch_id == "test-batch"
        assert status.total == 10
        assert status.completed == 5


@pytest.mark.unit
class TestDocumentModels:
    """Test document-related models."""

    def test_document_status_creation(self):
        """DocumentStatus can be created."""
        status = DocumentStatus(
            document_id="doc1",
            status=DocumentState.COMPLETED,
            start_time=datetime.now(),
            end_time=datetime.now(),
            num_pages=5,
        )

        assert status.document_id == "doc1"
        assert status.status == DocumentState.COMPLETED
        assert status.num_pages == 5

    def test_document_status_optional_fields(self):
        """DocumentStatus works with optional fields as None."""
        status = DocumentStatus(
            document_id="doc1",
            status=DocumentState.QUEUED,
            start_time=None,
            end_time=None,
        )

        assert status.document_id == "doc1"
        assert status.start_time is None
        assert status.end_time is None


@pytest.mark.unit
class TestConfigModels:
    """Test config-related models."""

    def test_config_create_result(self):
        """ConfigCreateResult can be created."""
        result = ConfigCreateResult(
            yaml_content="key: value", output_path="config.yaml"
        )

        assert result.yaml_content == "key: value"
        assert result.output_path == "config.yaml"

    def test_config_validation_result(self):
        """ConfigValidationResult can be created."""
        result = ConfigValidationResult(
            valid=False, errors=["Error 1"], warnings=["Warning 1"]
        )

        assert result.valid is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1


@pytest.mark.unit
class TestDeletionModels:
    """Test deletion-related models."""

    def test_document_deletion_result(self):
        """DocumentDeletionResult can be created."""
        result = DocumentDeletionResult(
            success=True,
            object_key="batch-123/doc1.pdf",
            deleted={"input_file": True, "output_files": 5},
            errors=[],
        )

        assert result.success is True
        assert result.object_key == "batch-123/doc1.pdf"
        assert result.deleted["input_file"] is True

    def test_batch_deletion_result(self):
        """BatchDeletionResult can be created."""
        result = BatchDeletionResult(
            success=True,
            deleted_count=2,
            failed_count=0,
            total_count=2,
            dry_run=False,
            results=[],
        )

        assert result.success is True
        assert result.deleted_count == 2
        assert result.dry_run is False
