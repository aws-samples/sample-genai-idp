"""Unit tests for circuit_breaker_manager Lambda."""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

_INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.py")
_MODULE_NAME = "circuit_breaker_manager_index_under_test"


@pytest.fixture
def index_module():
    """Import index with mocked boto3 clients/resources."""
    env_vars = {
        "CONCURRENCY_TABLE": "test-concurrency",
        "ALERTS_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:test-topic",
        "RECOVERY_TIMEOUT_SECONDS": "300",
        "ERROR_HANDLER_ARN": "",
        "METRIC_NAMESPACE": "TEST_NS",
    }
    with patch.dict(os.environ, env_vars, clear=False), \
         patch("boto3.resource") as mock_resource, \
         patch("boto3.client") as mock_client:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_client.side_effect = lambda name: MagicMock(name=f"client-{name}")

        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _INDEX_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)

        module.concurrency_table = mock_table
        module.sns = MagicMock()
        module.cloudwatch = MagicMock()
        module.lambda_client = MagicMock()
        yield module
        sys.modules.pop(_MODULE_NAME, None)


def _cond_check_failed() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "no"}},
        "UpdateItem",
    )


class TestHandleAlarmEvent:
    """Covers handle_alarm_event for ALARM/OK transitions."""

    def test_alarm_from_closed_opens_breaker(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED", "failure_count": 0}
        }
        index_module.handle_alarm_event("ALARM", "Bedrock 5xx")
        index_module.concurrency_table.update_item.assert_called_once()
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "CLOSED"
        index_module.sns.publish.assert_called_once()

    def test_alarm_from_half_open_reopens(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "HALF_OPEN", "failure_count": 1}
        }
        index_module.handle_alarm_event("ALARM", "Bedrock 5xx again")
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "HALF_OPEN"
        assert kwargs["ExpressionAttributeValues"][":fc"] == 2

    def test_alarm_from_open_is_noop(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN"}
        }
        index_module.handle_alarm_event("ALARM", "still down")
        index_module.concurrency_table.update_item.assert_not_called()
        index_module.sns.publish.assert_not_called()

    def test_ok_from_open_transitions_half_open(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN"}
        }
        index_module.handle_alarm_event("OK", "alarm cleared")
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "HALF_OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "OPEN"
        index_module.sns.publish.assert_called_once()

    def test_ok_from_closed_is_noop(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED"}
        }
        index_module.handle_alarm_event("OK", "alarm cleared")
        index_module.concurrency_table.update_item.assert_not_called()

    def test_alarm_conditional_failure_skips_side_effects(self, index_module):
        """If a concurrent writer already changed state, side effects must be skipped."""
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED", "failure_count": 0}
        }
        index_module.concurrency_table.update_item.side_effect = _cond_check_failed()
        index_module.handle_alarm_event("ALARM", "Bedrock 5xx")
        index_module.sns.publish.assert_not_called()
        index_module.lambda_client.invoke.assert_not_called()

    def test_ok_preserves_failure_count(self, index_module):
        """OPEN->HALF_OPEN on alarm OK must not reset failure_count."""
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN", "failure_count": 7}
        }
        index_module.handle_alarm_event("OK", "alarm cleared")
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert ":fc" not in kwargs["ExpressionAttributeValues"]
        assert "failure_count" not in kwargs["UpdateExpression"]


class TestHandleHealthCheck:
    """Covers handle_health_check recovery timeout elapsed vs not."""

    def test_recovery_timeout_elapsed_transitions_open_to_half_open(self, index_module):
        opened_at = (
            datetime.now(timezone.utc) - timedelta(seconds=400)
        ).isoformat()
        index_module.concurrency_table.get_item.return_value = {
            "Item": {
                "state": "OPEN",
                "opened_at": opened_at,
                "recovery_attempts": 2,
            }
        }
        index_module.handle_health_check()
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "HALF_OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "OPEN"
        assert kwargs["ExpressionAttributeValues"][":ra"] == 3

    def test_health_check_preserves_failure_count(self, index_module):
        """Health-check OPEN->HALF_OPEN must not reset failure_count."""
        opened_at = (
            datetime.now(timezone.utc) - timedelta(seconds=400)
        ).isoformat()
        index_module.concurrency_table.get_item.return_value = {
            "Item": {
                "state": "OPEN",
                "opened_at": opened_at,
                "failure_count": 9,
                "recovery_attempts": 2,
            }
        }
        index_module.handle_health_check()
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert ":fc" not in kwargs["ExpressionAttributeValues"]
        assert "failure_count" not in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":ra"] == 3

    def test_recovery_timeout_not_elapsed_stays_open(self, index_module):
        opened_at = (
            datetime.now(timezone.utc) - timedelta(seconds=30)
        ).isoformat()
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN", "opened_at": opened_at}
        }
        index_module.handle_health_check()
        index_module.concurrency_table.update_item.assert_not_called()

    def test_health_check_closed_is_noop(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED"}
        }
        index_module.handle_health_check()
        index_module.concurrency_table.update_item.assert_not_called()


class TestHandlerActions:
    """Covers manual reset and get_state actions via handler()."""

    def test_get_state_action(self, index_module):
        state_item = {
            "counter_id": "circuit_breaker",
            "state": "OPEN",
            "failure_count": 1,
        }
        index_module.concurrency_table.get_item.return_value = {"Item": state_item}
        result = index_module.handler({"action": "get_state"}, MagicMock())
        assert result["statusCode"] == 200
        assert result["body"] == state_item

    def test_reset_action_forces_closed(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN"}
        }
        result = index_module.handler({"action": "reset"}, MagicMock())
        assert result["statusCode"] == 200
        index_module.concurrency_table.update_item.assert_called_once()
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "CLOSED"
        # Manual reset zeros counters and removes stale last_error + opened_at.
        assert kwargs["ExpressionAttributeValues"][":fc"] == 0
        assert kwargs["ExpressionAttributeValues"][":ra"] == 0
        assert "REMOVE" in kwargs["UpdateExpression"]
        assert "last_error" in kwargs["UpdateExpression"]
        assert "opened_at" in kwargs["UpdateExpression"]
        index_module.sns.publish.assert_called_once()


class TestManualActions:
    """Covers manual_open / manual_close / manual_probe admin actions."""

    def test_manual_open_from_closed(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED", "failure_count": 3}
        }
        event = {"action": "manual_open", "user": "admin@x", "reason": "quiesce"}
        result = index_module.handler(event, MagicMock())
        assert result["statusCode"] == 200
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "CLOSED"
        # Admin pauses are operator actions, not Bedrock failures, so
        # failure_count must be left alone.
        assert ":fc" not in kwargs["ExpressionAttributeValues"]
        assert "failure_count" not in kwargs["UpdateExpression"]
        assert "Manual pause by admin@x: quiesce" in (
            kwargs["ExpressionAttributeValues"][":err"]
        )
        index_module.sns.publish.assert_called_once()

    def test_manual_open_from_open_is_noop(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN"}
        }
        event = {"action": "manual_open", "user": "admin@x", "reason": "x"}
        index_module.handler(event, MagicMock())
        index_module.concurrency_table.update_item.assert_not_called()
        index_module.sns.publish.assert_not_called()

    def test_manual_open_conditional_failure_skips_side_effects(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED"}
        }
        index_module.concurrency_table.update_item.side_effect = _cond_check_failed()
        index_module.handler(
            {"action": "manual_open", "user": "a", "reason": "r"}, MagicMock()
        )
        index_module.sns.publish.assert_not_called()

    def test_manual_close_unconditional_from_open(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN", "failure_count": 5, "recovery_attempts": 2}
        }
        event = {"action": "manual_close", "user": "admin@x", "reason": "override"}
        result = index_module.handler(event, MagicMock())
        assert result["statusCode"] == 200
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "CLOSED"
        assert kwargs["ExpressionAttributeValues"][":fc"] == 0
        assert kwargs["ExpressionAttributeValues"][":ra"] == 0
        assert "REMOVE" in kwargs["UpdateExpression"]
        assert "last_error" in kwargs["UpdateExpression"]
        # opened_at must also be cleared so the UI panel doesn't show a stale
        # outage timestamp after a manual override.
        assert "opened_at" in kwargs["UpdateExpression"]
        assert "ConditionExpression" not in kwargs
        index_module.sns.publish.assert_called_once()

    def test_manual_probe_from_open(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "OPEN", "recovery_attempts": 1}
        }
        event = {"action": "manual_probe", "user": "admin@x", "reason": "test"}
        index_module.handler(event, MagicMock())
        kwargs = index_module.concurrency_table.update_item.call_args.kwargs
        assert kwargs["ExpressionAttributeValues"][":state"] == "HALF_OPEN"
        assert kwargs["ExpressionAttributeValues"][":expected"] == "OPEN"
        assert kwargs["ExpressionAttributeValues"][":ra"] == 2
        index_module.sns.publish.assert_called_once()

    def test_manual_probe_from_closed_is_noop(self, index_module):
        index_module.concurrency_table.get_item.return_value = {
            "Item": {"state": "CLOSED"}
        }
        index_module.handler(
            {"action": "manual_probe", "user": "a", "reason": "r"}, MagicMock()
        )
        index_module.concurrency_table.update_item.assert_not_called()

    def test_unknown_action_returns_400(self, index_module):
        result = index_module.handler({"action": "bogus"}, MagicMock())
        assert result["statusCode"] == 400

    def test_broadcast_action_publishes_without_mutating_state(self, index_module):
        """The broadcast action must re-publish current state without writing DDB or SNS."""
        state_item = {
            "counter_id": "circuit_breaker",
            "state": "CLOSED",
            "failure_count": 0,
        }
        index_module.concurrency_table.get_item.return_value = {"Item": state_item}
        with patch.object(index_module, "publish_to_appsync") as mock_publish:
            result = index_module.handler({"action": "broadcast"}, MagicMock())
        assert result["statusCode"] == 200
        assert result["body"] == state_item
        mock_publish.assert_called_once_with(state_item)
        index_module.concurrency_table.update_item.assert_not_called()
        index_module.sns.publish.assert_not_called()
        index_module.cloudwatch.put_metric_data.assert_not_called()
