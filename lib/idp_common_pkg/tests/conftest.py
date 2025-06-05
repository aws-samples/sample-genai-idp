# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pytest configuration file for the IDP Common package tests.
"""

import sys
from unittest.mock import MagicMock


# Mock PIL module for tests
class MockImage:
    def open(self, *args, **kwargs):
        mock_image = MagicMock()
        mock_image.format = "JPEG"
        return mock_image


# Create a mock PIL module
mock_pil = MagicMock()
mock_pil.Image = MockImage()

# Add the mock to sys.modules
sys.modules["PIL"] = mock_pil
