# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for synthesis.engine adapter (seed_data Generator mocked)."""

import json
import sys
import types
from unittest.mock import patch

import pytest

from idp_common.synthesis import engine, packet_io

pytestmark = pytest.mark.unit


class _FakeGeneratedDoc:
    """Stand-in for seed_data's GeneratedDoc (typed attrs + lazy .data)."""

    def __init__(self, pdf, data_json_path, success=True, augmented_path=None):
        self.success = success
        self.pdf_path = pdf
        self.augmented_path = augmented_path
        self.data_json_path = data_json_path

    @property
    def data(self):
        if not self.data_json_path:
            return None
        with open(self.data_json_path, encoding="utf-8") as fh:
            return json.load(fh)


class _FakeBatchResult:
    def __init__(self, docs):
        self.documents = docs

    @property
    def succeeded(self):
        return [d for d in self.documents if d.success]


def _install_fake_seed_data(monkeypatch, docs, captured=None):
    """Register a fake ``seed_data`` module exposing Generator + ModelConfig."""

    class _Generator:
        def __init__(self, **kwargs):
            if captured is not None:
                captured["init"] = kwargs

        def generate_batch(self, schema_dir, *, count, scenario, on_document=None):
            if captured is not None:
                captured["call"] = {
                    "schema_dir": schema_dir,
                    "count": count,
                    "scenario": scenario,
                }
            for i, d in enumerate(docs, start=1):
                if on_document:
                    on_document(i, len(docs), d)
            return _FakeBatchResult(docs)

    fake = types.ModuleType("seed_data")
    fake.Generator = _Generator
    fake.ModelConfig = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "seed_data", fake)


def _write_schema_dir(tmp_path):
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "schema.json").write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "Paystub",
                "type": "object",
                "properties": {"EmployeeName": {"type": "string"}},
            }
        )
    )
    return str(schema_dir)


def _make_generated_doc(tmp_path, idx, data):
    pdf = tmp_path / f"gen_{idx}.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    dj = tmp_path / f"gen_{idx}.json"
    dj.write_text(json.dumps(data))
    return _FakeGeneratedDoc(pdf=str(pdf), data_json_path=str(dj))


class TestEstimateCost:
    def test_scales_with_count_and_threshold(self):
        low = engine.estimate_cost(5, threshold=7)
        high = engine.estimate_cost(5, threshold=8)
        assert low["documents"] == 5
        assert high["estimated_usd_low"] > low["estimated_usd_low"]


class TestSynthesizeShaping:
    def test_shapes_batch_into_test_set_layout(self, tmp_path, monkeypatch):
        schema_dir = _write_schema_dir(tmp_path)
        out_dir = str(tmp_path / "out")

        docs = [
            _make_generated_doc(tmp_path, 1, {"EmployeeName": "Jane"}),
            _make_generated_doc(tmp_path, 2, {"EmployeeName": "John"}),
        ]

        captured = {}
        _install_fake_seed_data(monkeypatch, docs, captured)
        monkeypatch.setattr(engine, "_pdf_page_indices", lambda p: [0])

        job = engine.SynthesisJob(
            schema_dir=schema_dir, out_dir=out_dir, count=2, extra="diverse paystubs"
        )
        progress = []
        result = engine.synthesize(job, status_cb=lambda pct, msg: progress.append(pct))

        assert result.success
        assert result.docs_completed == 2
        assert progress and progress[-1] >= 90
        # job.extra is passed through as the generate_batch scenario.
        assert captured["call"]["scenario"] == "diverse paystubs"

        documents = packet_io.read_packet(result.packet_dir)
        assert len(documents) == 2
        section = documents[0].sections[0]
        assert section["document_class"]["type"] == "Paystub"
        assert "EmployeeName" in section["inference_result"]

    def test_no_successful_docs_returns_failure(self, tmp_path, monkeypatch):
        schema_dir = _write_schema_dir(tmp_path)
        failed = _FakeGeneratedDoc(pdf=None, data_json_path=None, success=False)
        _install_fake_seed_data(monkeypatch, [failed])

        job = engine.SynthesisJob(
            schema_dir=schema_dir, out_dir=str(tmp_path / "out"), count=1
        )
        result = engine.synthesize(job)
        assert not result.success
        assert result.docs_completed == 0

    def test_raises_when_generator_unavailable(self, tmp_path):
        with patch.object(
            engine, "generator_available", return_value=(False, "no mod")
        ):
            job = engine.SynthesisJob(
                schema_dir=_write_schema_dir(tmp_path), out_dir=str(tmp_path / "o")
            )
            with pytest.raises(RuntimeError):
                engine.synthesize(job)


class TestDocumentClassFromSchemaDir:
    def test_reads_title(self, tmp_path):
        schema_dir = _write_schema_dir(tmp_path)
        assert engine._document_class_from_schema_dir(schema_dir) == "Paystub"

    def test_falls_back_to_document(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert engine._document_class_from_schema_dir(str(empty)) == "Document"
