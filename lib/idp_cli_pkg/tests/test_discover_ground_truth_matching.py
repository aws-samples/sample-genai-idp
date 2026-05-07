# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for `idp-cli discover` ground-truth matching behavior.

Regression tests for issue #310:
https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/310

Previously, `idp-cli discover -g` with a ground-truth filename stem that didn't
match any document silently ignored the ground truth, printed a yellow warning,
and exited 0. This led to subtly worse results that were hard to diagnose.

The fix:
1. Single document + single ground truth → paired by position regardless of
   filename stem.
2. Batch mode (multi-doc or multi-gt) with unmatched -g → fatal exit 1.
3. Duplicate ground-truth filename stems → fatal exit 1 (previously overwrote
   silently).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_idp_client():
    """Mock IDPClient so discover() doesn't actually call Bedrock."""

    def _make_success(doc_path):
        result = MagicMock()
        result.status = "SUCCESS"
        result.document_class = "TestClass"
        result.json_schema = {
            "$id": "TestClass",
            "type": "object",
            "properties": {"foo": {"type": "string"}},
        }
        result.error = None
        return result

    mock_client = MagicMock()
    mock_client.discovery.run.side_effect = lambda **kwargs: _make_success(
        kwargs.get("document_path")
    )
    # `discover` re-imports IDPClient inside the function body
    # (`from idp_sdk import IDPClient`), so we must patch the source module;
    # also patch the module-level import in idp_cli.cli for good measure.
    with (
        patch("idp_sdk.IDPClient", return_value=mock_client),
        patch("idp_cli.cli.IDPClient", return_value=mock_client),
    ):
        yield mock_client


def _create_files(tmp_path: Path, files: list[str]) -> list[Path]:
    """Create empty files and return their paths."""
    paths = []
    for name in files:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
        paths.append(p)
    return paths


@pytest.mark.unit
def test_single_doc_single_gt_paired_by_position_regardless_of_stem(
    runner, mock_idp_client, tmp_path
):
    """Core fix for issue #310: stems don't need to match for the common
    single-doc+single-gt case (e.g. baseline/<doc>/sections/1/result.json)."""
    from idp_cli.cli import discover

    (doc,) = _create_files(tmp_path, ["invoice.pdf"])
    # GT stem is "result" — would never match "invoice" via stem matching
    (gt,) = _create_files(tmp_path, ["baseline/invoice/sections/1/result.json"])

    result = runner.invoke(
        discover,
        ["-d", str(doc), "-g", str(gt)],
    )

    assert result.exit_code == 0, (
        f"Expected single-doc+single-gt to succeed; got exit {result.exit_code}.\n"
        f"Output:\n{result.output}"
    )
    # GT must have been passed to discovery.run — not dropped
    call_kwargs = mock_idp_client.discovery.run.call_args.kwargs
    assert call_kwargs["ground_truth_path"] == str(gt), (
        "Ground truth path was not paired with the single document"
    )
    assert call_kwargs["document_path"] == str(doc)


@pytest.mark.unit
def test_single_doc_no_gt_is_still_allowed(runner, mock_idp_client, tmp_path):
    """No -g provided → discovery runs without ground truth (unchanged behavior)."""
    from idp_cli.cli import discover

    (doc,) = _create_files(tmp_path, ["form.pdf"])

    result = runner.invoke(discover, ["-d", str(doc)])

    assert result.exit_code == 0, result.output
    call_kwargs = mock_idp_client.discovery.run.call_args.kwargs
    assert call_kwargs["ground_truth_path"] is None


@pytest.mark.unit
def test_batch_mode_unmatched_gt_exits_nonzero(runner, mock_idp_client, tmp_path):
    """Batch mode with an unmatched -g file must exit 1 (not silently skip)."""
    from idp_cli.cli import discover

    doc1, doc2 = _create_files(tmp_path, ["doc1.pdf", "doc2.pdf"])
    # Stem is 'result' — matches nothing
    (bad_gt,) = _create_files(tmp_path, ["baseline/doc1/sections/1/result.json"])

    result = runner.invoke(
        discover,
        ["-d", str(doc1), "-d", str(doc2), "-g", str(bad_gt)],
    )

    assert result.exit_code == 1, (
        f"Expected batch-mode unmatched GT to exit 1; got {result.exit_code}.\n"
        f"Output:\n{result.output}"
    )
    # Confirm the error message is clear and mentions the stem issue
    assert "could not be matched" in result.output
    assert "result" in result.output  # the unmatched stem
    # Discovery should NOT have been run — we fail fast before processing
    mock_idp_client.discovery.run.assert_not_called()


@pytest.mark.unit
def test_batch_mode_matched_stems_still_work(runner, mock_idp_client, tmp_path):
    """Regression: stem-matched batch mode keeps working."""
    from idp_cli.cli import discover

    doc1, doc2 = _create_files(tmp_path, ["invoice.pdf", "w2.pdf"])
    gt1, gt2 = _create_files(tmp_path, ["invoice.json", "w2.json"])

    result = runner.invoke(
        discover,
        [
            "-d",
            str(doc1),
            "-d",
            str(doc2),
            "-g",
            str(gt1),
            "-g",
            str(gt2),
        ],
    )

    assert result.exit_code == 0, result.output
    # Both docs should have been paired with their matching GT
    all_calls = mock_idp_client.discovery.run.call_args_list
    assert len(all_calls) == 2
    pairs = {
        call.kwargs["document_path"]: call.kwargs["ground_truth_path"]
        for call in all_calls
    }
    assert pairs[str(doc1)] == str(gt1)
    assert pairs[str(doc2)] == str(gt2)


@pytest.mark.unit
def test_batch_mode_duplicate_gt_stems_exits_nonzero(runner, mock_idp_client, tmp_path):
    """Multiple -g files with the same stem used to silently overwrite each
    other in the gt_map dict. Now we detect it and fail fast."""
    from idp_cli.cli import discover

    doc1, doc2 = _create_files(tmp_path, ["doc1.pdf", "doc2.pdf"])
    # Two GT files both with stem 'result' — classic case from IDP baselines
    gt1, gt2 = _create_files(
        tmp_path,
        [
            "baseline/doc1/sections/1/result.json",
            "baseline/doc2/sections/1/result.json",
        ],
    )

    result = runner.invoke(
        discover,
        [
            "-d",
            str(doc1),
            "-d",
            str(doc2),
            "-g",
            str(gt1),
            "-g",
            str(gt2),
        ],
    )

    assert result.exit_code == 1, (
        f"Expected duplicate GT stems to exit 1; got {result.exit_code}.\n"
        f"Output:\n{result.output}"
    )
    assert "same filename stem" in result.output or "duplicate" in result.output.lower()
    mock_idp_client.discovery.run.assert_not_called()


@pytest.mark.unit
def test_multi_gt_single_doc_requires_stem_match(runner, mock_idp_client, tmp_path):
    """len(documents)==1 but len(gt)>1 → positional pairing is ambiguous, so
    we fall back to stem matching. Unmatched GT still fails."""
    from idp_cli.cli import discover

    (doc,) = _create_files(tmp_path, ["invoice.pdf"])
    gt_matched, gt_unmatched = _create_files(tmp_path, ["invoice.json", "orphan.json"])

    result = runner.invoke(
        discover,
        ["-d", str(doc), "-g", str(gt_matched), "-g", str(gt_unmatched)],
    )

    # orphan.json doesn't match → fatal error
    assert result.exit_code == 1, (
        f"Expected orphan GT to fail; got {result.exit_code}.\n{result.output}"
    )
    assert "could not be matched" in result.output
