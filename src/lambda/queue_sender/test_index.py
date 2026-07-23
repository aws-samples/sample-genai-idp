# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the queue_sender Lambda function."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# idp_common and aws_xray_sdk are heavy/AWS-dependent; mock them before import.
sys.modules["idp_common"] = MagicMock()
sys.modules["idp_common.models"] = MagicMock()
sys.modules["idp_common.docs_service"] = MagicMock()

mock_xray_core = MagicMock()
# capture() is used as a decorator; make it a pass-through.
mock_xray_core.xray_recorder.capture.return_value = lambda fn: fn
sys.modules["aws_xray_sdk"] = MagicMock()
sys.modules["aws_xray_sdk.core"] = mock_xray_core


@pytest.fixture(autouse=True)
def mock_env():
    env_vars = {
        "QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        "DATA_RETENTION_IN_DAYS": "30",
        "OUTPUT_BUCKET": "test-output-bucket",
        "CONFIG_TABLE": "test-config-table",
        "LOG_LEVEL": "INFO",
    }
    with patch.dict(os.environ, env_vars):
        yield


def make_event(key: str) -> dict:
    return {
        "detail": {
            "bucket": {"name": "test-input-bucket"},
            "object": {"key": key},
        },
        "time": "2026-07-23T00:00:00Z",
    }


@pytest.mark.unit
class TestFolderPseudoObject:
    """The handler must ignore S3 console folder pseudo-objects."""

    def test_skips_trailing_slash_key(self):
        """A '/'-terminated key is skipped without enqueuing or tracking."""
        import index

        with (
            patch.object(index, "sqs") as mock_sqs,
            patch.object(index, "document_service") as mock_doc_service,
            patch.object(index.Document, "from_s3_event") as mock_from_event,
        ):
            response = index.handler(make_event("testfolder/"), None)

        assert response["statusCode"] == 200
        assert response["skipped"] == "folder_pseudo_object"
        # No document created, no SQS message sent, event never parsed.
        mock_sqs.send_message.assert_not_called()
        mock_doc_service.create_document.assert_not_called()
        mock_from_event.assert_not_called()

    def test_processes_regular_key(self):
        """A normal document key is processed (not skipped)."""
        import index

        mock_document = MagicMock()
        mock_document.config_version = "v1"
        mock_document.id = "doc.pdf"
        mock_document.input_key = "doc.pdf"
        mock_document.to_json.return_value = "{}"

        with (
            patch.object(index, "sqs") as mock_sqs,
            patch.object(index, "document_service") as mock_doc_service,
            patch.object(index.Document, "from_s3_event", return_value=mock_document),
            patch.object(index.xray_recorder, "current_segment", return_value=None),
        ):
            response = index.handler(make_event("doc.pdf"), None)

        assert response["statusCode"] == 200
        assert "skipped" not in response
        mock_doc_service.create_document.assert_called_once()
        mock_sqs.send_message.assert_called_once()
