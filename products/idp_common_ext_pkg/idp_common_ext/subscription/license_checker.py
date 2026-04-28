# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
LicenseChecker — IDPMonitor subscription/entitlement validation.

The checker is designed to be instantiated once per Lambda execution context
(outside the handler) and reused across invocations. It caches the last
successful check result for ``CACHE_TTL_SECONDS`` to avoid calling the
entitlement API on every single request.

Usage in Lambda resolver::

    # At module level (outside handler) — cached for Lambda lifetime
    _checker = LicenseChecker()

    def handler(event, context):
        status = _checker.check_entitlement()
        if not status.is_premium:
            # Return free-tier response
            ...

Fail-open policy:
    If the entitlement API is unreachable (network error, IAM missing, timeout),
    ``check_entitlement()`` logs a warning and returns ``SubscriptionTier.FREE``
    rather than blocking the customer entirely. A transient validation failure
    should degrade gracefully — not cause a production outage.

Environment variables:
    ``LICENSE_MECHANISM``       One of: ``marketplace`` | ``ssm_key`` | ``stub`` (default: ``stub``)
    ``MARKETPLACE_PRODUCT_CODE`` AWS Marketplace product code (required for ``marketplace`` mechanism)
    ``LICENSE_KEY_SSM_PATH``    SSM Parameter Store path for activation key (required for ``ssm_key``)
    ``AWS_REGION``              AWS region (falls back to ``us-east-1``)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from idp_common_ext.subscription.models import SubscriptionStatus, SubscriptionTier

logger = logging.getLogger(__name__)

# Default cache TTL: 5 minutes. Keeps Lambda per-request latency low while
# still picking up subscription changes within a reasonable window.
CACHE_TTL_SECONDS = int(os.environ.get("LICENSE_CACHE_TTL_SECONDS", "300"))


class LicenseChecker:
    """
    Validates IDPMonitor subscription entitlement with in-memory TTL caching.

    Thread-safe for read operations (cache is only written on cache miss).
    """

    def __init__(
        self,
        mechanism: Optional[str] = None,
        product_code: Optional[str] = None,
        ssm_key_path: Optional[str] = None,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ) -> None:
        """
        Args:
            mechanism:      License mechanism override. Falls back to ``LICENSE_MECHANISM``
                            env var, then defaults to ``"stub"``.
            product_code:   AWS Marketplace product code override. Falls back to
                            ``MARKETPLACE_PRODUCT_CODE`` env var.
            ssm_key_path:   SSM Parameter Store path override. Falls back to
                            ``LICENSE_KEY_SSM_PATH`` env var.
            cache_ttl:      Cache TTL in seconds (default: 300).
        """
        self._mechanism = (
            mechanism or os.environ.get("LICENSE_MECHANISM", "stub").lower()
        )
        self._product_code = product_code or os.environ.get(
            "MARKETPLACE_PRODUCT_CODE", ""
        )
        self._ssm_key_path = ssm_key_path or os.environ.get("LICENSE_KEY_SSM_PATH", "")
        self._cache_ttl = cache_ttl
        self._cached_status: Optional[SubscriptionStatus] = None
        self._cache_timestamp: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_entitlement(self) -> SubscriptionStatus:
        """
        Return the current subscription status, using the cache when fresh.

        Never raises — returns ``SubscriptionTier.FREE`` on any error (fail-open).
        """
        now = time.monotonic()
        if (
            self._cached_status is not None
            and (now - self._cache_timestamp) < self._cache_ttl
        ):
            logger.debug(
                "LicenseChecker: cache hit (age=%.1fs)", now - self._cache_timestamp
            )
            return self._cached_status

        status = self._fetch_entitlement()
        self._cached_status = status
        self._cache_timestamp = now
        logger.info(
            "LicenseChecker: resolved tier=%s mechanism=%s is_active=%s",
            status.tier.value,
            status.mechanism,
            status.is_active,
        )
        return status

    def invalidate_cache(self) -> None:
        """Force the next call to re-check the entitlement API."""
        self._cached_status = None
        self._cache_timestamp = 0.0

    # ------------------------------------------------------------------
    # Private: per-mechanism implementations
    # ------------------------------------------------------------------

    def _fetch_entitlement(self) -> SubscriptionStatus:
        """Dispatch to the configured mechanism. Never raises."""
        try:
            if self._mechanism == "marketplace":
                return self._check_marketplace()
            elif self._mechanism == "ssm_key":
                return self._check_ssm_key()
            else:
                # "stub" or any unknown value → always premium (dev/test)
                return self._check_stub()
        except Exception as exc:
            logger.warning(
                "LicenseChecker: entitlement check failed (%s: %s) — failing open to FREE tier",
                type(exc).__name__,
                exc,
            )
            return SubscriptionStatus(
                tier=SubscriptionTier.FREE,
                is_active=False,
                mechanism=self._mechanism,
                error=str(exc),
            )

    def _check_marketplace(self) -> SubscriptionStatus:
        """
        Check AWS Marketplace entitlement via GetEntitlements API.

        Requires IAM permission: ``aws-marketplace:GetEntitlements``
        """
        if not self._product_code:
            raise ValueError(
                "MARKETPLACE_PRODUCT_CODE env var not set — required for marketplace mechanism"
            )

        region = os.environ.get("AWS_REGION", "us-east-1")
        client = boto3.client("marketplace-entitlement", region_name=region)

        response = client.get_entitlements(
            ProductCode=self._product_code,
            Filter={"CUSTOMER_IDENTIFIER": [self._get_account_id()]},
        )

        entitlements = response.get("Entitlements", [])
        is_active = bool(entitlements)

        return SubscriptionStatus(
            tier=SubscriptionTier.PREMIUM if is_active else SubscriptionTier.FREE,
            is_active=is_active,
            product_code=self._product_code,
            mechanism="marketplace",
        )

    def _check_ssm_key(self) -> SubscriptionStatus:
        """
        Validate an activation key stored in SSM Parameter Store.

        The SSM parameter is expected to be a SecureString containing
        a JSON object with at minimum ``{"active": true, "tier": "premium"}``.
        """
        if not self._ssm_key_path:
            raise ValueError(
                "LICENSE_KEY_SSM_PATH env var not set — required for ssm_key mechanism"
            )

        import json

        region = os.environ.get("AWS_REGION", "us-east-1")
        ssm = boto3.client("ssm", region_name=region)

        try:
            param = ssm.get_parameter(Name=self._ssm_key_path, WithDecryption=True)
            value = json.loads(param["Parameter"]["Value"])
            is_active = bool(value.get("active", False))
            tier_str = value.get("tier", "free").lower()
            tier = (
                SubscriptionTier.PREMIUM
                if tier_str == "premium"
                else SubscriptionTier.FREE
            )
        except (ClientError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("LicenseChecker: SSM key validation failed: %s", exc)
            is_active = False
            tier = SubscriptionTier.FREE

        return SubscriptionStatus(
            tier=tier,
            is_active=is_active,
            mechanism="ssm_key",
        )

    @staticmethod
    def _check_stub() -> SubscriptionStatus:
        """
        Stub mechanism — always returns PREMIUM. Used in development and testing.
        """
        logger.debug("LicenseChecker: using stub mechanism — returning PREMIUM")
        return SubscriptionStatus(
            tier=SubscriptionTier.PREMIUM,
            is_active=True,
            mechanism="stub",
        )

    @staticmethod
    def _get_account_id() -> str:
        """Return the current AWS account ID via STS."""
        try:
            return boto3.client("sts").get_caller_identity()["Account"]
        except Exception:
            return ""
