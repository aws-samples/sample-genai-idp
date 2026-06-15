# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync Mutation.subscribeFeature resolver. Admin-only.

Returns a **URL** the UI must redirect the admin to — the AWS Marketplace
product listing / terms-acceptance page. The UI opens this URL in a new
tab, the admin accepts the 3 required terms checkboxes, the simulator
(or real AWS Marketplace) records the subscription, and the UI refreshes
the entitlement state via the existing `checkFeatureEntitlement` query.

**This mirrors how the real AWS Marketplace flow works:** a subscription
is not a silent, one-click RPC — the buyer is redirected to a Marketplace-
hosted page where they accept pricing + seller EULA + AWS Customer
Agreement before the subscription becomes ACTIVE.

Returned shape (`FeatureEntitlement`):

    {
      featureId:          <input>,
      state:              "NONE",          # still NONE until admin completes the flow
      expiresAt:          null,
      customerIdentifier: <default>,       # echoed for client-side logging
      productCode:        <resolved>,
      source:             "simulator"|"marketplace",
      marketplaceUrl:     "<url to redirect to>",   # <-- NEW
    }

The simulator's HTML buyer console lives at
``${SIMULATOR_ADMIN_ENDPOINT}/marketplace/pp/<productCode>`` — see
``subscription-features/marketplace-simulator/mp_simulator/handlers/marketplace_ui.py``.

The product code and marketplace listing URL come from the feature's
``InstalledFeatures`` row — baked from ``feature.yaml``'s ``marketplace`` block
at publish time and written at install — so the host needs no per-feature
product-code configuration.

Env vars:
    SIMULATOR_ADMIN_ENDPOINT     Base URL of the simulator (e.g. https://sim.example.com).
                                 When blank and SOURCE_TAG is "simulator", raises.
                                 Also used in marketplace mode if set, otherwise the
                                 feature's install-row marketplaceListingUrl is required.
    INSTALLED_FEATURES_TABLE     DynamoDB table holding installed-feature rows
                                 (productCode / marketplaceListingUrl per featureId).
    FEATURE_OFFER_ID_MAP         JSON map {featureId: offerId}. Optional; simulator
                                 auto-creates a default public offer if missing.
    DEFAULT_CUSTOMER_IDENTIFIER  Fallback CustomerIdentifier.
    DEFAULT_BUYER_ACCOUNT_ID     12-digit simulator buyer account. Default "111122223333".
    ADMIN_GROUP                  Cognito group name required (default "Admin").
    SIMULATOR_SOURCE_TAG         "simulator" | "marketplace" (default "simulator").
    LOG_LEVEL                    Logging level (default INFO).
"""

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_SIMULATOR_ADMIN_ENDPOINT = os.environ.get("SIMULATOR_ADMIN_ENDPOINT", "").rstrip("/")
_FEATURE_OFFER_ID_MAP_RAW = os.environ.get("FEATURE_OFFER_ID_MAP", "{}")
_DEFAULT_CUSTOMER_IDENTIFIER = os.environ.get("DEFAULT_CUSTOMER_IDENTIFIER", "")
_DEFAULT_BUYER_ACCOUNT_ID = os.environ.get("DEFAULT_BUYER_ACCOUNT_ID", "111122223333")
_ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Admin")
_SOURCE_TAG = os.environ.get("SIMULATOR_SOURCE_TAG", "simulator")
_INSTALLED_FEATURES_TABLE = os.environ.get("INSTALLED_FEATURES_TABLE", "")

_dynamodb = boto3.resource("dynamodb")


def _load_json_map(raw: str, name: str) -> Dict[str, str]:
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} must be a JSON object")
        return parsed
    except ValueError as exc:
        logger.warning("%s is not valid JSON: %s. Using {}.", name, exc)
        return {}


_FEATURE_OFFER_ID_MAP = _load_json_map(
    _FEATURE_OFFER_ID_MAP_RAW, "FEATURE_OFFER_ID_MAP"
)


def _installed_marketplace_identity(feature_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Read (productCode, marketplaceListingUrl) from the feature's
    InstalledFeatures row — baked from the feature manifest at install time, so
    the host needs no per-feature configuration. Returns (None, None) when the
    feature isn't installed or carries no marketplace identity."""
    if not _INSTALLED_FEATURES_TABLE:
        return None, None
    try:
        row = (
            _dynamodb.Table(_INSTALLED_FEATURES_TABLE)
            .get_item(Key={"featureId": feature_id})
            .get("Item")
            or {}
        )
    except Exception as exc:  # noqa: BLE001 — treat lookup failure as "absent"
        logger.warning("Could not read InstalledFeatures row for %s: %s", feature_id, exc)
        return None, None
    return row.get("productCode"), row.get("marketplaceListingUrl")


class AuthorizationError(Exception):
    """Raised when a non-admin caller requests subscribeFeature."""


class SubscribeError(Exception):
    """Raised when the Lambda cannot build a valid marketplace URL."""


def _assert_admin(event: Dict[str, Any]) -> None:
    groups = event.get("identity", {}).get("claims", {}).get("cognito:groups", []) or []
    if isinstance(groups, str):
        groups = [groups]
    if _ADMIN_GROUP not in groups:
        raise AuthorizationError(
            f"subscribeFeature requires membership in group {_ADMIN_GROUP!r}"
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


def _resolve_return_url(event: Dict[str, Any], feature_id: str) -> str:
    """Pull the caller-supplied `returnUrl` query arg (AppSync mutation arg).

    The UI sends the current FeaturePage URL so the simulator can redirect
    the admin back to the app after they complete the flow. If the UI
    didn't supply one we fall back to a relative /features/{featureId}
    path so at least the query string (`?subscribe=success`) is preserved.
    """
    args = event.get("arguments", {}) or {}
    return_url = args.get("returnUrl")
    if isinstance(return_url, str) and return_url.strip():
        return return_url.strip()
    return f"/features/{feature_id}"


def _build_simulator_url(
    *,
    product_code: str,
    offer_id: Optional[str],
    feature_id: str,
    buyer_account_id: str,
    return_url: str,
) -> str:
    """Build `${SIMULATOR_ADMIN_ENDPOINT}/marketplace/pp/<productCode>?...`."""
    if not _SIMULATOR_ADMIN_ENDPOINT:
        raise SubscribeError(
            "SIMULATOR_ADMIN_ENDPOINT is not configured; subscribeFeature "
            "cannot build a Marketplace Simulation URL."
        )
    params = {
        "featureId": feature_id,
        "buyerAccountId": buyer_account_id,
        "returnUrl": return_url,
    }
    if offer_id:
        params["offerId"] = offer_id
    return (
        f"{_SIMULATOR_ADMIN_ENDPOINT}/marketplace/pp/{product_code}?{urlencode(params)}"
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    logger.info("subscribeFeature event: %s", event)
    _assert_admin(event)

    args = event.get("arguments", {}) or {}
    feature_id = args.get("featureId")
    if not feature_id or not isinstance(feature_id, str):
        raise ValueError("featureId is required")

    # Resolve product code from the feature's InstalledFeatures row (baked from
    # the manifest at install time). Simulator mode synthesizes one when absent
    # so subscribe + check find the same row; real-MP mode requires the feature
    # to have been published with marketplace.productCode set.
    product_code, installed_listing_url = _installed_marketplace_identity(feature_id)
    if not product_code:
        if _SOURCE_TAG == "simulator":
            product_code = f"prod-{feature_id}-sim"
            logger.info(
                "No productCode on the install row for %r; synthesizing %r for "
                "simulator mode.",
                feature_id,
                product_code,
            )
        else:
            raise SubscribeError(
                f"No productCode for feature {feature_id!r}. Publish the feature "
                f"with marketplace.productCode set in feature.yaml and reinstall, "
                f"so the product code travels with the install."
            )

    customer_identifier = _resolve_customer_identifier(event)
    if not customer_identifier and _SOURCE_TAG == "simulator":
        customer_identifier = "cust-idp-default"
        logger.info(
            "No CustomerIdentifier provided; using default %r for simulator mode.",
            customer_identifier,
        )

    return_url = _resolve_return_url(event, feature_id)

    # Build the URL the UI should redirect to.
    if _SOURCE_TAG == "marketplace":
        marketplace_url = installed_listing_url
        if not marketplace_url:
            # Allow fallback to a simulator endpoint if one is configured — useful
            # for staged rollouts where a feature is being tested with the
            # simulator while others are live.
            if not _SIMULATOR_ADMIN_ENDPOINT:
                raise SubscribeError(
                    f"No marketplace listing URL for feature {feature_id!r}. "
                    f"Publish the feature with marketplace.listingUrl set in "
                    f"feature.yaml and reinstall."
                )
            marketplace_url = _build_simulator_url(
                product_code=product_code,
                offer_id=_FEATURE_OFFER_ID_MAP.get(feature_id),
                feature_id=feature_id,
                buyer_account_id=_DEFAULT_BUYER_ACCOUNT_ID,
                return_url=return_url,
            )
    else:
        marketplace_url = _build_simulator_url(
            product_code=product_code,
            offer_id=_FEATURE_OFFER_ID_MAP.get(feature_id),
            feature_id=feature_id,
            buyer_account_id=_DEFAULT_BUYER_ACCOUNT_ID,
            return_url=return_url,
        )

    logger.info(
        "Returning marketplaceUrl for feature=%s product=%s: %s",
        feature_id,
        product_code,
        marketplace_url,
    )

    # Entitlement state remains NONE until the admin accepts the terms and the
    # simulator (or real Marketplace) records the subscription. The UI polls /
    # refreshes checkFeatureEntitlement after the new-tab flow completes.
    return {
        "featureId": feature_id,
        "state": "NONE",
        "expiresAt": None,
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "source": _SOURCE_TAG,
        "marketplaceUrl": marketplace_url,
    }
