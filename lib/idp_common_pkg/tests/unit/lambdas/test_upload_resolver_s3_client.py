import importlib
import os
import sys

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../nested/api-resolvers/src/lambda/upload_resolver",
    )
)


@pytest.fixture(autouse=True)
def _path_setup(monkeypatch):
    sys.path.insert(0, LAMBDA_DIR)
    yield
    sys.path.remove(LAMBDA_DIR)
    sys.modules.pop("index", None)


def _reload():
    if "index" in sys.modules:
        del sys.modules["index"]
    return importlib.import_module("index")


def test_public_mode_uses_path_addressing_and_no_endpoint(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    cfg = mod.s3_client.meta.config
    assert cfg.signature_version == "s3v4"
    assert cfg.s3["addressing_style"] == "path"
    assert mod.s3_client.meta.endpoint_url.endswith("amazonaws.com")


def test_private_mode_uses_virtual_addressing_and_vpce_endpoint(monkeypatch):
    monkeypatch.setenv(
        "S3_ENDPOINT_URL",
        "https://bucket.vpce-abc123.s3.us-east-1.vpce.amazonaws.com",
    )
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    cfg = mod.s3_client.meta.config
    assert cfg.signature_version == "s3v4"
    assert cfg.s3["addressing_style"] == "virtual"
    assert (
        mod.s3_client.meta.endpoint_url
        == "https://bucket.vpce-abc123.s3.us-east-1.vpce.amazonaws.com"
    )


def test_empty_string_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    mod = _reload()
    cfg = mod.s3_client.meta.config
    assert cfg.s3["addressing_style"] == "path"
    assert mod.s3_client.meta.endpoint_url.endswith("amazonaws.com")
