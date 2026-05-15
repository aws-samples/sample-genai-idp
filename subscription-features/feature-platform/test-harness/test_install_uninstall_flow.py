"""End-to-end coverage of a feature's lifecycle: install → list → upgrade → uninstall."""

from __future__ import annotations

from conftest import _put_latest, appsync_event

_REG_INPUT = {
    "featureId": "docs-by-status",
    "displayName": "DemoFeature - Docs By Status",
    "installedVersion": "1.0.0",
    "stackName": "idp-main-feature-docs-by-status",
    "stackId": "arn:aws:cloudformation:us-east-1:111:stack/xxx/aaa",
    "stackRegion": "us-east-1",
    "uiBundlePath": "features/docs-by-status/v1.0.0/",
    "featureApiEndpoint": "https://example.execute-api.us-east-1.amazonaws.com",
}


def test_full_install_flow_register_then_list(loaders, mock_stack):
    _put_latest(mock_stack["bucket"], "docs-by-status", "1.0.0")

    # Empty initially
    assert loaders["list"].handler(appsync_event("listInstalledFeatures"), None) == []

    # Register (mimics feature stack's RegisterFeature custom resource)
    result = loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    assert result["featureId"] == "docs-by-status"

    # Now appears in the list
    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert len(features) == 1
    assert features[0]["displayName"] == "DemoFeature - Docs By Status"


def test_unregister_removes_from_list(loaders, mock_stack):
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    loaders["register"].handler(
        appsync_event("unregisterFeature", arguments={"featureId": "docs-by-status"}),
        None,
    )
    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert features == []


def test_upgrade_overwrites_installed_version(loaders, mock_stack):
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": _REG_INPUT}), None
    )
    upgraded = {
        **_REG_INPUT,
        "installedVersion": "2.0.0",
        "uiBundlePath": "features/docs-by-status/v2.0.0/",
    }
    loaders["register"].handler(
        appsync_event("registerFeature", arguments={"input": upgraded}), None
    )
    features = loaders["list"].handler(appsync_event("listInstalledFeatures"), None)
    assert len(features) == 1  # not duplicated
    assert features[0]["installedVersion"] == "2.0.0"
    assert features[0]["uiBundlePath"] == "features/docs-by-status/v2.0.0/"
