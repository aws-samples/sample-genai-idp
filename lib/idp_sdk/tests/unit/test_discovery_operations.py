# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Discovery operations (mocked).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from idp_sdk import IDPClient
from idp_sdk.exceptions import IDPConfigurationError, IDPResourceNotFoundError
from idp_sdk.models import DiscoveryBatchResult, DiscoveryResult

SAMPLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "Invoice",
    "x-aws-idp-document-type": "Invoice",
    "type": "object",
    "description": "Standard commercial invoice",
    "properties": {
        "InvoiceNumber": {"type": "string", "description": "Invoice number"},
        "TotalAmount": {"type": "number", "description": "Total amount due"},
    },
}


@pytest.mark.unit
class TestDiscoveryOperations:
    """Test discovery operations with mocked dependencies."""

    def test_discovery_namespace_exists(self):
        """Test that discovery namespace is registered on IDPClient."""
        client = IDPClient(stack_name="test-stack")
        assert hasattr(client, "discovery")
        assert client.discovery is not None

    def test_discovery_requires_stack(self):
        """Test that discovery.run requires a stack name."""
        client = IDPClient()  # No stack name
        with pytest.raises(IDPConfigurationError):
            client.discovery.run("./doc.pdf")

    def test_discovery_file_not_found(self):
        """Test that discovery.run raises FileNotFoundError for missing file."""
        client = IDPClient(stack_name="test-stack")
        with pytest.raises(FileNotFoundError, match="Document not found"):
            client.discovery.run("/nonexistent/path/doc.pdf")

    def test_discovery_ground_truth_not_found(self, tmp_path):
        """Test that discovery.run raises FileNotFoundError for missing ground truth."""
        # Create a temp document
        doc_file = tmp_path / "test.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test content")

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(FileNotFoundError, match="Ground truth file not found"):
            client.discovery.run(
                str(doc_file),
                ground_truth_path="/nonexistent/gt.json",
            )

    @patch("idp_sdk.operations.discovery.DiscoveryOperation._cleanup_s3")
    @patch(
        "idp_sdk.operations.discovery.DiscoveryOperation._get_last_discovered_schema"
    )
    @patch("idp_common.discovery.classes_discovery.ClassesDiscovery")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._upload_to_s3")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._get_discovery_resources")
    def test_discovery_run_success(
        self,
        mock_get_resources,
        mock_upload,
        mock_discovery_class,
        mock_get_schema,
        mock_cleanup,
        tmp_path,
    ):
        """Test successful discovery run without ground truth."""
        # Setup mocks
        mock_get_resources.return_value = {
            "input_bucket": "test-input-bucket",
            "config_table": "test-config-table",
        }
        mock_upload.return_value = "discovery-sdk/abc12345/test.pdf"

        mock_discovery = MagicMock()
        mock_discovery.discovery_classes_with_document.return_value = {
            "status": "SUCCESS"
        }
        mock_discovery_class.return_value = mock_discovery

        mock_get_schema.return_value = SAMPLE_SCHEMA

        # Create temp document
        doc_file = tmp_path / "invoice.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test content")

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run(str(doc_file))

        assert isinstance(result, DiscoveryResult)
        assert result.status == "SUCCESS"
        assert result.document_class == "Invoice"
        assert result.json_schema == SAMPLE_SCHEMA
        assert result.error is None

        # Verify ClassesDiscovery was called correctly
        mock_discovery.discovery_classes_with_document.assert_called_once()

        # Verify cleanup was called
        mock_cleanup.assert_called()

    @patch("idp_sdk.operations.discovery.DiscoveryOperation._cleanup_s3")
    @patch(
        "idp_sdk.operations.discovery.DiscoveryOperation._get_last_discovered_schema"
    )
    @patch("idp_common.discovery.classes_discovery.ClassesDiscovery")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._upload_to_s3")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._get_discovery_resources")
    def test_discovery_run_with_ground_truth(
        self,
        mock_get_resources,
        mock_upload,
        mock_discovery_class,
        mock_get_schema,
        mock_cleanup,
        tmp_path,
    ):
        """Test successful discovery run with ground truth."""
        # Setup mocks
        mock_get_resources.return_value = {
            "input_bucket": "test-input-bucket",
            "config_table": "test-config-table",
        }
        mock_upload.side_effect = [
            "discovery-sdk/abc/doc.pdf",
            "discovery-sdk/abc/gt.json",
        ]

        mock_discovery = MagicMock()
        mock_discovery.discovery_classes_with_document_and_ground_truth.return_value = {
            "status": "SUCCESS"
        }
        mock_discovery_class.return_value = mock_discovery

        mock_get_schema.return_value = SAMPLE_SCHEMA

        # Create temp files
        doc_file = tmp_path / "invoice.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test content")
        gt_file = tmp_path / "invoice-gt.json"
        gt_file.write_text(json.dumps({"InvoiceNumber": "INV-001"}))

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run(
            str(doc_file),
            ground_truth_path=str(gt_file),
        )

        assert result.status == "SUCCESS"
        assert result.document_class == "Invoice"

        # Verify ground truth method was called
        mock_discovery.discovery_classes_with_document_and_ground_truth.assert_called_once()

        # Verify both files were uploaded
        assert mock_upload.call_count == 2

        # Verify both files were cleaned up
        assert mock_cleanup.call_count == 2

    @patch("idp_sdk.operations.discovery.DiscoveryOperation._cleanup_s3")
    @patch("idp_common.discovery.classes_discovery.ClassesDiscovery")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._upload_to_s3")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._get_discovery_resources")
    def test_discovery_run_failure(
        self,
        mock_get_resources,
        mock_upload,
        mock_discovery_class,
        mock_cleanup,
        tmp_path,
    ):
        """Test discovery run that fails."""
        # Setup mocks
        mock_get_resources.return_value = {
            "input_bucket": "test-input-bucket",
            "config_table": "test-config-table",
        }
        mock_upload.return_value = "discovery-sdk/abc/doc.pdf"

        mock_discovery = MagicMock()
        mock_discovery.discovery_classes_with_document.side_effect = Exception(
            "Bedrock model error"
        )
        mock_discovery_class.return_value = mock_discovery

        # Create temp document
        doc_file = tmp_path / "bad-doc.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test content")

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run(str(doc_file))

        assert result.status == "FAILED"
        assert "Bedrock model error" in result.error
        assert result.json_schema is None

        # Verify cleanup still happened
        mock_cleanup.assert_called()

    @patch("idp_sdk.operations.discovery.DiscoveryOperation._cleanup_s3")
    @patch(
        "idp_sdk.operations.discovery.DiscoveryOperation._get_last_discovered_schema"
    )
    @patch("idp_common.discovery.classes_discovery.ClassesDiscovery")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._upload_to_s3")
    @patch("idp_sdk.operations.discovery.DiscoveryOperation._get_discovery_resources")
    def test_discovery_run_with_config_version(
        self,
        mock_get_resources,
        mock_upload,
        mock_discovery_class,
        mock_get_schema,
        mock_cleanup,
        tmp_path,
    ):
        """Test discovery run with specific config version."""
        # Setup mocks
        mock_get_resources.return_value = {
            "input_bucket": "test-input-bucket",
            "config_table": "test-config-table",
        }
        mock_upload.return_value = "discovery-sdk/abc/doc.pdf"

        mock_discovery = MagicMock()
        mock_discovery.discovery_classes_with_document.return_value = {
            "status": "SUCCESS"
        }
        mock_discovery_class.return_value = mock_discovery

        mock_get_schema.return_value = SAMPLE_SCHEMA

        # Create temp document
        doc_file = tmp_path / "form.pdf"
        doc_file.write_bytes(b"%PDF-1.4 test content")

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run(str(doc_file), config_version="v2")

        assert result.status == "SUCCESS"
        assert result.config_version == "v2"

        # Verify ClassesDiscovery was initialized with version
        mock_discovery_class.assert_called_once_with(
            input_bucket="test-input-bucket",
            input_prefix="discovery-sdk/abc/doc.pdf",
            region=None,
            version="v2",
        )

    @patch("boto3.client")
    def test_get_discovery_resources(self, mock_boto3):
        """Test _get_discovery_resources finds required resources."""
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-config-table",
                    },
                    {
                        "LogicalResourceId": "InputBucket",
                        "PhysicalResourceId": "test-input-bucket",
                    },
                ]
            }
        ]

        client = IDPClient(stack_name="test-stack")
        resources = client.discovery._get_discovery_resources("test-stack")

        assert resources["input_bucket"] == "test-input-bucket"
        assert resources["config_table"] == "test-config-table"

    @patch("boto3.client")
    def test_get_discovery_resources_missing_bucket(self, mock_boto3):
        """Test _get_discovery_resources raises when bucket not found."""
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-config-table",
                    },
                ]
            }
        ]

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(IDPResourceNotFoundError, match="Input S3 bucket not found"):
            client.discovery._get_discovery_resources("test-stack")

    @patch("boto3.client")
    def test_get_discovery_resources_missing_config_table(self, mock_boto3):
        """Test _get_discovery_resources raises when config table not found."""
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "InputBucket",
                        "PhysicalResourceId": "test-input-bucket",
                    },
                ]
            }
        ]

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(
            IDPResourceNotFoundError, match="ConfigurationTable not found"
        ):
            client.discovery._get_discovery_resources("test-stack")


@pytest.mark.unit
class TestDiscoveryBatchOperations:
    """Test batch discovery operations."""

    @patch("idp_sdk.operations.discovery.DiscoveryOperation.run")
    def test_batch_discovery_success(self, mock_run, tmp_path):
        """Test successful batch discovery."""
        # Create temp files
        doc1 = tmp_path / "doc1.pdf"
        doc1.write_bytes(b"%PDF test")
        doc2 = tmp_path / "doc2.pdf"
        doc2.write_bytes(b"%PDF test")

        # Setup mock
        mock_run.side_effect = [
            DiscoveryResult(
                status="SUCCESS",
                document_class="Invoice",
                json_schema=SAMPLE_SCHEMA,
                document_path=str(doc1),
            ),
            DiscoveryResult(
                status="SUCCESS",
                document_class="W2",
                json_schema=SAMPLE_SCHEMA,
                document_path=str(doc2),
            ),
        ]

        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run_batch([str(doc1), str(doc2)])

        assert isinstance(result, DiscoveryBatchResult)
        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
        assert len(result.results) == 2

    @patch("idp_sdk.operations.discovery.DiscoveryOperation.run")
    def test_batch_discovery_partial_failure(self, mock_run, tmp_path):
        """Test batch discovery with partial failures."""
        doc1 = tmp_path / "doc1.pdf"
        doc1.write_bytes(b"%PDF test")
        doc2 = tmp_path / "doc2.pdf"
        doc2.write_bytes(b"%PDF test")

        mock_run.side_effect = [
            DiscoveryResult(
                status="SUCCESS",
                document_class="Invoice",
                json_schema=SAMPLE_SCHEMA,
                document_path=str(doc1),
            ),
            DiscoveryResult(
                status="FAILED",
                error="Bedrock error",
                document_path=str(doc2),
            ),
        ]

        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run_batch([str(doc1), str(doc2)])

        assert result.total == 2
        assert result.succeeded == 1
        assert result.failed == 1

    def test_batch_discovery_mismatched_ground_truth(self, tmp_path):
        """Test batch discovery raises on mismatched ground truth count."""
        doc1 = tmp_path / "doc1.pdf"
        doc1.write_bytes(b"%PDF test")

        client = IDPClient(stack_name="test-stack")
        with pytest.raises(IDPConfigurationError, match="must match"):
            client.discovery.run_batch(
                [str(doc1)],
                ground_truth_paths=["gt1.json", "gt2.json"],
            )

    @patch("idp_sdk.operations.discovery.DiscoveryOperation.run")
    def test_batch_discovery_with_selective_ground_truth(self, mock_run, tmp_path):
        """Test batch discovery with ground truth for only some docs."""
        doc1 = tmp_path / "doc1.pdf"
        doc1.write_bytes(b"%PDF test")
        doc2 = tmp_path / "doc2.pdf"
        doc2.write_bytes(b"%PDF test")

        mock_run.return_value = DiscoveryResult(
            status="SUCCESS",
            document_class="Test",
            json_schema=SAMPLE_SCHEMA,
        )

        client = IDPClient(stack_name="test-stack")
        result = client.discovery.run_batch(
            [str(doc1), str(doc2)],
            ground_truth_paths=[None, "./gt.json"],
        )

        assert result.total == 2
        # First call should have no ground truth
        first_call = mock_run.call_args_list[0]
        assert first_call.kwargs.get("ground_truth_path") is None
        # Second call should have ground truth
        second_call = mock_run.call_args_list[1]
        assert second_call.kwargs.get("ground_truth_path") == "./gt.json"


@pytest.mark.unit
class TestDiscoveryModels:
    """Test discovery result models."""

    def test_discovery_result_success(self):
        """Test creating a successful DiscoveryResult."""
        result = DiscoveryResult(
            status="SUCCESS",
            document_class="Invoice",
            json_schema=SAMPLE_SCHEMA,
            config_version="v1",
            document_path="./invoice.pdf",
        )
        assert result.status == "SUCCESS"
        assert result.document_class == "Invoice"
        assert result.json_schema["$id"] == "Invoice"
        assert result.error is None

    def test_discovery_result_failure(self):
        """Test creating a failed DiscoveryResult."""
        result = DiscoveryResult(
            status="FAILED",
            error="Model invocation failed",
            document_path="./bad.pdf",
        )
        assert result.status == "FAILED"
        assert result.error == "Model invocation failed"
        assert result.json_schema is None
        assert result.document_class is None

    def test_discovery_batch_result(self):
        """Test creating a DiscoveryBatchResult."""
        results = [
            DiscoveryResult(status="SUCCESS", document_class="A"),
            DiscoveryResult(status="FAILED", error="err"),
            DiscoveryResult(status="SUCCESS", document_class="B"),
        ]
        batch = DiscoveryBatchResult(
            total=3,
            succeeded=2,
            failed=1,
            results=results,
        )
        assert batch.total == 3
        assert batch.succeeded == 2
        assert batch.failed == 1
        assert len(batch.results) == 3
