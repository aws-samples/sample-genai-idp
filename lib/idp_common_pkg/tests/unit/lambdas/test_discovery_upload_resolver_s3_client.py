import importlib
import os
import sys

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../nested/appsync/src/lambda/discovery_upload_resolver",
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
