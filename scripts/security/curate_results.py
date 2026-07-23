#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Curate security-test outputs into public-safe, auditable markdown snapshots.

The four security tests (SRT, ZAP DAST, RBAC static, RBAC dynamic) all write
raw reports to gitignored `scratch/`/`.srt/` locations. Those raw reports carry
environment-specific identifiers (AWS account IDs, Cognito pool IDs, API
Gateway hostnames, request IDs, absolute local paths) that must NOT be
committed to a public repo. This script reads those raw reports, strips/redacts
the sensitive bits, and writes curated summaries into

    security/test-results/<version>/

one file per test plus a MANIFEST.md tying the snapshot to a release version,
git SHA, date, and (for live tests) a redacted stack descriptor. See
`security/test-results/README.md` for the process and
`.claude/skills/curate-security-results.md` for the operator runbook.

Design notes:
  * PUBLIC-SAFE BY CONSTRUCTION. We never copy raw report files. We parse them
    and re-emit only fields that are safe to publish, running every emitted
    string through `redact()`. If a new raw field could leak an identifier,
    add it to the redaction patterns rather than passing it through verbatim.
  * IDEMPOTENT per (version). Re-running overwrites the version folder's files.
  * DEGRADES GRACEFULLY. A missing raw report for one test writes a "not run"
    stub for that test rather than aborting the whole snapshot, so a partial
    snapshot is still produced and the gap is visible.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "security" / "test-results"

# ---------------------------------------------------------------------------
# Redaction — the single choke point every emitted string passes through.
# ---------------------------------------------------------------------------

# Ordered list of (compiled pattern, replacement). Applied in sequence, so put
# the most specific patterns first.
_REDACTIONS = [
    # AWS account id (12 digits) — in ARNs, api hostnames, bucket names, etc.
    (re.compile(r"\b\d{12}\b"), "<ACCOUNT_ID>"),
    # API Gateway / execute-api hostnames: <id>.execute-api.<region>.amazonaws.com
    (
        re.compile(r"\b[a-z0-9]{10}\.execute-api\.[a-z0-9-]+\.amazonaws\.com"),
        "<API_HOST>",
    ),
    # Cognito user/identity pool ids: <region>_<alnum> and <region>:<uuid>
    (re.compile(r"\b[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+\b"), "<COGNITO_POOL>"),
    (
        re.compile(
            r"\b[a-z]{2}-[a-z]+-\d:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}"
            r"-[0-9a-f]{4}-[0-9a-f]{12}\b"
        ),
        "<IDENTITY_POOL>",
    ),
    # Generic ARNs.
    (re.compile(r"arn:aws[a-z-]*:[^\s`\"']+"), "<ARN>"),
    # Bare UUIDs (request ids that aren't already covered, agent ids, etc.).
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
        "<UUID>",
    ),
    # X-Ray / API Gateway request ids: base64-ish tokens, OR long mixed
    # letter+digit tokens. BOTH forms require at least one digit, so CamelCase
    # identifiers like "OriginAccessControl" or CFN expressions like
    # "RetentionInDays=LogRetentionDays" are not eaten.
    (
        re.compile(r"\b(?=[A-Za-z0-9+/]*[0-9])[A-Za-z0-9+/]{12,}={1,2}"),
        "<REQUEST_ID>",
    ),
    (
        re.compile(
            r"\b(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{24,}\b"
        ),
        "<REQUEST_ID>",
    ),
    # Absolute local paths (leak usernames / dir layout of the operator box).
    (re.compile(r"/(?:home|Users)/[^\s`\"')]+"), "<LOCAL_PATH>"),
]


def redact(text: str) -> str:
    """Scrub environment-specific identifiers from a string before publishing."""
    if not text:
        return text
    out = str(text)
    for pat, repl in _REDACTIONS:
        out = pat.sub(repl, out)
    return out


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def _repo_version() -> str:
    vf = REPO_ROOT / "VERSION"
    try:
        return vf.read_text().strip()
    except OSError:
        return "unknown"


def _latest_dir(pattern: str) -> Path | None:
    """Newest directory matching a glob (by mtime), or None."""
    matches = [Path(p) for p in glob.glob(pattern) if os.path.isdir(p)]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _write(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n")
    print(f"  wrote {path.relative_to(REPO_ROOT)}")


def _stub(title: str, source_hint: str) -> str:
    return (
        f"# {title}\n\n"
        f"> **NOT INCLUDED IN THIS SNAPSHOT.**\n>\n"
        f"> No raw report was found. Expected source: {source_hint}\n>\n"
        f"> Run the test (see this test's row in "
        f"`security/README.md`) and re-run the curator.\n"
    )


# ---------------------------------------------------------------------------
# SRT — reads the committed baseline scripts/srt/issues.json.
# ---------------------------------------------------------------------------


def _git_ignored_set(paths: list[str]) -> set[str]:
    """Return the subset of `paths` that git ignores (one batched call).

    A fresh local `.srt/issues.json` scans gitignored trees (`.aws-sam/`,
    `scratch/`, vendored `layer/python/`, …) that a CI clean-checkout never
    sees. To publish a result that matches what CI gates on, we drop findings
    whose path is git-ignored. `git check-ignore --stdin` classifies every path
    in one process (per-path spawning is far too slow for an 8k-finding scan).
    On any error we return an empty set — better a false-keep than silently
    hiding a real finding.
    """
    uniq = sorted({p for p in paths if p})
    if not uniq:
        return set()
    try:
        res = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=REPO_ROOT,
            input="\n".join(uniq),
            capture_output=True,
            text=True,
        )
        return {ln for ln in res.stdout.splitlines() if ln}
    except Exception:
        return set()


def curate_srt(issues_path: Path) -> tuple[str, dict]:
    if not issues_path.exists():
        return _stub("SRT — SAST & Dependency Scan", f"`{issues_path}`"), {
            "status": "not-run"
        }
    raw_issues = json.loads(issues_path.read_text())
    # Reconcile to CI's view: drop findings whose path is git-ignored.
    ignored = _git_ignored_set([i.get("path", "") for i in raw_issues])
    issues = [i for i in raw_issues if i.get("path", "") not in ignored]
    dropped = len(raw_issues) - len(issues)
    # Which source produced this — the live scan results or the committed
    # disposition register — is itself an audit-relevant fact.
    src_name = issues_path.name
    if str(issues_path).endswith(".srt/issues.json"):
        source_desc = "live scan results (`.srt/issues.json`)"
    elif "scripts/srt" in str(issues_path):
        source_desc = "committed disposition register (`scripts/srt/issues.json`)"
    else:
        source_desc = f"`{src_name}`"

    def prio(i: dict) -> str:
        return (i.get("priority") or "").upper()

    # Priority × status matrix over the CI-visible findings.
    prio_order = ["HIGH", "MEDIUM", "LOW", "INFO"]
    statuses = sorted({i.get("status", "unknown") for i in issues})
    matrix: dict[str, dict[str, int]] = {p: {} for p in prio_order}
    for i in issues:
        p = prio(i) if prio(i) in matrix else "INFO"
        s = i.get("status", "unknown")
        matrix[p][s] = matrix[p].get(s, 0) + 1

    open_high = [i for i in issues if prio(i) == "HIGH" and i.get("status") == "Open"]
    gate = "PASS ✅" if not open_high else f"FAIL ❌ ({len(open_high)} open HIGH)"

    lines = [
        "# SRT — SAST & Dependency Scan",
        "",
        "Static analysis (Bandit, Semgrep, Checkov), dependency inventory "
        "(Syft), and the security-matrix review, aggregated by the "
        "[Sample Security Review Tool](https://github.com/aws-samples/sample-security-review-tool). "
        "The gate is **open HIGH** findings only; lower tiers are reported as "
        "counts (they are dominated by tracked third-party/vendored code).",
        "",
        f"- **Gate (open HIGH findings):** {gate}",
        f"- **CI-visible findings:** {len(issues)}",
        f"- **Source:** {source_desc}"
        + (
            f" — {dropped} git-ignored finding(s) excluded to match the CI view"
            if dropped
            else ""
        ),
        "",
        "## Findings by priority × status",
        "",
        "| Priority | " + " | ".join(statuses) + " | Total |",
        "|----------|" + "|".join(["------:"] * (len(statuses) + 1)) + "|",
    ]
    for p in prio_order:
        row = matrix[p]
        total = sum(row.values())
        if total == 0:
            continue
        cells = " | ".join(str(row.get(s, 0)) for s in statuses)
        lines.append(f"| {p} | {cells} | {total} |")
    lines.append("")

    if open_high:
        lines += [
            "## ❌ Open HIGH findings (gate-blocking)",
            "",
            "| Source | Check | Path | Line | Issue |",
            "|--------|-------|------|-----:|-------|",
        ]
        for i in open_high:
            lines.append(
                f"| {redact(i.get('source', ''))} | `{redact(i.get('check_id', ''))}` "
                f"| `{redact(i.get('path', ''))}` | {i.get('line', '')} "
                f"| {redact(i.get('issue', ''))} |"
            )
        lines.append("")

    # HIGH-tier suppressions/resolutions are the audit-relevant dispositions —
    # show them; skip the thousands of LOW vendored-code rows.
    high_supp = [
        i
        for i in issues
        if prio(i) == "HIGH" and i.get("status") in ("suppressed", "resolved")
    ]
    if high_supp:
        supp = [i for i in high_supp if i.get("status") == "suppressed"]
        if supp:
            lines += [
                "## Suppressed HIGH findings (accepted risk / scanner limitation)",
                "",
                "Each carries a recorded justification; the authoritative register "
                "is `scripts/srt/issues.json`.",
                "",
                "| Source | Check | Path | Justification |",
                "|--------|-------|------|---------------|",
            ]
            for i in supp:
                lines.append(
                    f"| {redact(i.get('source', ''))} "
                    f"| `{redact(i.get('check_id', ''))}` "
                    f"| `{redact(i.get('path', ''))}` "
                    f"| {redact(i.get('suppressionReason', ''))} |"
                )
            lines.append("")

    meta = {
        "status": "run",
        "total": len(issues),
        "open_high": len(open_high),
        "gate": "pass" if not open_high else "fail",
    }
    return "\n".join(lines), meta


# ---------------------------------------------------------------------------
# RBAC dynamic — reads report.json + meta.json from a report-dir snapshot.
# ---------------------------------------------------------------------------


def curate_rbac_dynamic(report_dir: Path | None) -> tuple[str, dict]:
    hint = "`./scratch/api-test-results/<stack>-<ts>/` (from `make api-test`)"
    if report_dir is None:
        return _stub("RBAC — Dynamic API Authorization Tests", hint), {
            "status": "not-run"
        }
    meta_p = report_dir / "meta.json"
    results_p = report_dir / "report.json"
    if not meta_p.exists() or not results_p.exists():
        return _stub("RBAC — Dynamic API Authorization Tests", hint), {
            "status": "not-run"
        }

    meta = json.loads(meta_p.read_text())
    results = json.loads(results_p.read_text()).get("results", [])
    totals = meta.get("totals", {})
    hard = totals.get("hard_fail", 0)
    gate = "PASS ✅" if hard == 0 else f"FAIL ❌ ({hard} hard failures)"

    lines = [
        "# RBAC — Dynamic API Authorization Tests",
        "",
        "Live tests against a deployed stack: temporary Cognito users (one per "
        "group + a config-version-scoped Author + a second user for IDOR) "
        "exercise every API op across all roles, unauthenticated, and with "
        "malformed/expired tokens, plus the AppSec mandatory-cases checklist "
        "(IDOR, token lifecycle, TLS, input validation, deleted-resource).",
        "",
        f"- **Gate (hard failures):** {gate}",
        f"- **Checks:** {totals.get('checks', len(results))} "
        f"({totals.get('passed', '?')} passed, {hard} hard fail, "
        f"{totals.get('gap_warn', 0)} known-gap "
        f"warning{'s' if totals.get('gap_warn', 0) != 1 else ''})",
        f"- **Ran against:** stack `<REDACTED>` in region "
        f"`{redact(meta.get('region', '?'))}` (account `<ACCOUNT_ID>`)",
        f"- **Source git SHA:** `{redact(meta.get('git_sha', 'unknown'))}`",
        "",
    ]

    hard_fails = [r for r in results if not r["passed"] and not r.get("known_gap")]
    gap_fails = [r for r in results if not r["passed"] and r.get("known_gap")]

    if hard_fails:
        lines += [
            "## ❌ Hard failures",
            "",
            "| Op | Principal | Status | Detail |",
            "|----|-----------|-------:|--------|",
        ]
        for r in hard_fails:
            lines.append(
                f"| `{redact(r.get('op', ''))}` | {redact(r.get('principal', ''))} "
                f"| {r.get('http_status', '')} | {redact(r.get('detail', ''))} |"
            )
        lines.append("")

    if gap_fails:
        lines += [
            "## ⚠️ Known-gap findings (accepted risk)",
            "",
            "| Op | Principal | Status | Gap | Detail |",
            "|----|-----------|-------:|-----|--------|",
        ]
        for r in gap_fails:
            lines.append(
                f"| `{redact(r.get('op', ''))}` | {redact(r.get('principal', ''))} "
                f"| {r.get('http_status', '')} | {redact(str(r.get('known_gap', '')))} "
                f"| {redact(r.get('detail', ''))} |"
            )
        lines.append("")

    # Coverage summary: distinct ops and principals exercised (counts only —
    # the per-request-id full matrix stays in the gitignored raw report).
    ops = sorted({r.get("op", "") for r in results if r.get("op")})
    principals = sorted({r.get("principal", "") for r in results if r.get("principal")})
    lines += [
        "## Coverage",
        "",
        f"- **Distinct operations exercised:** {len(ops)}",
        f"- **Distinct principals (roles + negatives):** {len(principals)}",
        "",
        "> The full per-check matrix with request IDs stays in the gitignored "
        "raw report (`report.md`); it is environment-specific and not "
        "published. This snapshot publishes the gate outcome, failures, and "
        "coverage counts.",
    ]

    return "\n".join(lines), {
        "status": "run",
        "checks": totals.get("checks", len(results)),
        "hard_fail": hard,
        "gap_warn": totals.get("gap_warn", 0),
        "gate": "pass" if hard == 0 else "fail",
    }


# ---------------------------------------------------------------------------
# RBAC static — captured stdout from `make api-test-static`.
# ---------------------------------------------------------------------------


def curate_rbac_static(stdout_path: Path | None) -> tuple[str, dict]:
    hint = "captured stdout of `make api-test-static` (pass --rbac-static <file>)"
    if stdout_path is None or not stdout_path.exists():
        return _stub("RBAC — Static Authorization Scan", hint), {"status": "not-run"}
    raw = stdout_path.read_text()
    # The static scan is CI-safe / has no env identifiers, but redact anyway.
    body = redact(raw).strip()
    # Authoritative summary line is "<N> FAIL, <M> WARN". The gate is FAIL only
    # on FAIL>0; WARN entries are known/accepted gaps (pass-with-warnings).
    m = re.search(r"(\d+)\s+FAIL,\s*(\d+)\s+WARN", raw)
    n_fail = n_warn = None
    if m:
        n_fail, n_warn = int(m.group(1)), int(m.group(2))
        gate_key = "pass" if n_fail == 0 else "fail"
        gate = (
            f"FAIL ❌ ({n_fail} fail)"
            if n_fail
            else (
                f"PASS ✅ ({n_warn} known-gap warning{'s' if n_warn != 1 else ''})"
                if n_warn
                else "PASS ✅"
            )
        )
    else:
        gate_key = "unknown"
        gate = "SEE OUTPUT"
    lines = [
        "# RBAC — Static Authorization Scan",
        "",
        "Offline cross-check (no AWS): reconciles the API op universe, the "
        "schema `@aws_cognito_user_pools` directives, and the expectations file "
        "(`scripts/api_rbac_expectations.yaml`) for drift and missing "
        "server-side checks. WARN entries are known/accepted authorization "
        "gaps (documented in the expectations file), not failures.",
        "",
        f"- **Gate:** {gate}",
        "",
        "## Captured output",
        "",
        "```",
        body,
        "```",
    ]
    return "\n".join(lines), {
        "status": "run",
        "gate": gate_key,
        "fail": n_fail,
        "warn": n_warn,
    }


# ---------------------------------------------------------------------------
# ZAP DAST — reads zap-report.json from a report dir.
# ---------------------------------------------------------------------------


def _zap_ignored_plugin_ids(rules_conf_path: Path) -> set[str]:
    """Plugin ids marked IGNORE in zap-rules.conf ('<id>\\t<action>\\t..').

    Mirrors the parser in scripts/sdlc/codebuild_deployment.py so the curated
    counts match the tool's own console report.
    """
    ids: set[str] = set()
    try:
        for line in Path(rules_conf_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1].upper() == "IGNORE":
                ids.add(parts[0])
    except OSError:
        pass
    return ids


def curate_zap(report_dir: Path | None) -> tuple[str, dict]:
    hint = "`./scratch/zap-reports/` (from `make stacktest-zap`)"
    if report_dir is None:
        return _stub("ZAP DAST — Dynamic API Scan", hint), {"status": "not-run"}
    report_json = report_dir / "zap-report.json"
    if not report_json.exists():
        return _stub("ZAP DAST — Dynamic API Scan", hint), {"status": "not-run"}

    report = json.loads(report_json.read_text())
    # Apply the same IGNORE list the tool's own report uses (zap-rules.conf), so
    # the published counts match the console report and the rules-conf intent
    # (informational alerts muted there still land in the JSON otherwise).
    ignore_ids = _zap_ignored_plugin_ids(
        REPO_ROOT / "scripts" / "sdlc" / "zap-rules.conf"
    )
    risk_label = {"0": "Informational", "1": "Low", "2": "Medium", "3": "High"}
    counts = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0}
    alerts = []
    for site in report.get("site", []):
        for alert in site.get("alerts", []):
            if str(alert.get("pluginid", "")) in ignore_ids:
                continue  # muted in zap-rules.conf
            label = risk_label.get(str(alert.get("riskcode", "0")), "Informational")
            counts[label] = counts.get(label, 0) + 1
            alerts.append(
                {
                    "risk": label,
                    "name": alert.get("alert") or alert.get("name", ""),
                    "count": len(alert.get("instances", []) or [])
                    or int(alert.get("count", 0) or 0),
                    "solution": (alert.get("solution", "") or "").strip(),
                }
            )
    order = {"High": 0, "Medium": 1, "Low": 2, "Informational": 3}
    alerts.sort(key=lambda a: (order.get(a["risk"], 9), -a["count"]))
    gate = "PASS ✅" if counts["High"] == 0 else f"FAIL ❌ ({counts['High']} High)"

    lines = [
        "# ZAP DAST — Dynamic API Scan",
        "",
        "OWASP ZAP baseline/active scan of the deployed UI API "
        "(`POST /op/{field}`), seeded from a generated OpenAPI spec of every "
        "operation. Rules muted in `scripts/sdlc/zap-rules.conf` are excluded.",
        "",
        f"- **Gate (High alerts):** {gate}",
        f"- **Alerts:** High={counts['High']} Medium={counts['Medium']} "
        f"Low={counts['Low']} Info={counts['Informational']}",
        "",
        "## Alerts (most severe first)",
        "",
        "| Risk | Alert | Instances | Remediation |",
        "|------|-------|----------:|-------------|",
    ]
    if alerts:
        for a in alerts:
            sol = redact(re.sub(r"<[^>]+>", " ", a["solution"]))
            sol = re.sub(r"\s+", " ", sol).strip()[:160]
            lines.append(
                f"| {a['risk']} | {redact(a['name'])} | {a['count']} | {sol} |"
            )
    else:
        lines.append("| — | _No alerts_ | — | — |")
    lines.append("")

    return "\n".join(lines), {
        "status": "run",
        "alerts": counts,
        "gate": "pass" if counts["High"] == 0 else "fail",
    }


# ---------------------------------------------------------------------------
# MANIFEST.
# ---------------------------------------------------------------------------


def write_manifest(out_dir: Path, version: str, date: str, per_test: dict) -> None:
    def gate_of(k: str) -> str:
        m = per_test.get(k, {})
        if m.get("status") == "not-run":
            return "not run"
        g = m.get("gate", "?")
        return {"pass": "PASS ✅", "fail": "FAIL ❌"}.get(g, str(g))

    lines = [
        f"# Security Test Snapshot — {version}",
        "",
        "Auditable, public-safe summary of this release's security tests. "
        "Environment-specific identifiers (account IDs, pool IDs, API "
        "hostnames, request IDs, local paths) are redacted; raw reports live "
        "in gitignored `scratch/`/`.srt/` and are not published.",
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Release version | `{version}` |",
        f"| Git SHA | `{_git_sha()}` |",
        f"| Snapshot date | {date} |",
        "| Curated by | `scripts/security/curate_results.py` |",
        "",
        "## Results",
        "",
        "| Test | Gate | Detail |",
        "|------|------|--------|",
        f"| [SRT — SAST & deps](./srt.md) | {gate_of('srt')} | "
        f"{per_test.get('srt', {}).get('open_high', '?')} open HIGH of "
        f"{per_test.get('srt', {}).get('total', '?')} tracked |",
        f"| [RBAC — static](./rbac-static.md) | {gate_of('rbac_static')} | "
        f"{per_test.get('rbac_static', {}).get('fail', '?')} fail, "
        f"{per_test.get('rbac_static', {}).get('warn', '?')} known-gap warn |",
        f"| [RBAC — dynamic](./rbac-dynamic.md) | {gate_of('rbac_dynamic')} | "
        f"{per_test.get('rbac_dynamic', {}).get('checks', '?')} checks, "
        f"{per_test.get('rbac_dynamic', {}).get('hard_fail', '?')} hard fail |",
        f"| [ZAP DAST](./zap-dast.md) | {gate_of('zap')} | "
        f"High={per_test.get('zap', {}).get('alerts', {}).get('High', '?')} |",
        "",
        "See [`security/README.md`](../../README.md) for what each test covers "
        "and how to run it.",
    ]
    _write(out_dir / "MANIFEST.md", "\n".join(lines))


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Curate security-test outputs into a public-safe snapshot."
    )
    ap.add_argument(
        "--version",
        default=_repo_version(),
        help="Snapshot version label (default: repo VERSION file).",
    )
    ap.add_argument(
        "--date",
        required=True,
        help="Snapshot date YYYY-MM-DD (pass explicitly; the tool does not "
        "read the wall clock).",
    )
    ap.add_argument(
        "--srt-issues",
        default=None,
        help="Path to SRT issues.json. Default: the live scan results "
        "(.srt/issues.json) if present, else the committed disposition "
        "register (scripts/srt/issues.json).",
    )
    ap.add_argument(
        "--rbac-dynamic-dir",
        default=None,
        help="RBAC dynamic report dir (default: newest under "
        "scratch/api-test-results/).",
    )
    ap.add_argument(
        "--rbac-static",
        default=None,
        help="File with captured `make api-test-static` stdout.",
    )
    ap.add_argument(
        "--zap-dir",
        default=None,
        help="ZAP report dir (default: newest under scratch/zap-reports/).",
    )
    args = ap.parse_args()

    out_dir = RESULTS_ROOT / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Curating security snapshot → {out_dir.relative_to(REPO_ROOT)}")

    rbac_dyn_dir = (
        Path(args.rbac_dynamic_dir)
        if args.rbac_dynamic_dir
        else _latest_dir(str(REPO_ROOT / "scratch" / "api-test-results" / "*"))
    )
    zap_dir = (
        Path(args.zap_dir)
        if args.zap_dir
        else _latest_dir(str(REPO_ROOT / "scratch" / "zap-reports"))
    )
    rbac_static = Path(args.rbac_static) if args.rbac_static else None

    if args.srt_issues:
        srt_issues = Path(args.srt_issues)
    else:
        live = REPO_ROOT / ".srt" / "issues.json"
        srt_issues = (
            live if live.exists() else (REPO_ROOT / "scripts" / "srt" / "issues.json")
        )

    per_test: dict = {}

    srt_md, per_test["srt"] = curate_srt(srt_issues)
    _write(out_dir / "srt.md", srt_md)

    static_md, per_test["rbac_static"] = curate_rbac_static(rbac_static)
    _write(out_dir / "rbac-static.md", static_md)

    dyn_md, per_test["rbac_dynamic"] = curate_rbac_dynamic(rbac_dyn_dir)
    _write(out_dir / "rbac-dynamic.md", dyn_md)

    zap_md, per_test["zap"] = curate_zap(zap_dir)
    _write(out_dir / "zap-dast.md", zap_md)

    write_manifest(out_dir, args.version, args.date, per_test)

    not_run = [k for k, v in per_test.items() if v.get("status") == "not-run"]
    if not_run:
        print(
            f"\n⚠️  {len(not_run)} test(s) had no raw report and got a stub: "
            f"{', '.join(not_run)}"
        )
    print(
        "\nDone. Review the files before committing (they are public-safe by "
        "construction, but eyeball the redactions)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
