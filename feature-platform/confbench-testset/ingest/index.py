# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""ConfBench ingest worker — one invocation per (noise variant, byte-window).

Invoked by the feature's Step Functions state machine, which fans out a Map
state over the selected noise variants (MaxConcurrency 4). Each invocation:

  1. Reads the shared parquet row index from the job's S3 state prefix (written
     once by the planner, so 21 workers don't each re-download it).
  2. Streams this variant's PDFs from the HuggingFace CDN straight into the
     host's TestSet bucket via multipart upload, bounded memory.
  3. Writes each document's ground truth as a baseline result.json.
  4. Reports per-variant counters back to the state machine.

Design notes vs the original PR #583 deployer
---------------------------------------------
The original chained self-invocations across fixed 100-FILE chunks and only
answered CloudFormation after the last link, which put a ~32.7 GB serial
transfer inside CFN's 1-hour custom-resource deadline and made any overrun a
stack rollback. Three things change here:

* **Nothing waits.** The ingest runs as an on-demand job, not a custom
  resource. There is no deadline to straddle and no rollback failure mode; an
  overrun is a retryable job.

* **Sharding is per variant, by BYTES.** File count was the wrong unit: variant
  sizes range from `original` at 0.02 GB / 75 files to `custom15` at 7.12 GB /
  74 files — near-identical counts, a 300x size difference. Each worker walks
  its variant until it approaches MAX_WORKER_BYTES or the timeout guard, then
  returns a resume offset the state machine feeds back, so a heavy variant
  splits into several passes and a light one finishes in a single call.

* **State lives in S3 and the job table, never in an invoke payload.** The
  original accumulated a failed-id list inside the async self-invoke payload,
  which silently breaks the chain past Lambda's 256 KB Event limit during
  exactly the systemic failure you most want reported. Failures here are
  appended to a per-variant S3 object and summarised in the job table.

Retries (transient CDN 5xx, connection resets) are Step Functions' job, not
ours — see the Retry block on the Map's task state. We surface a retryable
error and let the state machine back off.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

import boto3
from botocore.config import Config
from variants import HF_PDF_DIR, HF_REPO_ID

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TESTSET_BUCKET = os.environ["TESTSET_BUCKET"]
STATE_BUCKET = os.environ["TESTSET_BUCKET"]
JOB_TABLE = os.environ["JOB_TABLE"]

# When S3_ENDPOINT_URL is set (private VPC mode), force virtual-host addressing
# so the SigV4 host header matches the VPC interface endpoint's bucket-vhost
# DNS. boto3's auto default usually picks virtual for DNS-compliant bucket names
# but is brittle (dotted bucket names fall back to path), so set it explicitly.
_s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL") or None
_s3 = boto3.client(
    "s3",
    endpoint_url=_s3_endpoint_url,
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual" if _s3_endpoint_url else "path"},
        # The CDN is the bottleneck, not S3; keep S3's own retries modest so a
        # genuine failure surfaces to Step Functions promptly.
        retries={"max_attempts": 3, "mode": "standard"},
    ),
)
_ddb = boto3.resource("dynamodb")

# Multipart part size. S3's minimum is 5 MB; 16 MB keeps peak memory well under
# the 1 GB function size while staying under the 10,000-part ceiling even for
# the 615 MB largest object in the dataset.
PART_SIZE = 16 * 1024 * 1024
# Stream read granularity.
READ_SIZE = 1024 * 1024

# Byte budget per invocation. Sized so even the slowest observed sustained CDN
# throughput (~2 MB/s) clears it inside the function's 900 s timeout with
# headroom: 900 s x 2 MB/s ~ 1.75 GB, so 1.2 GB leaves room for S3 upload time.
MAX_WORKER_BYTES = 1_200_000_000
# Stop starting new files once less than this much execution time remains.
TIME_GUARD_SECONDS = 120


class RetryableIngestError(Exception):
    """Signals Step Functions to retry this shard (transient upstream fault)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _truncate(text: str, limit: int = 500) -> str:
    """Bound an error string before it goes into S3/DynamoDB.

    botocore/urllib exception text can be long; the original deployer wrote it
    untruncated to the failure report while capping it elsewhere, so a systemic
    failure produced an unbounded object.
    """
    text = str(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _is_retryable(exc: BaseException) -> bool:
    """True for transient upstream faults worth another attempt."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    if isinstance(exc, (urllib.error.URLError, ConnectionResetError, TimeoutError)):
        return True
    # OSError last: HTTPError/URLError are subclasses, so the specific checks
    # above take precedence and a 404 is correctly NOT retried.
    return isinstance(exc, OSError)


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------
def _state_prefix(job_id: str) -> str:
    return f"_confbench_jobs/{job_id}"


def _load_rows(job_id: str) -> List[Dict[str, Any]]:
    """Read the row index the planner wrote for this job."""
    key = f"{_state_prefix(job_id)}/rows.json"
    resp = _s3.get_object(Bucket=STATE_BUCKET, Key=key)
    return json.loads(resp["Body"].read())


def _record_failures(job_id: str, variant: str, failures: List[Dict[str, str]]) -> None:
    """Append this pass's failures to the variant's failure object in S3.

    Kept out of the Step Functions payload deliberately: a systemic upstream
    failure yields hundreds of entries, and state-machine payloads are capped
    at 256 KB. S3 has no such ceiling and the object doubles as the operator's
    post-hoc report.
    """
    if not failures:
        return
    key = f"{_state_prefix(job_id)}/failures/{variant}.json"
    existing: List[Dict[str, str]] = []
    try:
        prior = _s3.get_object(Bucket=STATE_BUCKET, Key=key)
        existing = json.loads(prior["Body"].read())
    except _s3.exceptions.NoSuchKey:
        pass
    except Exception as exc:  # noqa: BLE001 - report is best-effort
        logger.warning("Could not read prior failure report %s: %s", key, exc)
    _s3.put_object(
        Bucket=STATE_BUCKET,
        Key=key,
        Body=json.dumps(existing + failures, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _bump_job_counters(job_id: str, uploaded: int, skipped: int, failed: int) -> None:
    """Atomically add this pass's counters to the job row.

    ADD (not SET) because up to 4 variant workers run concurrently; a
    read-modify-write would lose updates.
    """
    try:
        _ddb.Table(JOB_TABLE).update_item(
            Key={"jobId": job_id},
            UpdateExpression=(
                "ADD filesUploaded :u, filesSkipped :s, filesFailed :f "
                "SET updatedAt = :t"
            ),
            ExpressionAttributeValues={
                ":u": uploaded,
                ":s": skipped,
                ":f": failed,
                ":t": _now(),
            },
        )
    except Exception as exc:  # noqa: BLE001 - progress reporting is best-effort
        logger.warning("Could not update job counters for %s: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------
def _iter_parts(response: Any, part_size: int) -> Iterator[bytes]:
    """Yield fixed-size byte windows from an HTTP response body."""
    buf = bytearray()
    while True:
        chunk = response.read(READ_SIZE)
        if not chunk:
            break
        buf.extend(chunk)
        while len(buf) >= part_size:
            yield bytes(buf[:part_size])
            del buf[:part_size]
    if buf:
        yield bytes(buf)


def _hf_pdf_url(document_id: str) -> str:
    return f"https://huggingface.co/datasets/{HF_REPO_ID}/resolve/main/{HF_PDF_DIR}/{document_id}"


def _stream_pdf_to_s3(document_id: str, key: str) -> int:
    """Stream one PDF from the CDN into S3. Returns bytes written.

    Bounded memory: at most one PART_SIZE window is buffered regardless of the
    object's size (the dataset's largest is 615 MB).
    """
    mpu = _s3.create_multipart_upload(
        Bucket=TESTSET_BUCKET, Key=key, ContentType="application/pdf"
    )
    upload_id = mpu["UploadId"]
    parts: List[Dict[str, Any]] = []
    total = 0
    try:
        req = urllib.request.Request(
            _hf_pdf_url(document_id), headers={"User-Agent": "idp-confbench-extension"}
        )
        # URL is built from module constants (https://huggingface.co + the pinned
        # HF_REPO_ID), never from request input; the scheme is a fixed https.
        with urllib.request.urlopen(req, timeout=120) as response:  # nosec B310  # noqa: S310
            for part_num, data in enumerate(_iter_parts(response, PART_SIZE), start=1):
                part = _s3.upload_part(
                    Bucket=TESTSET_BUCKET,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_num,
                    Body=data,
                )
                parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
                total += len(data)
        if not parts:
            raise RetryableIngestError(f"{document_id}: upstream returned 0 bytes")
        _s3.complete_multipart_upload(
            Bucket=TESTSET_BUCKET,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        return total
    except BaseException:
        # Guard the abort itself. If abort raises (throttling, transient S3
        # fault) an unguarded call would REPLACE the original exception, hiding
        # the real cause. The bucket's AbortIncompleteMultipartUpload lifecycle
        # rule (1 day) reclaims the orphaned upload either way, so this is about
        # diagnosis, not cost.
        try:
            _s3.abort_multipart_upload(
                Bucket=TESTSET_BUCKET, Key=key, UploadId=upload_id
            )
        except Exception as abort_exc:  # noqa: BLE001
            logger.warning(
                "abort_multipart_upload failed for %s (upload %s): %s",
                key,
                upload_id,
                abort_exc,
            )
        raise


def _write_baseline(prefix: str, document_id: str, row: Dict[str, Any]) -> None:
    """Write the ground-truth baseline for one document.

    Shape matches the main stack's other test-set deployers exactly
    (document_class / split_document.page_indices / inference_result), which is
    what makes Test Studio's evaluation work against it.
    """
    page_count = int(row.get("page_count") or 0)
    result = {
        "document_class": {"type": "Invoice"},
        "split_document": {"page_indices": list(range(page_count))},
        "inference_result": row["json_response"],
    }
    _s3.put_object(
        Bucket=TESTSET_BUCKET,
        Key=f"{prefix}baseline/{document_id}/sections/1/result.json",
        Body=json.dumps(result, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Ingest one shard.

    Event (from the Map state):
      jobId, testSetId, variant, offset (resume index within the variant)

    Returns the same shape plus counters and `done`/`offset`. When `done` is
    false the state machine re-invokes with the returned offset.
    """
    job_id = event["jobId"]
    variant = event["variant"]
    test_set_id = event["testSetId"]
    offset = int(event.get("offset") or 0)
    prefix = f"{test_set_id}/"

    rows = [r for r in _load_rows(job_id) if r.get("noise_variant") == variant]
    # Sort defensively: a row missing `id` must not take down the whole shard
    # before the per-row guard below ever runs. Ordering matters because the
    # resume offset indexes into this list, so it has to be stable across
    # passes — sorting by the string form of a possibly-absent id keeps
    # malformed rows in a fixed position instead of raising.
    rows.sort(key=lambda r: str(r.get("id") or ""))
    total_rows = len(rows)

    uploaded = 0
    skipped = 0
    bytes_moved = 0
    failures: List[Dict[str, str]] = []
    idx = offset

    logger.info(
        "job=%s variant=%s resuming at %d/%d", job_id, variant, offset, total_rows
    )

    while idx < total_rows:
        # Byte budget and clock guard — stop cleanly and let the state machine
        # hand us the next window rather than dying mid-file at the timeout.
        if bytes_moved >= MAX_WORKER_BYTES:
            logger.info(
                "job=%s variant=%s byte budget reached at %d", job_id, variant, idx
            )
            break
        remaining_ms = (
            context.get_remaining_time_in_millis()
            if hasattr(context, "get_remaining_time_in_millis")
            else 900_000
        )
        if remaining_ms < TIME_GUARD_SECONDS * 1000:
            logger.info("job=%s variant=%s time guard at %d", job_id, variant, idx)
            break

        row = rows[idx]
        # Bind the id BEFORE the try. In the original this was the first
        # statement INSIDE the try, so a malformed row raised NameError from
        # the except clause itself, masking the real fault.
        document_id = str(row.get("id") or f"<row {idx}>")
        try:
            if not row.get("json_response"):
                logger.warning("Skipping %s: no ground truth", document_id)
                skipped += 1
                idx += 1
                continue
            if int(row.get("page_count") or 0) <= 0:
                logger.warning("Skipping %s: page_count is 0", document_id)
                skipped += 1
                idx += 1
                continue

            written = _stream_pdf_to_s3(document_id, f"{prefix}input/{document_id}")
            _write_baseline(prefix, document_id, row)
            uploaded += 1
            bytes_moved += written
            idx += 1
            if uploaded % 25 == 0:
                logger.info(
                    "job=%s variant=%s %d uploaded, %.2f GB",
                    job_id,
                    variant,
                    uploaded,
                    bytes_moved / 1e9,
                )
        except Exception as exc:  # noqa: BLE001
            if _is_retryable(exc):
                # Persist progress so the Step Functions retry resumes here
                # instead of re-transferring what already landed.
                _record_failures(job_id, variant, failures)
                _bump_job_counters(job_id, uploaded, skipped, len(failures))
                raise RetryableIngestError(
                    f"{variant}[{idx}] {document_id}: {_truncate(exc)}"
                ) from exc
            logger.error("Permanent failure on %s: %s", document_id, exc)
            failures.append({"id": document_id, "error": _truncate(exc)})
            idx += 1

    _record_failures(job_id, variant, failures)
    _bump_job_counters(job_id, uploaded, skipped, len(failures))

    done = idx >= total_rows
    logger.info(
        "job=%s variant=%s pass complete: %d uploaded, %d skipped, %d failed, "
        "%.2f GB, offset %d/%d, done=%s",
        job_id,
        variant,
        uploaded,
        skipped,
        len(failures),
        bytes_moved / 1e9,
        idx,
        total_rows,
        done,
    )
    return {
        "jobId": job_id,
        "testSetId": test_set_id,
        "variant": variant,
        "offset": idx,
        "totalRows": total_rows,
        "done": done,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": len(failures),
        "bytesMoved": bytes_moved,
    }
