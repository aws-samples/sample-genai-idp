# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Evaluation operations (mocked), focused on use_as_baseline.
"""

from unittest.mock import Mock, patch

import pytest

from idp_sdk import IDPClient
from idp_sdk.exceptions import IDPProcessingError, IDPResourceNotFoundError
from idp_sdk.models import UseAsBaselineResult


@pytest.mark.unit
class TestUseAsBaselineOperation:
    """Test the EvaluationOperation.use_as_baseline delegation."""

    @patch("idp_sdk._core.evaluation_processor.EvaluationProcessor")
    def test_use_as_baseline_success(self, mock_processor):
        mock_instance = Mock()
        mock_instance.use_as_baseline.return_value = {
            "document_id": "loan-123/package.pdf",
            "files_copied": 15,
            "evaluation_status": "BASELINE_AVAILABLE",
            "timestamp": "2024-01-01T00:00:00",
        }
        mock_processor.return_value = mock_instance

        client = IDPClient(stack_name="test-stack")
        result = client.evaluation.use_as_baseline(document_id="loan-123/package.pdf")

        assert isinstance(result, UseAsBaselineResult)
        assert result.document_id == "loan-123/package.pdf"
        assert result.files_copied == 15
        assert result.evaluation_status == "BASELINE_AVAILABLE"
        mock_instance.use_as_baseline.assert_called_once_with(
            document_id="loan-123/package.pdf"
        )

    @patch("idp_sdk._core.evaluation_processor.EvaluationProcessor")
    def test_use_as_baseline_not_found(self, mock_processor):
        mock_instance = Mock()
        mock_instance.use_as_baseline.side_effect = FileNotFoundError(
            "No output objects found"
        )
        mock_processor.return_value = mock_instance

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(IDPResourceNotFoundError):
            client.evaluation.use_as_baseline(document_id="missing.pdf")

    @patch("idp_sdk._core.evaluation_processor.EvaluationProcessor")
    def test_use_as_baseline_copy_error(self, mock_processor):
        mock_instance = Mock()
        mock_instance.use_as_baseline.side_effect = RuntimeError("copy boom")
        mock_processor.return_value = mock_instance

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(IDPProcessingError):
            client.evaluation.use_as_baseline(document_id="doc.pdf")


@pytest.mark.unit
class TestUseAsBaselineProcessor:
    """Test EvaluationProcessor.use_as_baseline copy + status logic."""

    def _make_processor(self):
        """Build a processor without touching AWS (bypass __init__)."""
        from idp_sdk._core.evaluation_processor import EvaluationProcessor

        proc = EvaluationProcessor.__new__(EvaluationProcessor)
        proc.s3 = Mock()
        proc.dynamodb = Mock()
        proc.resources = {
            "OutputBucket": "output-bucket",
            "EvaluationBaselineBucket": "baseline-bucket",
            "DocumentsTable": "tracking-table",
        }
        return proc

    def test_copies_all_objects_and_sets_status(self):
        proc = self._make_processor()

        paginator = Mock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "doc.pdf/pages/1.json"}]},
            {"Contents": [{"Key": "doc.pdf/sections/1/result.json"}]},
        ]
        proc.s3.get_paginator.return_value = paginator
        table = Mock()
        proc.dynamodb.Table.return_value = table

        result = proc.use_as_baseline("doc.pdf")

        assert result["files_copied"] == 2
        assert result["evaluation_status"] == "BASELINE_AVAILABLE"
        # Prefix must be document-id + "/" so sibling prefixes don't match
        paginator.paginate.assert_called_once_with(
            Bucket="output-bucket", Prefix="doc.pdf/"
        )
        assert proc.s3.copy_object.call_count == 2
        # Status transitions: BASELINE_COPYING then BASELINE_AVAILABLE
        statuses = [
            c.kwargs["ExpressionAttributeValues"][":es"]
            for c in table.update_item.call_args_list
        ]
        assert statuses == ["BASELINE_COPYING", "BASELINE_AVAILABLE"]

    def test_raises_when_no_output(self):
        proc = self._make_processor()
        paginator = Mock()
        paginator.paginate.return_value = [{}]  # no Contents
        proc.s3.get_paginator.return_value = paginator

        with pytest.raises(FileNotFoundError):
            proc.use_as_baseline("missing.pdf")
        proc.s3.copy_object.assert_not_called()

    def test_sets_error_status_on_copy_failure(self):
        proc = self._make_processor()
        paginator = Mock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "doc.pdf/pages/1.json"}]}
        ]
        proc.s3.get_paginator.return_value = paginator
        proc.s3.copy_object.side_effect = RuntimeError("copy failed")
        table = Mock()
        proc.dynamodb.Table.return_value = table

        with pytest.raises(RuntimeError):
            proc.use_as_baseline("doc.pdf")

        statuses = [
            c.kwargs["ExpressionAttributeValues"][":es"]
            for c in table.update_item.call_args_list
        ]
        assert statuses == ["BASELINE_COPYING", "BASELINE_ERROR"]
