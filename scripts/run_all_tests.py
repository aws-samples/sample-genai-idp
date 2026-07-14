# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Discover and run every Python test suite in the repo, one root at a time.

Why not a single ``pytest`` from the repo root? Several packages ship their own
``tests/conftest.py``; pytest imports them all as the module ``tests.conftest``
and aborts with ``ImportPathMismatchError`` / duplicate-plugin errors. Each
package/Lambda also has its own mini-environment (relative imports, per-dir
conftest, ``sys.modules`` shims). So each test *root* must run as a SEPARATE
pytest invocation.

The maintenance hazard with a hand-written list of roots (the old ``make test``)
is that a brand-new test directory is silently never run. This script removes
that hazard: it DISCOVERS every directory containing ``test_*.py`` and checks it
against two explicit registries — ``RUN_ROOTS`` (run in the gate) and
``QUARANTINE`` (known-excluded, each with a reason). A directory in NEITHER list
is a hard error, so adding tests in a new location forces a conscious decision
here.

Usage:
    python scripts/run_all_tests.py            # run the gate (unit-level suites)
    python scripts/run_all_tests.py --list     # print the plan, run nothing
    python scripts/run_all_tests.py --integration   # run only integration suites
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are NOT source test roots (build output, deps, vendored copies).
PRUNE_DIR_MARKERS = (
    "/.venv/",
    "/node_modules/",
    "/.aws-sam/",
    "/build/lib/",
    "/site-packages/",
    "/.git/",
    "/.pytest_cache/",
    # idp_common ships fixture-style helper "tests" that are not a suite.
    "/idp_common/agents/testing/",
)

# --- Registry 1: roots RUN in the fast (non-integration) gate -----------------
# Each entry is a path relative to the repo root. They are run as independent
# `pytest -m "not integration" <root>` invocations. Verified green headless.
RUN_ROOTS = [
    "lib/idp_common_pkg/tests",
    "lib/idp_cli_pkg/tests",
    "lib/idp_sdk/tests",
    "lib/idp_feature_sdk/tests",
    "feature-platform/main-stack-extensions/tests",
    "feature-platform/feature-template/feature-api/tests",
    "feature-platform/feature-template/ui-deployer/tests",
    "feature-platform/sample-feature/feature-api/tests",
    "feature-platform/sample-feature/ui-deployer/tests",
    "feature-platform/sample-health-insurance-review/feature-api/tests",
    "feature-platform/sample-health-insurance-review/hook/tests",
    "feature-platform/sample-health-insurance-review/ui-deployer/tests",
    "nested/api-resolvers/src/lambda/get_file_contents_resolver",
    "nested/api-resolvers/src/lambda/get_sample_document_resolver",
    "nested/api-resolvers/src/lambda/get_stepfunction_execution_resolver",
    "nested/api-resolvers/src/lambda/list_agent_chat_sessions_resolver/tests",
    "nested/api-resolvers/src/lambda/send_chat_document_message_resolver/tests",
    "nested/api-resolvers/src/lambda/upload_resolver",
    "nested/bedrockkb/src/start_ingestion_job_custom_resource",
    "samples/lambda-hook-inference/GENAIIDP-mistral-ocr-hook",
    "src/lambda/api_handler",
    "src/lambda/batch_pre_processor",
    "src/lambda/calculate_capacity",
    "src/lambda/chat_stream_processor/tests",
    "src/lambda/chat_with_document_processor/tests",
    "src/lambda/circuit_breaker_manager",
    "src/lambda/complete_section_review",
    "src/lambda/external_idp_group_mapping",
    "src/lambda/job_tracker",
    "src/lambda/queue_processor",
    "src/lambda/save_reporting_data",
    "src/lambda/version_check_resolver",
    "src/lambda/workflow_tracker",
    "config_library",
]

# --- Registry 2: roots explicitly EXCLUDED, each with a reason ----------------
# These are known-not-runnable in the shared gate. Kept here (not silently
# dropped) so the "unclassified dir" check stays meaningful and the reason is
# discoverable. Revisit periodically.
QUARANTINE = {
    "scripts": (
        "Not a test suite — scripts/test_api_rbac.py is the live RBAC harness "
        "(run via `make api-test`); pytest mis-collects its test_email() helper."
    ),
    "src/lambda/ocr_benchmark_deployer": (
        "Requires huggingface_hub, which is not a test dependency."
    ),
    "nested/bedrockkb/src/s3_vectors_manager": (
        "Requires the Lambda-runtime-only 'cfnresponse' module."
    ),
    "samples/lambda-hook-inference/GENAIIDP-chandra-ocr-hook": (
        "test_local.py is a manual local-run script; collects zero pytest tests."
    ),
    # Vendored/internal helper trees that contain test_*.py but are not suites.
    "lib/idp_sdk/idp_sdk/_core": (
        "Source tree, not a test root (contains helper modules named test_*)."
    ),
}


def discover_test_roots() -> set[str]:
    """Return the set of repo-relative dirs that directly contain a test_*.py."""
    roots: set[str] = set()
    for path in REPO_ROOT.rglob("test_*.py"):
        posix = "/" + path.as_posix().replace(REPO_ROOT.as_posix() + "/", "")
        if any(marker in posix for marker in PRUNE_DIR_MARKERS):
            continue
        rel_dir = path.parent.relative_to(REPO_ROOT).as_posix()
        roots.add(rel_dir)
    return roots


def classify(discovered: set[str]) -> tuple[list[str], list[str]]:
    """Split discovered roots against the registries; error on any unknown.

    A discovered dir counts as "known" if it equals, or is nested under, a
    registered RUN or QUARANTINE entry (some roots register a parent ``tests``
    dir that owns nested subdirs).
    """
    known_prefixes = [r.rstrip("/") for r in (*RUN_ROOTS, *QUARANTINE)]

    def is_known(d: str) -> bool:
        return any(d == k or d.startswith(k + "/") for k in known_prefixes)

    unknown = sorted(d for d in discovered if not is_known(d))
    if unknown:
        lines = "\n".join(f"  - {d}" for d in unknown)
        raise SystemExit(
            "ERROR: found test directories not registered in "
            f"scripts/run_all_tests.py:\n{lines}\n\n"
            "Add each to RUN_ROOTS (if it should run in the gate) or to "
            "QUARANTINE with a reason. This guard exists so new tests are never "
            "silently skipped."
        )
    # Only run registered roots that still exist on disk.
    run = [r for r in RUN_ROOTS if (REPO_ROOT / r).exists()]
    quarantined = sorted(QUARANTINE)
    return run, quarantined


def run_gate(roots: list[str], integration: bool) -> int:
    marker = "integration" if integration else "not integration"
    python = os.environ.get("PYTHON") or sys.executable
    failures: list[str] = []
    for root in roots:
        print(f"\n=== pytest -m '{marker}' {root} ===", flush=True)
        result = subprocess.run(
            [
                python,
                "-m",
                "pytest",
                "-m",
                marker,
                "-q",
                "-p",
                "no:cacheprovider",
                root,
            ],
            cwd=REPO_ROOT,
        )
        # Exit code 5 == "no tests collected for this marker", which is fine.
        if result.returncode not in (0, 5):
            failures.append(root)
    print("\n" + "=" * 70)
    if failures:
        print(f"❌ {len(failures)} test root(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"✅ All {len(roots)} test roots passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="print the plan and exit (run nothing)"
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="run integration-marked tests instead of the default gate",
    )
    args = parser.parse_args()

    discovered = discover_test_roots()
    run, quarantined = classify(discovered)

    if args.list:
        print(f"RUN ({len(run)} roots):")
        for r in run:
            print(f"  + {r}")
        print(f"\nQUARANTINE ({len(quarantined)} roots):")
        for q in quarantined:
            print(f"  - {q}: {QUARANTINE[q]}")
        return 0

    return run_gate(run, integration=args.integration)


if __name__ == "__main__":
    raise SystemExit(main())
