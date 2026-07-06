# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for samples-manifest.json generation in IDPPublisher.

Covers the pure (no-AWS) scanning logic:
- top-level sample documents are indexed as "document" entries
- known doc subdirs (w2, rule-validation) are indexed as single "batch" entries
- unknown / code-sample subdirs are skipped
- non-document files are skipped
- curated overrides win; unknown files get filename-derived names
- missing samples/ dir → no manifest, no error
"""

from __future__ import annotations

import json
import os

import pytest
from idp_sdk._core.publish import IDPPublisher


@pytest.fixture
def publisher_in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("config_library", exist_ok=True)
    pub = IDPPublisher(verbose=False)
    return pub, tmp_path


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 test")


def _read_manifest(tmp_path):
    return json.loads(
        (tmp_path / "config_library" / "samples-manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_missing_samples_dir_returns_none(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    assert pub.generate_samples_manifest() is None
    assert not (tmp_path / "config_library" / "samples-manifest.json").exists()


def test_indexes_docs_batches_and_skips_noise(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    samples = tmp_path / "samples"
    # Top-level docs
    _touch(samples / "lending_package.pdf")
    _touch(samples / "Nuveen.pdf")
    _touch(samples / "notes.txt")  # non-document → skipped
    # Known batch subdir
    _touch(samples / "w2" / "W2_0.pdf")
    _touch(samples / "w2" / "W2_1.pdf")
    # Unknown subdir → skipped
    _touch(samples / "lambda-hook-inference" / "handler.py")

    manifest = pub.generate_samples_manifest()
    by_id = {s["id"]: s for s in manifest["samples"]}

    assert manifest["schemaVersion"] == "1.0"
    # txt + code subdir excluded; 2 docs + 1 batch indexed.
    assert set(by_id) == {"lending_package", "Nuveen", "w2"}

    # Curated override applied.
    assert by_id["lending_package"]["name"] == "Lending Package"
    assert by_id["lending_package"]["kind"] == "document"
    assert by_id["lending_package"]["s3Key"] == "samples/lending_package.pdf"
    assert by_id["lending_package"]["fileCount"] == 1

    # Unknown file → filename-derived name.
    assert by_id["Nuveen"]["name"] == "Nuveen"

    # Batch subdir counts its docs and uses a trailing-slash key.
    assert by_id["w2"]["kind"] == "batch"
    assert by_id["w2"]["fileCount"] == 2
    assert by_id["w2"]["s3Key"] == "samples/w2/"

    # Written to disk.
    assert _read_manifest(tmp_path) == manifest


def test_empty_known_batch_dir_skipped(publisher_in_tmp):
    pub, tmp_path = publisher_in_tmp
    samples = tmp_path / "samples"
    (samples / "rule-validation").mkdir(parents=True)
    _touch(samples / "invoice.pdf")

    manifest = pub.generate_samples_manifest()
    ids = {s["id"] for s in manifest["samples"]}
    assert ids == {"invoice"}  # empty rule-validation/ produced no entry
