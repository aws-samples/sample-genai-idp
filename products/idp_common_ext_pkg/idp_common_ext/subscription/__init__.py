# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext.subscription`` — IDPMonitor license / subscription validation.

Public API::

    from idp_common_ext.subscription import LicenseChecker, SubscriptionTier, SubscriptionStatus

The :class:`LicenseChecker` is the sole entry point for validating whether a
customer has an active IDPMonitor subscription.  It is used ONLY in the Lambda
resolver (``products/idp-monitor/lambda/monitoring_dashboard_resolver/index.py``).
The monitoring foundation services in ``idp_common_ext.monitoring`` are
subscription-unaware — gating is the caller's responsibility.

Supported license mechanisms (determined by ``LICENSE_MECHANISM`` env var):
    ``marketplace``    AWS Marketplace GetEntitlements API
    ``ssm_key``        Activation key stored in SSM Parameter Store
    ``stub``           Always returns ``SubscriptionTier.PREMIUM`` (development/testing)
"""

from idp_common_ext.subscription.license_checker import LicenseChecker
from idp_common_ext.subscription.models import SubscriptionStatus, SubscriptionTier

__all__ = [
    "LicenseChecker",
    "SubscriptionTier",
    "SubscriptionStatus",
]
