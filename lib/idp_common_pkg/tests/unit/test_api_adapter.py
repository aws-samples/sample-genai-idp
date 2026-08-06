# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.api_adapter.

These tests are the RBAC-correctness gate for the AppSync -> API Gateway HTTP
API migration. The single most important behavior is that the HTTP API JWT
authorizer's flattened ``cognito:groups`` string (e.g. "[Admin Author]") is
restored to a list so resolver RBAC keeps working identically to AppSync.
"""

import json

import pytest

from idp_common.api_adapter import (
    _coerce_groups,
    api_resolver,
    normalize_event,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# _coerce_groups — the critical claim-shape normalization
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ([], []),
        (["Admin"], ["Admin"]),
        (["Admin", "Author"], ["Admin", "Author"]),
        ("Admin", ["Admin"]),
        # HTTP API JWT authorizer flattened forms:
        ("[Admin Author]", ["Admin", "Author"]),
        ("[Admin]", ["Admin"]),
        ("[]", []),
        ("[Admin Author Viewer]", ["Admin", "Author", "Viewer"]),
        # JSON-encoded list form:
        ('["Admin","Author"]', ["Admin", "Author"]),
        ('["Admin"]', ["Admin"]),
        # REST API Cognito authorizer comma-joined form:
        ("Admin,Author", ["Admin", "Author"]),
        ("Admin, Author, Viewer", ["Admin", "Author", "Viewer"]),
        ("Admin\nAuthor", ["Admin", "Author"]),
        # whitespace / empty string
        ("", []),
        ("   ", []),
    ],
)
def test_coerce_groups(raw, expected):
    assert _coerce_groups(raw) == expected


# --------------------------------------------------------------------------- #
# normalize_event — AppSync passthrough
# --------------------------------------------------------------------------- #
def test_appsync_event_passthrough():
    appsync_event = {
        "arguments": {"limit": 50},
        "identity": {
            "claims": {"cognito:groups": ["Admin"], "email": "a@b.com"},
            "username": "a@b.com",
        },
        "info": {"fieldName": "listDocuments"},
    }
    out = normalize_event(appsync_event)
    # Returned unchanged (same object) so AppSync behavior is untouched.
    assert out is appsync_event
    assert out["identity"]["claims"]["cognito:groups"] == ["Admin"]


# --------------------------------------------------------------------------- #
# normalize_event — HTTP API conversion
# --------------------------------------------------------------------------- #
def _http_event(field, groups_claim, arguments=None, email="user@example.com"):
    return {
        "version": "2.0",
        "routeKey": f"POST /op/{field}",
        "rawPath": f"/op/{field}",
        "pathParameters": {"field": field},
        "isBase64Encoded": False,
        "body": json.dumps({"arguments": arguments or {}}),
        "requestContext": {
            "http": {"method": "POST", "path": f"/op/{field}", "sourceIp": "1.2.3.4"},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "cognito:groups": groups_claim,
                        "cognito:username": "user-sub-123",
                        "email": email,
                        "sub": "user-sub-123",
                    }
                }
            },
        },
    }


def test_http_event_restores_groups_list():
    """The flattened authorizer groups string must become a list for RBAC."""
    event = _http_event("listDocuments", "[Admin Author]", {"limit": 10})
    out = normalize_event(event)
    groups = out["identity"]["claims"]["cognito:groups"]
    assert groups == ["Admin", "Author"]
    assert isinstance(groups, list)


def test_http_event_field_and_arguments():
    event = _http_event("reprocessDocument", "[Author]", {"objectKeys": ["k1"]})
    out = normalize_event(event)
    assert out["info"]["fieldName"] == "reprocessDocument"
    assert out["arguments"] == {"objectKeys": ["k1"]}


def _rest_event(field, groups_claim, arguments=None, email="user@example.com"):
    """API Gateway REST API (v1) proxy event with a Cognito User Pools authorizer.

    Claims live at requestContext.authorizer.claims (flat, not .jwt.claims) and
    cognito:groups is a comma-joined string.
    """
    return {
        "resource": "/op/{field}",
        "path": f"/op/{field}",
        "httpMethod": "POST",
        "pathParameters": {"field": field},
        "isBase64Encoded": False,
        "body": json.dumps({"arguments": arguments or {}}),
        "requestContext": {
            "resourcePath": "/op/{field}",
            "httpMethod": "POST",
            "identity": {"sourceIp": "1.2.3.4"},
            "authorizer": {
                "claims": {
                    "cognito:groups": groups_claim,
                    "cognito:username": "user-sub-123",
                    "email": email,
                    "sub": "user-sub-123",
                }
            },
        },
    }


def test_rest_event_claims_and_groups():
    """REST API authorizer claims (flat) + comma-joined groups normalize correctly."""
    event = _rest_event("listDocuments", "Admin,Author", {"limit": 5})
    out = normalize_event(event)
    assert out["info"]["fieldName"] == "listDocuments"
    assert out["arguments"] == {"limit": 5}
    assert out["identity"]["claims"]["cognito:groups"] == ["Admin", "Author"]
    assert out["identity"]["username"] == "user@example.com"


def test_rest_event_single_group():
    event = _rest_event("getPricing", "Viewer")
    out = normalize_event(event)
    assert out["identity"]["claims"]["cognito:groups"] == ["Viewer"]


def test_rest_event_rbac_parity():
    """An Admin-only handler behaves the same on REST API events."""

    @api_resolver
    def handler(event, context):
        if "Admin" not in event["identity"]["claims"]["cognito:groups"]:
            raise PermissionError("Admin only")
        return {"ok": True}

    assert handler(_rest_event("x", "Admin,Author"), None)["statusCode"] == 200
    assert handler(_rest_event("x", "Viewer"), None)["statusCode"] == 403


def test_http_event_identity_username_is_email():
    event = _http_event("getMyProfile", "[Viewer]", email="reviewer@corp.com")
    out = normalize_event(event)
    # Resolvers read identity.username as the email (AppSync convention).
    assert out["identity"]["username"] == "reviewer@corp.com"
    assert out["identity"]["claims"]["email"] == "reviewer@corp.com"


def test_http_event_empty_groups():
    event = _http_event("listDocuments", "[]")
    out = normalize_event(event)
    assert out["identity"]["claims"]["cognito:groups"] == []


def test_http_event_field_from_raw_path_when_no_path_params():
    event = _http_event("getPricing", "[Admin]")
    del event["pathParameters"]
    out = normalize_event(event)
    assert out["info"]["fieldName"] == "getPricing"


def test_http_event_base64_body():
    import base64 as b64

    raw = json.dumps({"arguments": {"x": 1}})
    event = _http_event("getPricing", "[Admin]")
    event["body"] = b64.b64encode(raw.encode()).decode()
    event["isBase64Encoded"] = True
    out = normalize_event(event)
    assert out["arguments"] == {"x": 1}


def test_http_event_bare_body_without_arguments_key():
    """Tolerate a body that is the arguments dict directly."""
    event = _http_event("x", "[Admin]")
    event["body"] = json.dumps({"objectKey": "abc"})
    out = normalize_event(event)
    assert out["arguments"] == {"objectKey": "abc"}


# --------------------------------------------------------------------------- #
# api_resolver decorator
# --------------------------------------------------------------------------- #
def test_decorator_appsync_returns_raw():
    @api_resolver
    def handler(event, context):
        return {"ok": True, "groups": event["identity"]["claims"]["cognito:groups"]}

    appsync_event = {
        "arguments": {},
        "identity": {"claims": {"cognito:groups": ["Admin"]}, "username": "a"},
        "info": {"fieldName": "x"},
    }
    result = handler(appsync_event, None)
    # AppSync path: raw return, no statusCode wrapping.
    assert result == {"ok": True, "groups": ["Admin"]}


def test_decorator_http_wraps_success():
    @api_resolver
    def handler(event, context):
        return {"value": event["arguments"].get("n", 0) * 2}

    event = _http_event("calc", "[Admin]", {"n": 21})
    result = handler(event, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"value": 42}
    assert result["headers"]["Content-Type"] == "application/json"


def test_http_response_sets_security_headers():
    # ZAP flagged the execute-api endpoint for missing security headers; the
    # dispatcher's own responses must now carry them (defense-in-depth for
    # direct-API access; CloudFront already sets them for the SPA origin).
    from idp_common.api_adapter import _http_response

    h = _http_response(200, {"ok": True})["headers"]
    assert h["X-Content-Type-Options"] == "nosniff"
    assert "max-age=31536000" in h["Strict-Transport-Security"]
    assert "includeSubDomains" in h["Strict-Transport-Security"]
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_http_response_cors_origin_defaults_star_and_is_overridable(monkeypatch):
    from idp_common.api_adapter import _http_response

    monkeypatch.delenv("CORS_ALLOW_ORIGIN", raising=False)
    assert _http_response(200, {})["headers"]["Access-Control-Allow-Origin"] == "*"
    # A deployment can lock the origin down without touching code (avoids the
    # CloudFront->API CFN dependency cycle that forces the wildcard default).
    monkeypatch.setenv("CORS_ALLOW_ORIGIN", "https://d123.cloudfront.net")
    assert (
        _http_response(200, {})["headers"]["Access-Control-Allow-Origin"]
        == "https://d123.cloudfront.net"
    )


def test_decorator_http_permission_error_403():
    @api_resolver
    def handler(event, context):
        raise PermissionError("not allowed")

    result = handler(_http_event("x", "[Viewer]"), None)
    assert result["statusCode"] == 403
    body = json.loads(result["body"])
    assert body["errors"][0]["errorType"] == "Unauthorized"


def test_decorator_http_value_error_400():
    @api_resolver
    def handler(event, context):
        raise ValueError("bad input")

    result = handler(_http_event("x", "[Admin]"), None)
    assert result["statusCode"] == 400
    assert json.loads(result["body"])["errors"][0]["errorType"] == "BadRequest"


def test_decorator_http_unexpected_error_500():
    @api_resolver
    def handler(event, context):
        raise RuntimeError("boom")

    result = handler(_http_event("x", "[Admin]"), None)
    assert result["statusCode"] == 500
    assert json.loads(result["body"])["errors"][0]["errorType"] == "InternalError"


def test_decorator_http_decimal_serialization():
    from decimal import Decimal

    @api_resolver
    def handler(event, context):
        return {"cost": Decimal("1.23"), "count": Decimal("5")}

    result = handler(_http_event("x", "[Admin]"), None)
    body = json.loads(result["body"])
    assert body == {"cost": 1.23, "count": 5}


def test_decorator_rbac_parity_appsync_vs_http():
    """A handler enforcing Admin-only must behave identically on both transports."""

    @api_resolver
    def handler(event, context):
        groups = event["identity"]["claims"]["cognito:groups"]
        if "Admin" not in groups:
            raise PermissionError("Admin only")
        return {"ok": True}

    # AppSync admin
    appsync = {
        "arguments": {},
        "identity": {"claims": {"cognito:groups": ["Admin"]}, "username": "a"},
        "info": {"fieldName": "x"},
    }
    assert handler(appsync, None) == {"ok": True}

    # HTTP admin (flattened groups) -> allowed
    http_admin = handler(_http_event("x", "[Admin Author]"), None)
    assert http_admin["statusCode"] == 200

    # HTTP non-admin -> 403
    http_viewer = handler(_http_event("x", "[Viewer]"), None)
    assert http_viewer["statusCode"] == 403
