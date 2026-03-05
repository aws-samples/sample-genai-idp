# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Custom exceptions for configuration management."""


class UseCaseRegistrationError(Exception):
    """Raised when use case registration fails after exhausting retries."""
