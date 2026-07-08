# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock Data Automation module for IDP Common Package.

Provides a service for calling Bedrock Data Automation.
"""

from idp_common.bda.bda_invocation import BdaInvocation
from idp_common.bda.bda_ocr import (
    bda_standard_output_to_textract_blocks,
    build_ocr_project_standard_output_config,
    extract_markdown,
)
from idp_common.bda.bda_service import BdaService

__all__ = [
    "BdaInvocation",
    "BdaService",
    "bda_standard_output_to_textract_blocks",
    "build_ocr_project_standard_output_config",
    "extract_markdown",
]
