# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext.cli`` — CLI plugin package for IDPMonitor.

The ``register(cli)`` function in ``monitoring.py`` is called automatically by
the open-source ``idp_cli`` plugin discovery hook at startup when this package
is installed.  It adds the ``monitoring`` command group to the IDP CLI.

This sub-package is NOT imported directly by consumers — it is discovered via
the ``idp_cli.plugins`` entry point registered in ``setup.py``.
"""
