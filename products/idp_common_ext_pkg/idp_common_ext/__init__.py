# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext`` — IDPMonitor premium shared extension library.

This package extends the open-source ``idp_common`` library with premium
monitoring capabilities, subscription/license checking, and plugin registration
hooks for the IDP SDK, CLI, and MCP connector.

Barrel imports for the most commonly used public API:

    from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange
    from idp_common_ext.subscription import LicenseChecker, SubscriptionTier

CLI/SDK/MCP plugins are NOT imported here — they are discovered at runtime via
Python ``entry_points`` registered in ``setup.py``. No monitoring code lives in
the open-source ``lib/`` packages.
"""

__version__ = "0.1.0"

from idp_common_ext import cli, mcp, monitoring, sdk, subscription  # noqa: E402, F401

__all__ = ["monitoring", "subscription", "cli", "sdk", "mcp"]
