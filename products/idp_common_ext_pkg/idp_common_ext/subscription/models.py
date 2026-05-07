# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Subscription data models for IDPMonitor license validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SubscriptionTier(str, Enum):
    """IDPMonitor subscription tiers."""

    FREE = "free"
    PREMIUM = "premium"


@dataclass
class SubscriptionStatus:
    """
    Result of a subscription entitlement check.

    Attributes:
        tier:           The resolved subscription tier.
        is_active:      ``True`` when the subscription is valid and not expired.
        product_code:   AWS Marketplace product code (empty for non-Marketplace mechanisms).
        customer_id:    AWS account or customer identifier.
        valid_until:    Expiry datetime (``None`` when no expiry / perpetual).
        mechanism:      How the status was determined: ``marketplace``, ``ssm_key``, ``stub``.
        error:          Non-empty string when status was determined via fail-open fallback.
    """

    tier: SubscriptionTier = SubscriptionTier.FREE
    is_active: bool = False
    product_code: str = ""
    customer_id: str = ""
    valid_until: Optional[datetime] = None
    mechanism: str = "stub"
    error: str = ""

    @property
    def is_premium(self) -> bool:
        """Return True when the customer has an active premium subscription."""
        return self.is_active and self.tier == SubscriptionTier.PREMIUM

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict for inclusion in API responses."""
        return {
            "tier": self.tier.value,
            "isActive": self.is_active,
            "mechanism": self.mechanism,
            "validUntil": self.valid_until.isoformat() if self.valid_until else None,
            "error": self.error or None,
        }
