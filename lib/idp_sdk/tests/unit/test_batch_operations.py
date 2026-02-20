# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Batch operations (mocked).
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from idp_sdk import IDPClient
from idp_sdk.models import BatchListResult, BatchProcessResult


@pytest.mark.unit
@pytest.mark.batch
class TestBatchOperationsMocked:
    """Test batch operations with mocked AWS calls."""

    @patch("idp_sdk.core.batch_processor.BatchProcessor")
    def test_list_batches(self, mock_processor):
        """Test listing batches."""
        # Setup mock
        mock_instance = Mock()
        mock_instance.list_batches.return_value = {
            "batches": [
                {
                    "batch_id": "batch-1",
                    "document_ids": ["doc1"],
                    "queued": 1,
                    "failed": 0,
                    "timestamp": "2024-01-01",
                }
            ],
            "count": 1,
        }
        mock_processor.return_value = mock_instance

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.batch.list(limit=5)

        assert isinstance(result, BatchListResult)
        assert result.count == 1
        assert len(result.batches) == 1

    @patch("idp_sdk.core.batch_processor.BatchProcessor")
    def test_run_batch(self, mock_processor):
        """Test running a batch."""
        # Setup mock
        mock_instance = Mock()
        mock_instance.process_batch.return_value = {
            "batch_id": "test-batch",
            "document_ids": ["doc1", "doc2"],
            "queued": 2,
            "uploaded": 2,
            "failed": 0,
            "source": "./test/",
            "output_prefix": "test",
            "timestamp": datetime.now().isoformat(),
        }
        mock_processor.return_value = mock_instance

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.batch.process(manifest="test.csv")

        assert isinstance(result, BatchProcessResult)
        assert result.batch_id == "test-batch"
        assert len(result.document_ids) == 2

    def test_batch_requires_stack(self):
        """Test batch operations require stack name."""
        client = IDPClient()

        with pytest.raises(Exception):
            client.batch.list()
