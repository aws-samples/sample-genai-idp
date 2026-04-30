# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""AutoTune Optimization State & Stream API Lambda Handler.

Endpoints:
  POST /cancel  — Cancel a running optimization (writes status=cancelled to DynamoDB)
  GET  /state   — Get optimization state (query: ?sessionId=xxx)
  GET  /stream  — Get agent event stream JSONL (query: ?sessionId=xxx&offset=N)
  GET  /log     — Get OPTIMIZATION-LOG.md content (query: ?sessionId=xxx)
  GET  /runs    — List all optimization runs
"""

import os
from typing import Any, Dict

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.logging.correlation_paths import API_GATEWAY_REST
from aws_lambda_powertools.utilities.typing import LambdaContext

TABLE_NAME = os.environ["TABLE_NAME"]
STREAM_BUCKET = os.environ.get("STREAM_BUCKET", "")
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "*")

cors_origins = [o.strip() for o in CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
cors_config = CORSConfig(
    allow_origin=cors_origins[0] if cors_origins else "*",
    extra_origins=cors_origins[1:] if len(cors_origins) > 1 else None,
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=True,
)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3")
logger = Logger()
app = APIGatewayRestResolver(cors=cors_config)


@app.post("/cancel")
def cancel_optimization() -> Dict[str, Any]:
    body = app.current_event.json_body or {}
    session_id = body.get("sessionId", "").strip()
    if not session_id:
        return {"error": "sessionId is required"}, 400
    try:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :c",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":c": "cancelled"},
        )
        return {"success": True, "sessionId": session_id, "status": "cancelled"}
    except Exception as e:
        logger.exception("Failed to cancel optimization")
        return {"error": str(e)}, 500


@app.get("/state")
def get_state() -> Dict[str, Any]:
    session_id = app.current_event.get_query_string_value("sessionId", "").strip()
    if not session_id:
        return {"error": "sessionId query parameter is required"}, 400
    try:
        resp = table.get_item(Key={"session_id": session_id})
        item = resp.get("Item")
        if not item:
            return {"error": "Session not found"}, 404
        return {"state": _serialize(item)}
    except Exception as e:
        logger.exception("Failed to get optimization state")
        return {"error": str(e)}, 500


@app.get("/stream")
def get_stream() -> Dict[str, Any]:
    """Return agent event stream lines from S3 JSONL, starting at byte offset."""
    session_id = app.current_event.get_query_string_value("sessionId", "").strip()
    if not session_id:
        return {"error": "sessionId query parameter is required"}, 400
    if not STREAM_BUCKET:
        return {"error": "Stream bucket not configured"}, 500

    offset = int(app.current_event.get_query_string_value("offset", "0") or "0")
    s3_key = f"autotune-streams/{session_id}/stream.jsonl"

    try:
        range_header = f"bytes={offset}-" if offset > 0 else None
        kwargs = {"Bucket": STREAM_BUCKET, "Key": s3_key}
        if range_header:
            kwargs["Range"] = range_header

        resp = s3.get_object(**kwargs)
        body = resp["Body"].read()
        content_length = resp.get("ContentLength", len(body))

        lines = body.decode("utf-8", errors="replace").rstrip("\n").split("\n") if body else []
        # Filter empty lines
        lines = [l for l in lines if l.strip()]

        next_offset = offset + len(body)
        return {"lines": lines, "nextOffset": next_offset, "totalBytes": next_offset}
    except s3.exceptions.NoSuchKey:
        return {"lines": [], "nextOffset": offset, "totalBytes": 0}
    except Exception as e:
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            return {"lines": [], "nextOffset": offset, "totalBytes": 0}
        if error_code == "InvalidRange":
            return {"lines": [], "nextOffset": offset, "totalBytes": offset}
        logger.exception("Failed to get stream")
        return {"error": str(e)}, 500


@app.get("/log")
def get_log() -> Dict[str, Any]:
    """Return OPTIMIZATION-LOG.md content from S3."""
    session_id = app.current_event.get_query_string_value("sessionId", "").strip()
    if not session_id:
        return {"error": "sessionId query parameter is required"}, 400
    if not STREAM_BUCKET:
        return {"error": "Stream bucket not configured"}, 500

    s3_key = f"autotune-streams/{session_id}/OPTIMIZATION-LOG.md"
    try:
        resp = s3.get_object(Bucket=STREAM_BUCKET, Key=s3_key)
        content = resp["Body"].read().decode("utf-8", errors="replace")
        return {"content": content}
    except Exception as e:
        error_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            return {"content": ""}
        logger.exception("Failed to get optimization log")
        return {"error": str(e)}, 500


@app.get("/runs")
def list_runs() -> Dict[str, Any]:
    """List all optimization runs, most recent first."""
    projection = "session_id, #s, test_set_id, best_accuracy, iteration, started_at, updated_at, phase, phase_detail, optimization_guidance"
    try:
        items = []
        kwargs = {
            "ProjectionExpression": projection,
            "ExpressionAttributeNames": {"#s": "status"},
        }
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return {"runs": [_serialize(i) for i in items]}
    except Exception as e:
        logger.exception("Failed to list runs")
        return {"error": str(e)}, 500


def _serialize(obj):
    import decimal
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, decimal.Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    return obj


@logger.inject_lambda_context(correlation_id_path=API_GATEWAY_REST)
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)
