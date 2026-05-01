# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock Error Message Handler

Provides user-friendly error messages and actionable recommendations for Bedrock service errors.
Converts technical error codes and exceptions into clear, understandable messages for end users.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional

import botocore.exceptions

logger = logging.getLogger(__name__)


@dataclass
class BedrockErrorInfo:
    """
    Structured information about a Bedrock error for user display.

    Attributes:
        error_type: Category of error (service, throttling, validation, etc.)
        user_message: User-friendly error message
        technical_details: Technical error information for debugging
        retry_recommended: Whether the user should retry the operation
        retry_delay_seconds: Recommended delay before retry (if applicable)
        action_recommendations: List of actions the user can take
        is_transient: Whether this is likely a temporary issue
    """

    error_type: str
    user_message: str
    technical_details: str
    retry_recommended: bool
    retry_delay_seconds: Optional[int] = None
    action_recommendations: Optional[list[str]] = None
    is_transient: bool = True


class BedrockErrorMessageHandler:
    """
    Handles conversion of Bedrock errors to user-friendly messages.

    This class provides methods to analyze Bedrock exceptions and generate
    appropriate user-facing error messages with actionable recommendations.
    """

    # Error type mappings for different Bedrock error codes
    ERROR_MAPPINGS: Dict[str, BedrockErrorInfo] = {
        "serviceUnavailableException": BedrockErrorInfo(
            error_type="service_unavailable",
            user_message="The AI service is temporarily unavailable. This is usually a temporary issue that resolves quickly.",
            technical_details="Bedrock service unavailable",
            retry_recommended=True,
            retry_delay_seconds=30,
            action_recommendations=[
                "Wait a moment and try your request again",
                "Check if the issue persists after a few minutes",
                "Contact support if the problem continues",
            ],
            is_transient=True,
        ),
        "ServiceUnavailableException": BedrockErrorInfo(
            error_type="service_unavailable",
            user_message="The AI service is temporarily unavailable. This is usually a temporary issue that resolves quickly.",
            technical_details="Bedrock service unavailable",
            retry_recommended=True,
            retry_delay_seconds=30,
            action_recommendations=[
                "Wait a moment and try your request again",
                "Check if the issue persists after a few minutes",
                "Contact support if the problem continues",
            ],
            is_transient=True,
        ),
        "ThrottlingException": BedrockErrorInfo(
            error_type="rate_limit",
            user_message="Too many requests are being processed right now. Please wait a moment before trying again.",
            technical_details="API rate limit exceeded",
            retry_recommended=True,
            retry_delay_seconds=60,
            action_recommendations=[
                "Wait 1-2 minutes before retrying",
                "Reduce the frequency of your requests",
                "Try again during off-peak hours",
            ],
            is_transient=True,
        ),
        "ModelThrottledException": BedrockErrorInfo(
            error_type="model_throttling",
            user_message="The AI model is currently handling too many requests. Please wait a moment before trying again.",
            technical_details="Model throttling limit reached",
            retry_recommended=True,
            retry_delay_seconds=45,
            action_recommendations=[
                "Wait 1-2 minutes before retrying",
                "Try your request again in a few moments",
                "Consider breaking large requests into smaller parts",
            ],
            is_transient=True,
        ),
        "ValidationException": BedrockErrorInfo(
            error_type="validation_error",
            user_message="There was an issue with your request. Please check your input and try again.",
            technical_details="Request validation failed",
            retry_recommended=False,
            action_recommendations=[
                "Check that your message is not too long",
                "Ensure your request doesn't contain inappropriate content",
                "Try rephrasing your question",
            ],
            is_transient=False,
        ),
        "AccessDeniedException": BedrockErrorInfo(
            error_type="access_denied",
            user_message="Access to the AI service is currently restricted. Please contact your administrator.",
            technical_details="Insufficient permissions for Bedrock access",
            retry_recommended=False,
            action_recommendations=[
                "Contact your system administrator",
                "Verify your account has proper permissions",
                "Check if your organization's AI usage policy allows this request",
            ],
            is_transient=False,
        ),
        "ModelNotReadyException": BedrockErrorInfo(
            error_type="model_unavailable",
            user_message="The requested AI model is not currently available. Please try again later.",
            technical_details="Model not ready or unavailable",
            retry_recommended=True,
            retry_delay_seconds=120,
            action_recommendations=[
                "Wait a few minutes and try again",
                "Contact support if the issue persists",
                "Check if there are any service announcements",
            ],
            is_transient=True,
        ),
        "RequestTimeout": BedrockErrorInfo(
            error_type="timeout",
            user_message="Your request took too long to process. Please try again with a shorter or simpler request.",
            technical_details="Request timeout",
            retry_recommended=True,
            retry_delay_seconds=30,
            action_recommendations=[
                "Try breaking your request into smaller parts",
                "Simplify your question or request",
                "Wait a moment and try again",
            ],
            is_transient=True,
        ),
        "RequestTimeoutException": BedrockErrorInfo(
            error_type="timeout",
            user_message="Your request took too long to process. Please try again with a shorter or simpler request.",
            technical_details="Request timeout",
            retry_recommended=True,
            retry_delay_seconds=30,
            action_recommendations=[
                "Try breaking your request into smaller parts",
                "Simplify your question or request",
                "Wait a moment and try again",
            ],
            is_transient=True,
        ),
        "ServiceQuotaExceededException": BedrockErrorInfo(
            error_type="quota_exceeded",
            user_message="Your usage quota has been exceeded. Please wait or contact your administrator to increase limits.",
            technical_details="Service quota exceeded",
            retry_recommended=True,
            retry_delay_seconds=3600,  # 1 hour
            action_recommendations=[
                "Wait for your quota to reset (usually hourly or daily)",
                "Contact your administrator to increase limits",
                "Reduce the frequency of your requests",
            ],
            is_transient=True,
        ),
        "TooManyRequestsException": BedrockErrorInfo(
            error_type="too_many_requests",
            user_message="Too many requests have been made recently. Please wait before trying again.",
            technical_details="Too many requests",
            retry_recommended=True,
            retry_delay_seconds=300,  # 5 minutes
            action_recommendations=[
                "Wait 5-10 minutes before retrying",
                "Reduce the frequency of your requests",
                "Try again during off-peak hours",
            ],
            is_transient=True,
        ),
    }

    @classmethod
    def extract_error_code(cls, exception: Exception) -> Optional[str]:
        """
        Extract error code from various exception types.

        Args:
            exception: The exception to analyze

        Returns:
            The error code if found, None otherwise
        """
        # Handle botocore ClientError (most common)
        if isinstance(exception, botocore.exceptions.ClientError):
            error_code = exception.response.get("Error", {}).get("Code")
            if error_code:
                return error_code

            # For EventStreamError (subclass of ClientError), extract from message
            # Format: "An error occurred (errorCode) when calling..."
            match = re.search(r"\((\w+)\)", str(exception))
            if match:
                return match.group(1)

        # Handle other exception types by name
        exception_name = type(exception).__name__
        if exception_name in cls.ERROR_MAPPINGS:
            return exception_name

        # Check if exception message contains known error patterns
        exception_str = str(exception).lower()
        for error_code in cls.ERROR_MAPPINGS:
            if error_code.lower() in exception_str:
                return error_code

        return None

    @classmethod
    def get_error_info(
        cls, exception: Exception, retry_attempts: int = 0
    ) -> BedrockErrorInfo:
        """
        Get structured error information for a Bedrock exception.

        Args:
            exception: The exception to analyze
            retry_attempts: Number of retry attempts made

        Returns:
            BedrockErrorInfo with user-friendly message and recommendations
        """
        error_code = cls.extract_error_code(exception)

        # Get base error info from mappings
        if error_code and error_code in cls.ERROR_MAPPINGS:
            error_info = cls.ERROR_MAPPINGS[error_code]
        else:
            # Default error info for unknown errors
            error_info = BedrockErrorInfo(
                error_type="unknown_error",
                user_message="An unexpected error occurred while processing your request. Please try again.",
                technical_details=f"Unknown error: {str(exception)}",
                retry_recommended=True,
                retry_delay_seconds=30,
                action_recommendations=[
                    "Wait a moment and try again",
                    "Check your internet connection",
                    "Contact support if the problem persists",
                ],
                is_transient=True,
            )

        # Enhance error info with retry context
        enhanced_error_info = BedrockErrorInfo(
            error_type=error_info.error_type,
            user_message=cls._enhance_message_with_retry_context(
                error_info.user_message, retry_attempts
            ),
            technical_details=(
                f"{error_info.technical_details} (after {retry_attempts} retries)"
                if retry_attempts > 0
                else error_info.technical_details
            ),
            retry_recommended=error_info.retry_recommended
            and retry_attempts < 3,  # Don't recommend retry after 3 attempts
            retry_delay_seconds=error_info.retry_delay_seconds,
            action_recommendations=error_info.action_recommendations,
            is_transient=error_info.is_transient,
        )

        return enhanced_error_info

    @classmethod
    def _enhance_message_with_retry_context(
        cls, base_message: str, retry_attempts: int
    ) -> str:
        """
        Enhance error message with retry context.

        Args:
            base_message: The base error message
            retry_attempts: Number of retry attempts made

        Returns:
            Enhanced message with retry context
        """
        if retry_attempts == 0:
            return base_message
        elif retry_attempts == 1:
            return f"{base_message} We tried once more but the issue persists."
        elif retry_attempts <= 3:
            return f"{base_message} We tried {retry_attempts} times but the issue persists."
        else:
            return f"{base_message} After multiple attempts, the service appears to be experiencing ongoing issues."

    @classmethod
    def format_error_for_frontend(
        cls, exception: Exception, retry_attempts: int = 0
    ) -> Dict[str, any]:
        """
        Format error information for frontend consumption.

        Args:
            exception: The exception to format
            retry_attempts: Number of retry attempts made

        Returns:
            Dictionary with error information formatted for frontend display
        """
        error_info = cls.get_error_info(exception, retry_attempts)

        return {
            "errorType": error_info.error_type,
            "message": error_info.user_message,
            "technicalDetails": error_info.technical_details,
            "retryRecommended": error_info.retry_recommended,
            "retryDelaySeconds": error_info.retry_delay_seconds,
            "actionRecommendations": error_info.action_recommendations or [],
            "isTransient": error_info.is_transient,
            "retryAttempts": retry_attempts,
        }

    @classmethod
    def is_retryable_error(cls, exception: Exception) -> bool:
        """
        Check if an error is retryable based on its type.

        Args:
            exception: The exception to check

        Returns:
            True if the error is retryable, False otherwise
        """
        error_info = cls.get_error_info(exception)
        return error_info.retry_recommended and error_info.is_transient
