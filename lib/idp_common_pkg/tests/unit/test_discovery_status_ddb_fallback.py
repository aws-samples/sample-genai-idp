# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test the HTTP API transport fallback in multi_doc_discovery/appsync_status.py:
when APPSYNC_API_URL is empty, discovery job status is written straight to the
DiscoveryTrackingTable (porting the AppSync VTL UpdateItem resolver).
"""

import importlib.util
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

pytestmark = pytest.mark.unit


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "lambda" / "multi_doc_discovery").is_dir():
            return parent
    raise RuntimeError("repo root not found")


def _load_module(table_name: str):
    """Import appsync_status with APPSYNC_API_URL empty + table configured."""
    os.environ.pop("APPSYNC_API_URL", None)
    os.environ["DISCOVERY_TRACKING_TABLE"] = table_name
    path = (
        _find_repo_root()
        / "src"
        / "lambda"
        / "multi_doc_discovery"
        / "appsync_status.py"
    )
    spec = importlib.util.spec_from_file_location("appsync_status", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["appsync_status"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def discovery_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="DiscoveryTable",
            KeySchema=[{"AttributeName": "jobId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "jobId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb


def test_writes_status_to_dynamodb_when_appsync_absent(discovery_table):
    mod = _load_module("DiscoveryTable")
    # Pre-create the job row (status updates use UpdateItem).
    discovery_table.Table("DiscoveryTable").put_item(Item={"jobId": "job-1"})

    ok = mod.update_status(
        "job-1",
        "CLUSTERING",
        current_step="Clustering documents",
        total_documents=42,
        clusters_found=3,
    )
    assert ok is True

    item = discovery_table.Table("DiscoveryTable").get_item(Key={"jobId": "job-1"})[
        "Item"
    ]
    assert item["status"] == "CLUSTERING"
    assert item["currentStep"] == "Clustering documents"
    assert item["totalDocuments"] == 42
    assert item["clustersFound"] == 3
    assert item["jobType"] == "multi-document"
    assert "updatedAt" in item
    assert "completedAt" not in item  # not terminal


def test_terminal_status_sets_completed_at(discovery_table):
    mod = _load_module("DiscoveryTable")
    discovery_table.Table("DiscoveryTable").put_item(Item={"jobId": "job-2"})

    ok = mod.update_status("job-2", "COMPLETED", discovered_classes='["Invoice"]')
    assert ok is True

    item = discovery_table.Table("DiscoveryTable").get_item(Key={"jobId": "job-2"})[
        "Item"
    ]
    assert item["status"] == "COMPLETED"
    assert item["completedAt"]
    assert item["discoveredClasses"] == '["Invoice"]'


def test_returns_false_when_no_table_and_no_appsync():
    """No AppSync URL and no table name → cannot persist; returns False."""
    os.environ.pop("APPSYNC_API_URL", None)
    os.environ.pop("DISCOVERY_TRACKING_TABLE", None)
    os.environ.pop("DISCOVERY_TABLE_NAME", None)
    path = (
        _find_repo_root()
        / "src"
        / "lambda"
        / "multi_doc_discovery"
        / "appsync_status.py"
    )
    spec = importlib.util.spec_from_file_location("appsync_status_notable", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.update_status("job-x", "FAILED") is False
