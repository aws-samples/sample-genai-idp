# Next Steps — May 1, 2026

## What's deployed and working

- **25 Strands tools** wrapping the full idpac toolkit, deployed on AgentCore
- **Fire-and-forget architecture** with S3 polling (stream + optimization log)
- **S3SessionManager** — zero NFS pressure, ENOSPC workaround confirmed (run survived 1+ hours)
- **Run history sidebar** from DynamoDB + resume button for failed/cancelled runs
- **Optimization loop** properly stops at max iterations
- **Model:** `us.anthropic.claude-opus-4-6-v1`
- **IDP stack:** `kaleko-IDPAutoTune-dev` with test sets `realkie-fcc-verified` (75 FCC invoices) and `davids-test-dataset` (45 multi-class images)
- **Amplify URL:** https://main.duq4hhla5pfaq.amplifyapp.com

## Priority 1: Silent Evaluation Failure Investigation

**What:** IDP evaluation runs sometimes get stuck at 0 completed files, RUNNING status indefinitely. The agent wastes entire iterations waiting for runs that will never complete.

**Evidence from session `ed4e4ec5`:**
- v2 run: all 75 files failed with "I don't see any document or image attached" (extraction model didn't receive OCR output)
- v1, v3 runs: stuck at 0 completed files, RUNNING status for 20+ minutes
- Agent's own analysis: "All runs including those from over an hour ago still show 0 completed files"

**This is an IDP-side bug, not AutoTune.** Create a standalone investigation doc (`autotune/planning-docs/silent-eval-failure-investigation.md`) for a colleague to follow. Steps:

1. **Reproduce locally** — Download configs from the IDP stack that caused the failure:
   ```bash
   source autotune/.venv/bin/activate
   idp-cli config-download --stack-name kaleko-IDPAutoTune-dev --config-version v2 --output /tmp/investigation/v2.yaml
   ```
   Already downloaded to `/tmp/silent-eval-investigation/v2.yaml` (and v1, v3, managed).
   Run with:
   ```bash
   idp-cli run-inference --stack-name kaleko-IDPAutoTune-dev --config-version v2 --test-set realkie-fcc-verified
   ```
   Note: a test run on April 30 evening with v2 config appeared to work — the issue may be intermittent or the config may have been overwritten by a later agent run.

2. **If not reproducible with existing configs** — Launch an AutoTune run on `davids-test-dataset` and watch for the agent to create a config that triggers the issue. Monitor via the stream endpoint.

3. **Root cause investigation** — Look at IDP pipeline logs (Step Functions, Lambda) for the stuck batch. Check if:
   - Documents were queued to SQS but never picked up
   - Lambda processing failed silently (no error, no output)
   - Config caused the processing Lambda to skip documents (e.g., malformed schema)
   - Race condition in batch tracking (batch created but documents not yet visible)

4. **Desired fix** — `idp-cli run-inference` / `run-evaluation` should fail fast with a clear error if the config causes documents to be silently skipped. Zero documents processed after N minutes should be an error, not eternal RUNNING.

5. **AutoTune workaround (if IDP fix is slow)** — Add timeout + retry logic in `run_evaluation` tool: if `check_evaluation_status` shows 0 completed files after 5 minutes, abort and surface error to agent.

## Priority 2: Reward Hacking Guardrail

**What:** The agent can modify evaluation metric definitions in the config (e.g., changing `x-aws-idp-evaluation-method` from `EXACT` to `FUZZY`, relaxing thresholds) to artificially inflate accuracy without improving extraction quality.

**Implementation:**
1. Identify which config sections define evaluation metrics vs. extraction behavior:
   - Metric-defining: `x-aws-idp-evaluation-method`, `x-aws-idp-evaluation-threshold`, `x-aws-idp-evaluation-weight` on individual fields
   - Extraction behavior: `extraction.model`, `extraction.task_prompt`, `classes[*].properties`, `classification.*`
2. In `upload_config` tool: before uploading, compare the new config against the baseline (first uploaded version). If any `x-aws-idp-evaluation-*` attributes changed, reject the upload with an error explaining why.
3. Alternative: strip `x-aws-idp-evaluation-*` changes silently and log a warning.

**Key files:** `autotune/agent/tools.py` (`upload_config` function)

## Priority 3: Cost Observability

**What:** Track and display total cost per optimization run.

**Cost components:**
1. **Agent token usage** — Opus input/output tokens. Strands exposes this via `agent.token_count` or callback hooks.
2. **IDP pipeline costs** — Each evaluation run's `get_evaluation_summary` returns `totalCost` and `costBreakdown`. Aggregate across all eval runs in a session.
3. **AgentCore compute** — microVM runtime hours (harder to track, may need CloudWatch metrics).

**Implementation:**
1. Add `total_agent_tokens`, `total_agent_cost`, `total_eval_cost` fields to DynamoDB state item
2. After each agent turn, update token counts (via Strands callback or `AfterInvocationEvent` hook)
3. After each `get_evaluation_summary`, extract `totalCost` and accumulate
4. Display in UI status bar and run history sidebar
5. Write cost summary to OPTIMIZATION-LOG.md at end of run

**Key files:** `autotune/agent/hooks.py`, `autotune/agent/tools.py` (`get_evaluation_summary`), `autotune/agent/state.py`, frontend components

## Priority 4: Automatic Optimization Log Updates

**What:** The agent frequently forgets to update OPTIMIZATION-LOG.md despite repeated prompt instructions.

**Options (in order of preference):**
1. **AfterToolCallEvent hook + lightweight subagent** — After each tool call, a small subagent (Haiku/Nova Lite) appends a one-line summary to the log. Decouples log maintenance from main agent reasoning.
2. **AfterToolCallEvent hook + template-based append** — No LLM call. Just append `[timestamp] Tool: {name}, Result: {summary}` to the log. Cheaper but less intelligent summaries.
3. **Stronger prompt instructions** — Already tried, insufficient.

**Key consideration:** Cost of extra LLM calls (option 1) vs. quality of log entries. Option 2 is free but produces mechanical logs. Option 1 produces human-readable summaries but adds ~$0.01 per tool call.

**Key files:** `autotune/agent/hooks.py`, `autotune/fast-template/patterns/strands-single-agent/basic_agent.py`

## Other TODO items (not prioritized for tomorrow)

These are tracked in `AUTOTUNE-DEVELOPMENT-PLAN.md` section 6.8:
- Test set ID dropdown in UI (replace text input with API-backed dropdown)
- Bundle IDP source code in container (for agent to read/debug)
- SummarizingConversationManager (when context overflow observed)
- Doom loop detection (programmatic oscillation detection)
- Small validation runs before full evaluation
- IDP feature request: hide test execution documents from main document list

## Deploy commands

```bash
# Backend
cd autotune/fast-template/infra-cdk
AWS_EC2_METADATA_DISABLED=true CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text) CDK_DEFAULT_REGION=us-east-1 npx cdk deploy --require-approval never

# Frontend
cd /home/ubuntu/gitlab/genaiic-idp-accelerator
python autotune/fast-template/scripts/deploy-frontend.py IDPAutoTune --region us-east-1

# Lint before frontend deploy
cd autotune/fast-template/frontend && npx tsc --noEmit && npm run lint
```

## Git state

- Branch: `feature-private/idp-autotune/initial-port`
- Working tree: clean
- Last commit: `42d90339c` — docs: add 6.12 session notes and update next priorities
