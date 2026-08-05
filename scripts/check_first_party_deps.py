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
# Keep in sync with FIRST_PARTY_EDITABLES in the Makefile.
FIRST_PARTY = [
    "idp_common",
    "idp-sdk",
    "idp-accelerator-cli",  # console command is still `idp-cli`
    "idp_feature_sdk",
    "idp_mcp_connector",
]

# Distribution names we USED to publish under, mapped to their replacement.
# Renaming a distribution does not uninstall the old one: pip keeps the previous
# dist-info, so `pip list` shows both names pointing at the same source tree. That
# is harmless but confusing, and a stale record could later be satisfied from an
# index. Report it so the user can clean up.
RETIRED_NAMES = {
    "idp-cli": "idp-accelerator-cli",
}

# Git hosts/repos that legitimately serve this source (installs that track the
# public accelerator repo are fine — they are the same first-party code).
TRUSTED_URL_FRAGMENTS = (
    "accelerated-intelligent-document-processing-on-aws",
    "genaiic-idp-accelerator",
)


def _direct_url(dist_name: str) -> dict | None:
    """Return the parsed PEP 610 direct_url.json, or None if absent.

    Raises PackageNotFoundError if the distribution is not installed at all.
    """
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


def _classify(name: str) -> tuple[str, str]:
    """Classify one distribution as "ok", "absent", or "bad", with detail.

    "absent" is deliberately NOT a failure. Installing a subset of the
    first-party packages is legitimate (CI installs only the ones whose suites it
    runs; a Lambda bundle installs one). The security property this script
    enforces is narrower and stricter: *nothing* that IS installed may have come
    from a package index.
    """
    try:
        info = _direct_url(name)
    except PackageNotFoundError:
        return "absent", "not installed (skipped)"

    if info is None:
        return "bad", (
            "installed from a package INDEX (no PEP 610 direct_url.json).\n"
            "      This name is squatted on public PyPI — it is almost certainly "
            "the wrong package."
        )

    url = info.get("url", "")

    if url.startswith("file://"):
        editable = bool(info.get("dir_info", {}).get("editable"))
        kind = "editable local" if editable else "local"
        return "ok", f"{kind} -> {url}"

    if "vcs_info" in info:
        if any(frag in url for frag in TRUSTED_URL_FRAGMENTS):
            commit = info["vcs_info"].get("commit_id", "")[:12]
            return "ok", f"git -> {url}@{commit}"
        return "bad", f"installed from an UNTRUSTED VCS URL -> {url}"

    return "bad", f"installed from an unrecognized source -> {url or '(unknown)'}"


def main() -> int:
    failures: list[str] = []
    checked = 0

    # Report every package first, then the error block — otherwise the stderr
    # failure text interleaves with buffered stdout and reads out of order.
    for name in FIRST_PARTY:
        status, detail = _classify(name)
        if status == "ok":
            checked += 1
            print(f"  ✓ {name}: {detail}")
        elif status == "absent":
            print(f"  - {name}: {detail}")
        else:
            checked += 1
            print(f"  ✗ {name}: see error below")
            failures.append(f"{name}: {detail}")

    # A leftover install under a retired distribution name is not a failure — the
    # code is the same — but it is stale and worth clearing.
    stale = []
    for old, new in RETIRED_NAMES.items():
        try:
            distribution(old)
        except PackageNotFoundError:
            continue
        stale.append((old, new))
        print(f"  ! {old}: retired distribution name (renamed to {new})")

    sys.stdout.flush()

    if stale:
        names = " ".join(old for old, _ in stale)
        print(
            "\nNOTE: a retired distribution name is still installed. Renaming a\n"
            "distribution does not remove the old dist-info, so pip lists both\n"
            f"names for the same source tree. Harmless, but clear it with:\n\n"
            f"  pip uninstall -y {names}\n",
            file=sys.stderr,
        )

    if failures:
        print(
            "\nERROR: first-party dependency check FAILED.\n\n"
            "One or more first-party packages did not come from source. The likely\n"
            "cause is dependency confusion: pip resolved a bare requirement (e.g.\n"
            "'idp-sdk' or 'idp_common') from public PyPI, where those names are\n"
            "squatted by a third party. See docs/dependency-confusion.md.\n\n"
            "Details:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  ✗ {failure}", file=sys.stderr)
        print(
            "\nTo fix, reinstall ALL first-party packages in ONE pip invocation so\n"
            "pip resolves the sibling names from the local checkout:\n\n"
            "  pip uninstall -y idp_common idp-sdk idp-accelerator-cli "
            "idp_feature_sdk idp_mcp_connector\n"
            "  make setup        # or: make setup-venv\n",
            file=sys.stderr,
        )
        return 1

    if checked == 0:
        print(
            "\nWARNING: no first-party packages are installed — nothing to verify.",
            file=sys.stderr,
        )
        return 0

    print(
        f"\nAll {checked} installed first-party package(s) resolved from source "
        "(not from an index)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
