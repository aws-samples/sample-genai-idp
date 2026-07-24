"""Unit tests for the workflow_tracker REDACTED_SUPERSEDED (redact-copy-and-stop)
halt path — the most safety-critical of the PII-anonymization changes.

Pins:
- a SUCCEEDED execution whose document status is REDACTED_SUPERSEDED does NOT
  crash the handler (regression: update_document_completion used to bare-return
  None, and the handler then dereferenced updated_doc → AttributeError → 4x
  retries → 4x counter decrement / concurrency drift);
- the counter is decremented EXACTLY once;
- run-record + latency metrics are skipped (the doc/outputs were deleted);
- the original is deleted via delete_single_document with the ORIGINAL key.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_INDEX_PATH = os.path.join(os.path.dirname(__file__), "index.py")
_MODULE_NAME = "workflow_tracker_redacted_under_test"


class _Status:
    """Stand-in for idp_common.models.Status with the members the tracker uses.
    Plain sentinel objects so `==` is identity (matches Enum-member semantics)."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    REDACTED_SUPERSEDED = "REDACTED_SUPERSEDED"


@pytest.fixture
def index_module(monkeypatch):
    env_vars = {
        "CONCURRENCY_TABLE": "test-concurrency",
        "METRIC_NAMESPACE": "TEST_NS",
        "TRACKING_TABLE": "test-tracking",
        "INPUT_BUCKET": "test-input",
        "OUTPUT_BUCKET": "test-output",
    }
    fake_models = MagicMock()
    fake_models.Status = _Status
    fake_docs_service = MagicMock()
    fake_docs_service.create_document_service = MagicMock(return_value=MagicMock())

    patches = {
        "idp_common": MagicMock(),
        "idp_common.models": fake_models,
        "idp_common.docs_service": fake_docs_service,
        "idp_common.document_versions": MagicMock(),
        "idp_common.delete_documents": MagicMock(),
    }
    for name, mod in patches.items():
        monkeypatch.setitem(sys.modules, name, mod)

    with (
        patch.dict(os.environ, env_vars, clear=False),
        patch("boto3.resource") as mock_resource,
        patch("boto3.client") as mock_client,
    ):
        mock_resource.return_value.Table.return_value = MagicMock()
        mock_client.return_value = MagicMock()
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _INDEX_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
        module.cloudwatch = MagicMock()
        yield module
        sys.modules.pop(_MODULE_NAME, None)


def _event():
    return {
        "detail": {
            "input": '{"document": {"document_id": "w2.pdf"}}',
            "output": '{"document": {"document_id": "w2.pdf", "status": "REDACTED_SUPERSEDED"}}',
            "status": "SUCCEEDED",
            "executionArn": "arn:aws:states:us-west-2:1:execution:sm:exec",
            "stopDate": 1700000000000,
        }
    }


def test_superseded_no_crash_counter_once_skips_run(index_module, monkeypatch):
    m = index_module
    # A real-ish document carrying the terminal status.
    doc = MagicMock()
    doc.status = _Status.REDACTED_SUPERSEDED
    doc.completion_time = "2026-07-24T00:00:00Z"
    doc.workflow_execution_arn = "arn:exec"

    monkeypatch.setattr(m, "update_document_completion", lambda *a, **k: doc)
    monkeypatch.setattr(m, "decrement_counter", MagicMock(return_value=3))
    monkeypatch.setattr(m, "record_document_run", MagicMock())
    monkeypatch.setattr(m, "put_latency_metrics", MagicMock())
    monkeypatch.setattr(m, "notify_circuit_breaker_success", MagicMock())

    resp = m.handler(_event(), None)  # must NOT raise

    assert resp["statusCode"] == 200
    # counter decremented exactly once (regression guard against 4x drift)
    assert m.decrement_counter.call_count == 1
    # no run record / metrics for a deleted original
    m.record_document_run.assert_not_called()
    m.put_latency_metrics.assert_not_called()


def test_superseded_deletes_original_key(index_module):
    m = index_module
    fake_delete = MagicMock(return_value={"success": True, "deleted": {}})
    # patch the delete_single_document imported inside _delete_superseded_original
    sys.modules["idp_common.delete_documents"].delete_single_document = fake_delete

    m._delete_superseded_original("w2.pdf")
    fake_delete.assert_called_once()
    kwargs = fake_delete.call_args.kwargs
    assert kwargs["object_key"] == "w2.pdf"
    assert kwargs["input_bucket"] == "test-input"
