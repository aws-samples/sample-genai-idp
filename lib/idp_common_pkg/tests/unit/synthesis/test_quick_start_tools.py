# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for Quick Start Agent tool logic (the *_impl functions)."""

import json
from unittest.mock import Mock, patch

import pytest

pytestmark = pytest.mark.unit


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "Paystub",
    "x-aws-idp-document-type": "Paystub",
    "type": "object",
    "description": "pay",
    "properties": {
        "NetPay": {
            "type": "number",
            "description": "net",
            "x-aws-idp-evaluation-method": "NUMERIC_EXACT",
        }
    },
}


def _mock_bedrock(text):
    mc = Mock()
    mc.invoke_model.return_value = {}
    mc.extract_text_from_response.return_value = text
    return mc


class TestEstimateAndAvailability:
    def test_estimate_returns_json(self):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        out = json.loads(bt.estimate_generation_cost_impl(5, 7))
        assert out["documents"] == 5
        assert "estimated_usd_low" in out

    def test_availability_reports_unavailable(self):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt
        from idp_common.synthesis import engine

        with patch.object(
            engine, "generator_available", return_value=(False, "no mod")
        ):
            assert "NOT available" in bt.check_generator_availability_impl()


class TestAuthorTool:
    def test_authors_schema(self):
        import idp_common.bedrock as bedrock_mod
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        with patch.object(
            bedrock_mod, "BedrockClient", return_value=_mock_bedrock(json.dumps(SCHEMA))
        ):
            out = json.loads(bt.author_schema_from_prompt_impl("a paystub"))
            assert out["$id"] == "Paystub"


class TestRequestGenerationGuards:
    def test_blocks_when_generator_unavailable(self):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt
        from idp_common.synthesis import engine

        with patch.object(engine, "generator_available", return_value=(False, "x")):
            out = json.loads(
                bt.request_document_generation_impl(json.dumps(SCHEMA), "v1")
            )
            assert out["enqueued"] is False

    def test_blocks_when_queue_not_configured(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt
        from idp_common.synthesis import engine

        monkeypatch.delenv("BOOTSTRAP_QUEUE_URL", raising=False)
        with patch.object(engine, "generator_available", return_value=(True, "")):
            out = json.loads(
                bt.request_document_generation_impl(json.dumps(SCHEMA), "v1")
            )
            assert out["enqueued"] is False

    def test_enqueues_when_available_and_configured(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt
        from idp_common.synthesis import engine

        monkeypatch.setenv("BOOTSTRAP_QUEUE_URL", "https://sqs/queue")
        sent = {}

        class _SQS:
            def send_message(self, QueueUrl, MessageBody):
                sent["url"] = QueueUrl
                sent["body"] = json.loads(MessageBody)

        with patch.object(engine, "generator_available", return_value=(True, "")):
            with patch("boto3.client", return_value=_SQS()):
                out = json.loads(
                    bt.request_document_generation_impl(
                        json.dumps(SCHEMA), "v1", doc_count=4
                    )
                )
        assert out["enqueued"] is True
        assert sent["body"]["targetVersion"] == "v1"
        assert sent["body"]["docCount"] == 4
        assert "NetPay" in sent["body"]["allowedFieldNames"]


class TestGenerateFromExistingConfig:
    def test_list_config_versions(self):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        mgr = Mock()
        mgr.list_config_versions.return_value = [
            {"versionName": "v1", "isActive": True, "description": "d"}
        ]
        mgr.get_raw_configuration.return_value = {"classes": [SCHEMA]}
        with patch(
            "idp_common.config.configuration_manager.ConfigurationManager",
            return_value=mgr,
        ):
            out = json.loads(bt.list_config_versions_impl())
        assert out["versions"][0]["versionName"] == "v1"
        assert out["versions"][0]["classes"] == ["Paystub"]

    def test_generate_from_existing_enqueues(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        monkeypatch.setenv("BOOTSTRAP_QUEUE_URL", "https://sqs/queue")
        mgr = Mock()
        mgr.get_raw_configuration.return_value = {"classes": [SCHEMA]}
        sent = {}

        class _SQS:
            def send_message(self, QueueUrl, MessageBody):
                sent["body"] = json.loads(MessageBody)

        with patch(
            "idp_common.config.configuration_manager.ConfigurationManager",
            return_value=mgr,
        ):
            with patch("boto3.client", return_value=_SQS()):
                out = json.loads(
                    bt.generate_from_existing_config_impl("v1", "Paystub", doc_count=2)
                )
        assert out["enqueued"] is True
        assert sent["body"]["targetVersion"] == "v1"
        assert sent["body"]["docCount"] == 2
        assert "NetPay" in sent["body"]["allowedFieldNames"]
        assert sent["body"]["preauthoredSchema"]["title"] == "Paystub"

    def test_generate_from_existing_missing_class(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        monkeypatch.setenv("BOOTSTRAP_QUEUE_URL", "https://sqs/queue")
        mgr = Mock()
        mgr.get_raw_configuration.return_value = {"classes": [SCHEMA]}
        with patch(
            "idp_common.config.configuration_manager.ConfigurationManager",
            return_value=mgr,
        ):
            out = json.loads(
                bt.generate_from_existing_config_impl("v1", "DoesNotExist")
            )
        assert out["enqueued"] is False
        assert "Paystub" in out["availableClasses"]


class TestListSampleDocuments:
    def test_unavailable_when_bucket_env_missing(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        monkeypatch.delenv("CONFIGURATION_BUCKET", raising=False)
        out = json.loads(bt.list_sample_documents_impl())
        assert out["available"] is False
        assert out["samples"] == []

    def test_reads_manifest_from_configuration_bucket(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        monkeypatch.setenv("CONFIGURATION_BUCKET", "cfg-bucket")
        manifest = {
            "schemaVersion": "1.0",
            "samples": [
                {
                    "id": "lending_package",
                    "name": "Lending Package",
                    "kind": "document",
                },
                {"id": "w2", "name": "W-2 Forms", "kind": "batch", "fileCount": 20},
            ],
        }

        class _Body:
            def read(self):
                return json.dumps(manifest).encode("utf-8")

        class _S3:
            def get_object(self, Bucket, Key):
                assert Bucket == "cfg-bucket"
                assert Key == "config_library/samples-manifest.json"
                return {"Body": _Body()}

        with patch("boto3.client", return_value=_S3()):
            out = json.loads(bt.list_sample_documents_impl())

        assert out["available"] is True
        assert [s["id"] for s in out["samples"]] == ["lending_package", "w2"]

    def test_missing_manifest_degrades_gracefully(self, monkeypatch):
        from idp_common.agents.quick_start.tools import bootstrap_tools as bt

        monkeypatch.setenv("CONFIGURATION_BUCKET", "cfg-bucket")

        class _S3:
            def get_object(self, Bucket, Key):
                raise Exception("NoSuchKey")

        with patch("boto3.client", return_value=_S3()):
            out = json.loads(bt.list_sample_documents_impl())

        assert out["available"] is False
        assert out["samples"] == []
