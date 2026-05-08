# Next Steps — May 8, 2026

**Previous next-steps doc (2026-05-04) is superseded by this one.**

## What's deployed and working

- **27 Strands tools** wrapping the full idpac toolkit + `image_reader` + `execute_python_analysis`, deployed on AgentCore
- **Fire-and-forget architecture** with S3 polling (stream + optimization log)
- **S3SessionManager** — zero NFS pressure, ENOSPC workaround confirmed
- **Run history sidebar** from DynamoDB + resume button for failed/cancelled runs
- **Optimization loop** properly stops at max iterations and max cost
- **FileReadSafetyHook** — forces `file_read` to `mode=view`, prevents image/document crash
- **Image resize** — `download_input_document` auto-resizes images >4MB for Bedrock's 5MB limit
- **Reward hacking guardrail** — `config_edit` rejects `x-aws-idp-evaluation-*` changes, shell/editor/file_write removed
- **Cost observability** — Real-time agent + eval cost tracking via `CostTrackingHook`, displayed in UI
- **Prompt caching** — System prompt, tools, messages cached (10x cheaper input reads)
- **Proactive context management** — Summarizes at 50% context fill, re-injects optimization log
- **Deterministic iteration counting** — Auto-incremented on `run_evaluation(n_files=0)`
- **Max cost stop** — Triggers finalizing when total cost exceeds limit
- **Max allowable cost per page** — Required input at run launch, budget warning in eval summaries, CRITICAL constraint in system prompt
- **Consolidated status field** — Single `status` carries lifecycle + activity info
- **Collapsible sidebar, full-width chat, context window % in UI**
- **Model:** `us.anthropic.claude-opus-4-6-v1`
- **IDP stack:** `kaleko-IDPAutoTune-dev` with test sets `realkie-fcc-verified` (75 FCC invoices) and `davids-test-dataset` (45 multi-class images)
- **Amplify URL:** https://main.d2hvyoqfm7h5q6.amplifyapp.com

## What was done May 8

- **Max allowable cost per page** — Required UI input, stored in DDB, passed to agent via env var + prompt + optimization log. `get_evaluation_summary` warns when cost exceeds budget. System prompt marks this as CRITICAL non-negotiable constraint.
- **Renamed DDB fields** — `best_accuracy` → `best_accuracy_within_budget`, `best_config_version` → `best_config_version_within_budget` (semantics: best viable config for the user's budget).
- **Discovery schema mismatch investigation** — Confirmed GT IS being passed (PR fix works), but the discovery prompt in `idp_common` has conflicting instructions causing the model to reorganize GT structure. Repro sent to IDP service team (`autotune/planning-docs/discovery-schema-mismatch/`).

## Completed priorities (from previous next-steps)

- [x] ~~Priority 1: Silent Evaluation Failure Investigation~~ — Documented, deferred to IDP team
- [x] ~~Priority 2: Reward Hacking Guardrail~~ — Done (May 5)
- [x] ~~Priority 3: Cost Observability~~ — Done (May 5)
- [x] ~~Max allowable cost per page at run launch~~ — Done (May 8)

## Next priorities

1. **Discovery schema mismatch fix** — Awaiting IDP service team response on prompt fix in `_prompt_classes_discovery_with_ground_truth`. If no fix forthcoming, consider a workaround in AutoTune (post-process discovered schema to match GT structure).

2. **Test proactive context summarization** — Verify the `ProactiveContextManager` triggers correctly at 50% and that the log re-read works.

3. **Silent evaluation failure investigation** — IDP-side bug where eval runs get stuck at 0 completed files. Needs standalone investigation doc for colleague.

4. **Automatic optimization log updates** — Agent frequently forgets to update OPTIMIZATION-LOG.md. Options: AfterToolCallEvent hook + lightweight subagent, or template-based append.

5. **Improve `validate_config`** — Catch configs that pass validation but break the pipeline (e.g., LLM responds "I don't see any document").

## Remaining TODO items (from dev plan 6.8)

- [ ] Scope IAM resource ARNs to specific IDP stack resources
- [ ] Bundle IDP source code in container
- [ ] Doom loop detection (programmatic oscillation detection)
- [ ] Optimization run history from DynamoDB (replace localStorage)
- [ ] Resume interrupted runs (UI button for failed/cancelled/stalled)
- [ ] Configure `idleRuntimeSessionTimeout` higher
- [ ] IDP feature request: hide test execution documents from main document list
- [ ] Research harness engineering (Anthropic, OpenAI papers)
- [ ] Monitor prompt cache hit rate

## Deploy commands

```bash
# Backend
cd autotune/fast-template/infra-cdk
AWS_EC2_METADATA_DISABLED=true CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text) CDK_DEFAULT_REGION=us-east-1 npx cdk deploy --require-approval never

# Frontend
cd /home/ubuntu/gitlab/genaiic-idp-accelerator
python autotune/fast-template/scripts/deploy-frontend.py kaleko-FAST-IDPAT-dev --region us-east-1

# Lint before frontend deploy
cd autotune/fast-template/frontend && npx tsc --noEmit && npm run lint
```

## Git state

- Branch: `feature-private/idp-autotune/initial-port`
- Last commit: `0161e596` — feat: max allowable cost per page constraint + discovery schema mismatch repro
