# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the sample-document operations in upload_resolver.

Covers listSampleDocuments (manifest read) and uploadSampleDocument
(server-side copy of a bundled sample from the ConfigurationBucket into the
InputBucket, including config-version metadata and batch expansion).
"""

import importlib
import json

import boto3
import pytest
from moto import mock_aws

CONFIG_BUCKET = "config-bucket"
INPUT_BUCKET = "input-bucket"

MANIFEST = {
    "schemaVersion": "1.0",
    "samples": [
        {
            "id": "bank-statement-multipage",
            "name": "Bank Statement (multi-page)",
            "description": "desc",
            "s3Key": "samples/bank-statement-multipage.pdf",
            "kind": "document",
            "fileCount": 1,
            "configId": "bank-statement-sample",
        },
        {
            "id": "w2",
            "name": "W-2 Forms",
            "description": "desc",
            "s3Key": "samples/w2/",
            "kind": "batch",
            "fileCount": 2,
            "configId": "fake-w2",
        },
    ],
}


def _event(field, arguments=None, groups=("Admin",)):
    return {
        "info": {"fieldName": field},
        "arguments": arguments or {},
        "identity": {"claims": {"cognito:groups": list(groups)}},
    }


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setenv("CONFIGURATION_BUCKET", CONFIG_BUCKET)
    monkeypatch.setenv("INPUT_BUCKET", INPUT_BUCKET)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=CONFIG_BUCKET)
        s3.create_bucket(Bucket=INPUT_BUCKET)
        s3.put_object(
            Bucket=CONFIG_BUCKET,
            Key="config_library/samples-manifest.json",
            Body=json.dumps(MANIFEST).encode(),
        )
        s3.put_object(
            Bucket=CONFIG_BUCKET,
            Key="samples/bank-statement-multipage.pdf",
            Body=b"%PDF-1.4 statement",
        )
        s3.put_object(Bucket=CONFIG_BUCKET, Key="samples/w2/W2_0.pdf", Body=b"%PDF a")
        s3.put_object(Bucket=CONFIG_BUCKET, Key="samples/w2/W2_1.pdf", Body=b"%PDF b")

        # Import after the mock + env are in place so the module-level S3 client
        # is created against moto.
        import index

        importlib.reload(index)
        yield index, s3


@pytest.mark.unit
def test_list_sample_documents(resolver):
    index, _ = resolver
    result = index.handler(_event("listSampleDocuments", groups=("Viewer",)))
    assert result["success"] is True
    ids = {s["id"] for s in result["samples"]}
    assert ids == {"bank-statement-multipage", "w2"}


@pytest.mark.unit
def test_list_sample_documents_denies_unauthorized(resolver):
    index, _ = resolver
    with pytest.raises(PermissionError):
        index.handler(_event("listSampleDocuments", groups=("Reviewer",)))


@pytest.mark.unit
def test_upload_sample_document_copies_with_version_metadata(resolver):
    index, s3 = resolver
    result = index.handler(
        _event(
            "uploadSampleDocument",
            {"sampleId": "bank-statement-multipage", "prefix": "demo", "version": "bank-statement-sample"},
        )
    )
    assert result["success"] is True
    assert result["objectKeys"] == ["demo/bank-statement-multipage.pdf"]

    head = s3.head_object(Bucket=INPUT_BUCKET, Key="demo/bank-statement-multipage.pdf")
    assert head["Metadata"]["config-version"] == "bank-statement-sample"


@pytest.mark.unit
def test_upload_sample_document_batch_expands_all_files(resolver):
    index, s3 = resolver
    result = index.handler(
        _event("uploadSampleDocument", {"sampleId": "w2", "version": "fake-w2"})
    )
    assert result["success"] is True
    assert sorted(result["objectKeys"]) == ["W2_0.pdf", "W2_1.pdf"]
    listing = s3.list_objects_v2(Bucket=INPUT_BUCKET)
    assert {o["Key"] for o in listing["Contents"]} == {"W2_0.pdf", "W2_1.pdf"}


@pytest.mark.unit
def test_upload_sample_document_unknown_id(resolver):
    index, _ = resolver
    result = index.handler(_event("uploadSampleDocument", {"sampleId": "nope"}))
    assert result["success"] is False
    assert "Unknown sampleId" in result["error"]


@pytest.mark.unit
def test_upload_sample_document_denies_viewer(resolver):
    index, _ = resolver
    with pytest.raises(PermissionError):
        index.handler(
            _event("uploadSampleDocument", {"sampleId": "w2"}, groups=("Viewer",))
        )
