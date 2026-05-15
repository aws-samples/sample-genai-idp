"""Fixtures shared by the Phase E test harness.

Loads the Phase A Lambda handlers as importable modules, mocks AWS via moto,
and provides helpers to drive each of the 7 UI-state transitions from the
resolver's perspective (the UI-side branching logic lives in FeaturePage.tsx
and is exercised separately under src/ui/).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict

import boto3
import pytest
from moto import mock_aws

_PHASE_A = Path(__file__).resolve().parents[1] / "main-stack-extensions" / "lambdas"


def _load(name: str):
    """Load `<Phase-A>/<name>/index.py` as module `phase_a_<name>`."""
    module_dir = _PHASE_A / name
    alias = f"phase_a_{name}"
    sys.path.insert(0, str(module_dir))
    try:
        sys.modules.pop(alias, None)
        sys.modules.pop("index", None)
        mod = importlib.import_module("index")
        sys.modules[alias] = mod
        return mod
    finally:
        if str(module_dir) in sys.path:
            sys.path.remove(str(module_dir))


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def mock_stack(aws_credentials):
    """Creates the InstalledFeatures DDB table + seller bucket under moto."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table_name = "InstalledFeaturesTest"
        ddb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "featureId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "featureId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
        s3 = boto3.client("s3", region_name="us-east-1")
        bucket = "test-seller"
        s3.create_bucket(Bucket=bucket)
        yield {"table_name": table_name, "bucket": bucket}


@pytest.fixture
def loaders(mock_stack, monkeypatch):
    """Load all 4 Phase A Lambdas with env vars pre-set for the test AWS world."""
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", mock_stack["table_name"])
    monkeypatch.setenv("SELLER_BUCKET", mock_stack["bucket"])
    monkeypatch.setenv("SELLER_BUCKET_REGION", "us-east-1")
    monkeypatch.setenv("MAIN_STACK_NAME", "idp-main")
    monkeypatch.setenv("ADMIN_GROUP", "Admin")
    monkeypatch.setenv(
        "FEATURE_PRODUCT_CODE_MAP", '{"docs-by-status": "prod-docs-by-status"}'
    )
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", "CUST-dev")
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", "simulator")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return {
        "list": _load("list_installed_features"),
        "register": _load("register_feature"),
        "launch": _load("get_feature_launch_url"),
        "entitle": _load("check_feature_entitlement"),
    }


def appsync_event(
    field: str,
    *,
    arguments: Dict[str, Any] | None = None,
    groups: list[str] | None = None,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return {
        "info": {"fieldName": field, "parentTypeName": "Query"},
        "arguments": arguments or {},
        "identity": {
            "username": "alice",
            "claims": {
                "cognito:username": "alice",
                "cognito:groups": groups or [],
                "email": "alice@example.com",
            },
        },
        "request": {"headers": headers or {}},
    }


def _put_latest(bucket: str, feature_id: str, version: str) -> None:
    import json

    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key=f"features/{feature_id}/latest.json",
        Body=json.dumps({"version": version}).encode(),
    )


def _put_manifest(
    bucket: str, feature_id: str, version: str, params: dict | None = None
) -> None:
    import json

    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key=f"features/{feature_id}/v{version}/manifest.json",
        Body=json.dumps(
            {"featureId": feature_id, "defaultParameters": params or {}}
        ).encode(),
    )
