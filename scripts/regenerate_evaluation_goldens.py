#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Regenerate evaluation golden fixtures against the installed stickler-eval.

Reads every ``*.input.json`` in
``lib/idp_common_pkg/tests/unit/evaluation/fixtures/`` and writes the
corresponding ``section_goldens/<name>.golden.json`` (or
``doc_split_goldens/<name>.golden.json`` for the doc-split fixture).

Run whenever a scoring change is intentional. Review the resulting diff before
committing — an unexpected golden change is a regression.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "lib" / "idp_common_pkg"
FIXTURE_DIR = PKG_ROOT / "tests" / "unit" / "evaluation" / "fixtures"

# ``_section_result_to_dict`` below imports the golden helper from
# ``tests.unit.evaluation.*``, which is only importable with the package root on
# sys.path. Add it here so the documented invocation
# (``python scripts/regenerate_evaluation_goldens.py``) works from any cwd —
# this script is the sanctioned way to update goldens, so it must not itself
# require a PYTHONPATH incantation to run.
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


def _sanitize(obj):
    """Convert non-JSON-serializable stickler types (numpy, Pydantic) to native."""
    from idp_common.evaluation.service import _convert_numpy_types

    return _convert_numpy_types(obj)


def _section_result_to_dict(result):
    """Convert SectionEvaluationResult to the same dict shape used by the test.

    Kept in lockstep with the same-named helper in
    ``lib/idp_common_pkg/tests/unit/evaluation/test_golden_fixture_stickler.py``.
    """
    from tests.unit.evaluation.test_golden_fixture_stickler import (  # type: ignore[import-not-found]
        _section_result_to_dict as _impl,
    )

    return _impl(result)


def _regenerate_section_golden(input_path: Path) -> None:
    """Regenerate a section-evaluation golden from its .input.json spec."""
    from idp_common.evaluation.service import EvaluationService
    from idp_common.models import Section

    spec = json.loads(input_path.read_text())
    svc = EvaluationService(region="us-east-1", config=spec["config"], max_workers=1)
    section = Section(
        section_id=spec["section_id"],
        classification=spec["classification"],
        page_ids=spec["page_ids"],
    )
    result = svc.evaluate_section(section, spec["expected"], spec["actual"])
    golden = _section_result_to_dict(result)

    out_dir = input_path.parent / "section_goldens"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{input_path.stem.rsplit('.', 1)[0]}.golden.json"
    out_path.write_text(
        json.dumps(golden, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(f"  wrote {out_path.relative_to(REPO_ROOT)}")


def _regenerate_doc_split_golden(input_path: Path) -> None:
    """Regenerate the doc-split-metrics golden from its .input.json spec."""
    from stickler.doc_split.doc_split_classification_metrics import (
        DocSplitClassificationMetrics,
    )

    spec = json.loads(input_path.read_text())
    calc = DocSplitClassificationMetrics()

    # Upstream accepts dicts directly; the fork wrapped Section objects. Use dicts
    # so the golden is stable across R8 (fork deletion) — the R8 swap must not
    # perturb the golden.
    for section in spec["ground_truth_sections"]:
        section_id = section.get("section_id", f"gt_{len(calc.sections_gt)}")
        doc_class = calc._get_document_class(section)
        page_indices = calc._get_page_indices(section)
        calc.sections_gt.append(
            {
                "section_id": section_id,
                "document_class": doc_class,
                "page_indices": page_indices,
            }
        )
        for page_idx in page_indices:
            calc.page_classifications_gt[page_idx] = doc_class

    for section in spec["predicted_sections"]:
        section_id = section.get("section_id", f"pred_{len(calc.sections_pred)}")
        doc_class = calc._get_document_class(section)
        page_indices = calc._get_page_indices(section)
        calc.sections_pred.append(
            {
                "section_id": section_id,
                "document_class": doc_class,
                "page_indices": page_indices,
            }
        )
        for page_idx in page_indices:
            calc.page_classifications_pred[page_idx] = doc_class

    metrics = calc.calculate_all_metrics()
    golden = _sanitize(metrics)

    out_dir = input_path.parent / "doc_split_goldens"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{input_path.stem.rsplit('.', 1)[0]}.golden.json"
    out_path.write_text(
        json.dumps(golden, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(f"  wrote {out_path.relative_to(REPO_ROOT)}")


def main() -> int:
    if not FIXTURE_DIR.is_dir():
        print(f"ERROR: fixture dir not found: {FIXTURE_DIR}", file=sys.stderr)
        return 1

    inputs = sorted(FIXTURE_DIR.glob("*.input.json"))
    if not inputs:
        print(f"ERROR: no .input.json fixtures under {FIXTURE_DIR}", file=sys.stderr)
        return 1

    print(f"Regenerating {len(inputs)} evaluation goldens...")
    for input_path in inputs:
        name = input_path.stem.rsplit(".", 1)[0]
        print(f"- {name}")
        if name == "doc_split_metrics":
            _regenerate_doc_split_golden(input_path)
        else:
            _regenerate_section_golden(input_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
