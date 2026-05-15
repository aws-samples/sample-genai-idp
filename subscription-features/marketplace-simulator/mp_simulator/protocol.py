"""AWS JSON-RPC 1.1 protocol helpers.

Both ``meteringmarketplace`` and ``marketplace-entitlement`` use AWS's
``json`` protocol (not REST, not EC2-query, not XML). A client request looks
like:

    POST /  HTTP/1.1
    Host: metering.marketplace.us-east-1.amazonaws.com
    X-Amz-Target: AWSMPMeteringService.ResolveCustomer
    Content-Type: application/x-amz-json-1.1
    { "RegistrationToken": "..." }

And a success response:

    HTTP/1.1 200 OK
    Content-Type: application/x-amz-json-1.1
    { "CustomerIdentifier": "...", "ProductCode": "...", "CustomerAWSAccountId": "..." }

Errors come back as:

    HTTP/1.1 4xx/5xx
    X-Amzn-Errortype: CustomerNotEntitledException
    Content-Type: application/x-amz-json-1.1
    { "__type": "CustomerNotEntitledException", "message": "..." }

boto3 consumes both the ``X-Amzn-Errortype`` header and the ``__type`` body
field; we emit both to be safe.

Target prefixes:
    - AWSMPMeteringService               -> ResolveCustomer, BatchMeterUsage, MeterUsage, RegisterUsage
    - AWSMPEntitlementService            -> GetEntitlements
    - AWSMPCommerceService_v20200301     -> DescribeAgreement, SearchAgreements, GetAgreementTerms
                                            (marketplace-agreement SDK)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CONTENT_TYPE = "application/x-amz-json-1.1"


class SimulatorError(Exception):
    """Raised by handlers to short-circuit with an AWS-shaped error response."""

    http_status: int = 400
    error_type: str = "InternalServiceErrorException"

    def __init__(
        self, message: str = "", *, http_status: int | None = None, error_type: str | None = None
    ):
        super().__init__(message)
        self.message = message or self.__class__.__name__
        if http_status is not None:
            self.http_status = http_status
        if error_type is not None:
            self.error_type = error_type


# Concrete exception types with canonical HTTP codes & error types.
# The HTTP codes follow the Smithy models where documented.
class InvalidTokenException(SimulatorError):
    http_status = 400
    error_type = "InvalidTokenException"


class ExpiredTokenException(SimulatorError):
    http_status = 400
    error_type = "ExpiredTokenException"


class InvalidProductCodeException(SimulatorError):
    http_status = 400
    error_type = "InvalidProductCodeException"


class InvalidCustomerIdentifierException(SimulatorError):
    http_status = 400
    error_type = "InvalidCustomerIdentifierException"


class InvalidUsageDimensionException(SimulatorError):
    http_status = 400
    error_type = "InvalidUsageDimensionException"


class TimestampOutOfBoundsException(SimulatorError):
    http_status = 400
    error_type = "TimestampOutOfBoundsException"


class CustomerNotEntitledException(SimulatorError):
    http_status = 400
    error_type = "CustomerNotEntitledException"


class DuplicateRequestException(SimulatorError):
    http_status = 400
    error_type = "DuplicateRequestException"


class ThrottlingException(SimulatorError):
    http_status = 400
    error_type = "ThrottlingException"


class DisabledApiException(SimulatorError):
    http_status = 400
    error_type = "DisabledApiException"


class InvalidParameterException(SimulatorError):
    http_status = 400
    error_type = "InvalidParameterException"


class ResourceNotFoundException(SimulatorError):
    http_status = 404
    error_type = "ResourceNotFoundException"


class ValidationException(SimulatorError):
    http_status = 400
    error_type = "ValidationException"


class AccessDeniedException(SimulatorError):
    http_status = 403
    error_type = "AccessDeniedException"


# ─────────────────────────────── serialisation ────────────────────────────────
def _to_jsonable(obj: Any) -> Any:
    """boto3 sends/receives ISO timestamps as strings or epoch floats depending
    on the shape. For AWS JSON-RPC, ``timestamp`` shapes are wire-formatted as
    numeric epoch seconds (float). We normalise ``datetime`` -> epoch seconds.
    """
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.timestamp()
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


def serialize(payload: dict[str, Any]) -> bytes:
    return json.dumps(_to_jsonable(payload)).encode("utf-8")


def parse_request_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidParameterException(f"invalid JSON body: {exc}") from exc


@dataclass
class ParsedTarget:
    service: str  # 'metering' | 'entitlement'
    operation: str


def parse_target(header_value: str) -> ParsedTarget:
    """Split ``AWSMPMeteringService.ResolveCustomer`` into (service, operation)."""
    if not header_value or "." not in header_value:
        raise InvalidParameterException(f"missing/invalid X-Amz-Target header: {header_value!r}")
    prefix, op = header_value.split(".", 1)
    if prefix == "AWSMPMeteringService":
        service = "metering"
    elif prefix == "AWSMPEntitlementService":
        service = "entitlement"
    elif prefix == "AWSMPCommerceService_v20200301":
        service = "agreement"
    else:
        raise InvalidParameterException(f"unknown target prefix: {prefix}")
    return ParsedTarget(service=service, operation=op)


def error_body(exc: SimulatorError) -> bytes:
    return json.dumps({"__type": exc.error_type, "message": exc.message}).encode("utf-8")
