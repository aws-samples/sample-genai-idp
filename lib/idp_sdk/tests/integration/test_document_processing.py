# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Integration tests for Document processing operations.

AWS Services Integrated:
- DynamoDB (DocumentsTable for status tracking)
- S3 (InputBucket, OutputBucket for storage)
- Step Functions (Document processing workflow)

Operations Tested:
- document.get_status() - Get document status from DynamoDB
- document.delete() - Delete document from S3 and DynamoDB
- batch.delete_documents() - Batch deletion operations

Prerequisites:
- Deployed IDP stack
- AWS credentials configured
- At least one processed document
"""

import pytest


@pytest.mark.integration
@pytest.mark.document
class TestDocumentProcessing:
    """Test document processing operations against real AWS stack."""

    def test_get_document_status(self, client):
        """Test getting document status from DynamoDB."""
        # Get a recent document
        batches = client.batch.list(limit=1)

        if not batches.batches or not batches.batches[0].document_ids:
            pytest.skip("No documents found")

        document_id = batches.batches[0].document_ids[0]
        status = client.document.get_status(document_id=document_id)

        assert status.document_id == document_id
        assert hasattr(status, "status")
        assert status.status in ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "UNKNOWN"]

    def test_delete_document_dry_run(self, client):
        """Test deleting a document (dry run) from S3 and DynamoDB."""
        # Get a recent document
        batches = client.batch.list(limit=1)

        if not batches.batches or not batches.batches[0].document_ids:
            pytest.skip("No documents found")

        document_id = batches.batches[0].document_ids[0]
        result = client.document.delete(document_id=document_id, dry_run=True)

        assert hasattr(result, "success")
        assert hasattr(result, "object_key")

    def test_batch_delete_documents_dry_run(self, client):
        """Test batch document deletion (dry run)."""
        # Get recent batch
        batches = client.batch.list(limit=1)

        if not batches.batches:
            pytest.skip("No batches found")

        batch_id = batches.batches[0].batch_id
        result = client.batch.delete_documents(batch_id=batch_id, dry_run=True)

        assert hasattr(result, "success")
        assert hasattr(result, "total_count")
        assert result.dry_run is True
