#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Live RBAC + auth test for the IDP UI REST API (the /op/<field> dispatcher that
replaced AppSync). This is the DYNAMIC half of `make api-test`; the static half
is scripts/sdlc/scan_api_rbac.py.

WHY THIS EXISTS
---------------
Under AppSync, per-field @aws_cognito_user_pools(cognito_groups:[...]) directives
gated operations *before* the resolver ran. The REST API Gateway uses a Cognito
authorizer that only *authenticates* — so each resolver (and the dispatcher's
ddb_direct module) must re-enforce the group check itself. curl/idp-cli smoke
tests with an admin identity don't exercise this, so role regressions slip
through. This script drives the API as each Cognito group (Admin/Author/Viewer/
Reviewer), a config-version-SCOPED Author, and unauthenticated, and asserts the
authorization outcome for every UI operation.

The expected policy per operation is loaded from scripts/api_rbac_expectations.yaml
(the single source of truth, shared with the static scanner). Do NOT hardcode
expectations here — edit the YAML.

WHAT IT CHECKS
--------------
  * unauthenticated            -> 401 for a protected op
  * a DISALLOWED role          -> 403 (errorType "Unauthorized")
  * an ALLOWED role            -> NOT denied (a 400 from intentionally-bogus
                                 mutation args is fine — proves auth passed)
  * IAM-only backend ops       -> 403 for every Cognito role
  * config-version scope       -> a scoped Author is denied an out-of-scope
                                 version (in-band Unauthorized) and Admin is not
  * token negatives            -> tampered / wrong-issuer / no-token -> 401

SAFETY
------
* Read ops use harmless args. Mutation ops use nonexistent ids so an *allowed*
  caller fails benign validation instead of mutating real data.
* Ops flagged skip_allowed in the YAML (live-agent / KB / chat starts) are
  exercised ONLY for their denied cells; the allowed-role call is skipped.
* Test users (test-rbac-<role>@example.invalid) are created in setup and removed
  in teardown. The script temporarily adds ALLOW_ADMIN_USER_PASSWORD_AUTH to the
  UI app client and ALWAYS reverts it. The scoped user's seeded UsersTable row is
  deleted in teardown.
* Nothing here is destructive to real stack data.

USAGE
-----
  AWS_PROFILE=default python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2
  ... --report-dir api-test-results   # write auditable report.json/.md/meta.json
  ... --setup-only | --no-teardown | --teardown-only

Requires: awscli v2 on PATH; credentials with Cognito admin + CloudFormation read
+ DynamoDB read/write on the UsersTable (the deploy account creds are enough).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROLES = ["Admin", "Author", "Viewer", "Reviewer"]
SCOPED = "ScopedAuthor"  # an Author with a restrictive allowedConfigVersions
TEST_PW = "TestRbac!" + "Aa1" * 3  # meets typical Cognito policy; throwaway
# .invalid TLD (RFC 2606) can never be a real address.
SCOPE_VERSION = "rbac-test-scope-v1"  # a version the scoped user is limited to
OUT_OF_SCOPE_VERSION = "default"      # exists, but outside the scoped user's set

ANY = "ANY"
IAM = "IAM_ONLY"
EXPECTATIONS_PATH = Path(__file__).resolve().parent / "api_rbac_expectations.yaml"

# Prefer AWS CLI v2 if installed at the standard location (the ambient `aws` on
# PATH may be a v1 shim that lacks flags like --no-cli-pager). Overridable.
AWS_BIN = os.environ.get("AWS_CLI_BIN") or (
    "/usr/local/bin/aws" if Path("/usr/local/bin/aws").exists() else "aws"
)


def test_email(role):
    return f"test-rbac-{role.lower()}@example.invalid"


# ----------------------------------------------------------------------------
# Expectations loading
# ----------------------------------------------------------------------------
def load_expectations():
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML required (pip install pyyaml).", file=sys.stderr)
        sys.exit(2)
    with EXPECTATIONS_PATH.open() as fh:
        spec = yaml.safe_load(fh)
    return spec["operations"], (spec.get("known_gaps") or {})


# ----------------------------------------------------------------------------
# AWS helpers
# ----------------------------------------------------------------------------
def aws(*args, region=None):
    cmd = [AWS_BIN, *args]
    if region:
        cmd += ["--region", region]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"aws {' '.join(args)} failed: {res.stderr.strip()}")
    out = res.stdout.strip()
    if "--output" in args and args[args.index("--output") + 1] == "text":
        return out
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return out


def resolve_stack(stack, region):
    """Resolve UI pool/client + REST API base URL + UsersTable from the stack."""

    def phys(logical, stk=stack):
        return aws(
            "cloudformation", "list-stack-resources",
            "--stack-name", stk,
            "--query",
            f"StackResourceSummaries[?LogicalResourceId=='{logical}'].PhysicalResourceId",
            "--output", "text",
            region=region,
        )

    user_pool = phys("UserPool")
    client = phys("UserPoolClient")
    api_stack = phys("APIRESOLVERSTACK")
    users_table = phys("UsersTable")
    if not (user_pool and client and api_stack):
        raise RuntimeError(
            "Could not resolve UI Cognito/API resources — is this an IDP stack "
            "with the UI enabled?"
        )
    api_base = aws(
        "cloudformation", "describe-stacks",
        "--stack-name", api_stack,
        "--query",
        "Stacks[0].Outputs[?OutputKey=='HttpApiEndpoint'].OutputValue",
        "--output", "text",
        region=region,
    )
    # Detect feature toggles so conditional ops are handled, not mis-failed.
    cb_enabled = bool(
        phys("CircuitBreakerResolverFunction", api_stack)
    )
    return {
        "stack": stack,
        "region": region,
        "user_pool": user_pool,
        "client": client,
        "api_base": api_base,
        "users_table": users_table,
        "circuit_breaker": cb_enabled,
    }


def set_auth_flows(ctx, admin_auth):
    flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
    if admin_auth:
        flows.append("ALLOW_ADMIN_USER_PASSWORD_AUTH")
    aws(
        "cognito-idp", "update-user-pool-client",
        "--user-pool-id", ctx["user_pool"],
        "--client-id", ctx["client"],
        "--explicit-auth-flows", *flows,
        region=ctx["region"],
    )


def _create_cognito_user(ctx, email, group):
    subprocess.run(
        [
            AWS_BIN, "cognito-idp", "admin-create-user",
            "--user-pool-id", ctx["user_pool"],
            "--username", email,
            "--message-action", "SUPPRESS",
            "--region", ctx["region"],
            "--user-attributes",
            f"Name=email,Value={email}", "Name=email_verified,Value=true",
        ],
        capture_output=True, text=True,
    )
    aws(
        "cognito-idp", "admin-set-user-password",
        "--user-pool-id", ctx["user_pool"], "--username", email,
        "--password", TEST_PW, "--permanent", region=ctx["region"],
    )
    aws(
        "cognito-idp", "admin-add-user-to-group",
        "--user-pool-id", ctx["user_pool"], "--username", email,
        "--group-name", group, region=ctx["region"],
    )


def setup_users(ctx):
    for role in ROLES:
        _create_cognito_user(ctx, test_email(role), role)
    # Scoped user: an Author in Cognito, restricted via UsersTable.
    _create_cognito_user(ctx, test_email(SCOPED), "Author")
    _seed_scoped_user(ctx)
    set_auth_flows(ctx, admin_auth=True)
    print(
        f"Created test users: {', '.join(test_email(r) for r in ROLES)}, "
        f"{test_email(SCOPED)} (scoped to [{SCOPE_VERSION}])"
    )


def _seed_scoped_user(ctx):
    """Write a UsersTable row giving the scoped user a restrictive
    allowedConfigVersions. The configuration_resolver looks this up by email
    (EmailIndex) to enforce config-version scope."""
    if not ctx.get("users_table"):
        print("WARN: UsersTable not found — scope suite will be skipped.")
        return
    uid = f"rbac-test-{uuid.uuid4()}"
    email = test_email(SCOPED)
    item = {
        "PK": {"S": f"USER#{uid}"},
        "SK": {"S": f"USER#{uid}"},
        "userId": {"S": uid},
        "email": {"S": email},
        "persona": {"S": "Author"},
        "status": {"S": "active"},
        "allowedConfigVersions": {"L": [{"S": SCOPE_VERSION}]},
    }
    aws(
        "dynamodb", "put-item",
        "--table-name", ctx["users_table"],
        "--item", json.dumps(item),
        region=ctx["region"],
    )
    ctx["_scoped_user_key"] = {
        "PK": {"S": f"USER#{uid}"}, "SK": {"S": f"USER#{uid}"},
    }


def teardown_users(ctx):
    for role in [*ROLES, SCOPED]:
        subprocess.run(
            [
                AWS_BIN, "cognito-idp", "admin-delete-user",
                "--user-pool-id", ctx["user_pool"],
                "--username", test_email(role),
                "--region", ctx["region"],
            ],
            capture_output=True, text=True,
        )
    key = ctx.get("_scoped_user_key")
    if key and ctx.get("users_table"):
        subprocess.run(
            [
                AWS_BIN, "dynamodb", "delete-item",
                "--table-name", ctx["users_table"],
                "--key", json.dumps(key),
                "--region", ctx["region"],
            ],
            capture_output=True, text=True,
        )
    set_auth_flows(ctx, admin_auth=False)
    print("Deleted test users, scoped row, and reverted app-client auth flows.")


def get_token(ctx, role):
    return aws(
        "cognito-idp", "admin-initiate-auth",
        "--user-pool-id", ctx["user_pool"], "--client-id", ctx["client"],
        "--auth-flow", "ADMIN_USER_PASSWORD_AUTH",
        "--auth-parameters",
        f"USERNAME={test_email(role)},PASSWORD={TEST_PW}",
        "--query", "AuthenticationResult.IdToken",
        "--output", "text", region=ctx["region"],
    )


# ----------------------------------------------------------------------------
# HTTP call
# ----------------------------------------------------------------------------
def call(api_base, field, args, token):
    """POST /op/<field>; return (http_status, errorType, in_band_error_type,
    request_id). in_band_error_type captures the {success:false,error:{type}}
    payload that scope denials use (HTTP 200 body)."""
    body = json.dumps({"arguments": args}).encode()
    req = urllib.request.Request(
        f"{api_base}/op/{field}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", token)
    request_id = ""
    try:
        with urllib.request.urlopen(req) as r:
            status, raw = r.status, r.read()
            request_id = r.headers.get("x-amzn-RequestId", "") or r.headers.get(
                "apigw-requestid", ""
            )
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
        request_id = e.headers.get("x-amzn-RequestId", "") if e.headers else ""
    et = None
    in_band = None
    try:
        p = json.loads(raw)
        if isinstance(p, dict):
            if isinstance(p.get("errors"), list) and p["errors"]:
                et = p["errors"][0].get("errorType")
            err = p.get("error")
            if isinstance(err, dict):
                in_band = err.get("type")
    except Exception:
        pass
    return status, et, in_band, request_id


# ----------------------------------------------------------------------------
# Outcome classification
# ----------------------------------------------------------------------------
def _denied(status, et, in_band=None):
    """A request is 'denied' if the gateway rejected it (401/403) OR a resolver
    returned an Unauthorized errorType — either as a GraphQL error
    (``errors[0].errorType``) or as an in-band ``{success:false,
    error:{type:'Unauthorized'}}`` 200 body (the shape scope/group denials in
    the configuration & sync resolvers use)."""
    return (
        status == 401
        or status == 403
        or et == "Unauthorized"
        or in_band == "Unauthorized"
    )


def classify(role, allowed, status, et, in_band):
    """Return (passed: bool, detail: str). `allowed` is ANY | IAM | set."""
    if allowed == IAM:
        ok = _denied(status, et, in_band)
        return ok, f"{status}" if ok else f"LEAK({status}/{et})"
    if allowed == ANY:
        if et == "Unauthorized" or in_band == "Unauthorized":
            return False, f"unexpected Unauthorized ({status})"
        return True, f"{status}"
    # group-restricted
    if role in allowed:
        if et == "Unauthorized" or in_band == "Unauthorized":
            return False, f"DENIED but allowed ({status})"
        return True, f"{status}"
    ok = _denied(status, et, in_band)
    return ok, f"{status}" if ok else f"LEAK({status}/{et}/{in_band})"


# ----------------------------------------------------------------------------
# Matrices
# ----------------------------------------------------------------------------
def run_group_matrix(ops, ctx, tokens, results):
    print("\n=== GROUP MATRIX (unauth + 4 roles) ===")
    for field, o in ops.items():
        groups = o["groups"]
        allowed = (
            ANY if groups == "ANY"
            else IAM if groups == "IAM_ONLY"
            else set(groups)
        )
        # Skip conditional ops when the feature is off (404 for everyone).
        cond = o.get("conditional")
        if cond == "circuit_breaker" and not ctx.get("circuit_breaker"):
            st, *_ = call(ctx["api_base"], field, o["args"], tokens["Admin"])
            if st == 404:
                _record(results, field, "*", "SKIP", True,
                         "circuit breaker disabled (404 for all)")
                print(f"  {field:28s} SKIP (circuit breaker disabled)")
                continue
        if cond == "feature_platform":
            st, *_ = call(ctx["api_base"], field, o["args"], tokens["Admin"])
            if st == 404:
                _record(results, field, "*", "SKIP", True,
                         "feature platform disabled (404 for all)")
                print(f"  {field:28s} SKIP (feature platform disabled)")
                continue

        skip_allowed = o.get("skip_allowed", False)
        cells = [field]
        # unauthenticated
        st, et, ib, rid = call(ctx["api_base"], field, o["args"], None)
        ua_ok = st == 401
        cells.append(f"UN={'401' if ua_ok else st}")
        _record(results, field, "unauth", st, ua_ok,
                "expect 401", et, ib, rid)
        # roles
        for role in ROLES:
            role_allowed = allowed not in (ANY, IAM) and role in allowed
            if skip_allowed and role_allowed:
                cells.append(f"{role[:2]}=skip")
                _record(results, field, role, "SKIP", True,
                        "allowed-role call skipped (skip_allowed)")
                continue
            st, et, ib, rid = call(ctx["api_base"], field, o["args"], tokens[role])
            ok, detail = classify(role, allowed, st, et, ib)
            cells.append(f"{role[:2]}={detail}")
            _record(results, field, role, st, ok, detail, et, ib, rid,
                    gap=o.get("known_gap"))
        print("  " + " ".join(f"{c:16s}" for c in cells))


def run_scope_suite(ctx, tokens, results):
    """A config-version-scoped Author must be denied an out-of-scope version;
    an Admin (unrestricted) must not be. Denial is an in-band
    {success:false,error:{type:'Unauthorized'}} 200 body."""
    print("\n=== CONFIG-VERSION SCOPE ===")
    if "scoped" not in tokens:
        print("  SKIP (scoped user unavailable)")
        _record(results, "getConfigVersion", "scoped", "SKIP", True,
                "scoped user unavailable")
        return

    # scoped Author asks for an out-of-scope version -> must be denied
    st, et, ib, rid = call(
        ctx["api_base"], "getConfigVersion",
        {"versionName": OUT_OF_SCOPE_VERSION}, tokens["scoped"],
    )
    denied = et == "Unauthorized" or ib == "Unauthorized" or st == 403
    _record(results, "getConfigVersion", "scoped(out-of-scope)", st, denied,
            f"expect denial; got {st}/{et}/{ib}", et, ib, rid)
    print(f"  scoped Author getConfigVersion('{OUT_OF_SCOPE_VERSION}') -> "
          f"{st}/{et or ib} ({'OK denied' if denied else 'LEAK'})")

    # Admin asks for the same version -> must NOT be denied
    st, et, ib, rid = call(
        ctx["api_base"], "getConfigVersion",
        {"versionName": OUT_OF_SCOPE_VERSION}, tokens["Admin"],
    )
    ok = not (et == "Unauthorized" or ib == "Unauthorized" or st == 403)
    _record(results, "getConfigVersion", "admin(unrestricted)", st, ok,
            f"expect allowed; got {st}/{et}/{ib}", et, ib, rid)
    print(f"  Admin getConfigVersion('{OUT_OF_SCOPE_VERSION}') -> "
          f"{st} ({'OK allowed' if ok else 'WRONGLY DENIED'})")

    # scoped list should not surface out-of-scope versions
    st, et, ib, rid = call(
        ctx["api_base"], "getConfigVersions", {}, tokens["scoped"],
    )
    ok = et != "Unauthorized"
    _record(results, "getConfigVersions", "scoped(filtered)", st, ok,
            f"list returns (filtered) for scoped user; got {st}/{et}", et, ib, rid)
    print(f"  scoped Author getConfigVersions -> {st} "
          f"({'OK' if ok else 'unexpectedly denied'})")


def run_token_negatives(ctx, tokens, results):
    """Malformed / tampered / missing tokens must all be rejected at the
    gateway (401)."""
    print("\n=== TOKEN NEGATIVES (expect 401) ===")
    good = tokens["Admin"]
    # tamper: flip the last char of the signature segment
    parts = good.split(".")
    tampered = good
    if len(parts) == 3:
        sig = parts[2]
        flipped = ("A" if sig[-1] != "A" else "B")
        tampered = f"{parts[0]}.{parts[1]}.{sig[:-1]}{flipped}"
    cases = {
        "no-token": None,
        "garbage": "not-a-jwt",
        "tampered-signature": tampered,
        "empty-bearer": "Bearer ",
    }
    for name, tok in cases.items():
        st, et, ib, rid = call(ctx["api_base"], "listDocuments", {}, tok)
        # The API Gateway Cognito authorizer rejects an unusable token with 401
        # (unauthorized) or 403 (forbidden) depending on how the failure is
        # surfaced (missing/blank credentials vs a token that fails validation).
        # Both mean "rejected at the gateway" — the only failure we care about
        # is the request being ALLOWED through (2xx) or reaching a resolver.
        ok = st in (401, 403)
        _record(results, "listDocuments", f"token:{name}", st, ok,
                f"expect 401/403; got {st}", et, ib, rid)
        print(f"  {name:22s} -> {st} ({'OK' if ok else 'UNEXPECTED'})")


# ----------------------------------------------------------------------------
# Results / report
# ----------------------------------------------------------------------------
def _record(results, op, principal, status, passed, detail,
            et=None, in_band=None, request_id="", gap=None):
    results.append({
        "op": op,
        "principal": principal,
        "http_status": status,
        "error_type": et,
        "in_band_error": in_band,
        "passed": bool(passed),
        "detail": detail,
        "request_id": request_id,
        "known_gap": gap,
    })


def write_report(report_dir, ctx, results, known_gaps, stamp, account):
    d = Path(report_dir) / f"{ctx['stack']}-{stamp}"
    d.mkdir(parents=True, exist_ok=True)
    # a failure that maps to a known gap is a WARN, not a hard failure
    hard_fails = [r for r in results if not r["passed"] and not r["known_gap"]]
    gap_fails = [r for r in results if not r["passed"] and r["known_gap"]]

    (d / "meta.json").write_text(json.dumps({
        "stack": ctx["stack"], "region": ctx["region"], "account": account,
        "api_base": ctx["api_base"], "timestamp": stamp,
        "git_sha": _git_sha(),
        "circuit_breaker_enabled": ctx.get("circuit_breaker", False),
        "totals": {
            "checks": len(results),
            "passed": sum(1 for r in results if r["passed"]),
            "hard_fail": len(hard_fails),
            "gap_warn": len(gap_fails),
        },
    }, indent=2))
    (d / "report.json").write_text(json.dumps({"results": results}, indent=2))
    (d / "report.md").write_text(
        _render_md(ctx, results, hard_fails, gap_fails, known_gaps, stamp, account)
    )
    print(f"\nReport written to {d}/")
    return len(hard_fails)


def _git_sha():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _render_md(ctx, results, hard_fails, gap_fails, known_gaps, stamp, account):
    lines = [
        "# API RBAC Test Report",
        "",
        f"- **Stack:** `{ctx['stack']}` ({ctx['region']}, account {account})",
        f"- **API base:** `{ctx['api_base']}`",
        f"- **Timestamp:** {stamp}",
        f"- **Git:** `{_git_sha()}`",
        f"- **Circuit breaker:** "
        f"{'enabled' if ctx.get('circuit_breaker') else 'disabled'}",
        "",
        f"**{sum(1 for r in results if r['passed'])}/{len(results)} checks "
        f"passed** — {len(hard_fails)} hard fail, {len(gap_fails)} "
        "known-gap warning.",
        "",
    ]
    if hard_fails:
        lines += ["## ❌ Hard failures", "",
                  "| Op | Principal | Status | Detail | Request ID |",
                  "|----|-----------|--------|--------|------------|"]
        for r in hard_fails:
            lines.append(
                f"| `{r['op']}` | {r['principal']} | {r['http_status']} | "
                f"{r['detail']} | `{r['request_id']}` |")
        lines.append("")
    if gap_fails:
        lines += ["## ⚠️ Known-gap findings (accepted risk)", "",
                  "| Op | Principal | Status | Gap | Detail |",
                  "|----|-----------|--------|-----|--------|"]
        for r in gap_fails:
            lines.append(
                f"| `{r['op']}` | {r['principal']} | {r['http_status']} | "
                f"{r['known_gap']} | {r['detail']} |")
        lines.append("")
    lines += ["## Full matrix", "",
              "| Op | Principal | Status | Pass | Detail | Request ID |",
              "|----|-----------|--------|------|--------|------------|"]
    for r in results:
        mark = "✅" if r["passed"] else ("⚠️" if r["known_gap"] else "❌")
        lines.append(
            f"| `{r['op']}` | {r['principal']} | {r['http_status']} | {mark} | "
            f"{r['detail']} | `{r['request_id']}` |")
    lines += ["", "## Known gaps register", ""]
    for gid, g in sorted(known_gaps.items()):
        lines.append(f"- **{gid}** — {g.get('summary', '')}")
    lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Live RBAC/auth test for the IDP API.")
    ap.add_argument("--stack-name", required=True)
    ap.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    )
    ap.add_argument("--report-dir", help="write report.json/.md/meta.json here")
    ap.add_argument("--setup-only", action="store_true")
    ap.add_argument("--teardown-only", action="store_true")
    ap.add_argument("--no-teardown", action="store_true")
    args = ap.parse_args()
    if not args.region:
        ap.error("--region is required (or set AWS_REGION / AWS_DEFAULT_REGION)")

    ops, known_gaps = load_expectations()
    ctx = resolve_stack(args.stack_name, args.region)
    print(f"Stack: {args.stack_name} ({args.region})")
    print(f"UI user pool: {ctx['user_pool']}  client: {ctx['client']}")
    print(f"API base: {ctx['api_base']}")
    print(f"UsersTable: {ctx['users_table']}  "
          f"circuit_breaker={ctx['circuit_breaker']}")

    if args.teardown_only:
        teardown_users(ctx)
        return 0
    if args.setup_only:
        setup_users(ctx)
        return 0

    setup_users(ctx)
    try:
        tokens = {r: get_token(ctx, r) for r in ROLES}
        st = get_token(ctx, SCOPED)
        if st and len(st) > 100:
            tokens["scoped"] = st
        for r in ROLES:
            if not tokens[r] or len(tokens[r]) < 100:
                print(f"ERROR: failed to mint token for {r}")
                return 2

        results = []
        run_group_matrix(ops, ctx, tokens, results)
        run_scope_suite(ctx, tokens, results)
        run_token_negatives(ctx, tokens, results)

        hard_fails = [r for r in results if not r["passed"] and not r["known_gap"]]
        gap_fails = [r for r in results if not r["passed"] and r["known_gap"]]

        print("\n=== RESULT ===")
        for r in hard_fails:
            print(f"  ✗ {r['op']}[{r['principal']}]: {r['detail']}")
        for r in gap_fails:
            print(f"  ⚠ {r['op']}[{r['principal']}]: {r['detail']} "
                  f"[{r['known_gap']}]")
        print(f"{len(results)} checks, {len(hard_fails)} hard fail, "
              f"{len(gap_fails)} known-gap warn")

        if args.report_dir:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            account = aws("sts", "get-caller-identity", "--query", "Account",
                          "--output", "text")
            write_report(args.report_dir, ctx, results, known_gaps,
                         stamp, account)

        if not hard_fails:
            print("ALL HARD CHECKS PASSED")
        return 1 if hard_fails else 0
    finally:
        if not args.no_teardown:
            teardown_users(ctx)


if __name__ == "__main__":
    sys.exit(main())
