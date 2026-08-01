import importlib.util
import json
import os
from unittest.mock import MagicMock, Mock, patch

import boto3
import pytest
from moto import mock_aws

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
                "../../../../nested/api-resolvers/src/lambda/test_set_resolver/index.py",
            ),
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not load test_set_resolver module")
        test_set_index = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_set_index)


# Test Studio test-set operations are Admin+Author; supply an authorized
# Cognito identity on handler events so the defense-in-depth group gate passes.
_ADMIN_IDENTITY = {
    "claims": {"cognito:groups": ["Admin"], "email": "admin@example.com"}
}


def _seed_test_set(table, test_set_id, **extra):
    """Write a minimal, never-published test-set metadata item."""
    item = {"PK": f"testset#{test_set_id}", "SK": "metadata", "id": test_set_id}
    item.update(extra)
    table.put_item(Item=item)


@pytest.fixture
def publish_table():
    """A real (moto) tracking table wired into the resolver's db_client.

    Version allocation depends on DynamoDB's atomic ADD, which a MagicMock
    cannot express — a mocked table would report whatever the test told it to
    and the concurrency guarantee would go untested. The module-level
    db_client is a mock (patched at import), so point its get_item/put_item at
    the real table for the duration of the test.
    """
    # The resolver builds its own boto3 resource with no explicit region, so it
    # picks up the ambient one. Pin the region for both here — other tests in
    # the suite mutate AWS_DEFAULT_REGION, and a mismatch makes the moto table
    # invisible to the resolver (ResourceNotFoundException on UpdateItem).
    region_env = {
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "TRACKING_TABLE": "test-table",
    }
    with mock_aws(), patch.dict(os.environ, region_env):
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-table",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        with _db_client_on(table):
            yield table


def _db_client_on(table):
    """Point the resolver's mocked db_client at a real moto table."""

    def _get_item(key):
        return table.get_item(Key=key).get("Item")

    def _put_item(item, condition_expression=None):
        kwargs = {"Item": item}
        if condition_expression:
            kwargs["ConditionExpression"] = condition_expression
        return table.put_item(**kwargs)

    def _update_item(
        key,
        update_expression,
        expression_attribute_names=None,
        expression_attribute_values=None,
        return_values="ALL_NEW",
    ):
        kwargs = {
            "Key": key,
            "UpdateExpression": update_expression,
            "ReturnValues": return_values,
        }
        if expression_attribute_names:
            kwargs["ExpressionAttributeNames"] = expression_attribute_names
        if expression_attribute_values:
            kwargs["ExpressionAttributeValues"] = expression_attribute_values
        return table.update_item(**kwargs)

    return _MultiPatch(
        patch.object(test_set_index.db_client, "get_item", side_effect=_get_item),
        patch.object(test_set_index.db_client, "put_item", side_effect=_put_item),
        patch.object(test_set_index.db_client, "update_item", side_effect=_update_item),
    )


class _MultiPatch:
    """Enter/exit several patches as one context manager."""

    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


@pytest.fixture
def labeling_env():
    """Real (moto) DynamoDB + S3 for the draft-labeling primitive.

    The harvester's whole job is moving JSON between real S3 keys and deciding
    what to overwrite, so mocked S3 clients would assert on call shapes instead
    of the actual outcome. Yields (table, s3_client).
    """
    region_env = {
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "TRACKING_TABLE": "test-table",
        "TEST_SET_BUCKET": "test-set-bucket",
        "TEST_RUNNER_FUNCTION_ARN": "arn:aws:lambda:us-east-1:123456789012:function:runner",
    }
    with mock_aws(), patch.dict(os.environ, region_env):
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-table",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-set-bucket")
        s3.create_bucket(Bucket="output-bucket")

        with _db_client_on(table), patch.object(test_set_index, "s3_client", s3):
            yield table, s3


def _seed_pipeline_result(s3, key, inference, explainability=None):
    """Write a pipeline section extraction result to the output bucket."""
    body = {"inference_result": inference}
    if explainability is not None:
        body["explainability_info"] = explainability
    s3.put_object(
        Bucket="output-bucket", Key=key, Body=json.dumps(body).encode("utf-8")
    )
    return f"s3://output-bucket/{key}"


def _seed_completed_run(table, job_id, test_set_id, files, sections_by_file):
    """Write a finished test run plus its per-document items."""
    table.put_item(
        Item={
            "PK": f"testrun#{job_id}",
            "SK": "metadata",
            "TestSetId": test_set_id,
            "Files": files,
            "Status": "RUNNING",
        }
    )
    for file_name in files:
        table.put_item(
            Item={
                "PK": f"doc#{job_id}/{file_name}",
                "SK": "none",
                "ObjectStatus": "COMPLETED",
                "Sections": sections_by_file.get(file_name, []),
            }
        )


@pytest.mark.unit
class TestTestSetResolver:
    def test_handler_field_routing(self):
        """Test that handler routes to correct functions"""
        with patch.object(test_set_index, "add_test_set") as mock_add:
            mock_add.return_value = {"id": "test"}
            event = {
                "info": {"fieldName": "addTestSet"},
                "arguments": {},
                "identity": _ADMIN_IDENTITY,
            }
            test_set_index.handler(event, {})
            mock_add.assert_called_once()

        with patch.object(test_set_index, "get_test_sets") as mock_get:
            mock_get.return_value = []
            event = {"info": {"fieldName": "getTestSets"}, "identity": _ADMIN_IDENTITY}
            test_set_index.handler(event, {})
            mock_get.assert_called_once()

        with patch.object(test_set_index, "update_test_set") as mock_update:
            mock_update.return_value = {"id": "test"}
            event = {
                "info": {"fieldName": "updateTestSet"},
                "arguments": {},
                "identity": _ADMIN_IDENTITY,
            }
            test_set_index.handler(event, {})
            mock_update.assert_called_once()

    def test_handler_unknown_field(self):
        """Test handler with unknown field"""
        event = {
            "info": {"fieldName": "unknown"},
            "arguments": {},
            "identity": _ADMIN_IDENTITY,
        }
        with pytest.raises(Exception, match="Unknown field: unknown"):
            test_set_index.handler(event, {})

    def test_handler_rejects_viewer(self):
        """Defense-in-depth: a Viewer must not reach any test-set operation."""
        event = {
            "info": {"fieldName": "addTestSet"},
            "arguments": {},
            "identity": {"claims": {"cognito:groups": ["Viewer"]}},
        }
        with pytest.raises(Exception, match="requires Admin or Author group"):
            test_set_index.handler(event, {})

    def test_handler_allows_direct_lambda_invoke_no_identity(self):
        """RBAC bypass: direct Lambda invocation (no identity) proceeds for CI/automation."""
        with patch.object(test_set_index, "get_test_sets") as mock_get:
            mock_get.return_value = []
            # Direct Lambda invoke: no 'identity' field (CI/automation path)
            event = {"info": {"fieldName": "getTestSets"}}
            # Should NOT raise - bypass works as designed
            test_set_index.handler(event, {})
            mock_get.assert_called_once()

    def test_handler_allows_direct_lambda_invoke_identity_none(self):
        """RBAC bypass: direct Lambda invocation (identity=None) proceeds for CI/automation."""
        with patch.object(test_set_index, "get_test_sets") as mock_get:
            mock_get.return_value = []
            # Direct Lambda invoke: identity explicitly None
            event = {"info": {"fieldName": "getTestSets"}, "identity": None}
            # Should NOT raise - bypass works as designed
            test_set_index.handler(event, {})
            mock_get.assert_called_once()

    def test_handler_still_enforces_rbac_for_appsync_viewer(self):
        """Regression guard: AppSync invocation with non-Admin/Author still raises."""
        # This is the same as test_handler_rejects_viewer but explicitly tests
        # that the RBAC bypass doesn't break AppSync RBAC enforcement
        event = {
            "info": {"fieldName": "getTestSets"},
            "identity": {"claims": {"cognito:groups": ["Viewer"]}},
        }
        with pytest.raises(Exception, match="requires Admin or Author group"):
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
                # 'source' maps through; absent on this record -> None (back-compat)
                assert result[0]["source"] is None

    @patch.dict(
        os.environ, {"INPUT_BUCKET": "test-bucket", "TRACKING_TABLE": "test-table"}
    )
    def test_get_test_sets_maps_source_when_present(self):
        """A record's 'source' attribute is returned in the mapped result."""
        with patch.object(test_set_index, "find_matching_files") as mock_find_files:
            mock_find_files.return_value = []
            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.query.return_value = {
                    "Items": [{"PK": "testset#syn-id", "SK": "metadata"}]
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table
                mock_boto3.resource.return_value.batch_get_item.return_value = {
                    "Responses": {
                        "test-table": [
                            {
                                "PK": "testset#syn-id",
                                "SK": "metadata",
                                "id": "syn-id",
                                "name": "syn-name",
                                "source": "synthetic",
                                "createdAt": "2025-10-17T16:00:00Z",
                            }
                        ]
                    }
                }
                result = test_set_index.get_test_sets()
                assert result[0]["source"] == "synthetic"

    def test_get_test_set_source_reads_marker(self):
        """_get_test_set_source returns 'synthetic' iff a '.source' marker exists."""
        s3 = MagicMock()
        # marker present -> synthetic
        s3.head_object.return_value = {}
        assert (
            test_set_index._get_test_set_source(s3, "bucket", "prefix") == "synthetic"
        )
        # marker absent (head_object raises) -> uploaded
        s3.head_object.side_effect = Exception("404")
        assert test_set_index._get_test_set_source(s3, "bucket", "prefix") == "uploaded"

    @patch.dict("os.environ", {"INPUT_BUCKET": "test-bucket"})
    def test_list_input_bucket_files(self):
        """Test list_input_bucket_files calls find_matching_files"""
        with patch.object(test_set_index, "find_matching_files") as mock_find:
            mock_find.return_value = ["file1.pdf", "file2.pdf"]

            args = {"filePattern": "*.pdf", "bucketType": "input"}
            result = test_set_index.list_bucket_files(args)

            mock_find.assert_called_once_with(
                "test-bucket", "*.pdf", modified_after=None
            )
            assert result == ["file1.pdf", "file2.pdf"]

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_description_only(self):
        """Test updating test set description only"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "old description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
                "documentClassType": "SINGLE_CLASS",
            }

            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.update_item.return_value = {
                    "Attributes": {
                        "id": "test-id",
                        "name": "test-set",
                        "description": "new description",
                        "filePattern": "*.pdf",
                        "fileCount": 5,
                        "createdAt": "2025-10-17T16:00:00Z",
                        "documentClassType": "SINGLE_CLASS",
                    }
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                args = {"input": {"id": "test-id", "description": "new description"}}
                result = test_set_index.update_test_set(args)

                # Verify update was called with correct expression
                mock_table.update_item.assert_called_once()
                call_args = mock_table.update_item.call_args
                assert "SET #desc = :desc" in call_args[1]["UpdateExpression"]
                assert (
                    call_args[1]["ExpressionAttributeValues"][":desc"]
                    == "new description"
                )
                assert (
                    call_args[1]["ExpressionAttributeNames"]["#desc"] == "description"
                )

                # Verify result
                assert result["id"] == "test-id"
                assert result["description"] == "new description"
                assert result["documentClassType"] == "SINGLE_CLASS"

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_document_class_type_only(self):
        """Test updating test set documentClassType only"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "test description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
            }

            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.update_item.return_value = {
                    "Attributes": {
                        "id": "test-id",
                        "name": "test-set",
                        "description": "test description",
                        "filePattern": "*.pdf",
                        "fileCount": 5,
                        "createdAt": "2025-10-17T16:00:00Z",
                        "documentClassType": "MULTI_CLASS",
                    }
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                args = {"input": {"id": "test-id", "documentClassType": "MULTI_CLASS"}}
                result = test_set_index.update_test_set(args)

                # Verify update was called with correct expression
                mock_table.update_item.assert_called_once()
                call_args = mock_table.update_item.call_args
                assert (
                    "SET documentClassType = :docType"
                    in call_args[1]["UpdateExpression"]
                )
                assert (
                    call_args[1]["ExpressionAttributeValues"][":docType"]
                    == "MULTI_CLASS"
                )

                # Verify result
                assert result["id"] == "test-id"
                assert result["documentClassType"] == "MULTI_CLASS"

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_remove_document_class_type(self):
        """Test removing documentClassType by setting to None"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "test description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
                "documentClassType": "SINGLE_CLASS",
            }

            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.update_item.return_value = {
                    "Attributes": {
                        "id": "test-id",
                        "name": "test-set",
                        "description": "test description",
                        "filePattern": "*.pdf",
                        "fileCount": 5,
                        "createdAt": "2025-10-17T16:00:00Z",
                    }
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                args = {"input": {"id": "test-id", "documentClassType": None}}
                result = test_set_index.update_test_set(args)

                # Verify update was called with REMOVE expression
                mock_table.update_item.assert_called_once()
                call_args = mock_table.update_item.call_args
                assert "REMOVE documentClassType" in call_args[1]["UpdateExpression"]
                # Should not have :docType in expression values when removing
                assert ":docType" not in call_args[1].get(
                    "ExpressionAttributeValues", {}
                )

                # Verify result has documentClassType as None (removed from DynamoDB)
                assert result["id"] == "test-id"
                assert result["documentClassType"] is None

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_both_fields(self):
        """Test updating both description and documentClassType"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "old description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
                "documentClassType": "SINGLE_CLASS",
            }

            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.update_item.return_value = {
                    "Attributes": {
                        "id": "test-id",
                        "name": "test-set",
                        "description": "new description",
                        "filePattern": "*.pdf",
                        "fileCount": 5,
                        "createdAt": "2025-10-17T16:00:00Z",
                        "documentClassType": "PACKET_SPLITTING",
                    }
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                args = {
                    "input": {
                        "id": "test-id",
                        "description": "new description",
                        "documentClassType": "PACKET_SPLITTING",
                    }
                }
                result = test_set_index.update_test_set(args)

                # Verify update was called with both fields in SET clause
                mock_table.update_item.assert_called_once()
                call_args = mock_table.update_item.call_args
                update_expr = call_args[1]["UpdateExpression"]
                assert "SET" in update_expr
                assert "#desc = :desc" in update_expr
                assert "documentClassType = :docType" in update_expr
                assert (
                    call_args[1]["ExpressionAttributeValues"][":desc"]
                    == "new description"
                )
                assert (
                    call_args[1]["ExpressionAttributeValues"][":docType"]
                    == "PACKET_SPLITTING"
                )

                # Verify result
                assert result["id"] == "test-id"
                assert result["description"] == "new description"
                assert result["documentClassType"] == "PACKET_SPLITTING"

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_description_and_remove_document_class_type(self):
        """Test updating description while removing documentClassType"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "old description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
                "documentClassType": "SINGLE_CLASS",
            }

            with patch.object(test_set_index, "boto3") as mock_boto3:
                mock_table = MagicMock()
                mock_table.update_item.return_value = {
                    "Attributes": {
                        "id": "test-id",
                        "name": "test-set",
                        "description": "new description",
                        "filePattern": "*.pdf",
                        "fileCount": 5,
                        "createdAt": "2025-10-17T16:00:00Z",
                    }
                }
                mock_boto3.resource.return_value.Table.return_value = mock_table

                args = {
                    "input": {
                        "id": "test-id",
                        "description": "new description",
                        "documentClassType": None,
                    }
                }
                result = test_set_index.update_test_set(args)

                # Verify update was called with SET and REMOVE
                mock_table.update_item.assert_called_once()
                call_args = mock_table.update_item.call_args
                update_expr = call_args[1]["UpdateExpression"]
                assert "SET #desc = :desc" in update_expr
                assert "REMOVE documentClassType" in update_expr
                assert (
                    call_args[1]["ExpressionAttributeValues"][":desc"]
                    == "new description"
                )

                # Verify result has documentClassType as None (removed from DynamoDB)
                assert result["id"] == "test-id"
                assert result["description"] == "new description"
                assert result["documentClassType"] is None

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_no_changes(self):
        """Test update_test_set with no actual changes"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = {
                "PK": "testset#test-id",
                "SK": "metadata",
                "id": "test-id",
                "name": "test-set",
                "description": "test description",
                "filePattern": "*.pdf",
                "fileCount": 5,
                "createdAt": "2025-10-17T16:00:00Z",
            }

            with patch.object(test_set_index.db_client, "update_item") as mock_update:
                args = {"input": {"id": "test-id"}}
                result = test_set_index.update_test_set(args)

                # Should not call update_item when there are no changes
                mock_update.assert_not_called()

                # Should return the current item
                assert result["id"] == "test-id"
                assert result["description"] == "test description"

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_invalid_description(self):
        """Test update_test_set with invalid description length"""
        args = {"input": {"id": "test-id", "description": "x" * 501}}

        with pytest.raises(Exception, match="Description cannot exceed 500 characters"):
            test_set_index.update_test_set(args)

    @patch.dict(
        os.environ,
        {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "test-set-bucket"},
    )
    def test_update_test_set_nonexistent_id(self):
        """Test update_test_set with non-existent test set ID"""
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = None

            args = {"input": {"id": "nonexistent-id", "description": "new description"}}

            with pytest.raises(Exception, match="Test set 'nonexistent-id' not found"):
                test_set_index.update_test_set(args)

    # -- Versioning -------------------------------------------------------

    def test_publish_first_version_sets_active_reference(self, publish_table):
        """Publishing with no prior versions creates v1 and makes it active."""
        _seed_test_set(publish_table, "ts1", source="uploaded", fileCount=10)

        result = test_set_index.publish_test_set_version(
            {"input": {"testSetId": "ts1", "label": "first"}}
        )

        assert result["version"] == 1
        assert result["label"] == "first"
        assert result["activeReference"] == 1
        # An immutable version item was written under SK=version#000001
        written = publish_table.get_item(
            Key={"PK": "testset#ts1", "SK": "version#000001"}
        )["Item"]
        assert written["ItemType"] == "testset_version"
        assert written["versionNumber"] == 1
        # The metadata pointers were advanced and the active reference set
        meta = publish_table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})[
            "Item"
        ]
        assert meta["latestVersion"] == 1
        assert meta["publishedVersion"] == 1
        assert meta["activeReference"] == 1

    def test_publish_increments_and_can_skip_active(self, publish_table):
        """Second publish is v2; setAsActiveReference=false leaves active alone."""
        _seed_test_set(publish_table, "ts1")
        test_set_index.publish_test_set_version({"input": {"testSetId": "ts1"}})

        result = test_set_index.publish_test_set_version(
            {"input": {"testSetId": "ts1", "setAsActiveReference": False}}
        )

        assert result["version"] == 2
        # active reference unchanged (still 1)
        assert result["activeReference"] == 1
        meta = publish_table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})[
            "Item"
        ]
        assert meta["latestVersion"] == 2
        assert meta["publishedVersion"] == 2
        assert meta["activeReference"] == 1

    def test_concurrent_publishes_get_distinct_versions(self, publish_table):
        """Two interleaved publishes must not collide on one version number.

        Guards the read-modify-write race: allocating from a previously-read
        latestVersion let both callers write version#000001, so the second
        silently overwrote the first's supposedly immutable version. The
        version number is now reserved by an atomic ADD, so interleaving the
        two reads still yields distinct versions and two surviving items.
        """
        _seed_test_set(publish_table, "ts1")

        real_get_item = test_set_index.db_client.get_item
        second_result = {}
        reentered = []

        def publish_other_first(key):
            """On the first caller's metadata read, run a whole second publish.

            This forces the worst-case interleaving — the first caller now
            holds a metadata snapshot taken before the second publish landed.
            The reentry flag is set *before* recursing so the nested publish's
            own metadata read doesn't trigger another one.
            """
            meta = real_get_item(key)
            if not reentered:
                reentered.append(True)
                second_result["r"] = test_set_index.publish_test_set_version(
                    {"input": {"testSetId": "ts1"}}
                )
            return meta

        with patch.object(
            test_set_index.db_client, "get_item", side_effect=publish_other_first
        ):
            first_result = test_set_index.publish_test_set_version(
                {"input": {"testSetId": "ts1"}}
            )

        versions = {second_result["r"]["version"], first_result["version"]}
        assert versions == {1, 2}, f"expected distinct versions, got {versions}"
        # Both immutable items survive — neither overwrote the other.
        stored = test_set_index.get_test_set_versions({"testSetId": "ts1"})
        assert [v["version"] for v in stored] == [1, 2]

    def test_publish_pointers_only_move_forward(self, publish_table):
        """An out-of-order publish must not rewind publishedVersion.

        Concurrent publishes can reach the pointer write in either order; the
        older version landing second must leave the pointers on the newer one.
        Seeding pointers ahead of the counter reproduces that end state: the
        reservation hands out v1 while the pointers already say v5.
        """
        _seed_test_set(
            publish_table, "ts1", publishedVersion=5, activeReference=5, latestVersion=0
        )

        result = test_set_index.publish_test_set_version(
            {"input": {"testSetId": "ts1"}}
        )

        # The version item is still written — this caller's work is not lost.
        assert result["version"] == 1
        assert (
            publish_table.get_item(Key={"PK": "testset#ts1", "SK": "version#000001"})[
                "Item"
            ]["versionNumber"]
            == 1
        )
        # But the pointers were NOT rewound to 1.
        meta = publish_table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})[
            "Item"
        ]
        assert meta["publishedVersion"] == 5
        assert meta["activeReference"] == 5

    def test_publish_nonexistent_test_set_raises(self, publish_table):
        with pytest.raises(Exception, match="Test set 'ghost' not found"):
            test_set_index.publish_test_set_version({"input": {"testSetId": "ghost"}})

    def test_publish_race_on_deleted_test_set_raises(self, publish_table):
        """A set deleted between the metadata read and the reservation must not
        be resurrected by update_item's upsert semantics."""
        _seed_test_set(publish_table, "ts1")
        real_get_item = test_set_index.db_client.get_item

        def delete_after_read(key):
            meta = real_get_item(key)
            publish_table.delete_item(Key={"PK": "testset#ts1", "SK": "metadata"})
            return meta

        with patch.object(
            test_set_index.db_client, "get_item", side_effect=delete_after_read
        ):
            with pytest.raises(Exception, match="Test set 'ts1' not found"):
                test_set_index.publish_test_set_version({"input": {"testSetId": "ts1"}})

        assert "Item" not in publish_table.get_item(
            Key={"PK": "testset#ts1", "SK": "metadata"}
        )

    @patch.dict(os.environ, {"TRACKING_TABLE": "test-table"})
    def test_get_test_set_versions_maps_and_sorts(self):
        with patch.object(test_set_index, "boto3") as mock_boto3:
            mock_table = MagicMock()
            mock_table.query.return_value = {
                "Items": [
                    {
                        "testSetId": "ts1",
                        "versionNumber": 2,
                        "label": "v2",
                        "fileCount": 12,
                        "createdAt": "2026-01-02T00:00:00Z",
                    },
                    {
                        "testSetId": "ts1",
                        "versionNumber": 1,
                        "label": "v1",
                        "fileCount": 10,
                        "createdAt": "2026-01-01T00:00:00Z",
                    },
                ]
            }
            mock_boto3.resource.return_value.Table.return_value = mock_table

            result = test_set_index.get_test_set_versions({"testSetId": "ts1"})

            assert [r["version"] for r in result] == [1, 2]  # ascending
            assert result[0]["label"] == "v1"
            assert result[1]["fileCount"] == 12

    # -- Membership editing: remove ---------------------------------------

    @patch.dict(
        os.environ, {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "ts-bucket"}
    )
    def test_remove_documents_deletes_input_and_baseline_and_recounts(self):
        with (
            patch.object(test_set_index.db_client, "get_item") as mock_get,
            patch.object(test_set_index, "boto3") as mock_boto3,
            patch.object(test_set_index, "_validate_test_set_files") as mock_validate,
        ):
            mock_get.return_value = {
                "id": "ts1",
                "name": "TS One",
                "status": "COMPLETED",
                "createdAt": "2026-01-01T00:00:00Z",
            }
            s3 = MagicMock()
            # baseline folder for doc.pdf has one nested result.json
            paginator = MagicMock()
            paginator.paginate.return_value = [
                {"Contents": [{"Key": "ts1/baseline/doc.pdf/sections/1/result.json"}]}
            ]
            s3.get_paginator.return_value = paginator
            mock_table = MagicMock()

            def _resource(name):
                return MagicMock(Table=MagicMock(return_value=mock_table))

            mock_boto3.client.return_value = s3
            mock_boto3.resource.side_effect = _resource
            mock_validate.return_value = {"valid": True, "input_count": 4}

            result = test_set_index.remove_documents_from_test_set(
                {"testSetId": "ts1", "fileNames": ["doc.pdf"]}
            )

            # Deleted both the input object and the baseline result
            deleted_keys = set()
            for call in s3.delete_objects.call_args_list:
                for obj in call.kwargs["Delete"]["Objects"]:
                    deleted_keys.add(obj["Key"])
            assert "ts1/input/doc.pdf" in deleted_keys
            assert "ts1/baseline/doc.pdf/sections/1/result.json" in deleted_keys
            # fileCount updated to the recounted value
            assert result["fileCount"] == 4
            update_kwargs = mock_table.update_item.call_args.kwargs
            assert update_kwargs["ExpressionAttributeValues"][":c"] == 4

    def test_remove_documents_nonexistent_test_set_raises(self):
        with patch.object(test_set_index.db_client, "get_item") as mock_get:
            mock_get.return_value = None
            with pytest.raises(Exception, match="Test set 'ghost' not found"):
                test_set_index.remove_documents_from_test_set(
                    {"testSetId": "ghost", "fileNames": ["a.pdf"]}
                )

    # -- Unlabeled sets (the draft-labeling on-ramp) -----------------------

    def test_validation_allows_a_set_with_no_baseline_when_opted_in(self):
        """'Upload documents only' is a valid set awaiting draft labels."""
        s3 = Mock()
        s3.get_paginator.return_value.paginate.side_effect = lambda **kw: (
            [{"Contents": [{"Key": "ts1/input/a.pdf"}, {"Key": "ts1/input/b.pdf"}]}]
            if "input" in kw["Prefix"]
            else [{}]
        )

        strict = test_set_index._validate_test_set_files(s3, "bucket", "ts1")
        assert strict["valid"] is False
        assert strict["error"] == "No baseline files found"

        relaxed = test_set_index._validate_test_set_files(
            s3, "bucket", "ts1", allow_unlabeled=True
        )
        assert relaxed["valid"] is True
        assert relaxed["labeled"] is False
        assert relaxed["input_count"] == 2

    def test_validation_still_rejects_a_partially_labeled_set(self):
        """A missing baseline for *some* docs is a botched upload, not a flow."""
        s3 = Mock()
        s3.get_paginator.return_value.paginate.side_effect = lambda **kw: (
            [{"Contents": [{"Key": "ts1/input/a.pdf"}, {"Key": "ts1/input/b.pdf"}]}]
            if "input" in kw["Prefix"]
            else [{"Contents": [{"Key": "ts1/baseline/a.pdf/sections/1/result.json"}]}]
        )
        result = test_set_index._validate_test_set_files(
            s3, "bucket", "ts1", allow_unlabeled=True
        )
        assert result["valid"] is False
        assert "b.pdf" in result["error"]

    def test_structure_check_no_longer_requires_a_baseline_folder(self):
        """Discovery must see documents-only sets, not skip them entirely."""
        s3 = Mock()
        s3.head_object.side_effect = Exception("no .uploading marker")
        s3.list_objects_v2.return_value = {"KeyCount": 1}
        assert test_set_index._is_valid_test_set_structure(s3, "bucket", "ts1") is True
        # Only the input/ prefix is consulted now.
        prefixes = [c.kwargs["Prefix"] for c in s3.list_objects_v2.call_args_list]
        assert prefixes == ["ts1/input/"]

    # -- Draft labeling ---------------------------------------------------

    def test_min_confidence_walks_nested_explainability(self):
        """Confidence leaves are nested irregularly; take the true minimum."""
        payload = [
            {
                "vendor": {"confidence": 0.95},
                "line_items": [
                    {"amount": {"confidence": 0.71}},
                    {"amount": {"confidence": 0.88}},
                ],
            }
        ]
        assert test_set_index._min_confidence(payload) == 0.71
        # No confidence anywhere is distinct from confidence 0.
        assert test_set_index._min_confidence({"vendor": {}}) is None
        assert test_set_index._min_confidence(None) is None

    def test_min_confidence_ignores_booleans(self):
        """A bool is an int in Python; it must not be read as a score."""
        assert test_set_index._min_confidence({"f": {"confidence": True}}) is None

    def test_min_confidence_handles_the_real_pipeline_shape(self):
        """Compound fields nest another level (PayPeriod.StartDate on a payslip).

        Shape captured from a live stack's explainability_info, where confidence
        sits beside confidence_threshold/geometry/ocr_confidence — none of which
        may be mistaken for the score.
        """
        payload = [
            {
                "EmployeeName": {
                    "confidence": 0.999,
                    "confidence_threshold": 0.8,
                    "geometry": [{"boundingBox": {"left": 0.07}, "page": 1}],
                    "geometry_source": "ocr",
                    "ocr_confidence": 0.999,
                },
                "PayPeriod": {
                    "StartDate": {"confidence": 0.994, "confidence_threshold": 0.8},
                    "EndDate": {"confidence": 0.998, "confidence_threshold": 0.8},
                },
            }
        ]
        assert test_set_index._min_confidence(payload) == 0.994
        assert test_set_index._confidence_threshold(payload) == 0.8

    def test_confidence_threshold_tracks_the_weakest_field(self):
        """The reported threshold must belong to the field minConfidence reports."""
        payload = [
            {
                "a": {"confidence": 0.99, "confidence_threshold": 0.5},
                "b": {"confidence": 0.60, "confidence_threshold": 0.9},
            }
        ]
        assert test_set_index._min_confidence(payload) == 0.60
        assert test_set_index._confidence_threshold(payload) == 0.9
        # Absent thresholds stay absent rather than defaulting server-side.
        assert (
            test_set_index._confidence_threshold([{"a": {"confidence": 0.6}}]) is None
        )
        assert test_set_index._confidence_threshold(None) is None

    def test_generate_draft_labels_delegates_to_the_test_runner(self, labeling_env):
        table, _ = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)

        lambda_client = MagicMock()
        lambda_client.invoke.return_value = {
            "Payload": Mock(read=lambda: json.dumps({"testRunId": "ts1-run"}).encode())
        }
        with patch.object(test_set_index.boto3, "client", return_value=lambda_client):
            result = test_set_index.generate_draft_labels(
                {"input": {"testSetId": "ts1"}},
                {"identity": {"claims": {"email": "me@example.com"}}},
            )

        assert result["jobId"] == "ts1-run"
        assert result["status"] == "RUNNING"
        assert result["total"] == 2
        # The run is created by the test runner (one owner of config capture and
        # version pinning), invoked without an identity as a trusted service call.
        payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
        assert payload["info"]["fieldName"] == "startTestRun"
        assert payload["arguments"]["input"]["testSetId"] == "ts1"
        assert "identity" not in payload
        # Job item recorded under the test set, and the set marked as labeling.
        job = table.get_item(Key={"PK": "testset#ts1", "SK": "labeljob#ts1-run"})[
            "Item"
        ]
        assert job["startedBy"] == "me@example.com"
        meta = table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})["Item"]
        assert meta["labelJobStatus"] == "RUNNING"

    def test_generate_draft_labels_rejects_an_empty_test_set(self, labeling_env):
        table, _ = labeling_env
        _seed_test_set(table, "ts1", fileCount=0)
        with pytest.raises(Exception, match="no documents to label"):
            test_set_index.generate_draft_labels({"input": {"testSetId": "ts1"}})

    def test_harvest_writes_draft_labels_with_confidence(self, labeling_env):
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        uri = _seed_pipeline_result(
            s3,
            "ts1-run/a.pdf/sections/1/result.json",
            {"vendor": "Acme"},
            [{"vendor": {"confidence": 0.42, "confidence_threshold": 0.8}}],
        )
        _seed_completed_run(
            table,
            "ts1-run",
            "ts1",
            ["a.pdf"],
            {"a.pdf": [{"Id": "1", "OutputJSONUri": uri}]},
        )
        table.put_item(
            Item={
                "PK": "testset#ts1",
                "SK": "labeljob#ts1-run",
                "testSetId": "ts1",
                "jobId": "ts1-run",
                "status": "RUNNING",
                "total": 1,
                "labeled": 0,
            }
        )

        result = test_set_index.get_draft_label_job(
            {"testSetId": "ts1", "jobId": "ts1-run"}
        )

        assert result["status"] == "COMPLETED"
        assert result["labeled"] == 1
        # Written to the baseline layout the GT editor and scoring already read.
        body = json.loads(
            s3.get_object(
                Bucket="test-set-bucket",
                Key="ts1/baseline/a.pdf/sections/1/result.json",
            )["Body"].read()
        )
        assert body["inference_result"] == {"vendor": "Acme"}
        assert body["labelSource"] == "draft-machine"
        assert body["minConfidence"] == 0.42
        assert body["confidenceThreshold"] == 0.8
        meta = table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})["Item"]
        assert meta["labelState"] == "draft"

    def test_harvest_never_overwrites_a_human_reviewed_label(self, labeling_env):
        """Re-running draft labeling must not destroy confirmed ground truth."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        reviewed = {
            "inference_result": {"vendor": "Corrected By Human"},
            "labelSource": "reviewed-human",
        }
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/a.pdf/sections/1/result.json",
            Body=json.dumps(reviewed).encode(),
        )
        uri = _seed_pipeline_result(
            s3, "ts1-run/a.pdf/sections/1/result.json", {"vendor": "Machine Guess"}
        )
        _seed_completed_run(
            table,
            "ts1-run",
            "ts1",
            ["a.pdf"],
            {"a.pdf": [{"Id": "1", "OutputJSONUri": uri}]},
        )
        table.put_item(
            Item={
                "PK": "testset#ts1",
                "SK": "labeljob#ts1-run",
                "testSetId": "ts1",
                "jobId": "ts1-run",
                "status": "RUNNING",
                "total": 1,
                "labeled": 0,
            }
        )

        test_set_index.get_draft_label_job({"testSetId": "ts1", "jobId": "ts1-run"})

        body = json.loads(
            s3.get_object(
                Bucket="test-set-bucket",
                Key="ts1/baseline/a.pdf/sections/1/result.json",
            )["Body"].read()
        )
        assert body["inference_result"] == {"vendor": "Corrected By Human"}
        assert body["labelSource"] == "reviewed-human"

    def test_harvest_treats_an_uploaded_baseline_as_human_owned(self, labeling_env):
        """A hand-uploaded baseline has no labelSource; never silently replace it."""
        table, s3 = labeling_env
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/a.pdf/sections/1/result.json",
            Body=json.dumps({"inference_result": {"vendor": "Uploaded GT"}}).encode(),
        )
        assert (
            test_set_index._existing_label_is_human(
                "test-set-bucket", "ts1/baseline/a.pdf/sections/1/result.json"
            )
            is True
        )
        # But a missing label is fair game.
        assert (
            test_set_index._existing_label_is_human("test-set-bucket", "ts1/nope.json")
            is False
        )
        # And a previous machine draft is replaceable, so re-running picks up a
        # newer config.
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/b.pdf/sections/1/result.json",
            Body=json.dumps({"labelSource": "draft-machine"}).encode(),
        )
        assert (
            test_set_index._existing_label_is_human(
                "test-set-bucket", "ts1/baseline/b.pdf/sections/1/result.json"
            )
            is False
        )

    def test_harvest_stays_running_while_documents_are_pending(self, labeling_env):
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        uri = _seed_pipeline_result(
            s3, "ts1-run/a.pdf/sections/1/result.json", {"vendor": "Acme"}
        )
        _seed_completed_run(
            table,
            "ts1-run",
            "ts1",
            ["a.pdf", "b.pdf"],
            {"a.pdf": [{"Id": "1", "OutputJSONUri": uri}]},
        )
        # b.pdf hasn't finished processing yet.
        table.put_item(
            Item={
                "PK": "doc#ts1-run/b.pdf",
                "SK": "none",
                "ObjectStatus": "RUNNING",
                "Sections": [],
            }
        )
        table.put_item(
            Item={
                "PK": "testset#ts1",
                "SK": "labeljob#ts1-run",
                "testSetId": "ts1",
                "jobId": "ts1-run",
                "status": "RUNNING",
                "total": 2,
                "labeled": 0,
            }
        )

        result = test_set_index.get_draft_label_job(
            {"testSetId": "ts1", "jobId": "ts1-run"}
        )
        assert result["status"] == "RUNNING"
        assert result["labeled"] == 1

    def test_harvest_marks_the_job_failed_when_the_run_fails(self, labeling_env):
        table, _ = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        table.put_item(
            Item={
                "PK": "testrun#ts1-run",
                "SK": "metadata",
                "TestSetId": "ts1",
                "Files": ["a.pdf"],
                "Status": "FAILED",
                "Error": "pipeline exploded",
            }
        )
        table.put_item(
            Item={
                "PK": "testset#ts1",
                "SK": "labeljob#ts1-run",
                "testSetId": "ts1",
                "jobId": "ts1-run",
                "status": "RUNNING",
                "total": 1,
                "labeled": 0,
            }
        )

        result = test_set_index.get_draft_label_job(
            {"testSetId": "ts1", "jobId": "ts1-run"}
        )
        assert result["status"] == "FAILED"
        assert result["error"] == "pipeline exploded"
        meta = table.get_item(Key={"PK": "testset#ts1", "SK": "metadata"})["Item"]
        assert meta["labelJobStatus"] == "FAILED"

    def test_get_draft_label_job_unknown_job_raises(self, labeling_env):
        table, _ = labeling_env
        _seed_test_set(table, "ts1")
        with pytest.raises(Exception, match="Labeling job 'nope' not found"):
            test_set_index.get_draft_label_job({"testSetId": "ts1", "jobId": "nope"})

    def test_attach_label_metadata_takes_the_worst_field_and_source(self, labeling_env):
        """A document's confidence is its weakest field, across all sections."""
        _, s3 = labeling_env
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/a.pdf/sections/1/result.json",
            Body=json.dumps(
                {
                    "labelSource": "reviewed-human",
                    "explainability_info": [
                        {"f": {"confidence": 0.99, "confidence_threshold": 0.9}}
                    ],
                }
            ).encode(),
        )
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/a.pdf/sections/2/result.json",
            Body=json.dumps(
                {
                    "labelSource": "draft-machine",
                    "explainability_info": [
                        {"f": {"confidence": 0.31, "confidence_threshold": 0.7}}
                    ],
                }
            ).encode(),
        )
        documents = [
            {
                "objectKey": "a.pdf",
                "sections": [
                    {
                        "sectionId": "1",
                        "baselineKey": "ts1/baseline/a.pdf/sections/1/result.json",
                    },
                    {
                        "sectionId": "2",
                        "baselineKey": "ts1/baseline/a.pdf/sections/2/result.json",
                    },
                ],
            },
            {"objectKey": "b.pdf", "sections": []},
        ]

        test_set_index._attach_label_metadata("test-set-bucket", documents)

        # Any draft section means the document is not fully reviewed.
        assert documents[0]["labelSource"] == "draft-machine"
        assert documents[0]["minConfidence"] == 0.31
        # The threshold reported is the weakest field's (section 2), not section 1's.
        assert documents[0]["confidenceThreshold"] == 0.7
        # No sections at all = unlabeled, not "confident".
        assert documents[1]["labelSource"] is None
        assert documents[1]["minConfidence"] is None
        assert documents[1]["confidenceThreshold"] is None

    # -- Review-effort estimator -------------------------------------------

    def test_estimate_review_effort_reports_prior_on_a_cold_set(self, labeling_env):
        """With no curve and no labels, the estimate must not look measured."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/a.pdf", Body=b"x")
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/b.pdf", Body=b"x")

        result = test_set_index.estimate_review_effort(
            {"testSetId": "ts1", "targetAccuracy": 99.0}
        )

        assert result["estimateConfidence"] == "prior"
        assert result["totalDocs"] == 2
        # A prior-driven estimate reports a range, not a bare point value.
        assert result["docsToReviewLow"] <= result["docsToReview"]
        assert result["docsToReviewHigh"] >= result["docsToReview"]
        assert result["calibration"]["totalObservations"] == 0

    def test_estimate_review_effort_uses_the_stored_curve(self, labeling_env):
        """Observations recorded from review must change the estimate."""
        from idp_common.evaluation.curve_store import CurveStore

        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/a.pdf", Body=b"x")

        # A review pass found the 0.3-confidence band is mostly wrong.
        CurveStore(table).add_observations("ts1", [(0.3, False)] * 40)

        result = test_set_index.estimate_review_effort({"testSetId": "ts1"})
        assert result["calibration"]["totalObservations"] == 40
        assert result["estimateConfidence"] in (
            "partially-measured",
            "unreliable",
        )

    def test_estimate_review_effort_recommends_reviewing_everything_when_overconfident(
        self, labeling_env
    ):
        """The dangerous quadrant must not yield a small, confident-looking number."""
        from idp_common.evaluation.curve_store import CurveStore

        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/a.pdf", Body=b"x")
        # Confident and wrong.
        CurveStore(table).add_observations("ts1", [(0.95, False)] * 60)

        result = test_set_index.estimate_review_effort({"testSetId": "ts1"})
        assert result["recommendReviewAll"] is True
        assert result["estimateConfidence"] == "unreliable"
        assert result["calibration"]["overconfident"] is True

    def test_estimate_review_effort_validates_its_inputs(self, labeling_env):
        table, _ = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        with pytest.raises(Exception, match="targetAccuracy"):
            test_set_index.estimate_review_effort(
                {"testSetId": "ts1", "targetAccuracy": 150}
            )
        with pytest.raises(Exception, match="not found"):
            test_set_index.estimate_review_effort({"testSetId": "ghost"})

    def test_estimate_review_effort_includes_the_reliability_table(self, labeling_env):
        """The curve must be inspectable, not just a number."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/a.pdf", Body=b"x")

        result = test_set_index.estimate_review_effort({"testSetId": "ts1"})
        assert len(result["reliabilityTable"]) == 10
        assert "burndown" in result

    # -- Annotation queue --------------------------------------------------

    def test_annotation_queue_is_worst_first(self, labeling_env):
        """Lowest confidence first — each review removes the most error."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=3)
        for name, conf in (("a.pdf", 0.95), ("b.pdf", 0.20), ("c.pdf", 0.60)):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")
            s3.put_object(
                Bucket="test-set-bucket",
                Key=f"ts1/baseline/{name}/sections/1/result.json",
                Body=json.dumps(
                    {
                        "labelSource": "draft-machine",
                        "explainability_info": [{"f": {"confidence": conf}}],
                    }
                ).encode(),
            )

        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, None)

        order = [d["objectKey"] for d in result["documents"]]
        assert order == ["b.pdf", "c.pdf", "a.pdf"], order
        assert result["nextObjectKey"] == "b.pdf"
        assert result["totalDocs"] == 3
        assert result["remainingDocs"] == 3

    def test_annotation_queue_puts_unlabeled_documents_first(self, labeling_env):
        """An unlabeled document is the least trustworthy, not the most."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/labeled.pdf", Body=b"x")
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/labeled.pdf/sections/1/result.json",
            Body=json.dumps(
                {
                    "labelSource": "draft-machine",
                    "explainability_info": [{"f": {"confidence": 0.1}}],
                }
            ).encode(),
        )
        # No baseline at all for this one.
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/bare.pdf", Body=b"x")

        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, None)
        assert result["documents"][0]["objectKey"] == "bare.pdf"

    def test_annotation_queue_excludes_reviewed_documents(self, labeling_env):
        """Reviewed work drops out of the queue but still counts as progress."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        for name, source in (
            ("done.pdf", "reviewed-human"),
            ("todo.pdf", "draft-machine"),
        ):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")
            s3.put_object(
                Bucket="test-set-bucket",
                Key=f"ts1/baseline/{name}/sections/1/result.json",
                Body=json.dumps(
                    {
                        "labelSource": source,
                        "explainability_info": [{"f": {"confidence": 0.4}}],
                    }
                ).encode(),
            )

        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, None)
        assert [d["objectKey"] for d in result["documents"]] == ["todo.pdf"]
        assert result["reviewedDocs"] == 1
        assert result["remainingDocs"] == 1

        # ...and can be included explicitly for a progress view.
        withall = test_set_index.get_annotation_queue(
            {"testSetId": "ts1", "includeCompleted": True}, None
        )
        assert len(withall["documents"]) == 2

    def test_annotation_queue_reflects_another_annotators_claim(self, labeling_env):
        """A claimed doc must drop out of everyone else's 'next in queue'."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2, labelJobId="run1")
        for name, conf in (("claimed.pdf", 0.1), ("free.pdf", 0.5)):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")
            s3.put_object(
                Bucket="test-set-bucket",
                Key=f"ts1/baseline/{name}/sections/1/result.json",
                Body=json.dumps(
                    {
                        "labelSource": "draft-machine",
                        "explainability_info": [{"f": {"confidence": conf}}],
                    }
                ).encode(),
            )
        # Someone else holds the lowest-confidence document.
        table.put_item(
            Item={
                "PK": "doc#run1/claimed.pdf",
                "SK": "none",
                "HITLReviewOwner": "other@example.com",
                "HITLStatus": "InProgress",
            }
        )

        event = {
            "identity": {
                "claims": {"cognito:groups": ["Admin"], "email": "me@example.com"}
            }
        }
        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, event)

        by_key = {d["objectKey"]: d for d in result["documents"]}
        assert by_key["claimed.pdf"]["claimedBy"] == "other@example.com"
        assert by_key["claimed.pdf"]["available"] is False
        assert by_key["claimed.pdf"]["claimedByMe"] is False
        # Still worst-first in the listing, but "next" skips to what I can take.
        assert result["nextObjectKey"] == "free.pdf"
        assert result["claimedByOthers"] == 1

    def test_annotation_queue_marks_my_own_claim_as_available(self, labeling_env):
        """Resuming my own in-progress document must not be blocked."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1, labelJobId="run1")
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/mine.pdf", Body=b"x")
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/mine.pdf/sections/1/result.json",
            Body=json.dumps(
                {
                    "labelSource": "draft-machine",
                    "explainability_info": [{"f": {"confidence": 0.3}}],
                }
            ).encode(),
        )
        table.put_item(
            Item={
                "PK": "doc#run1/mine.pdf",
                "SK": "none",
                "HITLReviewOwner": "me@example.com",
                "HITLStatus": "InProgress",
            }
        )

        event = {
            "identity": {
                "claims": {"cognito:groups": ["Admin"], "email": "me@example.com"}
            }
        }
        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, event)
        item = result["documents"][0]
        assert item["claimedByMe"] is True
        assert item["available"] is True
        assert result["nextObjectKey"] == "mine.pdf"

    def test_annotation_queue_denies_an_out_of_scope_annotator(self, labeling_env):
        """Scope is checked before the set is read, so nothing leaks."""
        from idp_common import testset_scope

        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=1)
        testset_scope.clear_scope_cache()

        event = {
            "identity": {
                "claims": {
                    "cognito:groups": ["Annotator"],
                    "email": "ann@example.com",
                }
            }
        }
        # No users table configured -> annotator has no resolvable scope -> denied.
        with pytest.raises(Exception, match="Unauthorized"):
            test_set_index.get_annotation_queue({"testSetId": "ts1"}, event)
        testset_scope.clear_scope_cache()

    def test_annotation_queue_validates_the_test_set_id(self, labeling_env):
        table, _ = labeling_env
        with pytest.raises(Exception, match="Invalid test set id"):
            test_set_index.get_annotation_queue({"testSetId": "../etc/passwd"}, None)

    def test_estimate_reports_the_real_set_size_not_the_sample_size(
        self, labeling_env, monkeypatch
    ):
        """Regression: a large set must not report its sampling cap as its size.

        Found on a live stack: a 2008-document test set reported totalDocs=500
        (MAX_DOCS_FOR_ESTIMATE), which understated the review work, the effort,
        and the audit pool by 4x. fileCount is the set's size; the sampled
        confidences are only how much of it we inspected.
        """
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2008)
        # Only three documents actually exist in S3 to sample from.
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")
            s3.put_object(
                Bucket="test-set-bucket",
                Key=f"ts1/baseline/{name}/sections/1/result.json",
                Body=json.dumps(
                    {
                        "labelSource": "draft-machine",
                        "explainability_info": [{"f": {"confidence": 0.5}}],
                    }
                ).encode(),
            )

        result = test_set_index.estimate_review_effort({"testSetId": "ts1"})

        assert result["totalDocs"] == 2008
        assert result["sampledDocs"] == 3
        # Review depth and audit pool are bounded by the real size, not the sample.
        assert result["docsToReview"] <= 2008
        assert result["docsToReviewHigh"] <= 2008
        assert len(result["burndown"]) == 2009  # 0..N inclusive

    def test_estimate_sampled_equals_total_for_a_small_set(self, labeling_env):
        """No extrapolation when every document was inspected."""
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        for name in ("a.pdf", "b.pdf"):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")

        result = test_set_index.estimate_review_effort({"testSetId": "ts1"})
        assert result["totalDocs"] == 2
        assert result["sampledDocs"] == 2

    def test_uploaded_ground_truth_is_not_counted_as_review_work(self, labeling_env):
        """Regression: a set that arrived with labels is not 100% annotated.

        Found live: a 500-document uploaded set reported reviewedDocs=500,
        remainingDocs=0 and an empty queue, because baselines with no labelSource
        defaulted to reviewed-human. Uploaded ground truth is authoritative — draft
        labeling still won't overwrite it — but nobody reviewed it *here*, so it
        must not claim completed annotation progress.
        """
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2)
        for name in ("a.pdf", "b.pdf"):
            s3.put_object(Bucket="test-set-bucket", Key=f"ts1/input/{name}", Body=b"x")
            # No labelSource key at all — how an uploaded baseline arrives.
            s3.put_object(
                Bucket="test-set-bucket",
                Key=f"ts1/baseline/{name}/sections/1/result.json",
                Body=json.dumps({"inference_result": {"f": "v"}}).encode(),
            )

        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, None)

        assert result["reviewedDocs"] == 0
        assert result["remainingDocs"] == 2
        assert len(result["documents"]) == 2
        assert result["nextObjectKey"] is not None
        # Reported as uploaded, distinct from a label a human reviewed here.
        assert result["documents"][0]["labelSource"] == "uploaded"
        assert result["documents"][0]["reviewed"] is False

    def test_uploaded_ground_truth_is_still_protected_from_overwrite(
        self, labeling_env
    ):
        """The relabel guard must not weaken just because progress changed.

        Overwrite safety keys on the label being an explicit draft, not on it
        being reviewed-human, so an untagged uploaded baseline stays protected.
        """
        _, s3 = labeling_env
        s3.put_object(
            Bucket="test-set-bucket",
            Key="ts1/baseline/a.pdf/sections/1/result.json",
            Body=json.dumps({"inference_result": {"f": "uploaded gt"}}).encode(),
        )
        assert (
            test_set_index._existing_label_is_human(
                "test-set-bucket", "ts1/baseline/a.pdf/sections/1/result.json"
            )
            is True
        )

    def test_queue_reports_the_real_set_size_not_the_inspected_page(self, labeling_env):
        """Regression: the queue cap must not be reported as the set size.

        Same conflation as the estimator had: a 2008-document set showed
        totalDocs=500, so reviewing the first page would have read as
        "0 remaining" with most of the set untouched.
        """
        table, s3 = labeling_env
        _seed_test_set(table, "ts1", fileCount=2008)
        s3.put_object(Bucket="test-set-bucket", Key="ts1/input/a.pdf", Body=b"x")

        result = test_set_index.get_annotation_queue({"testSetId": "ts1"}, None)

        assert result["totalDocs"] == 2008
        assert result["inspectedDocs"] == 1
        assert result["remainingDocs"] == 2008
