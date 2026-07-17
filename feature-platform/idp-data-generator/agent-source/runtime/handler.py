# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AgentCore Runtime entrypoint hosting the SEED generator for config bootstrap.

Runs as an HTTP server implementing the AgentCore Runtime service contract
(``/invocations`` POST + ``/ping`` GET on port 8080) via ``BedrockAgentCoreApp``.
WeasyPrint, augraphy, opencv and their native libraries exceed Lambda's package
limits and need a full Debian base, so the generator is hosted on an AgentCore
Runtime rather than a Lambda.

The invocation payload carries the SynthesisJob fields plus the bootstrap
identifiers (jobId, testSetId). A single generation run takes minutes, so the
work runs on a background thread tracked with ``add_async_task``: ``/ping``
reports ``HealthyBusy`` while it runs, keeping the runtime session alive, and
``/invocations`` returns immediately with an acknowledgement. Progress and the
terminal result are posted to AppSync so the UI sees live updates — the same
status contract the container-Lambda used.
"""

import logging
import os
import shutil
import tempfile
import threading

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

app = BedrockAgentCoreApp()


def _download_schema_dir(bucket, prefix, dest_dir):
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix) :].lstrip("/")
            if not rel:
                continue
            local_path = os.path.join(dest_dir, rel)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            s3.download_file(bucket, key, local_path)


def _run_job(payload):
    """Generate a labeled test set from a staged schema_dir.

    Runs on a background thread; never raises into the caller — terminal status
    is reported to AppSync.
    """
    from idp_common.synthesis import engine, packet_io

    job_id = payload["jobId"]
    test_set_id = payload["testSetId"]
    working_bucket = payload["workingBucket"]
    schema_prefix = payload["schemaPrefix"]
    test_set_bucket = payload["testSetBucket"]
    count = int(payload.get("count", 3))
    threshold = int(payload.get("threshold", 7))
    augment = bool(payload.get("augment", False))
    extra = payload.get("extra", "")
    model_id = payload.get("modelId")
    allowed_field_names = set(payload.get("allowedFieldNames", []))

    work_dir = tempfile.mkdtemp(prefix="synthesis-runtime-")
    try:
        schema_dir = os.path.join(work_dir, "schema")
        out_dir = os.path.join(work_dir, "out")
        os.makedirs(schema_dir, exist_ok=True)
        _download_schema_dir(working_bucket, schema_prefix, schema_dir)

        job = engine.SynthesisJob(
            schema_dir=schema_dir,
            out_dir=out_dir,
            count=count,
            threshold=threshold,
            augment=augment,
            extra=extra,
            model_id=model_id,
        )

        def _status(pct, msg):
            logger.info("[%s] %.0f%% %s", job_id, pct, msg)
            _post_status(payload, job_id, "IN_PROGRESS", f"{pct:.0f}% {msg}")

        result = engine.synthesize(job, status_cb=_status)
        if not result.success or not result.packet_dir:
            _post_status(payload, job_id, "FAILED", result.error or "Generation failed")
            return

        documents = packet_io.read_packet(result.packet_dir)
        if allowed_field_names:
            removed = packet_io.prune_documents_to_allowed_fields(
                documents, allowed_field_names
            )
            if removed:
                logger.info(
                    "[%s] pruned %d extra field(s) not in schema from baseline",
                    job_id,
                    removed,
                )

        uploaded = packet_io.upload_packet_to_test_set(
            documents, test_set_id, test_set_bucket
        )
        _post_status(
            payload,
            job_id,
            "COMPLETED",
            f"{uploaded} document(s) in test set {test_set_id}",
        )
    except Exception as e:
        logger.exception("Synthesis job %s failed", job_id)
        _post_status(payload, job_id, "FAILED", str(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.entrypoint
def invoke(payload, context=None):
    """AgentCore Runtime entrypoint.

    Kicks off generation on a background thread and returns immediately. The
    task is tracked so ``/ping`` reports ``HealthyBusy`` until it completes,
    keeping the runtime session alive for the full (multi-minute) run.
    """
    job_id = payload.get("jobId")
    task_id = app.add_async_task("synthesis", {"jobId": job_id})

    def _worker():
        try:
            _run_job(payload)
        finally:
            app.complete_async_task(task_id)

    threading.Thread(target=_worker, daemon=True).start()

    return {"accepted": True, "jobId": job_id, "testSetId": payload.get("testSetId")}


def _post_status(payload, job_id, status, message):
    # The runtime owns TERMINAL status: the BootstrapProcessor invokes this
    # runtime asynchronously and returns (leaving the job IN_PROGRESS), so only
    # the runtime knows when generation actually finishes. Write status to the
    # feature's BootstrapTrackingTable (read back via the FeatureApi GET /jobs).
    # The AppSync status channel was removed with the host's AppSync->REST
    # migration. Best-effort: never let a status write failure crash the run.
    logger.info("synthesis job %s: %s — %s", job_id, status, message)
    table_name = os.environ.get("BOOTSTRAP_TRACKING_TABLE")
    if not (table_name and job_id):
        return
    attrs = {"status": status}
    if message:
        attrs["statusMessage"] = message
    if status == "FAILED" and message:
        attrs["errorMessage"] = message
    try:
        boto3.resource("dynamodb").Table(table_name).update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in attrs),
            ExpressionAttributeNames={f"#{k}": k for k in attrs},
            ExpressionAttributeValues={f":{k}": v for k, v in attrs.items()},
        )
    except Exception:  # noqa: BLE001 — status is best-effort
        logger.warning("Failed to write job status for %s", job_id, exc_info=True)


if __name__ == "__main__":
    app.run()
