# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
HTTP API dispatcher — single entry point for the API Gateway HTTP API that
replaces AppSync for UI<->backend queries and mutations.

The HTTP API exposes one route, ``POST /op/{field}``, backed by a Cognito JWT
authorizer. This Lambda:

1. Normalizes the HTTP API (payload v2.0) event into the AppSync resolver event
   shape via :mod:`idp_common.api_adapter` (restoring ``cognito:groups`` to a
   list — see that module for why this matters).
2. Routes the field to its handler:
   - **Lambda-backed fields**: synchronously invokes the existing resolver
     Lambda (the same function AppSync invokes) with the AppSync-shaped event,
     so those resolvers need NO changes.
   - **DynamoDB-direct fields** (discovery jobs, agent jobs) that AppSync
     handled with VTL: served locally by :mod:`ddb_direct` (no Lambda hop).
3. Wraps the result into an HTTP API proxy response, mapping errors to status
   codes with the GraphQL-style ``{"errors": [...]}`` body the UI parses.

Field -> resolver function ARN mapping is provided via the ``FIELD_FUNCTION_MAP``
environment variable (JSON: ``{"fieldName": "FUNCTION_ARN", ...}``) populated by
CloudFormation. Fields absent from the map are handled by ``ddb_direct`` or
rejected as unknown.
"""

import json
import logging
import os
from typing import Any, Dict

import boto3

from idp_common.api_adapter import _http_response, normalize_event

import ddb_direct

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_lambda = boto3.client("lambda")

# {fieldName: resolverFunctionArn} — fields routed to existing resolver Lambdas.
FIELD_FUNCTION_MAP: Dict[str, str] = json.loads(
    os.environ.get("FIELD_FUNCTION_MAP", "{}")
)


def _invoke_resolver(function_arn: str, appsync_event: Dict[str, Any]) -> Any:
    """Synchronously invoke a resolver Lambda with an AppSync-shaped event."""
    resp = _lambda.invoke(
        FunctionName=function_arn,
        InvocationType="RequestResponse",
        Payload=json.dumps(appsync_event).encode("utf-8"),
    )
    payload = resp["Payload"].read()
    data = json.loads(payload) if payload else None

    # A handled Lambda error surfaces as FunctionError; raise so the wrapper
    # maps it to a 500 with the error message.
    if resp.get("FunctionError"):
        msg = "resolver error"
        if isinstance(data, dict):
            msg = data.get("errorMessage", msg)
        raise RuntimeError(msg)
    return data


def handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    # CORS preflight (HTTP API can be configured to route OPTIONS here).
    http = (event.get("requestContext") or {}).get("http") or {}
    if http.get("method") == "OPTIONS":
        return _http_response(200, {})

    appsync_event = normalize_event(event)
    field = appsync_event.get("info", {}).get("fieldName", "")

    if not field:
        return _http_response(
            400, {"errors": [{"message": "missing operation field", "errorType": "BadRequest"}]}
        )

    try:
        if field in FIELD_FUNCTION_MAP:
            result = _invoke_resolver(FIELD_FUNCTION_MAP[field], appsync_event)
        elif ddb_direct.handles(field):
            result = ddb_direct.dispatch(field, appsync_event)
        else:
            return _http_response(
                404,
                {"errors": [{"message": f"unknown operation: {field}", "errorType": "NotFound"}]},
            )
    except PermissionError as e:
        logger.warning("Authorization denied for %s: %s", field, e)
        return _http_response(403, {"errors": [{"message": str(e), "errorType": "Unauthorized"}]})
    except (ValueError, KeyError) as e:
        logger.warning("Bad request for %s: %s", field, e)
        return _http_response(400, {"errors": [{"message": str(e), "errorType": "BadRequest"}]})
    except Exception as e:  # noqa: BLE001
        logger.error("Dispatch error for %s: %s", field, e, exc_info=True)
        return _http_response(500, {"errors": [{"message": str(e), "errorType": "InternalError"}]})

    return _http_response(200, result)
