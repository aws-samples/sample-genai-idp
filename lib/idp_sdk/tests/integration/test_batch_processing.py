# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Integration tests for Batch processing operations.

AWS Services Integrated:
- S3 (InputBucket for uploads, OutputBucket for results)
- Step Functions (State Machine for workflow execution)
- DynamoDB (DocumentsTable for batch tracking)
- SQS (Document queue for processing)

Operations Tested:
- batch.list() - List batches from DynamoDB
- batch.get_status() - Query batch and document status
- batch.download_results() - Download processed results from S3

Prerequisites:
- Deployed IDP stack
- AWS credentials configured
- At least one processed batch (for download tests)
"""

import pytest


@pytest.mark.integration
@pytest.mark.batch
class TestBatchProcessing:
    """Test batch processing operations against real AWS stack."""

    def test_list_batches(self, client):
        """Test listing recent batches."""
        result = client.batch.list(limit=5)

        assert hasattr(result, "batches")
        assert hasattr(result, "count")
        assert isinstance(result.batches, list)
        assert result.count >= 0

    def test_get_batch_status(self, client):
        """Test getting batch status."""
        # Get a recent batch
        batches = client.batch.list(limit=1)

        if not batches.batches:
            pytest.skip("No batches found")

        batch_id = batches.batches[0].batch_id
        status = client.batch.get_status(batch_id=batch_id)

        assert status.batch_id == batch_id
        assert hasattr(status, "total")
        assert hasattr(status, "completed")
        assert hasattr(status, "failed")
        assert hasattr(status, "in_progress")
        assert status.total >= 0

    def test_download_results(self, client):
        """Test downloading batch results."""
        import tempfile

        # Get a completed batch
        batches = client.batch.list(limit=5)
        completed_batch = None

        for batch in batches.batches:
            status = client.batch.get_status(batch_id=batch.batch_id)
            if status.completed > 0:
                completed_batch = batch.batch_id
                break

        if not completed_batch:
            pytest.skip("No completed batches found")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = client.batch.download_results(
                batch_id=completed_batch, output_dir=tmpdir, file_types=["summary"]
            )

            assert result.files_downloaded >= 0
            assert result.documents_downloaded >= 0
            assert result.output_dir == tmpdir
