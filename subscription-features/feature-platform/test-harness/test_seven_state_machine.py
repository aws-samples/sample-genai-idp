"""Drives every branch of FeaturePage's 7-state machine through the real
Phase A Lambdas (register_feature / list_installed_features / check_feature_entitlement
/ get_feature_launch_url), against moto-mocked AWS.

For each of the 7 states we assert the *server-side* inputs the UI reduces
over. The UI-side reduction is tested separately in
src/ui/src/components/feature-page/FeaturePage.test.tsx.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from botocore.stub import Stubber
from conftest import _put_latest, _put_manifest, appsync_event

# Canonical valid register input used across tests.
_REG_INPUT = {
    "featureId": "docs-by-status",
    "displayName": "DemoFeature -Docs By Status",
    "installedVersion": "1.0.0",
    "stackName": "idp-main-feature-docs-by-status",
    "stackId": "arn:aws:cloudformation:us-east-1:111:stack/xxx/aaa",
    "stackRegion": "us-east-1",
    "uiBundlePath": "features/docs-by-status/v1.0.0/",
    "featureApiEndpoint": "https://example.execute-api.us-east-1.amazonaws.com",
}


def _stub_entitlement_none(mod):
    client = mod._client()
    s = Stubber(client)
    s.add_response(
        "get_entitlements",
        {"Entitlements": []},
        {
            "ProductCode": "prod-docs-by-status",
            "Filter": {"CUSTOMER_IDENTIFIER": ["CUST-dev"]},
        },
    )
    s.activate()
    return s


def _stub_entitlement_active(mod, expires_in_days: int = 30):
    client = mod._client()
    s = Stubber(client)
    exp = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    s.add_response(
        "get_entitlements",
        {
            "Entitlements": [
                {
                    "ProductCode": "prod-docs-by-status",
                    "Dimension": "USERS",
                    "CustomerIdentifier": "CUST-dev",
                    "ExpirationDate": exp,
                }
            ]
        },
        {
            "ProductCode": "prod-docs-by-status",
            "Filter": {"CUSTOMER_IDENTIFIER": ["CUST-dev"]},
        },
    )
    s.activate()
    return s


def _stub_entitlement_expired(mod):
    client = mod._client()
    s = Stubber(client)
    s.add_response(
        "get_entitlements",
        {
            "Entitlements": [
                {
                    "ProductCode": "prod-docs-by-status",
                    "Dimension": "USERS",
                    "CustomerIdentifier": "CUST-dev",
                    "ExpirationDate": datetime.now(timezone.utc) - timedelta(days=30),
                }
            ]
        },
        {
            "ProductCode": "prod-docs-by-status",
            "Filter": {"CUSTOMER_IDENTIFIER": ["CUST-dev"]},
        },
    )
    s.activate()
    return s


# ---------------------------------------------------------------------------
# State 1 — no entitlement, any role, any install state
# ---------------------------------------------------------------------------
def test_state_none_returns_subscription_required(loaders, mock_stack):
    stub = _stub_entitlement_none(loaders["entitle"])
    try:
        ent = loaders["entitle"].handler(
            appsync_event(
                "checkFeatureEntitlement", arguments={"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stub.deactivate()
    assert ent["state"] == "NONE"
    # The UI would render <SubscriptionRequired>.


# ---------------------------------------------------------------------------
# State 2 — ACTIVE + not installed + admin → InstallPrompt
# ---------------------------------------------------------------------------
def test_state_active_admin_not_installed(loaders, mock_stack):
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.0.0")
    _put_manifest(mock_stack["bucket"], "docs-by-status", "1.0.0", {"LogLevel": "INFO"})

    stub = _stub_entitlement_active(loaders["entitle"])
    try:
        ent = loaders["entitle"].handler(
            appsync_event(
                "checkFeatureEntitlement", arguments={"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stub.deactivate()
    assert ent["state"] == "ACTIVE"

    # Installed list is empty → UI renders <InstallPrompt>; admin fetches launch URL.
    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert features == []

    launch = loaders["launch"].handler(
        appsync_event(
            "getFeatureLaunchUrl",
            arguments={"featureId": "docs-by-status"},
            groups=["Admin"],
        ),
        None,
    )
    assert "stacks/quickcreate" in launch["launchUrl"]
    assert launch["stackName"] == "idp-main-feature-docs-by-status"


# ---------------------------------------------------------------------------
# State 3 — ACTIVE + not installed + non-admin → AwaitingAdminInstall
# ---------------------------------------------------------------------------
def test_state_active_nonadmin_not_installed(loaders, mock_stack):
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.0.0")
    stub = _stub_entitlement_active(loaders["entitle"])
    try:
        ent = loaders["entitle"].handler(
            appsync_event(
                "checkFeatureEntitlement", arguments={"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stub.deactivate()
    assert ent["state"] == "ACTIVE"

    # Non-admin is forbidden from fetching launch URL.
    with pytest.raises(loaders["launch"].AuthorizationError):
        loaders["launch"].handler(
            appsync_event(
                "getFeatureLaunchUrl",
                arguments={"featureId": "docs-by-status"},
                groups=["Viewer"],
            ),
            None,
        )


# ---------------------------------------------------------------------------
# State 4 — ACTIVE + installed at latest → UpToDate
# ---------------------------------------------------------------------------
def test_state_active_installed_up_to_date(loaders, mock_stack):
    # Install at v1.0.0 + latest is also v1.0.0
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.0.0")

    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert len(features) == 1
    assert features[0]["installedVersion"] == "1.0.0"
    assert features[0]["latestVersion"] == "1.0.0"
    assert features[0]["updateAvailable"] is False


# ---------------------------------------------------------------------------
# State 5 — ACTIVE + installed with newer latest → UpdateAvailable
# ---------------------------------------------------------------------------
def test_state_active_installed_update_available(loaders, mock_stack):
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.1.0")

    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert features[0]["installedVersion"] == "1.0.0"
    assert features[0]["latestVersion"] == "1.1.0"
    assert features[0]["updateAvailable"] is True


# ---------------------------------------------------------------------------
# State 6 — UpdateAvailable + admin triggers launch → stackName preserved
# ---------------------------------------------------------------------------
def test_update_preserves_stack_name(loaders, mock_stack):
    # Install with a custom stack name
    reg = {**_REG_INPUT, "stackName": "my-preferred-stackname"}
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": reg}), None
    )
    _put_latest(mock_stack["bucket"], "docs-by-status", "2.0.0")
    _put_manifest(mock_stack["bucket"], "docs-by-status", "2.0.0", {"LogLevel": "INFO"})

    launch = loaders["launch"].handler(
        appsync_event(
            "getFeatureLaunchUrl",
            arguments={"featureId": "docs-by-status"},
            groups=["Admin"],
        ),
        None,
    )
    # Upgrade goes to the new version…
    assert launch["version"] == "2.0.0"
    assert "v2.0.0" in launch["templateUrl"]
    # …but the stack name is preserved so CFN Console update the existing stack.
    assert launch["stackName"] == "my-preferred-stackname"


# ---------------------------------------------------------------------------
# State 7 — EXPIRED + installed → ExpiredBanner + read-only wrapper
# ---------------------------------------------------------------------------
def test_state_expired_installed(loaders, mock_stack):
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.0.0")

    stub = _stub_entitlement_expired(loaders["entitle"])
    try:
        ent = loaders["entitle"].handler(
            appsync_event(
                "checkFeatureEntitlement", arguments={"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stub.deactivate()
    assert ent["state"] == "EXPIRED"

    # Feature is still in the installed list, so UI renders it wrapped in
    # <ExpiredBanner> + dimmed overlay.
    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert len(features) == 1
