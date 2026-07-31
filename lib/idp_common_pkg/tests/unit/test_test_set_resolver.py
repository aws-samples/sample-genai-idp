import importlib.util
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

        def _get_item(key):
            return table.get_item(Key=key).get("Item")

        def _put_item(item, condition_expression=None):
            kwargs = {"Item": item}
            if condition_expression:
                kwargs["ConditionExpression"] = condition_expression
            return table.put_item(**kwargs)

        with patch.object(
            test_set_index.db_client, "get_item", side_effect=_get_item
        ), patch.object(
            test_set_index.db_client, "put_item", side_effect=_put_item
        ):
            yield table


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
        meta = publish_table.get_item(
            Key={"PK": "testset#ts1", "SK": "metadata"}
        )["Item"]
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
        meta = publish_table.get_item(
            Key={"PK": "testset#ts1", "SK": "metadata"}
        )["Item"]
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

        result = test_set_index.publish_test_set_version({"input": {"testSetId": "ts1"}})

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

    @patch.dict(os.environ, {"TRACKING_TABLE": "test-table", "TEST_SET_BUCKET": "ts-bucket"})
    def test_remove_documents_deletes_input_and_baseline_and_recounts(self):
        with patch.object(test_set_index.db_client, "get_item") as mock_get, patch.object(
            test_set_index, "boto3"
        ) as mock_boto3, patch.object(
            test_set_index, "_validate_test_set_files"
        ) as mock_validate:
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
