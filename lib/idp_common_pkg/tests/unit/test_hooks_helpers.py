# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for idp_common.hooks — the pipeline-hook authoring helpers.

These pin the two properties that make the load → mutate → return round-trip
safe for hook authors:

- ``load_hook_document`` resolves BOTH payload shapes the dispatcher may send
  (an inline document dict, or the far more common compressed reference), so a
  hook never has to know which it got.
- ``updated_document_result`` emits the exact key the dispatcher reads
  (``updatedDocument``) in one of the two shapes it accepts, and preserves the
  fields a hand-built document would silently drop (metering, errors, …).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from idp_common.hooks import (
    UPDATED_DOCUMENT_KEY,
    load_hook_document,
    updated_document_result,
)
from idp_common.models import Document, Section, Status


def _doc():
    return Document(
        id="w2.pdf",
        input_bucket="in",
        input_key="w2.pdf",
        output_bucket="out",
        status=Status.CLASSIFYING,
        num_pages=2,
        sections=[Section(section_id="1", classification="W2", page_ids=["1", "2"])],
        metering={"OCR/textract": {"pages": 2}},
    )


@pytest.mark.unit
class TestLoadHookDocument:
    def test_loads_inline_document_dict(self):
        doc = load_hook_document({"document": _doc().to_dict()})
        assert doc.id == "w2.pdf"
        assert doc.sections[0].classification == "W2"

    def test_loads_compressed_reference_from_working_bucket(self):
        payload = json.dumps(_doc().to_dict())
        ref = {"compressed": True, "s3_uri": "s3://wb/compressed_documents/w2/x.json"}
        with patch("boto3.client") as mock_client:
            body = MagicMock()
            body.read.return_value = payload.encode("utf-8")
            mock_client.return_value.get_object.return_value = {"Body": body}
            doc = load_hook_document({"document": ref}, working_bucket="wb")
        assert doc.id == "w2.pdf"
        assert doc.metering == {"OCR/textract": {"pages": 2}}

    def test_working_bucket_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("WORKING_BUCKET", "wb-from-env")
        payload = json.dumps(_doc().to_dict())
        ref = {"compressed": True, "s3_uri": "s3://wb-from-env/c/x.json"}
        with patch("boto3.client") as mock_client:
            body = MagicMock()
            body.read.return_value = payload.encode("utf-8")
            mock_client.return_value.get_object.return_value = {"Body": body}
            assert load_hook_document({"document": ref}).id == "w2.pdf"

    def test_compressed_reference_without_bucket_raises(self, monkeypatch):
        """Fail loudly rather than returning a half-empty document the hook
        would then hand back as an 'update'."""
        monkeypatch.delenv("WORKING_BUCKET", raising=False)
        ref = {"compressed": True, "s3_uri": "s3://wb/c/x.json"}
        with pytest.raises(ValueError, match="no working bucket"):
            load_hook_document({"document": ref})

    def test_missing_document_raises(self):
        for event in ({}, {"document": None}, {"document": {}}, {"document": "x"}):
            with pytest.raises(ValueError, match="no 'document' payload"):
                load_hook_document(event)


@pytest.mark.unit
class TestUpdatedDocumentResult:
    def test_small_document_returned_inline_under_reserved_key(self, monkeypatch):
        monkeypatch.delenv("WORKING_BUCKET", raising=False)
        out = updated_document_result(_doc())
        assert UPDATED_DOCUMENT_KEY == "updatedDocument"
        payload = out[UPDATED_DOCUMENT_KEY]
        assert payload["id"] == "w2.pdf"
        # Round-trip preserves what a hand-built document would drop.
        assert payload["metering"] == {"OCR/textract": {"pages": 2}}
        assert payload["sections"][0]["classification"] == "W2"

    def test_extra_kwargs_are_merged(self, monkeypatch):
        monkeypatch.delenv("WORKING_BUCKET", raising=False)
        out = updated_document_result(_doc(), myField="abc", halt=True)
        assert out["myField"] == "abc"
        assert out["halt"] is True
        assert UPDATED_DOCUMENT_KEY in out

    def test_large_document_is_compressed_to_reference(self):
        doc = _doc()
        doc.sections[0].attributes = {"blob": "x" * 400_000}
        with patch("boto3.client") as mock_client:
            mock_client.return_value.put_object.return_value = {}
            out = updated_document_result(
                doc, working_bucket="wb", size_threshold_kb=200
            )
        payload = out[UPDATED_DOCUMENT_KEY]
        assert payload["compressed"] is True
        assert payload["s3_uri"].startswith("s3://wb/")
        # Section IDs only — the workflow's Map state iterates this list.
        assert payload["sections"] == ["1"]

    def test_reserved_key_in_extra_is_rejected(self, monkeypatch):
        monkeypatch.delenv("WORKING_BUCKET", raising=False)
        with pytest.raises(ValueError, match="updatedDocument"):
            updated_document_result(_doc(), **{UPDATED_DOCUMENT_KEY: {"id": "x"}})

    def test_mutation_round_trip_preserves_untouched_fields(self, monkeypatch):
        """The canonical hook flow: load → mutate one field → return."""
        monkeypatch.delenv("WORKING_BUCKET", raising=False)
        doc = load_hook_document({"document": _doc().to_dict()})
        doc.sections[0].classification = "Invoice"
        payload = updated_document_result(doc)[UPDATED_DOCUMENT_KEY]
        restored = Document.from_dict(payload)
        assert restored.sections[0].classification == "Invoice"
        assert restored.metering == {"OCR/textract": {"pages": 2}}
        assert restored.input_key == "w2.pdf"
        assert restored.num_pages == 2
