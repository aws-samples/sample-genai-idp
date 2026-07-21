# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for test_set_resolver — getTestSetDocuments.

The resolver builds its S3 and DynamoDB clients at import time, so each test
imports the module inside moto with the env vars already set (same pattern as
get_file_contents_resolver/test_index.py).
"""

import importlib

import boto3
import pytest
from moto import mock_aws

TEST_SET_BUCKET = "test-set-bucket"
TRACKING_TABLE = "tracking-table"
TEST_SET_ID = "my-set"


def _event(field, arguments, groups=("Admin",)):
    return {
        "info": {"fieldName": field},
        "arguments": arguments,
        "identity": {"claims": {"cognito:groups": list(groups)}},
    }


def _seed_document(s3, name, sections=(1,)):
    s3.put_object(
        Bucket=TEST_SET_BUCKET,
        Key=f"{TEST_SET_ID}/input/{name}",
        Body=b"%PDF-1.4 fake",
    )
    for n in sections:
        s3.put_object(
            Bucket=TEST_SET_BUCKET,
            Key=f"{TEST_SET_ID}/baseline/{name}/sections/{n}/result.json",
            Body=b'{"inference_result": {}}',
        )


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("TEST_SET_BUCKET", TEST_SET_BUCKET)
    monkeypatch.setenv("TRACKING_TABLE", TRACKING_TABLE)
    monkeypatch.setenv("INPUT_BUCKET", "input-bucket")
    monkeypatch.setenv("TEST_SET_COPY_QUEUE_URL", "https://sqs/queue")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=TEST_SET_BUCKET)
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TRACKING_TABLE,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.put_item(
            TableName=TRACKING_TABLE,
            Item={
                "PK": {"S": f"testset#{TEST_SET_ID}"},
                "SK": {"S": "metadata"},
                "id": {"S": TEST_SET_ID},
                "name": {"S": "my set"},
                "status": {"S": "COMPLETED"},
                "createdAt": {"S": "2026-01-01T00:00:00Z"},
            },
        )

        # Import after mock + env are in place so the module-level clients
        # bind to moto.
        import index

        importlib.reload(index)
        yield index, s3


@pytest.mark.unit
def test_lists_documents_with_sections(resolver):
    index, s3 = resolver
    _seed_document(s3, "doc-a.pdf", sections=(1, 2, 10))
    _seed_document(s3, "doc-b.png")

    result = index.handler(
        _event("getTestSetDocuments", {"testSetId": TEST_SET_ID}), None
    )

    assert result["nextToken"] is None
    docs = {d["objectKey"]: d for d in result["documents"]}
    assert set(docs) == {"doc-a.pdf", "doc-b.png"}
    assert docs["doc-a.pdf"]["inputKey"] == f"{TEST_SET_ID}/input/doc-a.pdf"
    assert docs["doc-a.pdf"]["size"] > 0
    assert docs["doc-a.pdf"]["lastModified"]
    # Numeric sort: 1, 2, 10 (not 1, 10, 2)
    assert [s["sectionId"] for s in docs["doc-a.pdf"]["sections"]] == ["1", "2", "10"]
    assert (
        docs["doc-b.png"]["sections"][0]["baselineKey"]
        == f"{TEST_SET_ID}/baseline/doc-b.png/sections/1/result.json"
    )


@pytest.mark.unit
def test_handles_nested_input_names(resolver):
    index, s3 = resolver
    _seed_document(s3, "folder/nested doc.pdf")

    result = index.handler(
        _event("getTestSetDocuments", {"testSetId": TEST_SET_ID}), None
    )

    (doc,) = result["documents"]
    assert doc["objectKey"] == "folder/nested doc.pdf"
    assert doc["sections"] == [
        {
            "sectionId": "1",
            "baselineKey": f"{TEST_SET_ID}/baseline/folder/nested doc.pdf/sections/1/result.json",
        }
    ]


@pytest.mark.unit
def test_pagination_round_trip(resolver):
    index, s3 = resolver
    for i in range(5):
        _seed_document(s3, f"doc-{i}.pdf")

    first = index.handler(
        _event("getTestSetDocuments", {"testSetId": TEST_SET_ID, "limit": 2}), None
    )
    assert len(first["documents"]) == 2
    assert first["nextToken"]

    second = index.handler(
        _event(
            "getTestSetDocuments",
            {"testSetId": TEST_SET_ID, "limit": 3, "nextToken": first["nextToken"]},
        ),
        None,
    )
    assert len(second["documents"]) == 3
    assert second["nextToken"] is None
    all_names = {d["objectKey"] for d in first["documents"] + second["documents"]}
    assert all_names == {f"doc-{i}.pdf" for i in range(5)}


@pytest.mark.unit
def test_object_key_filter_returns_single_document(resolver):
    index, s3 = resolver
    _seed_document(s3, "doc-a.pdf", sections=(1, 2))
    _seed_document(s3, "doc-a.pdf.bak")  # same-prefix sibling must be excluded
    _seed_document(s3, "doc-b.pdf")

    result = index.handler(
        _event(
            "getTestSetDocuments",
            {"testSetId": TEST_SET_ID, "objectKey": "doc-a.pdf"},
        ),
        None,
    )
    (doc,) = result["documents"]
    assert doc["objectKey"] == "doc-a.pdf"
    assert [s["sectionId"] for s in doc["sections"]] == ["1", "2"]


@pytest.mark.unit
def test_object_key_traversal_rejected(resolver):
    index, _ = resolver
    with pytest.raises(Exception, match="Invalid object key"):
        index.handler(
            _event(
                "getTestSetDocuments",
                {"testSetId": TEST_SET_ID, "objectKey": "../other/secret.pdf"},
            ),
            None,
        )


@pytest.mark.unit
def test_missing_baseline_yields_empty_sections(resolver):
    index, s3 = resolver
    s3.put_object(
        Bucket=TEST_SET_BUCKET,
        Key=f"{TEST_SET_ID}/input/orphan.pdf",
        Body=b"x",
    )

    result = index.handler(
        _event("getTestSetDocuments", {"testSetId": TEST_SET_ID}), None
    )
    (doc,) = result["documents"]
    assert doc["sections"] == []


@pytest.mark.unit
def test_unknown_test_set_rejected(resolver):
    index, _ = resolver
    with pytest.raises(Exception, match="not found"):
        index.handler(
            _event("getTestSetDocuments", {"testSetId": "no-such-set"}), None
        )


@pytest.mark.unit
@pytest.mark.parametrize("bad_id", ["../other", "a/b", "set#1", ""])
def test_invalid_test_set_id_rejected(resolver, bad_id):
    index, _ = resolver
    with pytest.raises(Exception, match="Invalid test set id"):
        index.handler(
            _event("getTestSetDocuments", {"testSetId": bad_id}), None
        )


@pytest.mark.unit
@pytest.mark.parametrize("groups", [(), ("Viewer",), ("Reviewer",)])
def test_rbac_denies_non_admin_author(resolver, groups):
    index, _ = resolver
    with pytest.raises(Exception, match="Unauthorized"):
        index.handler(
            _event("getTestSetDocuments", {"testSetId": TEST_SET_ID}, groups=groups),
            None,
        )
