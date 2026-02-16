# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for SDK exceptions.
"""

import pytest
from idp_sdk.exceptions import (
    IDPConfigurationError,
    IDPError,
    IDPProcessingError,
    IDPResourceNotFoundError,
    IDPStackError,
    IDPTimeoutError,
    IDPValidationError,
)


@pytest.mark.unit
class TestExceptionHierarchy:
    """Test exception inheritance."""

    def test_all_inherit_from_idp_error(self):
        """All exceptions inherit from IDPError."""
        assert issubclass(IDPConfigurationError, IDPError)
        assert issubclass(IDPStackError, IDPError)
        assert issubclass(IDPProcessingError, IDPError)
        assert issubclass(IDPValidationError, IDPError)
        assert issubclass(IDPResourceNotFoundError, IDPError)
        assert issubclass(IDPTimeoutError, IDPError)

    def test_idp_error_inherits_from_exception(self):
        """IDPError inherits from Exception."""
        assert issubclass(IDPError, Exception)


@pytest.mark.unit
class TestExceptionMessages:
    """Test exception message handling."""

    def test_exception_preserves_message(self):
        """Exceptions preserve message."""
        exc = IDPConfigurationError("test message")
        assert str(exc) == "test message"

    def test_exception_with_empty_message(self):
        """Exceptions work with empty message."""
        exc = IDPError("")
        assert str(exc) == ""

    def test_exception_can_be_raised(self):
        """Exceptions can be raised and caught."""
        with pytest.raises(IDPConfigurationError) as exc_info:
            raise IDPConfigurationError("test error")
        assert "test error" in str(exc_info.value)


@pytest.mark.unit
class TestSpecificExceptions:
    """Test specific exception types."""

    def test_configuration_error(self):
        """IDPConfigurationError works correctly."""
        with pytest.raises(IDPConfigurationError):
            raise IDPConfigurationError("Invalid configuration")

    def test_stack_error(self):
        """IDPStackError works correctly."""
        with pytest.raises(IDPStackError):
            raise IDPStackError("Stack not found")

    def test_processing_error(self):
        """IDPProcessingError works correctly."""
        with pytest.raises(IDPProcessingError):
            raise IDPProcessingError("Processing failed")

    def test_resource_not_found_error(self):
        """IDPResourceNotFoundError works correctly."""
        with pytest.raises(IDPResourceNotFoundError):
            raise IDPResourceNotFoundError("Resource not found")
