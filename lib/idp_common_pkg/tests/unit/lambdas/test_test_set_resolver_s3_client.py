import importlib
import os
import sys

import pytest

LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../../nested/api-resolvers/src/lambda/test_set_resolver",
    )
)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    sys.path.insert(0, LAMBDA_DIR)
    monkeypatch.setenv("TRACKING_TABLE", "dummy-table")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    yield
    sys.path.remove(LAMBDA_DIR)
    sys.modules.pop("index", None)


def _reload():
    if "index" in sys.modules:
        del sys.modules["index"]
    return importlib.import_module("index")


def test_public_mode(monkeypatch):
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    mod = _reload()
    assert mod.s3_client.meta.config.s3["addressing_style"] == "path"


def test_private_mode(monkeypatch):
    monkeypatch.setenv(
        "S3_ENDPOINT_URL",
        "https://bucket.vpce-tst.s3.us-east-1.vpce.amazonaws.com",
    )
    mod = _reload()
    assert mod.s3_client.meta.config.s3["addressing_style"] == "virtual"
    assert (
        mod.s3_client.meta.endpoint_url
        == "https://bucket.vpce-tst.s3.us-east-1.vpce.amazonaws.com"
    )
