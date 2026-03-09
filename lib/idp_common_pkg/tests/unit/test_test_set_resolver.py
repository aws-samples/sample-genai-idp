import importlib.util
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock environment variables and dependencies before importing
with patch.dict(
    os.environ,
    {
        "TRACKING_TABLE": "test-table",
        "INPUT_BUCKET": "test-bucket",
        "TEST_SET_BUCKET": "test-set-bucket",
        "TEST_SET_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        "AWS_REGION": "us-east-1",
    },
):
    with patch("idp_common.dynamodb.DynamoDBClient"):
        # Import the specific lambda module
        spec = importlib.util.spec_from_file_location(
            "test_set_index",
            os.path.join(
                os.path.dirname(__file__),
                "../../../../nested/appsync/src/lambda/test_set_resolver/index.py",
            ),
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not load test_set_resolver module")
        test_set_index = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_set_index)


@pytest.mark.unit
class TestTestSetResolver:
    def test_handler_field_routing(self):
        """Test that handler routes to correct functions"""
        with patch.object(test_set_index, "add_test_set") as mock_add:
            mock_add.return_value = {"id": "test"}
            event = {"info": {"fieldName": "addTestSet"}, "arguments": {}}
            test_set_index.handler(event, {})
            mock_add.assert_called_once()

        with patch.object(test_set_index, "get_test_sets") as mock_get:
            mock_get.return_value = []
            event = {"info": {"fieldName": "getTestSets"}}
            test_set_index.handler(event, {})
            mock_get.assert_called_once()

    def test_handler_unknown_field(self):
        """Test handler with unknown field"""
        event = {"info": {"fieldName": "unknown"}, "arguments": {}}
        with pytest.raises(Exception, match="Unknown field: unknown"):
            test_set_index.handler(event, {})

    @patch("uuid.uuid4")
    @patch("datetime.datetime")
    @patch("boto3.client")
    @patch.dict(
        os.environ,
        {
            "TEST_SET_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
            "TRACKING_TABLE": "test-table",
            "TEST_SET_BUCKET": "test-set-bucket",
        },
    )
    def test_add_test_set_structure(self, mock_boto3, mock_datetime, mock_uuid):
        """Test add_test_set returns correct structure"""
        mock_uuid.return_value = "test-id"
        mock_datetime.utcnow.return_value.isoformat.return_value = "2025-10-17T16:00:00"

        # Mock SQS client
        mock_sqs = Mock()
        mock_boto3.return_value = mock_sqs

        with patch.object(test_set_index.db_client, "put_item") as mock_put:
            args = {
                "name": "test",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "bucketType": "input",
            }
            result = test_set_index.add_test_set(args)

            mock_put.assert_called_once()
            assert result["id"] == "test"  # ID is generated from name
            assert result["name"] == "test"
            assert result["name"] == "test"
            assert result["filePattern"] == "*.pdf"
            assert result["fileCount"] == 5
            assert "createdAt" in result

    @patch.dict(os.environ, {"TEST_SET_BUCKET": "test-set-bucket"})
    def test_delete_test_sets_calls_client(self):
        """Test delete_test_sets uses DynamoDB client"""
        with patch.object(test_set_index.db_client, "delete_item") as mock_delete:
            args = {"testSetIds": ["id1", "id2"]}
            result = test_set_index.delete_test_sets(args)

            assert mock_delete.call_count == 2
            assert result is True

    @patch.dict(
        os.environ, {"INPUT_BUCKET": "test-bucket", "TRACKING_TABLE": "test-table"}
    )
    def test_get_test_sets_uses_gsi_and_batch(self):
        """Test get_test_sets uses GSI query + BatchGetItem"""
        with patch.object(test_set_index, "find_matching_files") as mock_find_files:
            mock_find_files.return_value = ["file1.pdf", "file2.pdf", "file3.pdf"]

            with patch.object(test_set_index, "boto3") as mock_boto3:
                # Mock GSI query returning keys
                mock_table = MagicMock()
                mock_table.query.return_value = {
                    "Items": [{"PK": "testset#test-id", "SK": "metadata"}]
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                # Mock BatchGetItem returning full records
                mock_boto3.resource.return_value.batch_get_item.return_value = {
                    "Responses": {
                        "test-table": [
                            {
                                "PK": "testset#test-id",
                                "SK": "metadata",
                                "id": "test-id",
                                "name": "test-name",
                                "filePattern": "*.pdf",
                                "fileCount": 5,
                                "createdAt": "2025-10-17T16:00:00Z",
                            }
                        ]
                    }
                }

                result = test_set_index.get_test_sets()

                mock_table.query.assert_called_once()
                assert len(result) == 1
                assert result[0]["id"] == "test-id"

    @patch.dict("os.environ", {"INPUT_BUCKET": "test-bucket"})
    def test_list_input_bucket_files(self):
        """Test list_input_bucket_files calls find_matching_files"""
        with patch.object(test_set_index, "find_matching_files") as mock_find:
            mock_find.return_value = ["file1.pdf", "file2.pdf"]

            args = {"filePattern": "*.pdf", "bucketType": "input"}
            result = test_set_index.list_bucket_files(args)

            mock_find.assert_called_once_with("test-bucket", "*.pdf")
            assert result == ["file1.pdf", "file2.pdf"]
