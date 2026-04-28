# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""AutoTune Optimization State API Lambda Handler.

Endpoints:
  POST /cancel  — Cancel a running optimization (writes status=cancelled to DynamoDB)
  GET  /state   — Retrieve current optimization state for a session

The DynamoDB item schema may evolve. GET /state returns the raw item as-is
so the frontend should handle unknown/missing fields gracefully.
"""

import os
from typing import Any, Dict

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.logging.correlation_paths import API_GATEWAY_REST
from aws_lambda_powertools.utilities.typing import LambdaContext

TABLE_NAME = os.environ["TABLE_NAME"]
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
logger = Logger()
app = APIGatewayRestResolver(cors=cors_config)


@app.post("/cancel")
def cancel_optimization() -> Dict[str, Any]:
    """Cancel a running optimization by setting status=cancelled."""
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
    """Retrieve optimization state for a session. Returns raw DynamoDB item."""
    session_id = app.current_event.get_query_string_value("sessionId", "").strip()
    if not session_id:
        return {"error": "sessionId query parameter is required"}, 400

    try:
        resp = table.get_item(Key={"session_id": session_id})
        item = resp.get("Item")
        if not item:
            return {"error": "Session not found"}, 404
        # Return raw item — frontend should handle unknown/missing fields.
        # Convert Decimal to float/int for JSON serialization.
        return {"state": _serialize(item)}
    except Exception as e:
        logger.exception("Failed to get optimization state")
        return {"error": str(e)}, 500


def _serialize(obj):
    """Convert DynamoDB Decimals to Python numbers for JSON."""
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
