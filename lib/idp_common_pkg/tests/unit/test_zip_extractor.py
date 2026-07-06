# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# Import the actual Lambda handler module so the tests exercise the real
# baseline-matching logic instead of a duplicated copy.
_LAMBDA_INDEX = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "lambda"
    / "test_set_zip_extractor"
    / "index.py"
)
_spec = importlib.util.spec_from_file_location(
    "test_set_zip_extractor_index", _LAMBDA_INDEX
)
zip_extractor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = zip_extractor
_spec.loader.exec_module(zip_extractor)


def _collect_names(mock_files):
    """Replicate the extractor's two-pass partition + baseline resolution.

    Uses the real ``_match_baseline_name`` helper from the Lambda so a
    regression in the matching logic is caught here.
    """
    input_names = set()
    baseline_names = set()
    baseline_files = []

    # First pass: collect input names, stash baseline files.
    for file_info in mock_files:
        if file_info.is_dir():
            continue
        file_path = file_info.filename
        if "/input/" in file_path:
            input_names.add(file_path.split("/")[-1])
        elif "/baseline/" in file_path:
            baseline_files.append(file_info)

    # Second pass: resolve baseline directory names against known inputs.
    for file_info in baseline_files:
        parts = file_info.filename.split("/baseline/", 1)
        if len(parts) == 2 and "/" in parts[1]:
            path_parts = parts[1].split("/")
            if len(path_parts) >= 2:
                name = zip_extractor._match_baseline_name(path_parts, input_names)
                if name:
                    baseline_names.add(name)

    return input_names, baseline_names


@pytest.mark.unit
def test_file_validation_logic():
    """Test the file validation logic for input and baseline matching (PDF)"""

    mock_files = [
        Mock(filename="my-test-set/input/document1.pdf", is_dir=lambda: False),
        Mock(filename="my-test-set/input/document2.pdf", is_dir=lambda: False),
        Mock(
            filename="my-test-set/baseline/document1.pdf/sections/result.json",
            is_dir=lambda: False,
        ),
        Mock(
            filename="my-test-set/baseline/document1.pdf/metadata.json",
            is_dir=lambda: False,
        ),
        Mock(
            filename="my-test-set/baseline/document2.pdf/extraction.json",
            is_dir=lambda: False,
        ),
        # Directory entries (should be ignored)
        Mock(filename="my-test-set/input/", is_dir=lambda: True),
        Mock(filename="my-test-set/baseline/", is_dir=lambda: True),
    ]

    input_names, baseline_names = _collect_names(mock_files)

    assert input_names == {"document1.pdf", "document2.pdf"}
    assert baseline_names == {"document1.pdf", "document2.pdf"}
    assert not (input_names - baseline_names)
    assert not (baseline_names - input_names)


@pytest.mark.unit
def test_complex_file_structure():
    """Test with complex nested structure like the real S3 bucket"""

    mock_files = [
        Mock(
            filename="fcc_benchmark/input/fcc_benchmark/033f718b16cb597c065930410752c294.pdf",
            is_dir=lambda: False,
        ),
        Mock(
            filename="fcc_benchmark/input/fcc_benchmark/03f65053aea282ad8d5e759a9f18bdbb.pdf",
            is_dir=lambda: False,
        ),
        Mock(
            filename="fcc_benchmark/baseline/fcc_benchmark/033f718b16cb597c065930410752c294.pdf/sections/1/result.json",
            is_dir=lambda: False,
        ),
        Mock(
            filename="fcc_benchmark/baseline/fcc_benchmark/03f65053aea282ad8d5e759a9f18bdbb.pdf/sections/1/result.json",
            is_dir=lambda: False,
        ),
    ]

    input_names, baseline_names = _collect_names(mock_files)

    expected_names = {
        "033f718b16cb597c065930410752c294.pdf",
        "03f65053aea282ad8d5e759a9f18bdbb.pdf",
    }
    assert input_names == expected_names
    assert baseline_names == expected_names


@pytest.mark.unit
@pytest.mark.parametrize(
    "ext",
    ["png", "jpg", "jpeg", "tiff", "tif"],
)
def test_non_pdf_documents_flat(ext):
    """Regression for issue #380: non-PDF documents must match baselines."""

    mock_files = [
        Mock(filename=f"imgset/input/document1.{ext}", is_dir=lambda: False),
        Mock(filename=f"imgset/input/document2.{ext}", is_dir=lambda: False),
        Mock(
            filename=f"imgset/baseline/document1.{ext}/sections/1/result.json",
            is_dir=lambda: False,
        ),
        Mock(
            filename=f"imgset/baseline/document2.{ext}/sections/1/result.json",
            is_dir=lambda: False,
        ),
    ]

    input_names, baseline_names = _collect_names(mock_files)

    assert input_names == {f"document1.{ext}", f"document2.{ext}"}
    assert baseline_names == input_names
    assert not (input_names - baseline_names)


@pytest.mark.unit
def test_non_pdf_documents_nested_with_dotted_category():
    """Non-PDF docs in a nested layout under a dotted category folder.

    A category folder containing a dot must not be mistaken for the document
    directory; matching against known input names avoids that false positive.
    """

    mock_files = [
        Mock(
            filename="ds/input/my.category/scan1.png",
            is_dir=lambda: False,
        ),
        Mock(
            filename="ds/baseline/my.category/scan1.png/sections/1/result.json",
            is_dir=lambda: False,
        ),
    ]

    input_names, baseline_names = _collect_names(mock_files)

    assert input_names == {"scan1.png"}
    assert baseline_names == {"scan1.png"}


@pytest.mark.unit
def test_orphaned_non_pdf_baseline_reported_as_extra():
    """A baseline with no matching input is still surfaced (fallback path)."""

    mock_files = [
        Mock(filename="ds/input/document1.png", is_dir=lambda: False),
        Mock(
            filename="ds/baseline/document1.png/sections/1/result.json",
            is_dir=lambda: False,
        ),
        Mock(
            filename="ds/baseline/orphan.tiff/sections/1/result.json",
            is_dir=lambda: False,
        ),
    ]

    input_names, baseline_names = _collect_names(mock_files)

    assert input_names == {"document1.png"}
    # orphan.tiff has no matching input but is caught by the extension fallback
    assert baseline_names == {"document1.png", "orphan.tiff"}
    assert (baseline_names - input_names) == {"orphan.tiff"}
