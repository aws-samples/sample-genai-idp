"""Unit tests for workflow_tracker.notify_circuit_breaker_success()."""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

_INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.py")
_MODULE_NAME = "workflow_tracker_index_under_test"


@pytest.fixture
def index_module(monkeypatch):
    """Import index with idp_common and boto3 mocked out."""
    env_vars = {
        "CONCURRENCY_TABLE": "test-concurrency",
        "METRIC_NAMESPACE": "TEST_NS",
        "CIRCUIT_BREAKER_ENABLED": "true",
        "ALERTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test-topic",
    }

    fake_idp_common = MagicMock()
    fake_models = MagicMock()
    fake_docs_service = MagicMock()
    fake_docs_service.create_document_service = MagicMock(return_value=MagicMock())

    module_patches = {
        "idp_common": fake_idp_common,
        "idp_common.models": fake_models,
        "idp_common.docs_service": fake_docs_service,
    }
    for name, mod in module_patches.items():
        monkeypatch.setitem(sys.modules, name, mod)

    with patch.dict(os.environ, env_vars, clear=False), \
         patch("boto3.resource") as mock_resource, \
         patch("boto3.client") as mock_client:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_client.return_value = MagicMock()

        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _INDEX_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)

        module.concurrency_table = mock_table
        module.sns = MagicMock()
        module.cloudwatch = MagicMock()
        yield module
        sys.modules.pop(_MODULE_NAME, None)


class TestNotifyCircuitBreakerSuccess:
    """HALF_OPEN -> CLOSED transition after a successful workflow."""

    def test_half_open_transitions_to_closed(self, index_module):
        index_module.CIRCUIT_BREAKER_ENABLED = True
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "HALF_OPEN"}
        }
        index_module.notify_circuit_breaker_success()

        index_module.concurrency_table.update_item.assert_called_once()
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":closed"] == "CLOSED"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "HALF_OPEN"
        assert "ConditionExpression" in kwargs
        # Clear stale last_error and opened_at on recovery so operators don't
        # see old errors or a dangling outage timestamp on CLOSED.
        assert "REMOVE last_error" in kwargs["UpdateExpression"]
        assert "opened_at" in kwargs["UpdateExpression"]
        index_module.sns.publish.assert_called_once()
        index_module.cloudwatch.put_metric_data.assert_called_once()

    def test_not_half_open_is_noop(self, index_module):
        index_module.CIRCUIT_BREAKER_ENABLED = True
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN"}
        }
        index_module.notify_circuit_breaker_success()
        index_module.concurrency_table.update_item.assert_not_called()
        index_module.sns.publish.assert_not_called()

    def test_disabled_is_noop(self, index_module):
        index_module.CIRCUIT_BREAKER_ENABLED = False
        index_module.notify_circuit_breaker_success()
        index_module.concurrency_table.get_item.assert_not_called()
        index_module.concurrency_table.update_item.assert_not_called()

    def test_conditional_check_failure_skips_notifications(self, index_module):
        """A concurrent alarm bumping HALF_OPEN -> OPEN must not trigger CLOSED SNS/metrics."""
        index_module.CIRCUIT_BREAKER_ENABLED = True
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "HALF_OPEN"}
        }
        index_module.concurrency_table.update_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "no"}},
            "UpdateItem",
        )
        index_module.notify_circuit_breaker_success()
        index_module.sns.publish.assert_not_called()
        index_module.cloudwatch.put_metric_data.assert_not_called()
