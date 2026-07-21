# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""IDP Data Generator feature API.

Fronted by the host's Cognito JWT authorizer (template.yaml FeatureApi), so this
handler only does application logic. It is the endpoint the host's Quick Start
tools discover (via listInstalledFeatures.featureApiEndpoint) and POST jobs to,
and the surface the feature UI page calls.

Routes
------
POST /generate
    Body (one of):
      - { prompt: str, className?: str, docCount?: int, threshold?: int,
          augment?: bool } — the processor authors a schema from the prompt.
      - { schema: <json-schema obj>, configVersion: str, docCount?: int,
          threshold?: int, augment?: bool } — preauthored schema.
    Enqueues a generation job. Returns { jobId }.

POST /generate-from-config
    Body: { versionName: str, className: str, docCount?: int, threshold?: int,
            augment?: bool }
    Reads the class schema from an existing config version and enqueues. Returns
    { jobId }. (The processor resolves the class -> generator schema; see
    bootstrap-processor.)

GET /jobs
    Returns in-flight jobs (PENDING/IN_PROGRESS) so the UI can surface jobs it
    did not itself start (e.g. started from Quick Start).

GET /jobs/{jobId}
    Returns the BootstrapTrackingTable row for a job (status, message, etc.).

GET /config
    Returns lightweight UI config (featureId, version) for the feature page.

NOTE (scaffold): the request/response contract here is the proposed shape and
mirrors the SQS message body the host's quick_start bootstrap_tools enqueues
today. Finalize alongside the host Quick Start rewire (the discovery tool then
POSTs here instead of writing a host queue). See README.md.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict

import boto3
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_QUEUE_URL = os.environ.get("BOOTSTRAP_QUEUE_URL", "")
_TRACKING_TABLE = os.environ.get("BOOTSTRAP_TRACKING_TABLE", "")
_CONFIG_TABLE = os.environ.get("CONFIGURATION_TABLE_NAME", "")
_FEATURE_VERSION = os.environ.get("FEATURE_VERSION", "")

_sqs = boto3.client("sqs")
_dynamodb = boto3.resource("dynamodb")


def _resp(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _enqueue(message: Dict[str, Any]) -> str:
    job_id = message["jobId"]
    _sqs.send_message(QueueUrl=_QUEUE_URL, MessageBody=json.dumps(message))
    return job_id


def _handle_generate(body: Dict[str, Any]) -> Dict[str, Any]:
    # Two shapes: a natural-language prompt (the processor authors a schema), or
    # a preauthored schema + target version. Require one or the other.
    prompt = (body.get("prompt") or "").strip()
    schema = body.get("schema")
    if not prompt and not schema:
        return _resp(400, {"error": "either prompt or schema is required"})

    message = {
        "jobId": uuid.uuid4().hex,
        "prompt": prompt,
        "className": body.get("className"),
        "docCount": int(body.get("docCount", 3)),
        "threshold": int(body.get("threshold", 7)),
        "augment": bool(body.get("augment", False)),
        "generateDocs": True,
    }
    if schema:
        # Preauthored path — the processor uses the schema as-is and writes it
        # into targetVersion (defaults to a bootstrap-<class> version otherwise).
        message["preauthoredSchema"] = schema
        message["targetVersion"] = body.get("configVersion")
    return _resp(202, {"jobId": _enqueue(message)})


def _handle_generate_from_config(body: Dict[str, Any]) -> Dict[str, Any]:
    version_name = body.get("versionName")
    class_name = body.get("className")
    if not version_name or not class_name:
        return _resp(400, {"error": "versionName and className are required"})
    message = {
        "jobId": uuid.uuid4().hex,
        "prompt": "",
        "targetVersion": version_name,
        "className": class_name,
        "configVersion": version_name,
        "docCount": int(body.get("docCount", 3)),
        "threshold": int(body.get("threshold", 7)),
        "augment": bool(body.get("augment", False)),
        "generateDocs": True,
        # The processor reads the class from this version and builds the
        # generator schema (schema_bridge.config_class_to_generator_schema).
        "fromExistingConfig": True,
    }
    return _resp(202, {"jobId": _enqueue(message)})


def _handle_list_active_jobs() -> Dict[str, Any]:
    if not _TRACKING_TABLE:
        return _resp(500, {"error": "tracking table not configured"})
    table = _dynamodb.Table(_TRACKING_TABLE)
    jobs = []
    kwargs = {"FilterExpression": Attr("status").is_in(["PENDING", "IN_PROGRESS"])}
    while True:
        page = table.scan(**kwargs)
        jobs.extend(page.get("Items", []))
        key = page.get("LastEvaluatedKey")
        if not key:
            break
        kwargs["ExclusiveStartKey"] = key
    return _resp(200, {"jobs": jobs})


def _handle_get_job(job_id: str) -> Dict[str, Any]:
    if not _TRACKING_TABLE:
        return _resp(500, {"error": "tracking table not configured"})
    table = _dynamodb.Table(_TRACKING_TABLE)
    item = table.get_item(Key={"jobId": job_id}).get("Item")
    if not item:
        return _resp(404, {"error": "job not found", "jobId": job_id})
    return _resp(200, {"job": item})


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "GET"
    )
    raw_path = event.get("rawPath") or event.get("path") or "/"
    # Strip the API Gateway stage prefix if present.
    path = raw_path.rstrip("/") or "/"
    logger.info("%s %s", method, path)

    try:
        if method == "POST" and path.endswith("/generate"):
            return _handle_generate(json.loads(event.get("body") or "{}"))
        if method == "POST" and path.endswith("/generate-from-config"):
            return _handle_generate_from_config(json.loads(event.get("body") or "{}"))
        if method == "GET" and "/jobs/" in path:
            return _handle_get_job(path.rsplit("/jobs/", 1)[-1])
        if method == "GET" and path.endswith("/jobs"):
            return _handle_list_active_jobs()
        if method == "GET" and path.endswith("/config"):
            return _resp(
                200, {"featureId": "idp-data-generator", "version": _FEATURE_VERSION}
            )
        return _resp(404, {"error": f"no route for {method} {path}"})
    except json.JSONDecodeError:
        return _resp(400, {"error": "invalid JSON body"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("feature-api error")
        return _resp(500, {"error": str(exc)})
