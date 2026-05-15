# Progress — what works, what's left

> Reconstructed from `CHANGELOG.md`, `VERSION`, and current `git status`
> on 2026-05-11.

## Released & working (through v0.5.10)

### Core pipeline

- [x] Unified pattern stack (`patterns/unified/`): BDA branch + Pipeline
  branch + shared tail (rule-validation + summarization).
- [x] Bedrock Data Automation (BDA) path for end-to-end processing.
- [x] Textract OCR → Bedrock classification → Bedrock extraction
  (traditional or agentic via Strands) → assessment → rule validation
  → summarization.
- [x] Agentic extraction with deterministic Markdown table parser,
  page-break fragment merging, and lookahead recovery for OCR artifacts.
- [x] Few-shot examples, page-level + holistic classification,
  extraction confidence assessment.

### Reliability / ops

- [x] **Bedrock circuit breaker** (v0.5.10) with 3-state DDB-backed
  state machine, CloudWatch alarm → SNS → breaker, EventBridge-scheduled
  probe, UI badge + admin Pause/Resume/Probe controls.
- [x] Workflow tracking, concurrency gating via DDB counter.
- [x] SQS batch ingestion with DLQ + retry.
- [x] Per-document Step Functions execution with rich status events.

### Interfaces

- [x] Web UI (React + Cloudscape) — dashboards, document details,
  schema builder, discovery, policy discovery, HITL review, circuit
  breaker badge + admin controls.
- [x] Document-level Download ZIP (all / predictions / baselines)
  preserving bucket layout (v0.5.9).
- [x] **Headless Jobs REST API** (v0.5.9) with per-client ownership,
  presigned up/down URLs, safe zip extraction bounds.
- [x] **VPC-secured deployment** with private API Gateway + bastion
  host SSM tunneling (v0.5.9).
- [x] `idp-cli` with deploy / run-inference / download-results /
  discover / config-upload / config-validate.
- [x] MCP server + Amazon Q / Quick Suite integration (via AWS Bedrock
  AgentCore Gateway).

### Configuration / data

- [x] Configuration table with Default (presets) + Custom layering.
- [x] `config_library/` unified presets: `lending-package-sample`,
  `bank-statement-sample`, `rvl-cdip`, `rvl-cdip-with-few-shot-examples`,
  `realkie-fcc-verified`.
- [x] Policy Discovery + policy_classes rule validation (v0.5.9).
- [x] Managed-preset upload guard (rejects `managed: true`).
- [x] `idp-cli discover --model-id` override + hard-fail on mismatched
  ground truth (v0.5.10).

### Security

- [x] SRT (open-source security scanner) replaces DSR in CI (v0.5.10).
- [x] Cognito UI pool + *separate* Cognito pool for headless OAuth2.
- [x] Defense-in-depth: UI hides admin buttons + AppSync schema auth +
  resolver-layer re-check.
- [x] IMDSv2-required bastion with encrypted EBS + rotating KMS.
- [x] CFN `Rules:` fail-fast for headless/VPC/bastion misconfig.
- [x] Threat-modeling artifacts under `threat-modeling/`.

### Build / SDLC

- [x] `publish.py` multi-region build (us-west-2, us-east-1, eu-central-1).
- [x] `idp-main.yaml` + `idp-headless.yaml` variants per release.
- [x] `make lint` / `make test` / `make srt`.
- [x] UI checksum optimization (skip rebuild when unchanged).
- [x] cfn-lint with E/W regex anchors + commercial-only filtering in
  headless mode.

### Docs

- [x] `docs/` with per-feature deep-dives.
- [x] `docs-site/` (Astro/Starlight) mirror with sidebar sync.
- [x] CHANGELOG kept current per release.

## Unreleased (in `## [Unreleased]` — on `feature/private_marketplace`)

### Feature Platform (prototype, off by default)

- [x] `FeaturePlatformStack` nested stack (DDB `InstalledFeatures` + 7
  Lambdas + AppSync resolvers).
- [x] `SimulatorStack` nested stack (EC2 running a Marketplace-
  compatible REST API) auto-deployed when
  `FeaturePlatformSimulatorEndpoint` is blank.
- [x] Seller bucket + `publish.py` auto-publish of the
  `docs-by-status` sample feature.
- [x] GraphQL surface: `listCatalogFeatures`, `listInstalledFeatures`,
  `checkFeatureEntitlement`, `getFeatureLaunchUrl`,
  `subscribeFeature`, `unsubscribeFeature`.
- [x] Web UI: `FeaturePage` 7-state machine, catalog+installed union
  in nav, admin Subscribe/Cancel buttons, `ActiveSubscriptionBanner`.
- [x] `lib/idp_feature_sdk/` + `idp-feature-cli build|publish`.
- [x] Feature-template scaffold + `docs-by-status` sample feature.
- [x] Docs: `docs/feature-platform.md`, CREATING-A-FEATURE,
  PUBLISHING-A-FEATURE.
- [x] 217 new automated tests (58 main-stack Lambda, 13 e2e, 21 SDK,
  45 simulator, 80 vitest UI), cfn-lint clean, `npm run lint` clean.

### In flight (uncommitted as of 2026-05-11)

- [ ] **Marketplace simulator auto-creates a minimal VPC** when
  `FeaturePlatformSimulatorVpcId` is left blank. Code edits done on disk
  in `subscription-features/marketplace-simulator/template.yaml` and `template.yaml`
  (old `FeaturePlatformSimulatorRequiresVPC` rule removed). Still
  needs: cfn-lint, docs update, CHANGELOG sub-bullet, commit. See
  `activeContext.md` for the exact next-step list.

## Known issues / things to watch

- **`!Ref` to an optional empty-string parameter** is a classic CFN
  foot-gun. The current simulator-VPC change guards every use with
  `!If [CreateMinimalVpc, ..., !Ref VpcId]`; double-check this pattern
  any time a new `VpcId`/`SubnetId` consumer is added.
- **AppSync resource count** — nested template is close to the CFN
  cap. New GraphQL operations should be added to the generator, not
  hand-added to the main template.
- **Pattern-2 container builds** (inside the unified stack) require
  Docker + ECR perms; common stumbling block for new developers.
- **UI `npm run lint` drift** — global `.clinerules/` mandate is to
  run it on every UI change and fix all errors. Easy to forget.
- **GovCloud template divergence** — two templates must stay in lockstep
  for security-relevant changes. Headless mode already omits
  CloudFront/AppSync; anything new must be conditioned similarly if it
  can't run on `us-gov-*`.

## Evolution of project decisions (brief)

- Early on: separate `patterns/pattern-1|2|3/` directories. Unified
  into `patterns/unified/` — the legacy dirs were removed; pattern-1
  and pattern-2 live on only as doc references.
- Security scanner migrated DSR → SRT (open source) in v0.5.10.
- Headless REST API added alongside (not replacing) the web UI to
  enable GovCloud + machine-to-machine integrations.
- Feature Platform added as an opt-in prototype, designed to one day
  plug into real AWS Marketplace. The simulator EC2 was originally a
  dev tool but keeps expanding (now includes auto-VPC provisioning).
- `FeaturePlatformSimulatorRequiresVPC` Rules-based gate was replaced
  by the simulator being self-sufficient — "auto-fix > assert" when the
  fix is cheap and safe.
