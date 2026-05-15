# Product Context — Why GenAIIDP exists

## Problems this project solves

1. **Document backlog at scale**: Enterprises (lending, insurance,
   healthcare, public sector) receive high-volume mixed-document packets
   (PDFs, images, scans) that need to be *read, classified, extracted,
   validated, and filed* into downstream systems. Doing this manually is
   slow and expensive; doing it with point solutions (one vendor for
   classification, another for extraction) creates integration debt.
2. **GenAI is powerful but hard to productionize**: Raw foundation-model
   calls are non-deterministic, fail in long tails, are expensive without
   cost controls, and lack the surrounding workflow (queuing, retries,
   baselining, evaluation) needed for production. GenAIIDP ships all of
   that glue.
3. **GovCloud & regulated customers need the same capability** without
   public internet exposure. The headless + VPC-secured + bastion path
   gives them a private-only deployment variant.
4. **Amazon field teams need a reusable starting point** that showcases
   the Bedrock/Textract/BDA stack end-to-end and can be customized per
   customer engagement (hence the "accelerator" framing and the GenAIIC
   engagement-artifacts repo).

## How the system should work (at a glance)

```
S3:Input → EventBridge → SQS → Queue Processor Lambda
           (concurrency-gated by DDB counter)
           ↓
    Step Functions State Machine
    (unified stack; BDA branch OR Pipeline branch + shared tail)
           ↓
  S3:Output (+ DDB tracking, CloudWatch metrics, AppSync subscriptions)
           ↓
    Web UI (React/Cloudscape via CloudFront) — or —
    Jobs REST API (headless mode) — or —
    idp-cli (batch / programmatic) — or —
    MCP server (Amazon Q / Quick Suite integration)
```

## User / persona goals

| Persona | What they need | Where it lives in the product |
|---------|----------------|-------------------------------|
| Document operator | Upload docs, see status, inspect extractions, download results, request human review | Web UI (`src/ui/`), View Source, Download ZIP, HITL queue |
| Admin / builder | Deploy the stack, configure schemas & prompts, manage evaluation baselines, tune cost knobs | CFN parameters, Configuration DDB, Schema Builder UI, `config_library/` presets |
| Data engineer | Batch process N documents, baseline accuracy, push results to a warehouse | `idp-cli run-inference / download-results / config-validate`, reporting DB, Athena |
| SecOps / compliance | Deploy without public internet, audit logs, rotating keys, GovCloud partition | `DeployInVPC=true`, `EnableHeadless=true`, `DeployBastionHost=true`, SRT scanner, `make check-arn-partitions` |
| Feature author | Publish an "installable" subscription feature that shows up as a new tab in the IDP UI | `lib/idp_feature_sdk`, `idp-feature-cli`, `subscription-features/feature-platform/` |
| Agent / external caller | Query document analytics programmatically | AppSync GraphQL + MCP server + Agent Chat |

## UX principles in effect

- **Nothing destructive by default.** New capabilities ship off; customers
  opt in with a single CFN parameter.
- **Operator-first web UI.** Real-time status via AppSync subscriptions,
  live CircuitBreaker badge, HITL review queue.
- **Admin controls are Cognito-group-gated**, both in the UI and at the
  AppSync resolver layer (defense in depth).
- **Clear failure modes over silent fallbacks.** Examples: CFN `Rules:`
  assertions fail-fast at changeset time for misconfigured VPC/headless
  combos; `idp-cli discover` now hard-errors on mismatched ground truth
  filenames instead of silently running without baseline.
- **Cost awareness baked in.** `pricing.yaml`, `make test` hits
  `config-validate`, Bedrock circuit breaker prevents runaway retries.
