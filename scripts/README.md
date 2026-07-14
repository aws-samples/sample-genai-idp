# IDP Accelerator Scripts

This directory contains utility scripts for building, testing, deploying, and operating the IDP Accelerator.

## Directory Structure

```
scripts/
├── setup/               # Development environment setup scripts
├── srt/                 # SRT (Sample Security Review Tool) integration
├── sdlc/                # SDLC CI/CD scripts and infrastructure
│   ├── cfn/             # CloudFormation templates for CI/CD pipeline
│   └── [scripts]        # CI/CD automation scripts
└── generate_govcloud_template.py  # GovCloud template generation (deprecated — use `idp-cli publish --headless`)
```

## Subdirectories

### `setup/` - Development Environment Setup
Setup scripts for different operating systems. See [setup/README.md](setup/README.md).

### `srt/` - SRT Security Scanning
SRT (Sample Security Review Tool) integration for automated security scanning. See [srt/README.md](srt/README.md).

### `sdlc/` - SDLC CI/CD Scripts and Infrastructure
CloudFormation templates and scripts for CI/CD pipeline infrastructure.

| Script | Purpose | Usage |
|--------|---------|-------|
| `codebuild_deployment.py` | CodeBuild deployment automation | Used by CI/CD pipeline |
| `integration_test_deployment.py` | Integration test deployment | Used by CI/CD pipeline |
| `validate_buildspec.py` | Validate buildspec.yml files | See [sdlc/README_validate_buildspec.md](sdlc/README_validate_buildspec.md) |
| `typecheck_pr_changes.py` | Type check Python files in PRs | Used by CI/CD pipeline |
| `validate_service_role_permissions.py` | Validate IAM service role permissions | `python scripts/sdlc/validate_service_role_permissions.py` |

See [sdlc/cfn/README.md](sdlc/cfn/README.md) for CloudFormation templates.

## Utility Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `discover_model_limits.py` | Empirically test Bedrock model max_tokens limits | `python scripts/discover_model_limits.py` |
| `test_api_rbac.py` | Live RBAC/auth/arg-mapping test of the REST API across all Cognito roles | `python scripts/test_api_rbac.py --stack-name <stack> --region <region>` |
| `generate_govcloud_template.py` | Generate GovCloud-compatible template (**deprecated** — use `idp-cli publish --headless`) | `idp-cli publish --source-dir . --region <region> --headless` |

### Model Limit Discovery (`discover_model_limits.py`)

Tests actual Bedrock API behavior to discover model `max_tokens` limits, then auto-generates `config_library/model_config_limits.yaml`.

**Why:** Instead of trusting documentation, we verify limits empirically to prevent runtime failures.

**Basic usage:**
```bash
# Test all supported models and generate config
python scripts/discover_model_limits.py

# Test specific models only
python scripts/discover_model_limits.py \
    --models "us.anthropic.claude-sonnet-4-20250514-v1:0"

# Verbose mode
python scripts/discover_model_limits.py --verbose
```

**When to use:**
- Adding a new Bedrock model → Add to `DEFAULT_MODELS_TO_TEST`, run script, commit YAML
- Verifying limits are accurate → Run with `--verbose` to see test results
- Investigating one model → Use `--models` flag with specific model ID

**How it works:**
1. Progressively tests larger `max_tokens` values until API rejects it
2. Catches `ValidationException` to identify exact limit
3. Groups models by limit and creates regex patterns
4. Generates YAML with test dates and verified limits

**Requirements:** AWS credentials with Bedrock `InvokeModel` permissions

**See also:** [Config Validation](../docs/config-validation.md)

### API RBAC / Auth Test (`test_api_rbac.py`)

Drives the deployed REST API (the `/op/<field>` dispatcher that replaced
AppSync) as each Cognito group — **Admin, Author, Viewer, Reviewer** — plus
unauthenticated, and asserts the authorization outcome of every UI operation
against the AppSync schema baseline.

**Why:** Under AppSync, `@aws_cognito_user_pools(cognito_groups:[...])` schema
directives gated operations *before* the resolver ran. The REST API Gateway
transport uses a Cognito authorizer that only *authenticates*, so each resolver
(and the dispatcher's `ddb_direct` module) must re-enforce the group check
itself. A `curl`/`idp-cli` smoke test with an admin identity does **not**
exercise per-role RBAC, so group regressions (a Viewer reaching an Admin-only
op, a resolver soft-denying with HTTP 200, a broken argument mapping) slip
through. This script catches them.

Per operation it verifies:
- unauthenticated → `401`
- a **disallowed** role → `403` (`errorType: "Unauthorized"`)
- an **allowed** role → not denied (read ops use valid args, so a `BadRequest`
  flags an arg-mapping regression; mutation ops use nonexistent ids, so a
  benign validation error is expected and only proves auth passed)
- backend/IAM-only ops (e.g. `updateAgentJobStatus`) → `403` for every Cognito role

**Basic usage:**
```bash
# Full run: create test users, test all ops x 4 roles, tear down. Exit 0 = pass.
AWS_PROFILE=default python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2

# Iterate faster (keep users between runs):
python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2 --setup-only
python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2 --no-teardown
python3 scripts/test_api_rbac.py --stack-name IDP1 --region us-west-2 --teardown-only
```

**When to use:**
- After any change to a UI-facing resolver, the dispatcher, `ddb_direct`, or the
  REST client's argument mapping.
- Before merging changes to `nested/api-resolvers/` — to confirm RBAC parity with
  the AppSync schema is preserved.
- When adding a new operation: add it to `READ_OPS`/`MUTATION_OPS` with its
  required groups (mirroring the directive in `schema.graphql`).

**Safety:** Test users are `test-rbac-<role>@example.invalid` (created and
deleted by the script); mutation ops use nonexistent ids so allowed callers hit
benign validation, not real data. The script temporarily enables
`ALLOW_ADMIN_USER_PASSWORD_AUTH` on the UI app client and **always** reverts it
(even on failure). Nothing is destructive to stack data.

**Requirements:** AWS CLI v2 on `PATH`; credentials with Cognito admin +
CloudFormation read (the same credentials used for `idp-cli deploy`). Resolves
the UI user pool, app client, and API base URL from the stack — no hardcoding.

## Operational Commands (via idp-cli)

The following operations are available through the IDP CLI tool:

| Operation | CLI Command |
|-----------|-------------|
| Document status lookup | `idp-cli status --stack-name <name> --document-id <id>` |
| Batch status | `idp-cli status --stack-name <name> --batch-id <id>` |
| Stop workflows | `idp-cli stop-workflows --stack-name <name>` |
| Load testing | `idp-cli load-test --stack-name <name> --rate 2500` |
| Remove residual resources | `idp-cli remove-deleted-stack-resources --dry-run` |

See [CLI Documentation](../docs/idp-cli.md) for complete command reference.

## Migration Notes

The following scripts were migrated to the `idp-cli` tool and removed from this directory:

| Removed Script | Replacement CLI Command |
|----------------|------------------------|
| `lookup_file_status.sh` | `idp-cli status --stack-name <name> --document-id <id>` |
| `simulate_load.py` | `idp-cli load-test --stack-name <name> --rate 100` |
| `simulate_dynamic_load.py` | `idp-cli load-test --stack-name <name> --schedule schedule.csv` |
| `stop_workflows.sh` | `idp-cli stop-workflows --stack-name <name>` |
| `cleanup_orphaned_resources.py` | `idp-cli remove-deleted-stack-resources --dry-run` |

The CLI provides a unified interface with better error handling, progress display, and consistent options.
See [IDP CLI Documentation](../docs/idp-cli.md) for complete usage.

## Related Documentation

- [IDP CLI Documentation](../docs/idp-cli.md)
- [Deployment Guide](../docs/deployment.md)
- [Development Setup](../docs/setup-development-env-macos.md)
- [GovCloud Deployment](../docs/govcloud-deployment.md)