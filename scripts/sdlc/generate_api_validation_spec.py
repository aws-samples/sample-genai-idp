#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Build-time generator for the HTTP API dispatcher's argument-validation spec.

WHY
---
AppSync validated every operation's input arguments against ``schema.graphql``
for free (unknown args, missing non-null args, wrong scalar types, bad enum
values). The HTTP API dispatcher that replaces AppSync has no such gate, so a
malformed request would previously flow straight through to a resolver Lambda.

This script precomputes a compact JSON description of each Query/Mutation
field's argument signature (plus enum value sets and input-object shapes) so the
dispatcher can restore that validation at runtime WITHOUT a graphql-core
dependency (the Lambda bundle is stdlib-only). The generated JSON is committed
next to the dispatcher (in its CodeUri, so SAM bundles it automatically) and a
drift guard (``--check``) keeps it in sync with schema.graphql in CI.

APPROACH
--------
Reuse the battle-tested regex parser in ``scan_api_rbac.py`` (``_extract_type_body``
/ ``_iter_fields``) to walk the ``type Query`` / ``type Mutation`` bodies, then
parse each field's argument list into ``{name, type, is_list, non_null,
elem_non_null}`` records. Enum blocks become ``{EnumName: [values]}`` and input
object blocks are parsed one level deep (their nested input args are recorded but
validated only shallowly — "must be an object" — at runtime in v1).

USAGE
-----
  python3 scripts/sdlc/generate_api_validation_spec.py           # (re)write the JSON
  python3 scripts/sdlc/generate_api_validation_spec.py --check   # CI drift guard

EXIT CODES
----------
  0  wrote the spec (default), or --check found no drift
  1  --check found drift (regenerated spec differs from the committed file)
  2  usage / file-not-found error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Reuse the schema parser rather than duplicating it (single source of truth for
# how Query/Mutation field bodies are extracted).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_api_rbac import _extract_type_body, _iter_fields  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "nested" / "api-resolvers" / "src" / "api" / "schema.graphql"
SPEC_OUT = (
    REPO
    / "nested"
    / "api-resolvers"
    / "src"
    / "lambda"
    / "http_api_dispatcher"
    / "api_validation_spec.json"
)


def _read(path: Path) -> str:
    if not path.exists():
        print(f"ERROR: expected file not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path.read_text()


# --- schema sanitization -----------------------------------------------------


def _strip_descriptions_and_comments(text: str) -> str:
    """Remove GraphQL descriptions and comments before any structural parsing.

    The regex field/arg parsers below (and scan_api_rbac's `_iter_fields`) look
    for ``name: Type`` patterns. A GraphQL **block description** (``\"\"\"…\"\"\"``)
    or a ``#`` comment can contain a line like ``Idempotent: re-applying…`` — a
    prose colon that the parsers would otherwise mistake for a field or argument
    (this produced a phantom ``Idempotent`` field in the spec, and — worse — a
    description/comment of the form ``word: Type!`` sitting INSIDE an argument
    list or ``input`` block would inject a spurious, possibly-required arg that
    would then 400 every call to that operation).

    We neutralize descriptions/comments while PRESERVING line structure (replace
    their content with spaces, keep newlines) so downstream line- and
    offset-based scans are unaffected:
      * ``\"\"\"…\"\"\"`` block strings (may span lines),
      * ``"…"`` single-line string descriptions,
      * ``#`` line comments (to end of line).
    String/enum VALUES in this schema are not affected: GraphQL enum values are
    bare identifiers, and no default-value string literals appear in Query/
    Mutation argument lists.
    """

    def _blank(m: "re.Match[str]") -> str:
        # Keep newlines so line numbers / multi-line arg scans stay aligned;
        # replace everything else with spaces.
        return re.sub(r"[^\n]", " ", m.group(0))

    # Order matters: block strings first (greedy over newlines), then line
    # comments, then remaining single-line double-quoted descriptions.
    text = re.sub(r'"""[\s\S]*?"""', _blank, text)
    text = re.sub(r"#[^\n]*", _blank, text)
    text = re.sub(r'"[^"\n]*"', _blank, text)
    return text


# --- type-expression + argument-list parsing ---------------------------------


def _parse_type_expr(expr: str) -> dict:
    """Parse a GraphQL type reference into a flat record.

    Handles the shapes that appear in this schema: ``Type``, ``Type!``,
    ``[Type]``, ``[Type!]``, ``[Type]!``, ``[Type!]!``. Returns
    ``{type, is_list, non_null, elem_non_null}`` where ``type`` is the base
    (named) type. Nested lists (``[[Type]]``) do not occur here and are not
    modeled.
    """
    s = expr.strip()
    is_list = False
    non_null = False
    elem_non_null = False
    if s.startswith("["):
        is_list = True
        # outer non-null applies AFTER the closing bracket: e.g. "[String!]!"
        close = s.rfind("]")
        outer = s[close + 1 :].strip()
        non_null = outer.startswith("!")
        inner = s[1:close].strip()
        elem_non_null = inner.endswith("!")
        base = inner.rstrip("!").strip()
    else:
        non_null = s.endswith("!")
        base = s.rstrip("!").strip()
    return {
        "type": base,
        "is_list": is_list,
        "non_null": non_null,
        "elem_non_null": elem_non_null,
    }


def _extract_arg_paren(defn: str) -> str | None:
    """Return the argument-list body of a field definition, or None if the field
    takes no arguments.

    The argument parentheses immediately follow the field name; directive
    parentheses (e.g. ``@aws_cognito_user_pools(cognito_groups: [...])``) come
    AFTER the return type and must not be mistaken for the arg list. We therefore
    only treat a ``(`` as the arg list when it is the first non-whitespace
    character after the field name.
    """
    m = re.match(r"\s*[a-zA-Z]\w*", defn)
    if not m:
        return None
    i = m.end()
    # skip whitespace between name and the next significant char
    while i < len(defn) and defn[i] in " \t\r\n":
        i += 1
    if i >= len(defn) or defn[i] != "(":
        return None  # next char is ':' (return type) — no args
    # balanced-paren scan from this opening paren
    depth = 0
    start = i
    while i < len(defn):
        c = defn[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return defn[start + 1 : i]
        i += 1
    return None  # unbalanced (shouldn't happen for valid SDL)


def _parse_args(arg_body: str) -> list[dict]:
    """Parse an argument-list body into an ordered list of arg records.

    GraphQL makes commas optional, so args may be separated by newlines only.
    We match ``name: TypeExpr`` pairs directly. No field in this schema has arg
    default values or arg-level directives, so the type expression runs to the
    next arg name / end.
    """
    args: list[dict] = []
    # name : <type expr up to the next 'name:' or end>
    for m in re.finditer(
        r"([a-zA-Z]\w*)\s*:\s*(\[?\s*[a-zA-Z]\w*\s*!?\s*\]?\s*!?)",
        arg_body,
    ):
        name = m.group(1)
        parsed = _parse_type_expr(m.group(2))
        args.append({"name": name, **parsed})
    return args


def _iter_named_blocks(text: str, keyword: str):
    """Yield (name, body) for each top-level ``<keyword> Name ... { ... }`` block
    (used for ``enum`` and ``input`` definitions). Brace-matched so nested braces
    (none occur here, but be safe) don't confuse the scan.
    """
    for m in re.finditer(
        rf"\b{keyword}\s+([A-Za-z]\w*)[ \t]*(?:@[\w]+(?:\([^)]*\))?[ \t]*)*\{{",
        text,
    ):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        yield name, text[start : i - 1]


def _parse_enum_values(body: str) -> list[str]:
    values: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith('"'):
            continue
        m = re.match(r"([A-Za-z]\w*)", s)
        if m:
            values.append(m.group(1))
    return values


def build_spec(schema_text: str) -> dict:
    """Build the validation spec dict from schema.graphql text."""
    # Strip descriptions/comments FIRST so a prose ``word: Type`` inside a
    # """…""" block or a # comment can never be misparsed as a field/arg (see
    # _strip_descriptions_and_comments — this removed the phantom `Idempotent`
    # field and closes a latent "description injects a required arg" landmine).
    schema_text = _strip_descriptions_and_comments(schema_text)
    fields: dict[str, dict] = {}
    for type_name in ("Query", "Mutation"):
        body = _extract_type_body(schema_text, type_name)
        if body is None:
            continue
        for field, defn in _iter_fields(body):
            arg_body = _extract_arg_paren(defn)
            args = _parse_args(arg_body) if arg_body is not None else []
            fields[field] = {"args": args}

    enums: dict[str, list[str]] = {}
    for name, body in _iter_named_blocks(schema_text, "enum"):
        enums[name] = _parse_enum_values(body)

    inputs: dict[str, list[dict]] = {}
    for name, body in _iter_named_blocks(schema_text, "input"):
        # Input fields share the "name: TypeExpr" grammar with args.
        inputs[name] = _parse_args(body)

    return {"fields": fields, "enums": enums, "inputs": inputs}


def _dump(spec: dict) -> str:
    """Deterministic serialization (stable key order, trailing newline)."""
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate the HTTP API dispatcher argument-validation spec."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and fail (exit 1) if it differs from the "
        "committed api_validation_spec.json (CI drift guard)",
    )
    args = ap.parse_args()

    schema_text = _read(SCHEMA)
    spec = build_spec(schema_text)
    rendered = _dump(spec)

    if args.check:
        if not SPEC_OUT.exists():
            print(
                f"ERROR: committed spec missing: {SPEC_OUT}\n"
                "Run: python3 scripts/sdlc/generate_api_validation_spec.py",
                file=sys.stderr,
            )
            return 1
        current = SPEC_OUT.read_text()
        if current != rendered:
            print(
                "DRIFT: api_validation_spec.json is out of date with "
                "schema.graphql.\n"
                "Regenerate: python3 scripts/sdlc/generate_api_validation_spec.py",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK: {SPEC_OUT.name} matches schema.graphql "
            f"({len(spec['fields'])} fields, {len(spec['enums'])} enums, "
            f"{len(spec['inputs'])} input types)"
        )
        return 0

    SPEC_OUT.write_text(rendered)
    print(
        f"Wrote {SPEC_OUT} "
        f"({len(spec['fields'])} fields, {len(spec['enums'])} enums, "
        f"{len(spec['inputs'])} input types)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
