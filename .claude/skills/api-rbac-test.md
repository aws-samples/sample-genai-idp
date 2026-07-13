# API RBAC Test — GenAI IDP Accelerator

Use this skill to verify that **every** UI API operation is correctly protected
by (a) its required Cognito group(s) and (b) config-version scope, using two
complementary layers that share one source of truth:

1. **Static scan** (`make api-test-static`) — no AWS, CI-safe. Cross-checks the
   op universe, the schema directives, and the expectations file for drift and
   missing server-side checks.
2. **Dynamic tests** (`make api-test STACK_NAME=<stack>`) — spins up temporary
   Cognito users (one per group + a config-version-scoped Author), calls every
   op as every role + unauthenticated + with malformed tokens against a
   *deployed* stack, and writes an auditable report.

> The dynamic harness has already caught a real, shipping vulnerability
> (config-version scope silently failing open because a resolver was missing a
> `dynamodb:Query` IAM grant). Treat a hard fail as real until proven otherwise.

## The architecture you are testing (read this first)

- **Single route:** the UI calls `POST /op/{field}` on an API Gateway REST API
  (logical id `HttpApiDispatcher`). The Cognito authorizer only
  **authenticates** (401 for missing/bad token); it does **no** group checks.
- **Per-resolver RBAC:** each resolver Lambda reads
  `identity.claims['cognito:groups']` and raises `PermissionError` →
  the dispatcher maps that to **HTTP 403** with `errorType: "Unauthorized"`.
- **Config-version scope denials are IN-BAND:** the configuration & sync
  resolvers return `{success:false, error:{type:"Unauthorized"}}` with **HTTP
  200** (NOT a 403). The harness treats an in-band `Unauthorized` as a denial.
- **4 groups** (precedence): Admin(0) > Author(1) > Reviewer(2) > Viewer(3),
  defined in `template.yaml`.
- **`@aws_auth(cognito_groups)` is SILENTLY IGNORED** on this multi-auth API
  (it also allows AWS_IAM). Only `@aws_cognito_user_pools(...)` directives and
  server-side checks are real. Server-side enforcement is the source of truth;
  the schema directive is defense-in-depth.
- **IAM_ONLY ops** (`updateAgentJobStatus`, `updateDiscoveryJobStatus`) must
  reject every Cognito caller.

## Three sources of truth that MUST NOT drift

| Source | Where |
|--------|-------|
| Op universe | `FIELD_FUNCTION_MAP` (SSM `/<stack>/http-api/field-function-map`) ∪ `ddb_direct._HANDLED` ∪ `FIELD_ALIASES` in the dispatcher |
| Schema groups | `@aws_cognito_user_pools(cognito_groups:[...])` in `nested/api-resolvers/src/api/schema.graphql` |
| Expectations | `scripts/api_rbac_expectations.yaml` ← **edit this when you add an op** |

The static scan **fails** if these diverge. When you add an API operation you
MUST add an entry to `scripts/api_rbac_expectations.yaml` (and the schema).

## Files

- `scripts/api_rbac_expectations.yaml` — single source of truth (96 ops + gap
  register). Entry schema is documented at the top of the file.
- `scripts/sdlc/scan_api_rbac.py` — static scanner (`--strict` fails on known
  gaps, use to confirm a gap was fixed; `--json PATH` for machine output).
- `scripts/test_api_rbac.py` — dynamic harness.

## Environment (gotchas)

```bash
# ALL AWS calls target the deployment account — use AWS_PROFILE=default,
# NOT the sandbox's ambient creds (which may point elsewhere). Confirm first:
AWS_PROFILE=default aws sts get-caller-identity

# The harness prefers AWS CLI v2 at /usr/local/bin/aws (the conda `aws` on PATH
# is v1 and lacks some flags). It handles this internally via AWS_BIN.
```

## Workflow

```bash
# 1. Static scan — run on every change to an API op / schema / expectations.
make api-test-static                 # exit 0 with WARNs for known gaps
make api-test-static STRICT=1        # exit 1 on any known gap (verify a fix)

# 2. Dynamic tests against a deployed stack (needs deploy-account creds).
AWS_PROFILE=default make api-test STACK_NAME=IDP1 REGION=us-west-2
#   -> writes ./api-test-results/<stack>-<ts>/{report.md,report.json,meta.json}
#   REPORT_DIR=<dir>   override output location
#   NO_TEARDOWN=1      keep the temp Cognito users (debugging; rerun teardown
#                      later with:  python3 scripts/test_api_rbac.py \
#                        --stack-name <s> --region <r> --teardown-only)
```

The harness **always tears down** its temp users and reverts the app client's
auth flows on exit (even NO_TEARDOWN only skips the user delete). Exit code is
non-zero only on **hard fails** (a real leak) — known gaps are WARNs.

## Reading the report

- `meta.json` — stack, account, git_sha, api_base, per-run totals, request IDs.
- `report.md` — the group matrix (op × role), scope suite, token negatives.
- A finding is a **hard fail** only if it has no `known_gap`; documented gaps
  (GAP-01..) surface as WARN so they stay visible without failing the gate.

## When a hard fail appears — triage order

1. **In-band denial not recognized?** If the op denies via `{success:false,
   error:{type:Unauthorized}}` (200), confirm `classify()`/`_denied()` treat
   in-band `Unauthorized` as denied. (Config & sync resolvers use this.)
2. **Expectation wrong?** Read the `enforced_in` file and confirm the actual
   server-side group set. The code is the source of truth; fix the YAML.
3. **Test input short-circuits?** For mutations, auth is checked BEFORE the
   bogus id is used, so an *allowed* role legitimately gets 400 (not-found) —
   that's a pass, not a leak. A *disallowed* role must still get Unauthorized.
4. **Real leak / fail-open?** If a scoped/lower-privilege caller is ALLOWED,
   check the resolver's IAM grants (a caught `AccessDeniedException` on the
   UsersTable scope query fails OPEN to unrestricted) and the actual group gate.
   Confirm via the resolver's CloudWatch logs (look for
   "Config scope for ...: unrestricted" right after an AccessDenied WARNING).

## Adding a new API operation — checklist

1. Add the resolver's server-side group/scope check.
2. Add the `@aws_cognito_user_pools` directive in `schema.graphql`.
3. Add an entry to `scripts/api_rbac_expectations.yaml` (mirror a similar op).
4. `make api-test-static` must be clean, then run `make api-test` live.
