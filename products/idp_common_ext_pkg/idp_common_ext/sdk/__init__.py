# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext.sdk`` — SDK plugin package for IDPMonitor.

The ``register(client, stack_name)`` function in ``monitoring.py`` is called
automatically by the open-source ``idp_sdk`` plugin discovery hook at client
initialization when this package is installed.  It sets
``client.monitoring = MonitoringOperations(stack_name)``.

This sub-package is NOT imported directly by consumers — it is discovered via
the ``idp_sdk.plugins`` entry point registered in ``setup.py``.
"""
