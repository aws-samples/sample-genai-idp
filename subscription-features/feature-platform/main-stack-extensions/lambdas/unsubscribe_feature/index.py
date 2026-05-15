# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Mutation.unsubscribeFeature resolver. Admin-only.

Symmetric with subscribe_feature — marks the simulator entitlement as
EXPIRED by POSTing to the simulator's admin API. The real-Marketplace
equivalent is a 'Cancel subscription' redirect to the AWS Marketplace
Subscription Management portal; when pointed at the real Marketplace we
simply no-op here (the UI redirects the user to the portal instead).

Env vars mirror subscribe_feature's. See that module for docs.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_SIMULATOR_ADMIN_ENDPOINT = os.environ.get("SIMULATOR_ADMIN_ENDPOINT", "").rstrip("/")
_FEATURE_PRODUCT_CODE_MAP_RAW = os.environ.get("FEATURE_PRODUCT_CODE_MAP", "{}")
_DEFAULT_CUSTOMER_IDENTIFIER = os.environ.get("DEFAULT_CUSTOMER_IDENTIFIER", "")
_ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Admin")
_SOURCE_TAG = os.environ.get("SIMULATOR_SOURCE_TAG", "simulator")

try:
    _FEATURE_PRODUCT_CODE_MAP: Dict[str, str] = json.loads(
        _FEATURE_PRODUCT_CODE_MAP_RAW
    )
    if not isinstance(_FEATURE_PRODUCT_CODE_MAP, dict):
        raise ValueError("FEATURE_PRODUCT_CODE_MAP must be a JSON object")
except ValueError as exc:
    logger.warning("FEATURE_PRODUCT_CODE_MAP is not valid JSON: %s. Using {}.", exc)
    _FEATURE_PRODUCT_CODE_MAP = {}


class AuthorizationError(Exception):
    """Raised when a non-admin caller requests unsubscribeFeature."""


class UnsubscribeError(Exception):
    """Raised when the simulator's admin API returns an error."""


def _assert_admin(event: Dict[str, Any]) -> None:
    groups = event.get("identity", {}).get("claims", {}).get("cognito:groups", []) or []
    if isinstance(groups, str):
        groups = [groups]
    if _ADMIN_GROUP not in groups:
        raise AuthorizationError(
            f"unsubscribeFeature requires membership in group {_ADMIN_GROUP!r}"
        )


def _resolve_customer_identifier(event: Dict[str, Any]) -> Optional[str]:
    headers = (event.get("request", {}) or {}).get("headers", {}) or {}
    for key in (
        "x-amzn-marketplace-customer-identifier",
        "X-Amzn-Marketplace-Customer-Identifier",
    ):
        if headers.get(key):
            return headers[key]
    return _DEFAULT_CUSTOMER_IDENTIFIER or None


def _post_json(url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — admin API is trusted-env
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500] if exc.fp else ""
        raise UnsubscribeError(
            f"Simulator admin API returned {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UnsubscribeError(f"Failed to reach simulator at {url}: {exc}") from exc
    try:
        return json.loads(raw) if raw else {}
    except ValueError as exc:
        raise UnsubscribeError(f"Simulator admin API returned non-JSON: {exc}") from exc


def _expire_entitlement(
    customer_identifier: str, product_code: str, feature_id: str
) -> Dict[str, Any]:
    """Call the simulator's admin endpoint to expire the entitlement."""
    if not _SIMULATOR_ADMIN_ENDPOINT:
        raise UnsubscribeError(
            "SIMULATOR_ADMIN_ENDPOINT is not configured; unsubscribeFeature "
            "requires a running simulator (or a real Marketplace redirect in "
            "production)."
        )
    url = f"{_SIMULATOR_ADMIN_ENDPOINT}/admin/entitlements/expire"
    body = {
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "featureId": feature_id,
    }
    logger.info("Simulator expire entitlement: POST %s body=%s", url, body)
    return _post_json(url, body)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return (
            datetime.fromtimestamp(float(value), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    return None


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("unsubscribeFeature event: %s", event)
    _assert_admin(event)

    args = event.get("arguments", {}) or {}
    feature_id = args.get("featureId")
    if not feature_id or not isinstance(feature_id, str):
        raise ValueError("featureId is required")

    # In simulator mode, synthesize the same product code + customer
    # identifier as subscribe_feature / check_feature_entitlement so the
    # simulator's expire-entitlement call targets the row we created.
    product_code = _FEATURE_PRODUCT_CODE_MAP.get(feature_id)
    if not product_code:
        if _SOURCE_TAG == "simulator":
            product_code = f"prod-{feature_id}-sim"
            logger.info(
                "No productCode mapped for %r; synthesizing %r for simulator mode.",
                feature_id,
                product_code,
            )
        else:
            raise UnsubscribeError(
                f"No productCode mapped for feature {feature_id!r}. "
                f"Configure FeaturePlatformProductCodeMap to include this feature."
            )

    customer_identifier = _resolve_customer_identifier(event)
    if not customer_identifier:
        if _SOURCE_TAG == "simulator":
            customer_identifier = "cust-idp-default"
            logger.info(
                "No CustomerIdentifier provided; using default %r for simulator mode.",
                customer_identifier,
            )
        else:
            raise UnsubscribeError(
                "No CustomerIdentifier available. Configure "
                "FeaturePlatformDefaultCustomerIdentifier or pass "
                "X-Amzn-Marketplace-Customer-Identifier."
            )

    sim_resp = _expire_entitlement(customer_identifier, product_code, feature_id)
    expires_at = _iso(sim_resp.get("expiresAt"))
    # Fallback: stamp 'now' so the UI can sort by expiry.
    if expires_at is None:
        expires_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "featureId": feature_id,
        "state": "EXPIRED",
        "expiresAt": expires_at,
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "source": _SOURCE_TAG,
    }
