# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Error Analyzer Agent package for troubleshooting CloudWatch logs and DynamoDB data.
"""

from .agent import create_error_analyzer_agent

__all__ = ["create_error_analyzer_agent"]
