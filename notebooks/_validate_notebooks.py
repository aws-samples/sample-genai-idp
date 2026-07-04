#!/usr/bin/env python3
"""Static + import validation harness for the example/misc notebooks.

Full end-to-end execution of these notebooks is not feasible in CI (they call
live Bedrock/Textract/S3 and chain state across step0->step7 against a deployed
stack). This harness instead catches the failure class the v0.6 extraction /
assessment refactor could introduce:

  1. references to symbols/modules that were REMOVED (granular assessment) or
     config attributes that moved (assessment.* -> extraction.confidence.*),
  2. import statements that no longer resolve, exercised against a real Python
     env with idp_common installed.

Run:  python3 notebooks/_validate_notebooks.py
Exit code is nonzero if any notebook has a hard problem. Notebooks in
KNOWN_DEPRECATED reference removed symbols on purpose (they carry an in-notebook
deprecation banner); their known failures are reported as warnings, so a clean
tree exits 0 and only *new* API drift fails the run.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path

NB_ROOT = Path(__file__).resolve().parent

# Notebooks intentionally kept for historical reference that still reference
# removed symbols on purpose (they carry an in-notebook deprecation banner
# pointing at the supported replacement). Their known failures are demoted to
# warnings so a clean tree exits 0 and any *new* drift still surfaces as HARD.
KNOWN_DEPRECATED = {
    "misc/criteria-validation-test.ipynb",
    "misc/e2e-holistic-packet-classification-summarization.ipynb",
}

# --- Patterns that would be HARD failures after the v0.6 refactor -----------
# Removed Python symbols / modules.
REMOVED_IMPORT_RE = re.compile(
    r"(from\s+idp_common\.assessment\.granular_service\s+import"
    r"|import\s+idp_common\.assessment\.granular_service"
    r"|(?<![\w.])GranularAssessmentService)"
)
# Typed attribute access that no longer exists on IDPConfig.
# We flag `.assessment.` chained access on a config/IDPConfig-looking object,
# but NOT dict access like CONFIG['assessment'] (still valid: dicts are migrated
# on construction) and NOT the .assessment string keys.
REMOVED_ATTR_RE = re.compile(
    r"\b(config|cfg|idp_config|idpconfig)\b\s*\.\s*assessment\b", re.IGNORECASE
)


def iter_code(nb_path: Path):
    """Yield (cell_index, source) for each code cell."""
    data = json.loads(nb_path.read_text())
    for i, cell in enumerate(data.get("cells", [])):
        if cell.get("cell_type") == "code":
            yield i, "".join(cell.get("source", []))


def extract_imports(source: str) -> list[str]:
    """Return top-level `import idp_common...` statements from a code cell.

    Strips Jupyter magics/shell lines (`%`, `!`) so ast.parse succeeds.
    """
    lines = [
        ln
        for ln in source.splitlines()
        if not ln.lstrip().startswith(("%", "!"))
    ]
    cleaned = "\n".join(lines)
    imports: list[str] = []
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("idp_common"):
                names = ", ".join(a.name for a in node.names)
                imports.append(f"from {mod} import {names}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("idp_common"):
                    imports.append(f"import {a.name}")
    return imports


def check_import_resolves(stmt: str) -> str | None:
    """Try to resolve an import statement. Return an error string or None."""
    m = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", stmt)
    if m:
        mod, names = m.group(1), m.group(2)
        try:
            module = importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            return f"module '{mod}' import error: {type(e).__name__}: {e}"
        for name in [n.strip() for n in names.split(",")]:
            if name == "*":
                continue
            if not hasattr(module, name):
                # sub-module import (from a.b import c where c is a module)
                try:
                    importlib.import_module(f"{mod}.{name}")
                except Exception:
                    return f"'{name}' not found in '{mod}'"
        return None
    m = re.match(r"import\s+([\w.]+)", stmt)
    if m:
        mod = m.group(1)
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            return f"module '{mod}' import error: {type(e).__name__}: {e}"
        return None
    return None


def main() -> int:
    notebooks = sorted(NB_ROOT.rglob("*.ipynb"))
    skip = {".ipynb_checkpoints", ".aws-sam"}
    notebooks = [p for p in notebooks if not skip.intersection(p.parts)]

    hard_failures: list[str] = []
    warnings: list[str] = []
    checked_imports: dict[str, list[str]] = {}

    # Track which import statements come *only* from deprecated notebooks, so a
    # failure to resolve them is demoted to a warning rather than a HARD.
    deprecated_only_imports: dict[str, bool] = {}

    for nb in notebooks:
        rel = nb.relative_to(NB_ROOT)
        is_deprecated = rel.as_posix() in KNOWN_DEPRECATED
        for idx, src in iter_code(nb):
            if REMOVED_IMPORT_RE.search(src):
                # A logger-name STRING or metering-key string is not a hard
                # failure; a real import/usage is. Distinguish.
                for ln in src.splitlines():
                    if REMOVED_IMPORT_RE.search(ln):
                        stripped = ln.strip()
                        is_string_only = (
                            "getLogger" in ln
                            or re.search(r"['\"][^'\"]*granular_service", ln)
                            or re.search(r"['\"][^'\"]*GranularAssessment", ln)
                        )
                        if is_string_only:
                            tag = "WARN(string-ref)"
                        elif is_deprecated:
                            tag = "WARN(deprecated-nb)"
                        else:
                            tag = "HARD"
                        msg = f"[{tag}] {rel} cell {idx}: {stripped}"
                        bucket = warnings if tag != "HARD" else hard_failures
                        bucket.append(msg)
            if REMOVED_ATTR_RE.search(src):
                for ln in src.splitlines():
                    if REMOVED_ATTR_RE.search(ln):
                        if is_deprecated:
                            warnings.append(
                                f"[WARN(deprecated-nb)] {rel} cell {idx}: typed "
                                f".assessment attr access -> {ln.strip()}"
                            )
                        else:
                            hard_failures.append(
                                f"[HARD] {rel} cell {idx}: typed .assessment attr "
                                f"access -> {ln.strip()}"
                            )
            for stmt in extract_imports(src):
                checked_imports.setdefault(stmt, []).append(str(rel))
                # An import stays "deprecated-only" until a non-deprecated
                # notebook is seen using it.
                prev = deprecated_only_imports.get(stmt, True)
                deprecated_only_imports[stmt] = prev and is_deprecated

    # Resolve every unique idp_common import once.
    import_errors: list[str] = []
    for stmt in sorted(checked_imports):
        err = check_import_resolves(stmt)
        if err:
            where = ", ".join(sorted(set(checked_imports[stmt])))
            if deprecated_only_imports.get(stmt, False):
                # Only deprecated notebooks reference this removed symbol; the
                # banner in those notebooks documents it. Warn, don't fail.
                warnings.append(
                    f"[WARN(deprecated-nb)] import fails: {stmt}  -->  {err}\n"
                    f"         used only in: {where}"
                )
            else:
                import_errors.append(
                    f"[HARD] import fails: {stmt}  -->  {err}\n"
                    f"         used in: {where}"
                )

    print(f"Scanned {len(notebooks)} notebooks; "
          f"{len(checked_imports)} unique idp_common imports.\n")

    if warnings:
        print("WARNINGS (string references, not breakage):")
        for w in warnings:
            print("  " + w)
        print()

    all_hard = hard_failures + import_errors
    if all_hard:
        print("HARD FAILURES:")
        for f in all_hard:
            print("  " + f)
        return 1

    print("OK: no removed symbols referenced, all idp_common imports resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
