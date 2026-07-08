# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for synthesis.catalog (asset index + LLM matcher)."""

import json
import os
from unittest.mock import Mock

import pytest
from idp_common.synthesis import catalog

pytestmark = pytest.mark.unit


def _write_generator_schema(root, name, title, description, with_sample=False):
    sdir = os.path.join(root, name)
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "schema.json"), "w") as fh:
        json.dump(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": title,
                "description": description,
                "type": "object",
                "properties": {"x": {"type": "string"}},
            },
            fh,
        )
    if with_sample:
        samples = os.path.join(sdir, "samples")
        os.makedirs(samples, exist_ok=True)
        with open(os.path.join(samples, "ref.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 fake")


class TestIndexGeneratorSchemas:
    def test_indexes_schema_dirs_and_samples(self, tmp_path):
        root = str(tmp_path)
        _write_generator_schema(root, "invoice", "Invoice", "A commercial invoice")
        _write_generator_schema(
            root, "fcc-invoice", "FCC-Invoice", "An FCC invoice", with_sample=True
        )
        entries = catalog.index_generator_schemas(root)
        assert {e.name for e in entries} == {"Invoice", "FCC-Invoice"}
        fcc = next(e for e in entries if e.name == "FCC-Invoice")
        assert len(fcc.sample_pdfs) == 1
        assert fcc.source == "generator"

    def test_missing_root_is_empty(self):
        assert catalog.index_generator_schemas("/no/such/dir") == []


class TestIndexConfigClasses:
    def test_keys_on_document_type(self):
        classes = [
            {
                "$id": "Bank Statement",
                "x-aws-idp-document-type": "Bank Statement",
                "description": "Monthly statement",
                "type": "object",
                "properties": {},
            },
            {"type": "object"},  # no doc type -> skipped
        ]
        entries = catalog.index_config_classes(classes)
        assert len(entries) == 1
        assert entries[0].name == "Bank Statement"
        assert entries[0].source == "config"


class TestBuildCatalog:
    def test_combines_both_sources(self, tmp_path):
        root = str(tmp_path)
        _write_generator_schema(root, "invoice", "Invoice", "An invoice")
        entries = catalog.build_catalog(
            generator_schemas_root=root,
            config_classes=[
                {"x-aws-idp-document-type": "W2", "description": "Tax form"}
            ],
        )
        assert {e.source for e in entries} == {"generator", "config"}


class TestMatchCatalog:
    def _entries(self):
        return [
            catalog.CatalogEntry(name="Invoice", source="generator", description="inv"),
            catalog.CatalogEntry(name="W2", source="config", description="tax"),
        ]

    def test_returns_match_above_confidence(self):
        client = Mock()
        client.invoke_model.return_value = {}
        client.extract_text_from_response.return_value = json.dumps(
            {"index": 1, "confidence": 0.9, "reason": "tax form"}
        )
        match = catalog.match_catalog(
            "a W2 wage and tax statement", self._entries(), bedrock_client=client
        )
        assert match is not None and match.name == "W2"

    def test_low_confidence_returns_none(self):
        client = Mock()
        client.invoke_model.return_value = {}
        client.extract_text_from_response.return_value = json.dumps(
            {"index": 0, "confidence": 0.2, "reason": "weak"}
        )
        assert (
            catalog.match_catalog("something", self._entries(), bedrock_client=client)
            is None
        )

    def test_null_index_returns_none(self):
        client = Mock()
        client.invoke_model.return_value = {}
        client.extract_text_from_response.return_value = json.dumps(
            {"index": None, "confidence": 0.0, "reason": "no match"}
        )
        assert (
            catalog.match_catalog("alien form", self._entries(), bedrock_client=client)
            is None
        )

    def test_empty_catalog_returns_none(self):
        assert catalog.match_catalog("anything", [], bedrock_client=Mock()) is None

    def test_bedrock_error_falls_back_to_none(self):
        client = Mock()
        client.invoke_model.side_effect = RuntimeError("boom")
        assert (
            catalog.match_catalog("invoice", self._entries(), bedrock_client=client)
            is None
        )
