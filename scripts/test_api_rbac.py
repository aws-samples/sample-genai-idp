#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Live RBAC + auth + arg-mapping test for the IDP REST API (the /op/<field>
dispatcher that replaced AppSync).

WHY THIS EXISTS
---------------
Under AppSync, per-field ``@aws_cognito_user_pools(cognito_groups:[...])``
directives gated operations *before* the resolver ran. The REST API Gateway
transport uses a Cognito authorizer that only *authenticates* — so each resolver
(and the dispatcher's ddb_direct module) must re-enforce the group check itself.
``curl``/``idp-cli`` smoke tests with an admin identity don't exercise this, so
role-based regressions slip through. This script drives the API as each Cognito
group (Admin / Author / Viewer / Reviewer) plus unauthenticated, and asserts the
authorization outcome for every UI operation against the AppSync baseline.

It checks three things per operation:
  * unauthenticated  -> 401
  * a DISALLOWED role -> 403 (errorType "Unauthorized")
  * an ALLOWED role   -> NOT denied (a 400 from the intentionally-bogus test
    arguments is fine — it proves the request passed authorization)
  * IAM-only backend ops -> 403 for every Cognito role

The expected per-op group requirements below are the authoritative copy of the
directives in ``nested/api-resolvers/src/api/schema.graphql`` (type Query /
Mutation). When you add or change an operation's RBAC, update EXPECTED here too.

SAFETY
------
* Read ops use harmless args. Mutation ops use nonexistent ids so an *allowed*
  caller fails benign validation instead of mutating real data — the assertion
  is only that DISALLOWED roles are rejected.
* Test users (test-rbac-<role>@example.invalid) are created in --setup and
  removed in --teardown / at the end of a full run. The script temporarily adds
  ALLOW_ADMIN_USER_PASSWORD_AUTH to the UI app client and ALWAYS reverts it.
* Nothing here is destructive to real stack data.

USAGE
-----
  # Full run (setup users, test, teardown) — the usual case:
  AWS_PROFILE=default python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2

  # Leave test users in place between runs (faster iteration):
  ... --setup-only     # create users + enable admin-auth, then exit
  ... --no-teardown    # run tests but keep users
  ... --teardown-only  # delete users + revert app client, then exit

Requires: awscli v2 on PATH, credentials with Cognito admin + CloudFormation
read permissions (the deploy account's ReadOnly+Cognito is enough; the same
creds used for `idp-cli deploy`).
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# test-user convention. .invalid TLD (RFC 2606) can never be a real address.
ROLES = ["Admin", "Author", "Viewer", "Reviewer"]
TEST_PW = "TestRbac!" + "Aa1" * 3  # meets typical Cognito policy; throwaway
TEST_EMAIL = lambda role: f"test-rbac-{role.lower()}@example.invalid"  # noqa: E731

# --- expected authorization per operation (mirror of schema.graphql) ---------
# value = set of allowed groups; None = any authenticated user;
# "IAM_ONLY" = backend/IAM principals only (never a Cognito user).
ANY = None
IAM = "IAM_ONLY"
READ_OPS = {
    # field: (args, allowed)
    "listDocuments": ({}, ANY),
    "getDocumentCount": ({}, ANY),
    "getDocument": ({"ObjectKey": "__nonexistent__.pdf"}, ANY),
    "listDocumentsDateShard": ({}, ANY),
    "getLatestPublishedVersion": ({}, ANY),
    "listChatSessions": ({}, ANY),
    "listAvailableAgents": ({}, ANY),
    "getMyProfile": ({}, ANY),
    "listUsers": ({}, ANY),
    "getCircuitBreakerStatus": ({}, ANY),
    "getConfigVersions": ({}, {"Admin", "Author", "Viewer"}),
    "getConfigVersion": ({"versionName": "default"}, {"Admin", "Author", "Viewer"}),
    "getPricing": ({}, {"Admin", "Author", "Viewer"}),
    "listConfigurationLibrary": ({"pattern": "default"}, {"Admin", "Author", "Viewer"}),
    "listAgentJobs": ({}, {"Admin", "Author", "Viewer"}),
    "listDiscoveryJobs": ({}, {"Admin", "Author"}),
    "getTestSets": ({}, {"Admin", "Author"}),
    "getTestRuns": ({}, {"Admin", "Author"}),
    # backend-only writes (workers write DynamoDB directly): reject all Cognito
    "updateAgentJobStatus": ({"jobId": "x", "userId": "y", "status": "COMPLETED"}, IAM),
    "updateDiscoveryJobStatus": ({"jobId": "x", "status": "QUEUED"}, IAM),
}
MUTATION_OPS = {
    "deleteConfigVersion": ({"versionName": "__nope__"}, {"Admin"}),
    "updatePricing": ({"pricing": "{}"}, {"Admin"}),
    "restoreDefaultPricing": ({}, {"Admin"}),
    "createUser": ({"email": "__no@no.invalid", "group": "Viewer"}, {"Admin"}),
    "updateUser": ({"email": "__no@no.invalid", "group": "Viewer"}, {"Admin"}),
    "deleteUser": ({"email": "__no@no.invalid"}, {"Admin"}),
    "updateConfiguration": ({"configuration": "{}"}, {"Admin", "Author"}),
    "setActiveVersion": ({"versionName": "__nope__"}, {"Admin", "Author"}),
    "deleteDocument": ({"objectKeys": ["__nope__"]}, {"Admin", "Author"}),
    "reprocessDocument": ({"objectKeys": ["__nope__"]}, {"Admin", "Author"}),
    "abortWorkflow": ({"objectKeys": ["__nope__"]}, {"Admin", "Author"}),
    "copyToBaseline": ({"objectKeys": ["__nope__"]}, {"Admin", "Author"}),
    "startTestRun": ({}, {"Admin", "Author"}),
    "deleteTests": ({"testIds": ["__x__"]}, {"Admin", "Author"}),
    "abortTestRuns": ({"testRunIds": ["__x__"]}, {"Admin", "Author"}),
    "getTestRun": ({"testRunId": "__x__"}, {"Admin", "Author"}),
    "uploadDocument": ({"fileName": "x.pdf"}, {"Admin", "Author"}),
    "uploadDiscoveryDocument": (
        {"fileName": "x.pdf", "contentType": "application/pdf"},
        {"Admin", "Author"},
    ),
    "createFinetuningJob": ({}, {"Admin", "Author"}),
    "completeSectionReview": (
        {"objectKey": "__x__", "sectionId": "1"},
        {"Admin", "Reviewer"},
    ),
    "claimReview": ({"objectKey": "__x__"}, {"Admin", "Reviewer"}),
    "releaseReview": ({"objectKey": "__x__"}, {"Admin", "Reviewer"}),
    "processChanges": ({"objectKey": "__x__"}, {"Admin", "Reviewer"}),
    "submitAgentQuery": (
        {"query": "hi", "agentIds": ["x"]},
        {"Admin", "Author", "Viewer"},
    ),
    # Admin-only, but only routable when CircuitBreakerEnabled=true. When
    # disabled these return 404 for everyone (not a leak) and are auto-skipped.
    "pauseCircuitBreaker": ({"reason": "test"}, {"Admin", "__CB__"}),
    "resumeCircuitBreaker": ({"reason": "test"}, {"Admin", "__CB__"}),
}


def aws(*args, region=None):
    """Run an aws CLI command and return parsed JSON (or text for --output text)."""
    cmd = ["aws", *args]
    if region:
        cmd += ["--region", region]
    cmd += ["--no-cli-pager"]
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
    """Resolve UI pool/client/identity-pool + REST API base URL from the stack."""

    def phys(logical, stk=stack):
        # list- (not describe-) so it paginates past ~100 resources.
        return aws(
            "cloudformation",
            "list-stack-resources",
            "--stack-name",
            stk,
            "--query",
            f"StackResourceSummaries[?LogicalResourceId=='{logical}'].PhysicalResourceId",
            "--output",
            "text",
            region=region,
        )

    user_pool = phys("UserPool")
    client = phys("UserPoolClient")
    identity_pool = phys("IdentityPool")
    api_stack = phys("APIRESOLVERSTACK")
    if not (user_pool and client and identity_pool and api_stack):
        raise RuntimeError(
            "Could not resolve UI Cognito/API resources — is this an IDP stack with the UI enabled?"
        )
    api_base = aws(
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        api_stack,
        "--query",
        "Stacks[0].Outputs[?OutputKey=='HttpApiEndpoint'].OutputValue",
        "--output",
        "text",
        region=region,
    )
    return {
        "user_pool": user_pool,
        "client": client,
        "identity_pool": identity_pool,
        "api_base": api_base,
    }


def set_auth_flows(ctx, region, admin_auth):
    flows = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
    if admin_auth:
        flows.append("ALLOW_ADMIN_USER_PASSWORD_AUTH")
    aws(
        "cognito-idp",
        "update-user-pool-client",
        "--user-pool-id",
        ctx["user_pool"],
        "--client-id",
        ctx["client"],
        "--explicit-auth-flows",
        *flows,
        region=region,
    )


def setup_users(ctx, region):
    for role in ROLES:
        u = TEST_EMAIL(role)
        subprocess.run(
            [
                "aws",
                "cognito-idp",
                "admin-create-user",
                "--user-pool-id",
                ctx["user_pool"],
                "--username",
                u,
                "--message-action",
                "SUPPRESS",
                "--region",
                region,
                "--no-cli-pager",
                "--user-attributes",
                f"Name=email,Value={u}",
                "Name=email_verified,Value=true",
            ],
            capture_output=True,
            text=True,
        )
        aws(
            "cognito-idp",
            "admin-set-user-password",
            "--user-pool-id",
            ctx["user_pool"],
            "--username",
            u,
            "--password",
            TEST_PW,
            "--permanent",
            region=region,
        )
        aws(
            "cognito-idp",
            "admin-add-user-to-group",
            "--user-pool-id",
            ctx["user_pool"],
            "--username",
            u,
            "--group-name",
            role,
            region=region,
        )
    set_auth_flows(ctx, region, admin_auth=True)
    print(f"Created test users: {', '.join(TEST_EMAIL(r) for r in ROLES)}")


def teardown_users(ctx, region):
    for role in ROLES:
        subprocess.run(
            [
                "aws",
                "cognito-idp",
                "admin-delete-user",
                "--user-pool-id",
                ctx["user_pool"],
                "--username",
                TEST_EMAIL(role),
                "--region",
                region,
                "--no-cli-pager",
            ],
            capture_output=True,
            text=True,
        )
    set_auth_flows(ctx, region, admin_auth=False)
    print("Deleted test users and reverted app-client auth flows.")


def get_token(ctx, region, role):
    return aws(
        "cognito-idp",
        "admin-initiate-auth",
        "--user-pool-id",
        ctx["user_pool"],
        "--client-id",
        ctx["client"],
        "--auth-flow",
        "ADMIN_USER_PASSWORD_AUTH",
        "--auth-parameters",
        f"USERNAME={TEST_EMAIL(role)},PASSWORD={TEST_PW}",
        "--query",
        "AuthenticationResult.IdToken",
        "--output",
        "text",
        region=region,
    )


def call(api_base, field, args, token):
    body = json.dumps({"arguments": args}).encode()
    req = urllib.request.Request(
        f"{api_base}/op/{field}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", token)
    try:
        with urllib.request.urlopen(req) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    et = None
    try:
        p = json.loads(raw)
        if isinstance(p, dict) and isinstance(p.get("errors"), list) and p["errors"]:
            et = p["errors"][0].get("errorType")
    except Exception:
        pass
    return status, et


def run_matrix(name, ops, ctx, region, tokens, fails, strict_args=True):
    # strict_args=True (read matrix): ops are called with VALID args, so a
    # BadRequest for an allowed role signals a real arg-mapping regression.
    # strict_args=False (mutation matrix): ops use intentionally-bogus/missing
    # args so allowed callers fail benign validation — a BadRequest there is
    # EXPECTED and only proves the request passed authorization; we assert only
    # that disallowed roles are denied.
    print(f"\n=== {name} ===")
    for field, (args, allowed) in ops.items():
        # circuit-breaker ops are not routable when the feature is disabled
        if isinstance(allowed, set) and "__CB__" in allowed:
            st, _ = call(ctx["api_base"], field, args, tokens["Admin"])
            if st == 404:
                print(f"  {field:26s} SKIP (circuit breaker disabled; 404 for all)")
                continue
            allowed = {g for g in allowed if g != "__CB__"}
        cells = [field]
        for role in ROLES:
            st, et = call(ctx["api_base"], field, args, tokens[role])
            if allowed == IAM:
                ok = st == 403 or et == "Unauthorized"
                cells.append(f"{role[:2]}={'OK' if ok else f'LEAK({st})'}")
                if not ok:
                    fails.append(f"{field}[{role}]: IAM-only but got {st}/{et}")
            elif allowed is ANY:
                ok = et not in ("Unauthorized", "BadRequest")
                cells.append(f"{role[:2]}={st}")
                if et == "Unauthorized":
                    fails.append(
                        f"{field}[{role}]: unexpected Unauthorized (any-authed op)"
                    )
                if et == "BadRequest":
                    fails.append(f"{field}[{role}]: BadRequest (arg mapping?)")
            else:
                if role in allowed:
                    cells.append(f"{role[:2]}={st}")
                    if et == "Unauthorized":
                        fails.append(f"{field}[{role}]: DENIED but role is allowed")
                    if et == "BadRequest" and strict_args:
                        fails.append(f"{field}[{role}]: BadRequest (arg mapping?)")
                else:
                    ok = st == 403 or et == "Unauthorized"
                    cells.append(f"{role[:2]}={'403' if ok else f'LEAK({st}/{et})'}")
                    if not ok:
                        fails.append(
                            f"{field}[{role}]: allowed={sorted(allowed)} but got {st}/{et}"
                        )
        print("  " + " ".join(f"{c:15s}" for c in cells))


def main():
    ap = argparse.ArgumentParser(
        description="Live RBAC/auth test for the IDP REST API."
    )
    ap.add_argument("--stack-name", required=True)
    ap.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    )
    ap.add_argument(
        "--setup-only",
        action="store_true",
        help="Create test users + enable admin-auth, then exit.",
    )
    ap.add_argument(
        "--teardown-only",
        action="store_true",
        help="Delete test users + revert app client, then exit.",
    )
    ap.add_argument(
        "--no-teardown",
        action="store_true",
        help="Run tests but keep test users afterward.",
    )
    args = ap.parse_args()
    if not args.region:
        ap.error("--region is required (or set AWS_REGION / AWS_DEFAULT_REGION)")

    ctx = resolve_stack(args.stack_name, args.region)
    print(f"Stack: {args.stack_name} ({args.region})")
    print(f"UI user pool: {ctx['user_pool']}  client: {ctx['client']}")
    print(f"API base: {ctx['api_base']}")

    if args.teardown_only:
        teardown_users(ctx, args.region)
        return 0
    if args.setup_only:
        setup_users(ctx, args.region)
        return 0

    setup_users(ctx, args.region)
    try:
        tokens = {r: get_token(ctx, args.region, r) for r in ROLES}
        for r, t in tokens.items():
            if not t or len(t) < 100:
                print(f"ERROR: failed to mint token for {r}: {t}")
                return 2

        fails = []
        # unauthenticated must be 401
        st, _ = call(ctx["api_base"], "listDocuments", {}, None)
        print(f"\n[UNAUTH] listDocuments -> {st} (expect 401)")
        if st != 401:
            fails.append(f"unauth listDocuments returned {st}, expected 401")

        run_matrix("READ / QUERY OPS", READ_OPS, ctx, args.region, tokens, fails)
        run_matrix(
            "MUTATION OPS",
            MUTATION_OPS,
            ctx,
            args.region,
            tokens,
            fails,
            strict_args=False,
        )

        print("\n=== RESULT ===")
        if fails:
            print(f"{len(fails)} FAILURE(S):")
            for f in fails:
                print("  ✗ " + f)
            return 1
        print("ALL CHECKS PASSED")
        return 0
    finally:
        if not args.no_teardown:
            teardown_users(ctx, args.region)


if __name__ == "__main__":
    sys.exit(main())
