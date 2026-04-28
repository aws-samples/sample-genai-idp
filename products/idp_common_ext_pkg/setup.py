# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
setup.py for idp_common_ext — the shared premium extension library for IDP Accelerator.

This package:
- Contains all monitoring services (moved from idp_common/monitoring/)
- Contains the subscription/license-checking module
- Registers CLI, SDK, and MCP plugin entry points so premium commands
  appear automatically when this package is installed alongside the
  open-source idp_common, idp_cli, idp_sdk, and idp_mcp_connector packages.

Install (editable, for development):
    pip install -e products/idp_common_ext_pkg/

Entry points registered:
    idp_cli.plugins  → idp_common_ext.cli.monitoring:register
    idp_sdk.plugins  → idp_common_ext.sdk.monitoring:register
    idp_mcp.plugins  → idp_common_ext.mcp.monitoring:register
"""

from setuptools import find_packages, setup

setup(
    name="idp_common_ext",
    version="0.1.0",
    description="IDPMonitor — premium monitoring and subscription extension for IDP Accelerator",
    author="IDP Accelerator Team",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.12",
    install_requires=[
        "idp_common",  # open-source base library
        "boto3>=1.34",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov",
            "moto[s3,dynamodb,cloudwatch,xray]>=4.0",
        ],
    },
    entry_points={
        # CLI plugin — adds `idp monitoring` command group when installed
        "idp_cli.plugins": [
            "monitoring = idp_common_ext.cli.monitoring:register",
        ],
        # SDK plugin — sets client.monitoring = MonitoringOperations(...) when installed
        "idp_sdk.plugins": [
            "monitoring = idp_common_ext.sdk.monitoring:register",
        ],
        # MCP plugin — adds 7 monitoring tools when installed
        "idp_mcp.plugins": [
            "monitoring = idp_common_ext.mcp.monitoring:register",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.12",
        "License :: Other/Proprietary License",
    ],
)
