# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Query.checkFeatureEntitlement resolver.

Resolves the caller's entitlement state for a given feature by calling
`marketplace-entitlement:GetEntitlements`. Works against both the real AWS
Marketplace endpoint and the local marketplace-simulator — `boto3` picks the
endpoint from the `AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE` env var
(set by the nested stack when `SimulatorEntitlementEndpoint` is non-empty).

Each feature's Marketplace product code is read from its `InstalledFeatures`
row — baked from the feature manifest at publish time and written at install —
so the host needs no per-feature product-code configuration. The caller's
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
    INSTALLED_FEATURES_TABLE   DynamoDB table holding installed-feature rows
                               (productCode per featureId, baked from the manifest).
    DEFAULT_CUSTOMER_IDENTIFIER  (optional) fallback customer identifier
    DEFAULT_BUYER_ACCOUNT_ID   buyer AWS account used as the GetEntitlements
                               filter when no CustomerIdentifier is available
                               (the deterministic key shared with subscribeFeature).
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

_DEFAULT_CUSTOMER_IDENTIFIER = os.environ.get("DEFAULT_CUSTOMER_IDENTIFIER", "")
_DEFAULT_BUYER_ACCOUNT_ID = os.environ.get("DEFAULT_BUYER_ACCOUNT_ID", "111122223333")
_SOURCE_TAG = os.environ.get("SIMULATOR_SOURCE_TAG", "marketplace")
_CONFIGURATION_BUCKET = os.environ.get("CONFIGURATION_BUCKET", "")
_CATALOG_KEY = os.environ.get("CATALOG_KEY", "config_library/catalog.json")
_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")

_dynamodb = boto3.resource("dynamodb")


def _installed_product_code(feature_id: str) -> Optional[str]:
    """Read productCode from the feature's InstalledFeatures row (baked from the
    manifest at install time). Returns None when absent."""
    if not _INSTALLED_FEATURES_TABLE:
        return None
    try:
        row = (
            _dynamodb.Table(_INSTALLED_FEATURES_TABLE)
            .get_item(Key={"featureId": feature_id})
            .get("Item")
            or {}
        )
    except Exception as exc:  # noqa: BLE001 — treat lookup failure as "absent"
        logger.warning(
            "Could not read InstalledFeatures row for %s: %s", feature_id, exc
        )
        return None
    return row.get("productCode")


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
    product_code: str,
    *,
    customer_identifier: Optional[str] = None,
    customer_aws_account_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call GetEntitlements filtered by customer identifier OR buyer AWS account.

    The two filters are mutually exclusive (per the real API). When the caller
    has a concrete CustomerIdentifier (Marketplace header / configured default)
    we filter by it; otherwise we filter by the buyer AWS account, which is the
    deterministic key both subscribe and check share in simulator mode (the
    simulator mints a random CustomerIdentifier per subscribe, so the account is
    the only id known on both sides ahead of time).
    """
    client = _client()
    if customer_identifier:
        filt = {"CUSTOMER_IDENTIFIER": [customer_identifier]}
    elif customer_aws_account_id:
        filt = {"CUSTOMER_AWS_ACCOUNT_ID": [customer_aws_account_id]}
    else:
        return []
    try:
        resp = client.get_entitlements(ProductCode=product_code, Filter=filt)
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

    # Resolve product code from the feature's InstalledFeatures row (baked from
    # the manifest at install). In simulator mode, synthesize one when absent to
    # match what subscribe_feature synthesizes, so subscribe → check find the
    # same entitlement row. In marketplace mode, return NONE when absent (rather
    # than crashing) so the UI can still render the page.
    product_code = _installed_product_code(feature_id)
    if not product_code:
        if _SOURCE_TAG == "simulator":
            product_code = f"prod-{feature_id}-sim"
            logger.info(
                "No productCode on the install row for %r; using synthesized %r "
                "for simulator mode.",
                feature_id,
                product_code,
            )
        else:
            logger.info(
                "No productCode on the install row for feature %s; returning NONE.",
                feature_id,
            )
            return {
                "featureId": feature_id,
                "state": "NONE",
                "expiresAt": None,
                "customerIdentifier": None,
                "productCode": None,
                "source": "none",
            }

    # Resolve who to look up. A concrete CustomerIdentifier (Marketplace header
    # or configured default) wins. Otherwise — the common simulator case — fall
    # back to the buyer AWS account, the deterministic key shared with
    # subscribe_feature: the simulator mints a RANDOM CustomerIdentifier per
    # subscribe, so the account is the only id both sides know ahead of time.
    # GetEntitlements(CUSTOMER_AWS_ACCOUNT_ID) resolves it to whatever the
    # subscription recorded. (In simulator mode the buyer account always has a
    # value; in real-Marketplace mode without a header/default we return NONE.)
    customer_identifier = _resolve_customer_identifier(event)
    account_filter = None
    if not customer_identifier:
        if _SOURCE_TAG == "simulator" and _DEFAULT_BUYER_ACCOUNT_ID:
            account_filter = _DEFAULT_BUYER_ACCOUNT_ID
            logger.info(
                "No CustomerIdentifier provided; filtering by buyer AWS account "
                "%r for simulator mode.",
                account_filter,
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

    entitlements = _get_entitlements(
        product_code,
        customer_identifier=customer_identifier,
        customer_aws_account_id=account_filter,
    )
    evaluated = _evaluate(entitlements)

    # Echo back the resolved customer identifier from the matched entitlement
    # when we looked up by account (so the UI can display it).
    resolved_cid = customer_identifier
    if resolved_cid is None and entitlements:
        resolved_cid = entitlements[0].get("CustomerIdentifier")

    return {
        "featureId": feature_id,
        "state": evaluated["state"],
        "expiresAt": evaluated["expiresAt"],
        "customerIdentifier": resolved_cid,
        "productCode": product_code,
        "source": _SOURCE_TAG,
    }
