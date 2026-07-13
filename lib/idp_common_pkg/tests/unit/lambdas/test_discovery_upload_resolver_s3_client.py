import importlib
import os
import sys
from unittest.mock import MagicMock

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../nested/api-resolvers/src/lambda/discovery_upload_resolver",
    )
)


@pytest.fixture(autouse=True)
def _path_setup():
    sys.path.insert(0, LAMBDA_DIR)
    yield
    sys.path.remove(LAMBDA_DIR)
    sys.modules.pop("index", None)


def _reload():
    if "index" in sys.modules:
        del sys.modules["index"]
    return importlib.import_module("index")


def test_public_mode_path_addressing(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    assert mod.s3_client.meta.config.s3["addressing_style"] == "path"
    assert mod.s3_client.meta.endpoint_url.endswith("amazonaws.com")


def test_private_mode_vpce(monkeypatch):
    monkeypatch.setenv(
        "S3_ENDPOINT_URL",
        "https://bucket.vpce-xyz.s3.us-west-2.vpce.amazonaws.com",
    )
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    mod = _reload()
    assert mod.s3_client.meta.config.s3["addressing_style"] == "virtual"
    assert (
        mod.s3_client.meta.endpoint_url
        == "https://bucket.vpce-xyz.s3.us-west-2.vpce.amazonaws.com"
    )


def _mock_config_manager(monkeypatch, existing):
    """Patch ConfigurationManager (imported lazily inside the resolver) so
    _clear_version_schema operates on an in-memory config dict."""
    manager = MagicMock()
    manager.get_raw_configuration.return_value = existing

    fake_cm_module = MagicMock()
    fake_cm_module.ConfigurationManager.return_value = manager
    monkeypatch.setitem(
        sys.modules, "idp_common.config.configuration_manager", fake_cm_module
    )
    return manager


def test_clear_version_schema_classes(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    existing = {
        "classes": [{"$id": "A"}, {"$id": "B"}],
        "extraction": {"model": "m"},
    }
    manager = _mock_config_manager(monkeypatch, existing)

    mod._clear_version_schema("v1", discovery_type="classes")

    # classes cleared, other sections preserved, saved back to same version
    saved_type, saved_config = manager.save_raw_configuration.call_args[0][:2]
    assert saved_type == "Config"
    assert saved_config["classes"] == []
    assert saved_config["extraction"] == {"model": "m"}
    assert manager.save_raw_configuration.call_args.kwargs["version"] == "v1"


def test_clear_version_schema_rules_clears_policy_classes(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    existing = {"policy_classes": [{"x-aws-idp-policy-type": "P"}], "classes": [{"$id": "A"}]}
    manager = _mock_config_manager(monkeypatch, existing)

    mod._clear_version_schema("v1", discovery_type="rules")

    saved_config = manager.save_raw_configuration.call_args[0][1]
    # rules discovery only clears policy_classes, leaves classes untouched
    assert saved_config["policy_classes"] == []
    assert saved_config["classes"] == [{"$id": "A"}]


def test_clear_version_schema_noop_when_empty(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    manager = _mock_config_manager(monkeypatch, {"classes": []})

    mod._clear_version_schema("v1", discovery_type="classes")

    # Nothing to clear -> no save call
    manager.save_raw_configuration.assert_not_called()


def test_clear_version_schema_noop_without_version(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    # No ConfigurationManager import should even happen; passing None returns early.
    mod._clear_version_schema(None, discovery_type="classes")
