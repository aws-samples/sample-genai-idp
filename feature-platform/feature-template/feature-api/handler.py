# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Feature API Lambda — example. Customise per feature.

The host's FeatureLoader passes a fresh Cognito JWT in the Authorization header.
The HTTP API Gateway's Cognito JWT authorizer (configured in template.yaml)
verifies it against the main stack's User Pool, so by the time this handler
runs we know the caller is authenticated.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    logger.info("Feature API request: %s", event.get("rawPath"))

    # API Gateway v2 event: routeKey / rawPath / requestContext.authorizer.jwt.claims
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    username = claims.get("cognito:username", "unknown")

    # TODO: replace with your feature's logic.
    body = {
        "message": f"Hello {username}, from my-feature API!",
        "mainStackName": os.environ.get("MAIN_STACK_NAME"),
    }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
