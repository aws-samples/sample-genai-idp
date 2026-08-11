# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the post-processing decompressor Lambda.

This Lambda sits between the EventBridge "execution SUCCEEDED" rule and the
customer's `PostProcessingLambdaHookFunctionArn`, inflating the compressed
document so the external function needs no `idp_common` dependency.

The tests pin two failure modes that made the hook silently not fire:

- **Async payload ceiling.** The handoff is `InvocationType='Event'`, which AWS
  caps at 1MB — verified live: a 1,441,631-byte payload is rejected with
  `RequestEntityTooLargeException ... (limit 1048576 bytes)`, while ~700KB is
  accepted. (The 6MB limit applies only to synchronous invokes.) Inflating the
  document pushes a large multi-section packet past that, so the invoke raised
  `RequestEntityTooLargeException` → 3 EventBridge retries → DLQ. The hook never
  fired for exactly the biggest documents. It now falls back to the original
  compressed event, which is always small.
- **Superseded originals.** A PII-redaction preprocessing hook halts the
  original after spawning a redacted copy, and that execution still ends
  SUCCEEDED — so the rule matched and the un-redacted original was handed to the
  customer's function. The status lives inside `detail.output` (invisible to an
  EventBridge pattern), so the guard has to live here.
"""

import importlib
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../src/lambda/post_processing_decompressor",
    )
)

_ARN = "arn:aws:lambda:us-east-1:123456789012:function:customer-post-processor"


@pytest.fixture
def mod(monkeypatch):
    """Import the handler with its required env vars and a stubbed Lambda client."""
    monkeypatch.setenv("CUSTOM_POST_PROCESSOR_ARN", _ARN)
    monkeypatch.setenv("WORKING_BUCKET", "test-working-bucket")
    sys.path.insert(0, LAMBDA_DIR)
    sys.modules.pop("index", None)
    try:
        m = importlib.import_module("index")
        m.lambda_client = MagicMock()
        m.lambda_client.invoke.return_value = {"StatusCode": 202}
        yield m
    finally:
        sys.path.remove(LAMBDA_DIR)
        sys.modules.pop("index", None)


def _event(document, include_input=True):
    """An EventBridge Step Functions completion event carrying `document`."""
    detail = {
        "executionArn": "arn:aws:states:us-east-1:123456789012:execution:wf:doc",
        "status": "SUCCEEDED",
        "output": json.dumps({"document": document}),
    }
    if include_input:
        detail["input"] = json.dumps({"document": {"id": "doc.pdf"}})
    return {"detail-type": "Step Functions Execution Status Change", "detail": detail}


def _compressed_ref(**over):
    ref = {
        "compressed": True,
        "s3_uri": "s3://test-working-bucket/compressed_documents/doc.pdf/state.json",
        "document_id": "doc.pdf",
        "num_pages": 3,
        "sections": ["1"],
    }
    ref.update(over)
    return ref


def _invoked_payload(mod):
    return json.loads(mod.lambda_client.invoke.call_args.kwargs["Payload"])


def test_uncompressed_document_is_passed_through(mod):
    """The pre-existing happy path: nothing to inflate, invoke verbatim."""
    doc = {"id": "doc.pdf", "status": "COMPLETED", "sections": []}
    result = mod.handler(_event(doc, include_input=False), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["outputDecompressed"] is False
    assert body["sentCompressedFallback"] is False
    mod.lambda_client.invoke.assert_called_once()
    assert mod.lambda_client.invoke.call_args.kwargs["InvocationType"] == "Event"


def test_compressed_document_is_decompressed_before_invoke(mod, monkeypatch):
    """The reason this Lambda exists: the customer function sees a real document,
    not a `{compressed: true, s3_uri}` reference."""
    inflated = MagicMock()
    inflated.num_pages = 3
    inflated.sections = ["1"]
    inflated.to_dict.return_value = {"id": "doc.pdf", "status": "COMPLETED"}
    monkeypatch.setattr(mod.Document, "load_document", lambda *a, **k: inflated)

    result = mod.handler(_event(_compressed_ref()), None)

    assert json.loads(result["body"])["outputDecompressed"] is True
    payload = _invoked_payload(mod)
    output = json.loads(payload["detail"]["output"])
    assert output["document"] == {"id": "doc.pdf", "status": "COMPLETED"}
    assert "compressed" not in output["document"]


def test_oversized_decompressed_payload_falls_back_to_compressed_event(
    mod, monkeypatch
):
    """The 1MB async ceiling. Rather than raise (and lose the invocation after
    EventBridge's retries), send the ORIGINAL compressed event — always small —
    so the hook still fires for large documents."""
    huge = {
        "id": "doc.pdf",
        "status": "COMPLETED",
        "pages": {str(i): {"text": "x" * 4000} for i in range(400)},
    }
    inflated = MagicMock()
    inflated.num_pages = 200
    inflated.sections = ["1"]
    inflated.to_dict.return_value = huge
    monkeypatch.setattr(mod.Document, "load_document", lambda *a, **k: inflated)

    ref = _compressed_ref()
    event = _event(ref)
    # Make the INPUT compressed too, so decompression rewrites both strings and
    # the rollback below is actually exercised on both (not just `output`).
    event["detail"]["input"] = json.dumps({"document": _compressed_ref()})
    original_input = event["detail"]["input"]
    result = mod.handler(event, None)

    body = json.loads(result["body"])
    assert body["sentCompressedFallback"] is True
    assert body["outputDecompressed"] is False

    # The customer function still gets invoked, with the compressed reference.
    payload = _invoked_payload(mod)
    assert json.loads(payload["detail"]["output"])["document"] == ref
    sent_bytes = len(mod.lambda_client.invoke.call_args.kwargs["Payload"].encode())
    assert sent_bytes <= mod.MAX_ASYNC_PAYLOAD_BYTES

    # BOTH decompressed strings are rolled back, not just the output one — the
    # fallback restores `detail.input`/`detail.output` in place rather than
    # deep-copying the event up front, so a partial rollback would ship a
    # half-inflated event.
    assert payload["detail"]["input"] == original_input
    assert "inputDecompressed" in body and body["inputDecompressed"] is False


def test_fallback_rollback_drops_a_key_that_was_absent(mod, monkeypatch):
    """Rollback must restore *absence*, not write None: an event with no
    `detail.input` must not gain an `input: null` key on the fallback path."""
    huge = {
        "id": "doc.pdf",
        "pages": {str(i): {"text": "x" * 4000} for i in range(400)},
    }
    inflated = MagicMock()
    inflated.num_pages = 200
    inflated.sections = ["1"]
    inflated.to_dict.return_value = huge
    monkeypatch.setattr(mod.Document, "load_document", lambda *a, **k: inflated)

    result = mod.handler(_event(_compressed_ref(), include_input=False), None)
    assert json.loads(result["body"])["sentCompressedFallback"] is True
    assert "input" not in _invoked_payload(mod)["detail"]


def test_payload_just_under_the_limit_is_still_sent_decompressed(mod, monkeypatch):
    """Guard the boundary from the other side: the fallback must not trigger for
    ordinary documents, which would silently regress every existing hook to
    receiving compressed references."""
    inflated = MagicMock()
    inflated.num_pages = 2
    inflated.sections = ["1"]
    inflated.to_dict.return_value = {"id": "doc.pdf", "blob": "x" * 1000}
    monkeypatch.setattr(mod.Document, "load_document", lambda *a, **k: inflated)

    result = mod.handler(_event(_compressed_ref()), None)
    body = json.loads(result["body"])
    assert body["sentCompressedFallback"] is False
    assert body["outputDecompressed"] is True


def test_superseded_document_skips_the_custom_processor(mod):
    """A PII-redaction hook halted this original after spawning a redacted copy.
    Handing the UN-REDACTED original to the customer's function is precisely what
    the redaction was meant to prevent."""
    ref = _compressed_ref(status=mod.Status.REDACTED_SUPERSEDED.value)
    result = mod.handler(_event(ref), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is True
    assert body["reason"] == "REDACTED_SUPERSEDED"
    mod.lambda_client.invoke.assert_not_called()


def test_normal_completed_document_is_not_skipped(mod):
    """The superseded guard must be narrow — only REDACTED_SUPERSEDED."""
    result = mod.handler(
        _event({"id": "doc.pdf", "status": "COMPLETED"}, include_input=False), None
    )
    assert json.loads(result["body"]).get("skipped") is None
    mod.lambda_client.invoke.assert_called_once()


def test_missing_output_raises(mod):
    """A malformed event should surface (DLQ) rather than silently no-op."""
    with pytest.raises(ValueError, match="Missing output data"):
        mod.handler({"detail": {"status": "SUCCEEDED"}}, None)
