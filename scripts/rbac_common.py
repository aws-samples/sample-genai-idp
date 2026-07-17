#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Shared primitives for driving the IDP UI REST API against a deployed stack.

Extracted from scripts/test_api_rbac.py so more than one caller can reuse the
same stack-resolution and Cognito-token logic without drifting:

  * scripts/test_api_rbac.py         — the dynamic RBAC/authorization matrix
  * scripts/sdlc/codebuild_deployment.py::validate_zap_dast — the ZAP DAST probe

Both need to (a) resolve the UI Cognito pool/client + REST API base URL from a
CloudFormation stack, and (b) mint a real Cognito ID token by temporarily
enabling ADMIN_USER_PASSWORD_AUTH on the app client and restoring the original
auth flows afterward. Keeping that in one place means a change to the stack
shape (output key names, resource logical ids) is fixed once.

Requires: awscli v2 on PATH; credentials with Cognito admin + CloudFormation
read (the deploy-account creds are enough).
"""

import json
import os
import subprocess
from pathlib import Path

# Prefer AWS CLI v2 if installed at the standard location (the ambient `aws` on
# PATH may be a v1 shim that lacks flags like --no-cli-pager). Overridable via
# AWS_CLI_BIN.
AWS_BIN = os.environ.get("AWS_CLI_BIN") or (
    "/usr/local/bin/aws" if Path("/usr/local/bin/aws").exists() else "aws"
)

# The one auth flow the token helpers add (and always remove) on the UI app
# client so admin-initiate-auth can mint a token with just a username/password.
ADMIN_AUTH_FLOW = "ALLOW_ADMIN_USER_PASSWORD_AUTH"


def aws(*args, region=None):
    """Run an AWS CLI command. Returns parsed JSON, or the raw string for
    `--output text`. Raises RuntimeError on a non-zero exit."""
    cmd = [AWS_BIN, *args]
    if region:
        cmd += ["--region", region]
    res = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
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
    """Resolve UI pool/client + REST API base URL + UsersTable from the stack.

    Returns a ctx dict:
      {stack, region, user_pool, client, api_base, users_table, circuit_breaker}

    api_base is the nested APIRESOLVERSTACK's HttpApiEndpoint output, e.g.
    https://<id>.execute-api.<region>.amazonaws.com/api — the base that the UI
    dispatcher serves POST /op/{field} under.
    """

    def phys(logical, stk=stack):
        return aws(
            "cloudformation",
            "list-stack-resources",
            "--stack-name",
            stk,
            "--query",
            f"StackResourceSummaries[?LogicalResourceId=='{logical}']"
            ".PhysicalResourceId",
            "--output",
            "text",
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
    # Detect feature toggles so conditional ops are handled, not mis-failed.
    cb_enabled = bool(phys("CircuitBreakerResolverFunction", api_stack))
    return {
        "stack": stack,
        "region": region,
        "user_pool": user_pool,
        "client": client,
        "api_base": api_base,
        "users_table": users_table,
        "circuit_breaker": cb_enabled,
    }


# ----------------------------------------------------------------------------
# App-client auth-flow management (capture-and-restore)
# ----------------------------------------------------------------------------
def get_auth_flows(ctx):
    return (
        aws(
            "cognito-idp",
            "describe-user-pool-client",
            "--user-pool-id",
            ctx["user_pool"],
            "--client-id",
            ctx["client"],
            "--query",
            "UserPoolClient.ExplicitAuthFlows",
            region=ctx["region"],
        )
        or []
    )


def set_auth_flows(ctx, flows):
    aws(
        "cognito-idp",
        "update-user-pool-client",
        "--user-pool-id",
        ctx["user_pool"],
        "--client-id",
        ctx["client"],
        "--explicit-auth-flows",
        *flows,
        region=ctx["region"],
    )


def enable_admin_auth(ctx):
    """Add ALLOW_ADMIN_USER_PASSWORD_AUTH to the app client, remembering the
    client's original flows so restore_auth_flows() can put back exactly what
    the operator had (not a hardcoded guess)."""
    flows = get_auth_flows(ctx)
    ctx["orig_auth_flows"] = flows
    if ADMIN_AUTH_FLOW not in flows:
        set_auth_flows(ctx, [*flows, ADMIN_AUTH_FLOW])


def restore_auth_flows(ctx):
    """Revert the app client's auth flows. With the originals captured this
    run, restore them verbatim; otherwise strip only the flag we add, leaving
    all other flows untouched."""
    orig = ctx.get("orig_auth_flows")
    if orig:
        set_auth_flows(ctx, orig)
        return
    cur = get_auth_flows(ctx)
    if ADMIN_AUTH_FLOW in cur:
        set_auth_flows(ctx, [f for f in cur if f != ADMIN_AUTH_FLOW])


# ----------------------------------------------------------------------------
# Generic Cognito user + token helpers
# ----------------------------------------------------------------------------
def create_cognito_user(ctx, email, group, password):
    """Create a confirmed Cognito user with a permanent password and add it to
    a group. admin-create-user is tolerant of a pre-existing user (the caller
    typically uses a random per-run email)."""
    subprocess.run(  # nosec B603 - admin-create-user may 'fail' if user exists
        [
            AWS_BIN,
            "cognito-idp",
            "admin-create-user",
            "--user-pool-id",
            ctx["user_pool"],
            "--username",
            email,
            "--message-action",
            "SUPPRESS",
            "--region",
            ctx["region"],
            "--user-attributes",
            f"Name=email,Value={email}",
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
        email,
        "--password",
        password,
        "--permanent",
        region=ctx["region"],
    )
    aws(
        "cognito-idp",
        "admin-add-user-to-group",
        "--user-pool-id",
        ctx["user_pool"],
        "--username",
        email,
        "--group-name",
        group,
        region=ctx["region"],
    )


def delete_cognito_user(ctx, email):
    """Delete a Cognito user. Best-effort (never raises) so it is safe in a
    teardown/finally path."""
    subprocess.run(  # nosec B603
        [
            AWS_BIN,
            "cognito-idp",
            "admin-delete-user",
            "--user-pool-id",
            ctx["user_pool"],
            "--username",
            email,
            "--region",
            ctx["region"],
        ],
        capture_output=True,
        text=True,
    )


def get_id_token(ctx, email, password):
    """Mint a Cognito ID token via ADMIN_USER_PASSWORD_AUTH. The app client must
    already have ALLOW_ADMIN_USER_PASSWORD_AUTH enabled (see enable_admin_auth).
    The ID token is the bearer the API Gateway COGNITO_USER_POOLS authorizer
    expects in the raw `Authorization` header (no `Bearer ` prefix)."""
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
        f"USERNAME={email},PASSWORD={password}",
        "--query",
        "AuthenticationResult.IdToken",
        "--output",
        "text",
        region=ctx["region"],
    )


def get_auth_result(ctx, email, password):
    """Mint a full auth result (IdToken + AccessToken + RefreshToken) via
    ADMIN_USER_PASSWORD_AUTH. Used by the token-lifecycle security tests, which
    need the AccessToken (for global-sign-out revocation checks) alongside the
    IdToken (the API bearer). Returns the AuthenticationResult dict, or {} on
    failure."""
    res = aws(
        "cognito-idp",
        "admin-initiate-auth",
        "--user-pool-id",
        ctx["user_pool"],
        "--client-id",
        ctx["client"],
        "--auth-flow",
        "ADMIN_USER_PASSWORD_AUTH",
        "--auth-parameters",
        f"USERNAME={email},PASSWORD={password}",
        "--query",
        "AuthenticationResult",
        region=ctx["region"],
    )
    return res or {}


def global_sign_out(ctx, email):
    """Globally sign a user out (admin-user-global-sign-out). Revokes the user's
    refresh tokens and, per Cognito docs, marks issued access/ID tokens for
    revocation checking. Best-effort — used by the logout-revocation security
    test to observe whether previously-issued tokens remain accepted."""
    return aws(
        "cognito-idp",
        "admin-user-global-sign-out",
        "--user-pool-id",
        ctx["user_pool"],
        "--username",
        email,
        region=ctx["region"],
    )
