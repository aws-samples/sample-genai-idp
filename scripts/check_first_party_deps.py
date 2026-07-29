#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Verify first-party packages were installed from source, not from public PyPI.

Why this exists
---------------
Several packages in this repo depend on their siblings by bare name — e.g.
``idp_cli_pkg`` requires ``"idp-sdk"`` and ``idp_sdk`` requires ``"idp_common"``.
Those packages are first-party: they live in ``lib/`` and are NOT published to
PyPI. The names ARE registered on public PyPI by a third party.

That combination is a dependency-confusion hazard. If the packages are installed
one ``pip install`` at a time, pip resolves a sibling that is not yet installed
from public PyPI and silently installs the squatted package instead of the local
one. The failure is quiet: the import succeeds, but the module is a stub, so the
real breakage surfaces much later as a confusing, unrelated error.

How the check works
-------------------
PEP 610: pip records a ``direct_url.json`` in the ``.dist-info`` of any package
installed from a local path or a VCS URL, and records NOTHING for a package
resolved from an index (PyPI). So for these first-party names:

  * ``direct_url.json`` present, ``file://``      -> local checkout          OK
  * ``direct_url.json`` present, trusted git repo -> official source         OK
  * ``direct_url.json`` absent                    -> came from an INDEX    FAIL

This works for editable and non-editable installs alike, which a
path-based check cannot do (a non-editable local install lands in
site-packages, indistinguishable by path from a PyPI install).

Run after install (``make setup`` / ``make setup-venv`` do) and in CI.
Exit codes: 0 = all good, 1 = something is missing or came from an index.
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, distribution

# Distribution names that must never be satisfied from a package index.
FIRST_PARTY = [
    "idp_common",
    "idp-sdk",
    "idp-cli",
    "idp_feature_sdk",
]

# Git hosts/repos that legitimately serve this source (installs that track the
# public accelerator repo are fine — they are the same first-party code).
TRUSTED_URL_FRAGMENTS = (
    "accelerated-intelligent-document-processing-on-aws",
    "genaiic-idp-accelerator",
)


def _direct_url(dist_name: str) -> dict | None:
    """Return the parsed PEP 610 direct_url.json, or None if absent."""
    dist = distribution(dist_name)
    try:
        raw = dist.read_text("direct_url.json")
    except Exception:  # noqa: BLE001 - treat unreadable metadata as absent
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _classify(name: str) -> tuple[bool, str]:
    """Return (ok, human-readable detail) for one distribution."""
    try:
        info = _direct_url(name)
    except PackageNotFoundError:
        return False, "NOT INSTALLED"

    if info is None:
        return False, (
            "installed from a package INDEX (no PEP 610 direct_url.json).\n"
            "      This name is squatted on public PyPI — it is almost certainly "
            "the wrong package."
        )

    url = info.get("url", "")

    if url.startswith("file://"):
        editable = bool(info.get("dir_info", {}).get("editable"))
        kind = "editable local" if editable else "local"
        return True, f"{kind} -> {url}"

    if "vcs_info" in info:
        if any(frag in url for frag in TRUSTED_URL_FRAGMENTS):
            commit = info["vcs_info"].get("commit_id", "")[:12]
            return True, f"git -> {url}@{commit}"
        return False, f"installed from an UNTRUSTED VCS URL -> {url}"

    return False, f"installed from an unrecognized source -> {url or '(unknown)'}"


def main() -> int:
    failures: list[str] = []

    for name in FIRST_PARTY:
        ok, detail = _classify(name)
        if ok:
            print(f"  ✓ {name}: {detail}")
        else:
            failures.append(f"{name}: {detail}")

    if failures:
        print(
            "\nERROR: first-party dependency check FAILED.\n\n"
            "One or more first-party packages did not come from source. The likely\n"
            "cause is dependency confusion: pip resolved a bare requirement (e.g.\n"
            "'idp-sdk' or 'idp_common') from public PyPI, where those names are\n"
            "squatted by a third party.\n\n"
            "Details:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  ✗ {failure}", file=sys.stderr)
        print(
            "\nTo fix, reinstall ALL first-party packages in ONE pip invocation so\n"
            "pip resolves the sibling names from the local checkout:\n\n"
            "  pip uninstall -y idp_common idp-sdk idp-cli idp_feature_sdk\n"
            "  make setup        # or: make setup-venv\n",
            file=sys.stderr,
        )
        return 1

    print("\nAll first-party packages resolved from source (not from an index).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
