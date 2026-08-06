# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the ConfBench ingest worker.

Focused on the failure modes the original PR #583 deployer got wrong, since
those are the reason this was reworked:

  * `document_id` unbound in the exception handler (masked the real error)
  * `abort_multipart_upload` unguarded (replaced the original exception)
  * unbounded error strings in the failure report
  * 404 treated the same as a transient 5xx
"""

# The fakes below mirror boto3's keyword-only call signatures (Bucket=, Key=,
# UploadId=, ...) so the code under test calls them exactly as it calls botocore.
# Most parameters are deliberately unused by the fake.
# pyright: reportUnusedParameter=false

import io
import urllib.error
from typing import Any, Dict, List

import pytest


class FakeContext:
    """Lambda context stub with a controllable remaining-time clock."""

    def __init__(self, remaining_ms: int = 900_000):
        self._remaining = remaining_ms

    def get_remaining_time_in_millis(self) -> int:
        return self._remaining

    def set_remaining(self, ms: int) -> None:
        self._remaining = ms


def _row(doc_id: str, variant: str = "original", pages: int = 2) -> Dict[str, Any]:
    return {
        "id": doc_id,
        "noise_variant": variant,
        "page_count": pages,
        "json_response": {"Agency": "ACME", "Advertiser": "Widgets", "LineItems": []},
    }


@pytest.fixture
def worker(monkeypatch):
    """The worker module with S3/DynamoDB replaced by recording fakes."""
    import index

    state: Dict[str, Any] = {
        "puts": [],
        "mpu_created": [],
        "mpu_completed": [],
        "mpu_aborted": [],
        "counters": [],
        "failure_reports": [],
        "abort_should_raise": False,
    }

    class FakeS3:
        class exceptions:  # noqa: N801 - mirrors botocore's attribute shape
            class NoSuchKey(Exception):
                pass

        def get_object(self, Bucket, Key):  # noqa: N803
            if Key.endswith("rows.json"):
                import json

                return {"Body": io.BytesIO(json.dumps(state["rows"]).encode())}
            raise FakeS3.exceptions.NoSuchKey()

        def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
            if "/failures/" in Key:
                state["failure_reports"].append((Key, Body))
            else:
                state["puts"].append(Key)

        def create_multipart_upload(self, Bucket, Key, **kw):  # noqa: N803
            state["mpu_created"].append(Key)
            return {"UploadId": f"upload-{len(state['mpu_created'])}"}

        def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):  # noqa: N803
            return {"ETag": f'"etag-{PartNumber}"'}

        def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):  # noqa: N803
            state["mpu_completed"].append(Key)

        def abort_multipart_upload(self, Bucket, Key, UploadId):  # noqa: N803
            state["mpu_aborted"].append(Key)
            if state["abort_should_raise"]:
                raise RuntimeError("abort failed: throttled")

    class FakeTable:
        def update_item(self, **kw):
            state["counters"].append(kw)

    class FakeDdb:
        def Table(self, name):  # noqa: N802
            return FakeTable()

    monkeypatch.setattr(index, "_s3", FakeS3())
    monkeypatch.setattr(index, "_ddb", FakeDdb())
    index._test_state = state  # type: ignore[attr-defined]
    return index, state


def _stub_download(monkeypatch, index, payload: bytes = b"%PDF-1.4 fake"):
    """Replace the CDN fetch with an in-memory body."""

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        index.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(payload)
    )


@pytest.mark.unit
class TestRetryClassification:
    def test_5xx_is_retryable(self, worker):
        index, _ = worker
        for code in (500, 502, 503, 504):
            exc = urllib.error.HTTPError("u", code, "err", None, None)  # type: ignore[arg-type]
            assert index._is_retryable(exc), f"{code} should be retryable"

    def test_429_is_retryable(self, worker):
        """Throttling from the CDN — the whole point of backoff."""
        index, _ = worker
        exc = urllib.error.HTTPError("u", 429, "slow down", None, None)  # type: ignore[arg-type]
        assert index._is_retryable(exc)

    def test_404_is_not_retryable(self, worker):
        """A missing object will still be missing after 5 retries; retrying it
        just burns the state machine's attempt budget."""
        index, _ = worker
        exc = urllib.error.HTTPError("u", 404, "not found", None, None)  # type: ignore[arg-type]
        assert not index._is_retryable(exc)

    def test_403_is_not_retryable(self, worker):
        index, _ = worker
        exc = urllib.error.HTTPError("u", 403, "forbidden", None, None)  # type: ignore[arg-type]
        assert not index._is_retryable(exc)

    def test_connection_reset_is_retryable(self, worker):
        index, _ = worker
        assert index._is_retryable(ConnectionResetError("reset"))

    def test_value_error_is_not_retryable(self, worker):
        index, _ = worker
        assert not index._is_retryable(ValueError("malformed"))


@pytest.mark.unit
class TestErrorTruncation:
    def test_long_errors_are_bounded(self, worker):
        """The original wrote str(e) untruncated into the failure report while
        capping it elsewhere, so a systemic failure produced an unbounded S3
        object."""
        index, _ = worker
        assert len(index._truncate("x" * 5000)) == 500
        assert index._truncate("x" * 5000).endswith("...")

    def test_short_errors_pass_through_unchanged(self, worker):
        index, _ = worker
        assert index._truncate("boom") == "boom"


@pytest.mark.unit
class TestMalformedRows:
    def test_missing_id_does_not_raise_name_error(self, worker, monkeypatch):
        """PR #583 bound document_id as the first statement INSIDE the try, so a
        row whose id lookup failed raised NameError from the except clause
        itself — masking the real fault and aborting the chunk."""
        index, state = worker
        state["rows"] = [{"noise_variant": "original"}]  # no id, no ground truth
        _stub_download(monkeypatch, index)

        result = index.handler(
            {
                "jobId": "job1",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        # Skipped cleanly rather than exploding.
        assert result["skipped"] == 1
        assert result["uploaded"] == 0
        assert result["done"] is True

    def test_zero_page_count_is_skipped(self, worker, monkeypatch):
        index, state = worker
        state["rows"] = [_row("a__original.pdf", pages=0)]
        _stub_download(monkeypatch, index)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["skipped"] == 1
        assert result["uploaded"] == 0

    def test_missing_ground_truth_is_skipped(self, worker, monkeypatch):
        index, state = worker
        row = _row("a__original.pdf")
        row["json_response"] = None
        state["rows"] = [row]
        _stub_download(monkeypatch, index)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["skipped"] == 1


@pytest.mark.unit
class TestAbortGuard:
    def test_failing_abort_does_not_mask_the_original_error(self, worker, monkeypatch):
        """PR #583 called abort_multipart_upload unguarded before recording the
        error, so a failing abort replaced the real exception and lost the retry
        classification entirely."""
        index, state = worker
        state["rows"] = [_row("a__original.pdf")]
        state["abort_should_raise"] = True

        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 503, "cdn down", None, None)  # type: ignore[arg-type]

        monkeypatch.setattr(index.urllib.request, "urlopen", boom)

        # The original 503 must survive as a RetryableIngestError; the abort's
        # own RuntimeError must not take its place.
        with pytest.raises(index.RetryableIngestError, match="503|cdn down"):
            index.handler(
                {
                    "jobId": "j",
                    "testSetId": "confbench-clean",
                    "variant": "original",
                    "offset": 0,
                },
                FakeContext(),
            )
        assert state["mpu_aborted"], "abort should still have been attempted"

    def test_abort_is_called_on_transfer_failure(self, worker, monkeypatch):
        index, state = worker
        state["rows"] = [_row("a__original.pdf")]

        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 404, "gone", None, None)  # type: ignore[arg-type]

        monkeypatch.setattr(index.urllib.request, "urlopen", boom)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        # 404 is permanent: recorded as a failure, not raised.
        assert result["failed"] == 1
        assert state["mpu_aborted"] == ["confbench-clean/input/a__original.pdf"]


@pytest.mark.unit
class TestHappyPath:
    def test_uploads_pdf_and_baseline(self, worker, monkeypatch):
        index, state = worker
        state["rows"] = [_row("a__original.pdf"), _row("b__original.pdf")]
        _stub_download(monkeypatch, index)

        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["uploaded"] == 2
        assert result["done"] is True
        assert result["offset"] == 2
        assert state["mpu_completed"] == [
            "confbench-clean/input/a__original.pdf",
            "confbench-clean/input/b__original.pdf",
        ]
        # One baseline per document, at the shape Test Studio's evaluation reads.
        assert state["puts"] == [
            "confbench-clean/baseline/a__original.pdf/sections/1/result.json",
            "confbench-clean/baseline/b__original.pdf/sections/1/result.json",
        ]

    def test_only_processes_the_requested_variant(self, worker, monkeypatch):
        """Each worker owns exactly one variant; cross-contamination would
        double-upload under concurrency."""
        index, state = worker
        state["rows"] = [
            _row("a__original.pdf", "original"),
            _row("b__custom15.pdf", "custom15"),
        ]
        _stub_download(monkeypatch, index)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench",
                "variant": "custom15",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["uploaded"] == 1
        assert state["mpu_completed"] == ["confbench/input/b__custom15.pdf"]

    def test_baseline_shape_matches_host_expectations(self, worker, monkeypatch):
        """document_class / split_document.page_indices / inference_result — the
        exact shape the main stack's other deployers write."""
        import json

        index, state = worker
        state["rows"] = [_row("a__original.pdf", pages=3)]
        captured: List[bytes] = []

        original_put = index._s3.put_object

        def capture(Bucket, Key, Body, **kw):  # noqa: N803
            captured.append(Body)
            return original_put(Bucket=Bucket, Key=Key, Body=Body, **kw)

        monkeypatch.setattr(index._s3, "put_object", capture)
        _stub_download(monkeypatch, index)
        index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        payload = json.loads(captured[0])
        assert payload["document_class"] == {"type": "Invoice"}
        assert payload["split_document"]["page_indices"] == [0, 1, 2]
        assert payload["inference_result"]["Agency"] == "ACME"


@pytest.mark.unit
class TestResumeAndGuards:
    def test_resumes_from_offset(self, worker, monkeypatch):
        index, state = worker
        state["rows"] = [_row(f"{c}__original.pdf") for c in "abcd"]
        _stub_download(monkeypatch, index)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 2,
            },
            FakeContext(),
        )
        assert result["uploaded"] == 2
        assert result["offset"] == 4
        # Rows are sorted by id, so offset 2 starts at 'c'.
        assert state["mpu_completed"] == [
            "confbench-clean/input/c__original.pdf",
            "confbench-clean/input/d__original.pdf",
        ]

    def test_time_guard_stops_early_and_reports_not_done(self, worker, monkeypatch):
        """The worker must stop cleanly and hand back an offset rather than die
        at the timeout mid-file."""
        index, state = worker
        state["rows"] = [_row(f"{c}__original.pdf") for c in "abcdef"]
        _stub_download(monkeypatch, index)
        # Below TIME_GUARD_SECONDS from the start: no file should be attempted.
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(remaining_ms=30_000),
        )
        assert result["done"] is False
        assert result["uploaded"] == 0
        assert result["offset"] == 0

    def test_byte_budget_stops_early(self, worker, monkeypatch):
        """Sharding is by bytes, not file count: variant sizes span 0.02 GB to
        7.12 GB, so a fixed file count cannot bound the work."""
        index, state = worker
        state["rows"] = [_row(f"{c}__original.pdf") for c in "abcd"]
        _stub_download(monkeypatch, index, payload=b"x" * 1024)
        monkeypatch.setattr(index, "MAX_WORKER_BYTES", 2048)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["done"] is False
        assert result["uploaded"] == 2  # stopped once the budget was reached
        assert result["offset"] == 2

    def test_resume_loop_returns_all_keys_the_next_pass_needs(
        self, worker, monkeypatch
    ):
        """The state machine feeds the worker's own output back in as the next
        pass's input, so the return value must be a valid input."""
        index, state = worker
        state["rows"] = [_row(f"{c}__original.pdf") for c in "abcd"]
        _stub_download(monkeypatch, index, payload=b"x" * 1024)
        monkeypatch.setattr(index, "MAX_WORKER_BYTES", 1024)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        for key in ("jobId", "testSetId", "variant", "offset"):
            assert key in result


@pytest.mark.unit
class TestFailureReporting:
    def test_failures_go_to_s3_not_the_payload(self, worker, monkeypatch):
        """PR #583 accumulated failures inside the async self-invoke payload,
        which silently breaks the chain past Lambda's 256 KB Event limit during
        exactly the systemic failure you most want reported."""
        index, state = worker
        state["rows"] = [_row(f"{c}__original.pdf") for c in "ab"]

        def boom(*a, **kw):
            raise urllib.error.HTTPError("u", 404, "gone", None, None)  # type: ignore[arg-type]

        monkeypatch.setattr(index.urllib.request, "urlopen", boom)
        result = index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert result["failed"] == 2
        # The payload carries a COUNT; the detail lives in S3.
        assert isinstance(result["failed"], int)
        assert state["failure_reports"], "failures should be persisted to S3"
        key, _ = state["failure_reports"][0]
        assert key == "_confbench_jobs/j/failures/original.json"

    def test_counters_are_added_not_set(self, worker, monkeypatch):
        """Up to 4 variant workers run concurrently, so a read-modify-write on
        the shared job row would lose updates."""
        index, state = worker
        state["rows"] = [_row("a__original.pdf")]
        _stub_download(monkeypatch, index)
        index.handler(
            {
                "jobId": "j",
                "testSetId": "confbench-clean",
                "variant": "original",
                "offset": 0,
            },
            FakeContext(),
        )
        assert state["counters"], "job counters should be updated"
        expr = state["counters"][-1]["UpdateExpression"]
        assert expr.startswith("ADD "), f"expected an atomic ADD, got {expr!r}"
