# Tech Context — GenAIIDP

## Core runtimes

| Layer | Tech | Version / constraint |
|-------|------|----------------------|
| Backend Lambdas | Python | **3.12** (target in `ruff.toml`, `pyrightconfig.json`) |
| Build tooling | SAM CLI, Docker, AWS CLI | latest supported |
| Shared library | `idp_common_pkg` | editable install, extras-based |
| Web UI | React 18 + Vite + Cloudscape Design System | Node **22.12+**, npm |
| Docs site | Astro + Starlight | under `docs-site/` |
| CLI | `idp-cli` (click-based) | `lib/idp_cli_pkg/` |
| Infra | CloudFormation + SAM transforms | templates checked with `cfn-lint` |
| Tests | pytest (+ moto), vitest (UI), Jest vestiges | pytest markers: `unit`, `integration` |

## AWS services touched

- **Amazon Bedrock** — foundation models (Claude 3.x/4.x, Nova, Titan embeddings), Bedrock Data Automation (BDA), Bedrock Knowledge Bases.
- **Amazon Textract** — OCR in pipeline mode.
- **AWS Lambda** — ZIP packaging for most functions; container images for some heavier workloads.
- **Step Functions** — workflow engine (`patterns/unified/`).
- **Amazon S3** — Input / Output / Working / Configuration / EvaluationBaseline / WebUI / Seller buckets.
- **Amazon SQS** (+ DLQ) — batch ingestion buffer.
- **Amazon DynamoDB** — Tracking, Concurrency (doubles as circuit-breaker state), Configuration, InstalledFeatures, HITL queue.
- **Amazon EventBridge** — S3→queue trigger, scheduled circuit-breaker health check.
- **Amazon CloudWatch** — dashboards, alarms, metrics, logs.
- **AWS AppSync** — GraphQL API for web UI + feature platform. Split into a dedicated nested template due to CFN resource-count limits.
- **Amazon Cognito** — user pool for UI; *separate* pool + resource server for headless Jobs API OAuth2 client-credentials.
- **Amazon CloudFront** — web UI distribution (commercial only; skipped in `idp-headless.yaml` for GovCloud).
- **Amazon SNS** — alerts topic (+ alarm fan-out).
- **AWS Glue + Amazon Athena** — evaluation analytics reporting.
- **Amazon SageMaker** — historical for Pattern-3 UDOP (removed in unified stack; noted for legacy context).

## Dev environment setup

```bash
# Install everything editable
make setup
# or isolated venv
make setup-venv

# From within lib/idp_common_pkg you can re-install:
cd lib/idp_common_pkg && make dev
```

See `docs/setup-development-env-{linux,macos,windows,WSL}.md` for
platform-specific notes.

## Build / publish

```bash
python3 publish.py <cfn_bucket_basename> <cfn_prefix> <region> [--verbose]
# Uploads to s3://<cfn_bucket_basename>-<region>/<cfn_prefix>/
```

Outputs per version:
- `idp-main_<version>.yaml` (commercial)
- `idp-headless_<version>.yaml` (GovCloud-compatible subset)

## Testing matrix

```bash
make lint              # ruff + ui-lint
make fastlint          # UI skip via checksum
make ruff-lint / format / typecheck
make ui-lint / ui-build

make test              # idp_common_pkg + idp_cli + srt security scan

cd lib/idp_common_pkg && make test-unit
cd lib/idp_common_pkg && make test-integration   # needs real AWS creds

cd idp_cli && pytest -v

# Pytest markers
pytest -m unit
pytest -m integration
```

UI commands (from `src/ui/`):
```bash
npm ci
npm run dev           # Vite dev server
npm run build         # production build
npm run lint          # MUST be clean (per .clinerules global rule)
npm run test          # vitest
```

## Technical constraints

- **Python 3.12** is the only supported backend version. `ruff.toml`
  pins `target-version = "py312"`. Using newer syntax is fine; older
  syntax from 3.9-era compatibility must be removed, not preserved.
- **Line length 88** (ruff default).
- **CloudFormation resource limit** forces the AppSync split-out —
  *do not* add AppSync resources directly to the main template; add
  them to the nested-appsync generator instead.
- **GovCloud compatibility** — avoid hardcoding partition/URL suffix,
  avoid commercial-only services (CloudFront, AppSync) in the headless
  path.
- **Docker required** for Pattern-2 container images at build time (the
  Pattern-2 content lives inside the unified stack now but still builds
  containers).
- **Default Bedrock model access** must be granted in the deploying
  account — Claude 3.x/4.x family, Nova family, Titan Text Embeddings v2.
- **Lambda package size** — modular `idp_common[...]` extras exist to
  keep deps small; do not blindly depend on `idp_common[all]` in a new
  Lambda.

## Tool-usage patterns (for me / Cline)

- **Always run `make` (= `make lint && make test`) before
  `attempt_completion`** — this is mandatory per `.clinerules`.
- **UI changes** — must pass `npm run lint` in `src/ui/` (global rule).
- **Never edit `nested/appsync-nested-template.yaml` directly** — it's
  generated. Edit the source or the generator in `scripts/`.
- **`docs/<topic>.md`** is canonical; `docs-site/` syncs from it via
  `docs-site/sync-sidebar.mjs` + `add-frontmatter.sh`.
- **CHANGELOG.md** — new user-visible changes go under `## [Unreleased]`
  (first section), matching the tone of existing entries (imperative,
  gives *why* not just *what*).
- **Domain skills live in `.cline/skills/`** — consult `backend.md`,
  `frontend.md`, `infra.md`, `extraction.md`, `review.md`, `testing.md`,
  `docs.md`, `pr-review.md` per task domain.
- **Test UI in browser at `http://172.27.128.1:3000`**, login
  `strahanr@amazon.com` / `S1mpl3t0n!` (global `.clinerules/`).
- **Git** — feature branches only (`feature/`, `fix/`, `docs/`); MRs
  into `develop`.

## Dependencies worth knowing

- `strands-agents` — agentic extraction framework used in
  `idp_common/extraction/agentic_idp.py`. Claude 4.7+ rejects deprecated
  `top_p`; both traditional and Strands code paths now share detection
  via `is_claude_4_7_model`.
- `@aws-amplify/api`, `@aws-amplify/auth` v6 — UI auth + GraphQL.
- `boto3` — always the current SAM-runtime-bundled version; no pinning
  in Lambda `requirements.txt`.
- `moto` — mocked AWS for `lib/idp_common_pkg/tests/unit/`.
- `basedpyright` — type-checker (`make typecheck` / `typecheck-stats`).
- `cfn-lint` — run by `publish.py`, also in CI.
- `ruff` — lint + format for all Python.
