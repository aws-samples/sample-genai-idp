# Code Review Checklist — GenAI IDP Accelerator

## Pre-Submit Checks (REQUIRED)
Run these before every commit:
```bash
make lint               # Full lint (ruff + format + ARN + buildspec + UI + codegen)
make test               # All tests
make typecheck          # basedpyright
```
Or use the convenience command:
```bash
make commit             # lint + test + auto-generate commit message + push
make fastcommit         # fastlint (skip UI) + auto-commit + push
```

## Python Backend Review

### Style & Formatting
- [ ] `ruff check --fix` passes clean
- [ ] `ruff format` applied (double quotes, 88-char lines)
- [ ] basedpyright passes (basic mode)
- [ ] License header present: `# Copyright Amazon.com, Inc. ...` + `# SPDX-License-Identifier: MIT-0`

### Lambda Functions
- [ ] Handler is `handler(event, context)` in `index.py`
- [ ] X-Ray tracing: `patch_all()` at module level
- [ ] AWS clients initialized at module level (not inside handler)
- [ ] Logging via `logging.getLogger()` with `LOG_LEVEL` env var
- [ ] Type hints on function signatures
- [ ] Explicit `ClientError` catches with `exc_info=True`
- [ ] No hardcoded AWS account IDs or regions

### idp_common Library
- [ ] New modules use lazy loading pattern (register in `__init__.py.__getattr__`)
- [ ] Modular dependency groups updated if new deps added (`pyproject.toml`)
- [ ] No direct imports from `idp_sdk._core` (use `IDPClient`)
- [ ] Tests added mirroring module structure in `tests/unit/`

## Frontend UI Review

### Style & Formatting
- [ ] ESLint passes (`make ui-lint`)
- [ ] Prettier applied (140-char lines, single quotes, trailing commas)
- [ ] TypeScript strict mode passes (`npm run typecheck`)

### Component Standards
- [ ] Arrow function components (not `function` declarations)
- [ ] Cloudscape Design System components used (not Material UI, Ant Design, etc.)
- [ ] `ConsoleLogger` for logging (not `console.log` in production code)
- [ ] Context API for state (not Redux)
- [ ] New hooks use kebab-case filenames (`use-my-hook.ts`)

### GraphQL
- [ ] If schema changed, `make codegen` run and committed
- [ ] Generated files (`src/graphql/generated/`) not manually edited

## Infrastructure Review

### CloudFormation Templates
- [ ] `make check-arn-partitions` passes — NO hardcoded `arn:aws:`
- [ ] Service endpoints use `${AWS::URLSuffix}` — NO hardcoded `amazonaws.com`
- [ ] PermissionsBoundary conditional on all IAM roles
- [ ] Dedicated LogGroup per Lambda with KMS encryption
- [ ] cfn-nag + checkov suppression metadata where needed (with justification)
- [ ] `make validate-buildspec` passes

### Security
- [ ] No credentials, API keys, or secrets in code or templates
- [ ] No full JWT tokens logged in plaintext (Talos finding #10)
- [ ] S3 access properly scoped (no wildcard resource ARNs without justification)
- [ ] Input validation on all API endpoints
- [ ] DOMPurify used for any HTML rendering in UI

## Documentation
- [ ] New features documented in `docs/`
- [ ] YAML frontmatter with `title` field
- [ ] License header after frontmatter
- [ ] `CHANGELOG.md` updated for user-facing changes
- [ ] Cross-references to related docs where appropriate

## Testing
- [ ] Unit tests added (`@pytest.mark.unit`)
- [ ] Tests use `moto` `@mock_aws` for AWS service mocking
- [ ] Class-based test organization with `setup_method`
- [ ] Test files mirror module structure in `tests/unit/`
- [ ] Integration tests tagged with `@pytest.mark.integration`
- [ ] Config library validation tests pass: `make test-config-library`

## Git Workflow
- [ ] Branch from `develop` using prefix: `feature/`, `fix/`, `docs/`
- [ ] Focused, single-issue changes
- [ ] Version bump if needed: `make version V=x.y.z` (PEP 440 compliant)
