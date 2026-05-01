# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock Data Automation module for IDP Common Package.

Provides a service for calling Bedrock Data Automation.
"""

from idp_common.bda.bda_invocation import BdaInvocation
from idp_common.bda.bda_service import BdaService

__all__ = ["BdaInvocation", "BdaService"]
