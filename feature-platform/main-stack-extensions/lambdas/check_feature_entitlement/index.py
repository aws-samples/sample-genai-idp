# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.checkFeatureEntitlement resolver.

Resolves the caller's entitlement state for a given feature by calling
`marketplace-entitlement:GetEntitlements`. Works against both the real AWS
Marketplace endpoint and the local marketplace-simulator — `boto3` picks the
endpoint from the `AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE` env var
(set by the nested stack when `SimulatorEntitlementEndpoint` is non-empty).

Each feature is mapped to a Marketplace product code via a lookup table passed
in through the `FEATURE_PRODUCT_CODE_MAP` env var (JSON object). The caller's
CustomerIdentifier is resolved from:
  1. `X-Amzn-Marketplace-Customer-Identifier` header via event.request.headers
     (when the main stack is deployed inside a subscribed account), or
  2. The env var `DEFAULT_CUSTOMER_IDENTIFIER` (dev/simulator convenience).

Returns `{state: ACTIVE, source: 'auto'}` immediately when SIMULATOR_SOURCE_TAG=auto
(stack deployed without simulator or Marketplace endpoint — all features are
treated as subscribed and the UI goes straight to the Install prompt).
Returns `{state: ACTIVE, source: 'oss'}` immediately for features whose catalog
entry is source="oss" — open-source features have no Marketplace contract and
install directly even when a simulator/Marketplace endpoint is configured. This
mirrors get_feature_launch_url, which skips the entitlement check for OSS.
Returns `{state: NONE}` if no product code is registered for the feature.
Returns `{state: NONE}` if the caller has no active entitlement.
Returns `{state: ACTIVE, expiresAt}` if at least one entitlement is active.
Returns `{state: EXPIRED, expiresAt}` if an entitlement exists but has expired.

Environment:
    FEATURE_PRODUCT_CODE_MAP   JSON, e.g. '{"docs-by-status": "abcdef123"}'
    DEFAULT_CUSTOMER_IDENTIFIER  (optional) fallback customer identifier
    SIMULATOR_SOURCE_TAG       "auto" | "simulator" | "marketplace"
    CONFIGURATION_BUCKET       (optional) bucket holding catalog.json; used to
                               detect OSS features. Blank disables the OSS check.
    CATALOG_KEY                Catalog key (default config_library/catalog.json)
    LOG_LEVEL                  Logging level (default INFO)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_FEATURE_PRODUCT_CODE_MAP_RAW = os.environ.get("FEATURE_PRODUCT_CODE_MAP", "{}")
_DEFAULT_CUSTOMER_IDENTIFIER = os.environ.get("DEFAULT_CUSTOMER_IDENTIFIER", "")
_SOURCE_TAG = os.environ.get("SIMULATOR_SOURCE_TAG", "marketplace")
_CONFIGURATION_BUCKET = os.environ.get("CONFIGURATION_BUCKET", "")
_CATALOG_KEY = os.environ.get("CATALOG_KEY", "config_library/catalog.json")

try:
    _FEATURE_PRODUCT_CODE_MAP: Dict[str, str] = json.loads(
        _FEATURE_PRODUCT_CODE_MAP_RAW
    )
    if not isinstance(_FEATURE_PRODUCT_CODE_MAP, dict):
        raise ValueError("FEATURE_PRODUCT_CODE_MAP must be a JSON object")
except ValueError as exc:
    logger.warning("FEATURE_PRODUCT_CODE_MAP is not valid JSON: %s. Using {}.", exc)
    _FEATURE_PRODUCT_CODE_MAP = {}

# Lazily constructed so unit tests can patch endpoint_url via env vars.
_entitlement_client = None

# Catalog lives in the stack's own ConfigurationBucket (Lambda's default region).
_config_s3_client = None


def _config_s3():
    global _config_s3_client
    if _config_s3_client is None:
        _config_s3_client = boto3.client("s3")
    return _config_s3_client


def _read_catalog_source(feature_id: str) -> Optional[str]:
    """Return the catalog.json `source` ("oss"/"marketplace") for `feature_id`.

    Returns None when the catalog is unavailable or the feature is absent.
    Single GetObject against ConfigurationBucket — never lists. Mirrors
    `_read_catalog_entry` in get_feature_launch_url so the two resolvers agree
    on which features are open-source (install-direct, no entitlement).
    """
    if not _CONFIGURATION_BUCKET:
        return None
    try:
        resp = _config_s3().get_object(Bucket=_CONFIGURATION_BUCKET, Key=_CATALOG_KEY)
        catalog = json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        logger.warning("Failed to read catalog: %s", exc)
        return None
    except (BotoCoreError, ValueError) as exc:
        logger.warning("Bad catalog JSON: %s", exc)
        return None
    for entry in catalog.get("features") or []:
        if isinstance(entry, dict) and entry.get("featureId") == feature_id:
            src = entry.get("source")
            return src if isinstance(src, str) else None
    return None


# Short explicit timeouts (override botocore's 60s default) so a stalled cold-
# start TLS/HTTP exchange is retried and fails fast inside the 30s Lambda
# budget, rather than hanging the whole invocation until Lambda kills it.
# 3 attempts × (5s connect + 5s read) worst-case = ~30s with jittered retries.
_CLIENT_CONFIG = Config(
    connect_timeout=5,
    read_timeout=5,
    retries={"max_attempts": 3, "mode": "standard"},
)


def _client():
    global _entitlement_client
    if _entitlement_client is None:
        _entitlement_client = boto3.client(
            "marketplace-entitlement", config=_CLIENT_CONFIG
        )
    return _entitlement_client


def _resolve_customer_identifier(event: Dict[str, Any]) -> Optional[str]:
    # AppSync Lambda resolver event has `request.headers` (lowercase) when
    # the caller passed custom HTTP headers through the AppSync API.
    headers = (event.get("request", {}) or {}).get("headers", {}) or {}
    for key in (
        "x-amzn-marketplace-customer-identifier",
        "X-Amzn-Marketplace-Customer-Identifier",
    ):
        if headers.get(key):
            return headers[key]
    return _DEFAULT_CUSTOMER_IDENTIFIER or None


def _get_entitlements(
    product_code: str, customer_identifier: str
) -> List[Dict[str, Any]]:
    client = _client()
    # Filters per the real GetEntitlements API: CUSTOMER_IDENTIFIER is a list of values.
    try:
        resp = client.get_entitlements(
            ProductCode=product_code,
            Filter={"CUSTOMER_IDENTIFIER": [customer_identifier]},
        )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("GetEntitlements failed for product %s: %s", product_code, exc)
        return []
    return resp.get("Entitlements", []) or []


def _parse_expiration(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        # Accept both 2026-05-05T10:00:00Z and 2026-05-05T10:00:00+00:00
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Unparseable expiration %r", raw)
            return None
    return None


def _evaluate(entitlements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the most-permissive entitlement and derive state+expiresAt.

    ACTIVE wins over EXPIRED; the latest expiration is reported.
    """
    if not entitlements:
        return {"state": "NONE", "expiresAt": None}

    now = datetime.now(timezone.utc)
    active_expirations: List[datetime] = []
    expired_expirations: List[datetime] = []
    any_no_expiry = False

    for ent in entitlements:
        exp = _parse_expiration(ent.get("ExpirationDate"))
        if exp is None:
            any_no_expiry = True
            continue
        if exp > now:
            active_expirations.append(exp)
        else:
            expired_expirations.append(exp)

    if any_no_expiry or active_expirations:
        latest_active = max(active_expirations) if active_expirations else None
        return {
            "state": "ACTIVE",
            "expiresAt": latest_active.isoformat().replace("+00:00", "Z")
            if latest_active
            else None,
        }
    latest_expired = max(expired_expirations) if expired_expirations else None
    return {
        "state": "EXPIRED",
        "expiresAt": latest_expired.isoformat().replace("+00:00", "Z")
        if latest_expired
        else None,
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("checkFeatureEntitlement event: %s", event)

    args = event.get("arguments", {}) or {}
    feature_id = args.get("featureId")
    if not feature_id or not isinstance(feature_id, str):
        raise ValueError("featureId is required")

    # Auto-subscribe mode: stack was deployed without a marketplace simulator
    # or external Marketplace endpoint. Every catalog feature is treated as
    # subscribed so the UI goes straight to the Install prompt; no Marketplace
    # call is needed (and the boto3 client is never instantiated).
    if _SOURCE_TAG == "auto":
        return {
            "featureId": feature_id,
            "state": "ACTIVE",
            "expiresAt": None,
            "customerIdentifier": None,
            "productCode": None,
            "source": "auto",
        }

    # OSS features have no AWS Marketplace contract — they install directly
    # regardless of whether a simulator/Marketplace endpoint is configured.
    # Short-circuit to ACTIVE so the UI shows the Install prompt instead of
    # "Subscription required". This mirrors get_feature_launch_url, which skips
    # the entitlement check for source=="oss" catalog entries. Only consult the
    # entitlement endpoint for marketplace features below.
    if _read_catalog_source(feature_id) == "oss":
        return {
            "featureId": feature_id,
            "state": "ACTIVE",
            "expiresAt": None,
            "customerIdentifier": None,
            "productCode": None,
            "source": "oss",
        }

    # In simulator mode, synthesize product code + customer identifier to
    # match what subscribe_feature synthesizes, so subscribe → check finds
    # the same entitlement row. In marketplace mode, return NONE when not
    # configured (rather than crashing) so the UI can still render the page
    # and prompt the admin to configure the mapping.
    product_code = _FEATURE_PRODUCT_CODE_MAP.get(feature_id)
    if not product_code:
        if _SOURCE_TAG == "simulator":
            product_code = f"prod-{feature_id}-sim"
            logger.info(
                "No productCode mapped for %r; using synthesized %r for simulator mode.",
                feature_id,
                product_code,
            )
        else:
            logger.info(
                "No productCode mapped for feature %s; returning NONE.", feature_id
            )
            return {
                "featureId": feature_id,
                "state": "NONE",
                "expiresAt": None,
                "customerIdentifier": None,
                "productCode": None,
                "source": "none",
            }

    customer_identifier = _resolve_customer_identifier(event)
    if not customer_identifier:
        if _SOURCE_TAG == "simulator":
            customer_identifier = "cust-idp-default"
            logger.info(
                "No CustomerIdentifier provided; using default %r for simulator mode.",
                customer_identifier,
            )
        else:
            logger.info(
                "No CustomerIdentifier available for feature %s; returning NONE.",
                feature_id,
            )
            return {
                "featureId": feature_id,
                "state": "NONE",
                "expiresAt": None,
                "customerIdentifier": None,
                "productCode": product_code,
                "source": _SOURCE_TAG,
            }

    entitlements = _get_entitlements(product_code, customer_identifier)
    evaluated = _evaluate(entitlements)

    return {
        "featureId": feature_id,
        "state": evaluated["state"],
        "expiresAt": evaluated["expiresAt"],
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "source": _SOURCE_TAG,
    }
