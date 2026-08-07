#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Flag DynamoDB filtered `Scan` calls that cannot see all their matches.

A filtered `Scan` is the wrong shape whenever you need *matches* rather than a
sample. DynamoDB applies both `Limit` and the implicit 1MB page size to the
items it **examines**, not to the items that pass `FilterExpression`, so:

    resp = table.scan(FilterExpression=..., Limit=10)   # WRONG
    if resp["Items"]: ...

finds a match only when it happens to fall inside the examined window. The row
count needed to break it is data-dependent and grows over time, so this fails
*silently* and *later* — typically on the longest-lived stack. It has now bitten
this codebase five times, with symptoms as unalike as "configuration appears
empty", "a list view shows fewer rows than exist", and "pipeline hooks stop
firing" (issue #599). In every case the fix was to page.

This check enforces that every `.scan(FilterExpression=...)` call site either:

  * paginates — the enclosing function mentions `LastEvaluatedKey` (the loop may
    live a few lines away, so the check is function-scoped rather than
    expression-scoped); or
  * is explicitly marked as a deliberate bounded sample, with a reason:

        # filtered-scan-ok: sampling one row to detect whether backfill ran

The marker is deliberately verbose and requires prose after the colon, so
silencing the check is a conscious act that leaves a reviewable justification.

Usage:
    python3 scripts/check_filtered_scans.py            # whole repo
    python3 scripts/check_filtered_scans.py path/...   # specific files/dirs

Exit codes:
    0 - no unpaginated filtered scans
    1 - one or more found
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

MARKER = "filtered-scan-ok:"

# Not source we own or gate: build output, vendored trees, virtualenvs. Mirrors
# the spirit of scripts/run_all_tests.py's PRUNE_DIR_MARKERS.
PRUNE_MARKERS = (
    "/.venv/",
    "/node_modules/",
    "/.aws-sam/",
    "/build/lib/",
    "/site-packages/",
    "/.git/",
    "/.pytest_cache/",
    "/scratch/",
    "/__pycache__/",
    # Vendored third-party code, kept byte-for-byte to ease re-sync.
    "/pii-anonymizer/hook/vendor/",
    # Bundled copies of idp_common shipped inside an extension's build context.
    "/idp-data-generator/idp_common_pkg/",
    "/idp-data-generator/bootstrap-processor/",
    # Throwaway fixtures written by this check's own tests (see
    # scripts/sdlc/tests/test_check_filtered_scans.py). Excluded so a
    # whole-repo run cannot trip over another xdist worker's in-flight file.
    "/_tmp_filtered_scan_case_",
)


class Finding(NamedTuple):
    path: str
    line: int
    func: str
    has_limit: bool

    def render(self) -> str:
        why = (
            "bounded by `Limit`, which caps items EXAMINED not MATCHED"
            if self.has_limit
            else "reads only the first 1MB page of examined items"
        )
        return (
            f"  {self.path}:{self.line}  (in {self.func}())\n"
            f"      filtered scan {why}, and the enclosing function never\n"
            f"      references LastEvaluatedKey."
        )


def _is_scan_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "scan"
    )


def _kwarg_names(call: ast.Call) -> set:
    return {kw.arg for kw in call.keywords if kw.arg}


def _enclosing_functions(tree: ast.AST) -> List[ast.AST]:
    """Every function/method body in the module, innermost-first when nested."""
    out: List[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out


def _owner(
    call: ast.Call, funcs: List[ast.AST]
) -> Tuple[Optional[ast.AST], str]:
    """The innermost function containing `call`, plus a display name."""
    best: Optional[ast.AST] = None
    for fn in funcs:
        start = getattr(fn, "lineno", None)
        end = getattr(fn, "end_lineno", None)
        if start is None or end is None:
            continue
        if start <= call.lineno <= end:
            # Innermost wins: prefer the candidate that starts latest.
            if best is None or start > best.lineno:  # type: ignore[attr-defined]
                best = fn
    return best, (best.name if best is not None else "<module>")


_PAGING_KEYS = ("LastEvaluatedKey", "ExclusiveStartKey")


def _paginates(scope: Optional[ast.AST], tree: ast.AST) -> bool:
    """True if `scope` (or the module, for a top-level call) pages the scan.

    Detected by any mention of LastEvaluatedKey / ExclusiveStartKey. This is a
    textual signal rather than control-flow analysis on purpose: the loop shape
    varies (while True, do/while, a helper generator), and a false negative here
    is a nuisance while a false positive is a silent bug.

    Deliberately does NOT accept a boto3 paginator as evidence. A paginator
    pages the call made *through* it (`paginator.paginate(...)`), which is not a
    `table.scan(...)` call at all — so a paginator elsewhere in the function
    says nothing about this scan. `list_users` in src/lambda/user_management is
    exactly that trap: it pages *Cognito* while its DynamoDB scan reads one page.
    """
    target = scope if scope is not None else tree
    for node in ast.walk(target):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in _PAGING_KEYS:
                return True
        if isinstance(node, ast.Attribute) and node.attr in _PAGING_KEYS:
            return True
        if isinstance(node, ast.Name) and node.id in _PAGING_KEYS:
            return True
    return False


def _comment_block_start(lines: List[str], call_lineno: int) -> int:
    """First line of the contiguous comment block directly above `call_lineno`.

    Returns `call_lineno` itself when the preceding line is not a comment. Lets a
    multi-line justification sit above the call, which is where a reviewer would
    naturally write one.
    """
    i = call_lineno - 1  # 1-indexed -> the line above, as a 0-indexed offset
    while i > 0 and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i + 1


def _marked_lines(source: str) -> set:
    """Line numbers carrying a `filtered-scan-ok:` marker with a reason."""
    marked = set()
    for i, line in enumerate(source.splitlines(), start=1):
        idx = line.find(MARKER)
        if idx == -1:
            continue
        reason = line[idx + len(MARKER) :].strip()
        if reason:
            marked.add(i)
    return marked


def check_file(path: Path) -> List[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    marked = _marked_lines(source)
    if not marked and "scan" not in source:
        return []

    lines = source.splitlines()
    funcs = _enclosing_functions(tree)
    rel = path.relative_to(REPO_ROOT).as_posix()
    findings: List[Finding] = []

    for node in ast.walk(tree):
        if not _is_scan_call(node):
            continue
        kwargs = _kwarg_names(node)
        if "FilterExpression" not in kwargs:
            continue
        # A marker may sit anywhere inside the call expression, or in the comment
        # block immediately preceding it. Justifications are usually a sentence
        # or two of prose, so scan back over contiguous comment/blank lines
        # rather than a fixed one-line lookbehind.
        span = set(range(_comment_block_start(lines, node.lineno), (node.end_lineno or node.lineno) + 1))
        if span & marked:
            continue
        scope, name = _owner(node, funcs)
        if _paginates(scope, tree):
            continue
        findings.append(Finding(rel, node.lineno, name, "Limit" in kwargs))

    return findings


def iter_python_files(targets: List[str]) -> List[Path]:
    roots = [Path(t) for t in targets] if targets else [REPO_ROOT]
    files: List[Path] = []
    for root in roots:
        root = root if root.is_absolute() else (REPO_ROOT / root)
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        for path in root.rglob("*.py"):
            posix = "/" + path.as_posix().replace(REPO_ROOT.as_posix() + "/", "")
            if any(m in posix for m in PRUNE_MARKERS):
                continue
            files.append(path)
    return sorted(set(files))


def main(argv: List[str]) -> int:
    files = iter_python_files(argv)
    findings: List[Finding] = []
    for path in files:
        findings.extend(check_file(path))

    if not findings:
        print(f"✅ No unpaginated filtered DynamoDB scans ({len(files)} files checked)")
        return 0

    print(
        f"❌ Found {len(findings)} filtered DynamoDB scan(s) that cannot see all "
        "their matches:\n"
    )
    for f in findings:
        print(f.render())
    print(
        "\nDynamoDB applies `Limit` and the 1MB page size to the items EXAMINED,"
        "\nnot the items matching FilterExpression — so these find a match only"
        "\nwhen it lands in the examined window. This breaks silently as data"
        "\ngrows (see issue #599). Either page:"
        "\n"
        "\n    kwargs = {\"FilterExpression\": ..., \"ProjectionExpression\": ...}"
        "\n    while True:"
        "\n        resp = table.scan(**kwargs)"
        "\n        for item in resp.get(\"Items\") or []:"
        "\n            return item          # first match wins"
        "\n        last = resp.get(\"LastEvaluatedKey\")"
        "\n        if not last:"
        "\n            return None"
        "\n        kwargs[\"ExclusiveStartKey\"] = last"
        "\n"
        "\n...or, if a bounded sample is genuinely what you want, say so and why:"
        "\n"
        f"\n    # {MARKER} sampling one row to detect whether backfill ran"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
