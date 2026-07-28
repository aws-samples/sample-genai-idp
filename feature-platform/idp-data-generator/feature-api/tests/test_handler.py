# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the Test Set Generator feature API."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_QUEUE_NAME = "TestBootstrapQueue"
_TRACKING_TABLE = "TestBootstrapTracking"
_HOST_TABLE = "TestHostTracking"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_TRACKING_TABLE", _TRACKING_TABLE)
    monkeypatch.setenv("HOST_TRACKING_TABLE", _HOST_TABLE)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def _make_queue(mod):
    sqs = boto3.client("sqs", region_name="us-west-2")
    url = sqs.create_queue(QueueName=_QUEUE_NAME)["QueueUrl"]
    mod._QUEUE_URL = url
    mod._sqs = sqs
    return url


def _make_host_table():
    ddb = boto3.resource("dynamodb", region_name="us-west-2")
    ddb.create_table(
        TableName=_HOST_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
    )
    return ddb.Table(_HOST_TABLE)


def _post(mod, path, body, *, groups="[Admin]"):
    event = {
        "rawPath": path,
        "requestContext": {
            "http": {"method": "POST"},
            "authorizer": {"jwt": {"claims": {"cognito:groups": groups}}},
        },
        "body": json.dumps(body),
    }
    return mod.lambda_handler(event, None)


class TestTestSetDest:
    def test_append_valid_id(self, mod):
        dest = mod._test_set_dest({"testSetId": "fake-w2"})
        assert dest == {
            "testSetId": "fake-w2",
            "testSetName": "fake-w2",
            "append": True,
        }

    def test_append_invalid_id_rejected(self, mod):
        with pytest.raises(mod._BadRequest):
            mod._test_set_dest({"testSetId": "bad/id"})

    def test_append_overlong_id_rejected(self, mod):
        with pytest.raises(mod._BadRequest):
            mod._test_set_dest({"testSetId": "a" * 51})

    def test_create_new_valid(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_test_set_exists", lambda _id: False)
        dest = mod._test_set_dest({"testSetName": "W2 Synthetic"})
        assert dest == {
            "testSetId": "w2-synthetic",
            "testSetName": "W2 Synthetic",
            "append": False,
        }

    def test_create_new_collision_rejected(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_test_set_exists", lambda _id: True)
        with pytest.raises(mod._BadRequest):
            mod._test_set_dest({"testSetName": "W2 Synthetic"})

    def test_create_new_bad_name_rejected(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_test_set_exists", lambda _id: False)
        with pytest.raises(mod._BadRequest):
            mod._test_set_dest({"testSetName": "bad/name"})

    def test_missing_destination_rejected(self, mod):
        with pytest.raises(mod._BadRequest):
            mod._test_set_dest({})


class TestRbac:
    @mock_aws
    def test_generate_requires_write_group(self, mod):
        resp = _post(mod, "/generate", {"prompt": "a W2"}, groups="[Viewer]")
        assert resp["statusCode"] == 403

    @mock_aws
    def test_generate_from_config_requires_write_group(self, mod):
        resp = _post(
            mod,
            "/generate-from-config",
            {"versionName": "v1", "className": "W2"},
            groups="[Viewer]",
        )
        assert resp["statusCode"] == 403

    @mock_aws
    def test_author_can_generate(self, mod):
        _make_queue(mod)
        _make_host_table()
        resp = _post(
            mod,
            "/generate",
            {"prompt": "a W2", "testSetName": "W2 Synthetic"},
            groups="[Author]",
        )
        assert resp["statusCode"] == 202
        assert json.loads(resp["body"])["jobId"]
