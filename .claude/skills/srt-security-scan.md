# SRT Security Scan — Running, Triaging, Suppressing & Mitigating

Use this skill whenever you run the [Sample Security Review Tool
(SRT)](https://github.com/aws-samples/sample-security-review-tool) — via
`make srt-scan` / `make srt` — or when CI's `security_review` stage fails on
an MR to `develop`. It covers reproducing the scan, telling real issues from
false positives, and the two ways to make a HIGH finding go away: **mitigate**
(fix the code) or **suppress** (record accepted-risk / scanner-limitation).

## What SRT is and how the gate works

- `make srt-setup` downloads the `srt` binary into `.srt/`, writes
  `.srt/srtconfig.json`, installs prerequisites, and **copies the committed
  baseline `scripts/srt/issues.json` → `.srt/issues.json`** (this is how
  suppressions are restored).
- **Prerequisites are five scanners** — `checkov`, `semgrep`, `bandit`, `syft`
  (`anchore_syft`), `jupyter` — that SRT pip-installs into its OWN managed venv
  at `.srt/.venv/bin/` (NOT the system PATH). `srt assess` calls
  `checkAllInstalled()` and aborts with **`✗ Prerequisites not installed. Run
  'srt config' first`** (exit 1) if **any one** is missing. **Contrary to older
  guidance, semgrep is NOT optional** for SRT ≥ v1.0.2 — a missing semgrep
  blocks the scan exactly like any other scanner. `scripts/srt/setup.py` now
  verifies all five landed in the venv, retries `./srt config
  --reinstall-prerequisites` once, and hard-fails the setup step in CI if they
  didn't (instead of printing a misleading "✅ setup complete"). A cold install
  (no pip cache) of all five is slow (~10-15 min); the CI job allows 50 min.
- `make srt-scan` runs `scripts/srt/run.py`, which shells out to
  `./srt assess -y -p <repo> --no-diagrams --no-threat-models --no-license-update`.
  SRT merges new findings into `.srt/issues.json`, then `run.py` parses that
  file and prints the `OPEN HIGH PRIORITY SECURITY ISSUES` table.
- **The gate = HIGH priority AND `status == "Open"`.** Medium/Low never block.
  Suppressed/resolved/fixed never block.
- **Exit code differs by environment** (`run.py`):
  - **CI** (`CI`/`GITLAB_CI`/`GITHUB_ACTIONS` set): exits **1** on any HIGH-open
    → pipeline fails.
  - **Local**: exits **0** even with findings and prints a "run `make srt-fix`"
    hint. So **read the printed table / `.srt/issues.json`, never trust the
    local exit code.**
- The scan itself is Bedrock-backed and **slow (~5–15 min)**; `run.py` buffers
  through `tail`, so you see nothing until it finishes. Run it in the background
  and wait — don't assume it hung.

## CRITICAL: local scans see more than CI

CI runs on a **clean checkout of tracked files only**. Your working tree
usually has gitignored dirs that SRT will happily scan and flag, producing
findings that **do not exist in CI**:

- `.aws-sam/`, `**/.aws-sam/packaged.yaml` — SAM build artifacts (the `srt-clean`
  target strips these; CI checkouts never have them)
- `scratch/`, `subscription-features/`, vendored Lambda `layer/python/` trees —
  gitignored; full of third-party code (botocore, aiohttp, sympy, …) that trips
  bandit B105/B106/B324/B602 by the hundred

**Before triaging, reconcile your finding list against CI by dropping anything
gitignored.** A finding only matters if its file is tracked:

```bash
# For each open-HIGH path, is it actually in the CI checkout?
git check-ignore -q "<path>" && echo "IGNORED (not in CI)" || echo "in CI"
git ls-files --error-unmatch "<path>"   # exit 0 = tracked
```

If the user reports N findings and your local scan shows many more, the extra
ones are almost always gitignored — confirm, then focus only on the tracked
subset. (To match CI exactly, run `make srt-clean` first, and/or scan a fresh
`git archive` / clean clone.)

## Reproducing a scan locally

```bash
make srt-setup     # one-time (or after upgrading SRT); restores suppressions
make srt-scan      # ~5–15 min; run in background
```

If `srt assess` errors with **"Configuration not found. Run: srt config"**, the
`.srt/srtconfig.json` is missing. Recreate it (non-interactive) and install
prereqs:

```bash
cat > .srt/srtconfig.json <<'EOF'
{ "AWS_PROFILE": "default", "AWS_REGION": "us-east-1",
  "TELEMETRY_ENABLED": false, "INSTALLATION_ID": "local-dev" }
EOF
( cd .srt && yes '' | ./srt config )   # installs all 5 scanners into .srt/.venv/bin/
# Verify every scanner landed — assess needs ALL of them (a missing one → "Prerequisites not installed"):
ls .srt/.venv/bin/{checkov,semgrep,bandit,syft,jupyter}
cp scripts/srt/issues.json .srt/issues.json   # restore suppressions before re-scan
```

Uses the `default` AWS profile (needs Bedrock access) — see the AWS-access note
in CLAUDE.md. To list current HIGH-open findings without re-scanning:

```bash
python3 -c "import json;[print(i['source'],i.get('check_id'),i['path'],i.get('line'),i.get('resourceName')) \
  for i in json.load(open('.srt/issues.json')) \
  if (i.get('priority') or '').upper()=='HIGH' and i.get('status')=='Open']"
```

## Triage: real issue → mitigate; false positive / accepted risk → suppress

For every HIGH-open finding, decide **mitigate vs suppress**. Default to
mitigating; suppress only with a specific, defensible justification.

**Mitigate (fix the code)** when the finding is a genuine weakness: missing
encryption, over-broad IAM, a real hardcoded secret, public resource that
shouldn't be, missing logging you actually want. Change the template/code so
the check passes, then re-scan to confirm it flips to resolved.

**Suppress** only when one of these holds — and say which in the reason:
- **Scanner false positive** — the property IS set but the checker can't see it.
  The most common cause in this repo: **the check can't resolve `Fn::If`**, so
  conditionally-set `AccessLogSetting`, `MethodSettings`, etc. read as absent.
  (SRT's security-matrix checks call a `resolveValue` that handles `Ref` but not
  `Fn::If` branches.)
- **Tool heuristic false positive** — e.g. bandit **B105** "hardcoded password"
  fires on any literal assigned near an identifier containing `token`/`secret`/
  `password`/`pwd`/`pass`/`key`/`auth`. A variable/dict-key like
  `shard_token_budget = 40000` trips it though `40000` is an LLM token budget.
- **Accepted architectural risk** — the flagged config is intentional and
  compensated. Example: `AuthorizationType: NONE` on the Web UI SPA static-asset
  routes (`WebUIRootMethod`, `WebUIProxyMethod`) — the browser must fetch
  index.html + hashed assets before the user logs in; a JWT can't ride the
  document fetch. Compensating controls: WAFv2 IP allowlist + PRIVATE-endpoint
  policy still gate the stage, and only non-sensitive static files are exposed.
- **Third-party / vendored code** not in the CI checkout — usually just
  gitignored (see above); prefer excluding it over suppressing each line.

## The two suppression mechanisms

### 1. `# nosec` for Bandit (Python) findings — MITIGATE-in-place

Bandit honors an inline comment. Scope it to the exact test id and add a why:

```python
# nosec B105 - the 40000 literal is an LLM token-budget default, not a
# credential. Bandit's heuristic fires only because the dict key
# "shard_token_budget" contains the substring "token".
DEFAULTS = {"max_tokens": 10000, "shard_token_budget": 40000}  # nosec B105
```

The `# nosec BXXX` must be on the flagged source line. Verify with:
`python3 -m bandit <file>` — the count under "specifically being disabled"
should increment and the issue disappears. This is preferred over a JSON
suppression for Python because the justification lives next to the code.
(Checkov findings similarly honor `# checkov:skip=CKV_AWS_NNN: "reason"`, and
semgrep honors `# nosemgrep: <rule-id> - reason` — both already used in this
repo, e.g. `scripts/srt/run.py`, the WAF WebACL in `nested/api-resolvers`.)

### 2. `scripts/srt/issues.json` for security-matrix / Checkov CFN findings

SRT matches a scan finding to an existing issue by the **4-tuple**
`(path, resourceType, resourceName, check_id)` (see `mergeIssues` in the
binary). To suppress, add an entry with that exact key and
`"status": "suppressed"` plus a `"suppressionReason"`. The scanner emits
`resourceName` = the CloudFormation **logical id** and `path` = the template it
found the resource in (note: it scans **both** the source `template.yaml` **and**
any built `.aws-sam/packaged.yaml`; the `.aws-sam` copy is gitignored/absent in
CI, so suppressing the `template.yaml` path is what matters for the gate).

**The file that counts is the committed `scripts/srt/issues.json`** —
`srt-setup` copies it into `.srt/` at the start of every run, so suppressions
must live there to survive. Editing only `.srt/issues.json` is lost on next
setup.

Entry shape (copy the `issue`/`fix`/`resourceType`/`resourceName`/`check_id`
verbatim from the scan's finding object so the key matches):

```json
{
  "source": "security-matrix",
  "path": "nested/api-resolvers/template.yaml",
  "resourceType": "AWS::ApiGateway::Stage",
  "resourceName": "HttpApiStage",
  "issue": "API Gateway does not have access logging enabled with proper retention",
  "fix": "Ensure both DestinationArn and Format properties are specified in AccessLogSetting",
  "priority": "HIGH",
  "check_id": "API-GW-001",
  "status": "suppressed",
  "isCustomResource": false,
  "firstDetectedAt": "<ISO8601>",
  "assessmentCount": 1,
  "suppressionReason": "Accepted (scanner limitation): AccessLogSetting IS configured with DestinationArn + Format but wrapped in Fn::If [EnableApiAccessLogs], which SRT cannot resolve. Logging is correctly implemented."
}
```

Two ways to add entries:
- **Interactive:** `make srt-fix` walks each open finding and lets you
  suppress with a typed reason — then **commit the updated
  `scripts/srt/issues.json`**.
- **Scripted (when srt-fix isn't practical):** append entries to
  `scripts/srt/issues.json` with a small Python script. Dedupe on the 4-tuple
  key so you don't double-add. Grab the exact finding objects from
  `.srt/issues.json` (the `Open` records) to copy their fields.

After either, restore + re-scan to confirm:
```bash
cp scripts/srt/issues.json .srt/issues.json && make srt-scan
```
The finding should now show `Suppressed` and drop out of the HIGH-open table.

## Verifying and finishing

1. Re-run `make srt-scan` (after `cp scripts/srt/issues.json .srt/issues.json`).
2. Confirm the HIGH-open table no longer lists tracked-file findings (gitignored
   noise may remain locally — that's fine, CI won't see it).
3. **Commit `scripts/srt/issues.json`** and any `# nosec`/`# checkov:skip`
   source edits. Do **not** commit `.srt/` (gitignored binary/cache).
4. In the PR/MR description, list each finding and whether it was mitigated or
   suppressed-with-reason so reviewers can audit the security posture.

## Known-good suppressions already in the baseline (context)

These are accepted and living in `scripts/srt/issues.json` — don't "re-fix":
- **API-GW-001 / API-GW-006** (`HttpApiStage`) — access/execution logging IS set
  behind `Fn::If [EnableApiAccessLogs]`; scanner can't resolve the conditional.
- **API-GW-004** (`WebUIRootMethod`, `WebUIProxyMethod`) — intentional auth-less
  public SPA static-asset routes; WAF + PRIVATE-endpoint policy compensate.
- **API-GW-002** (`HttpApi`) — REST API in Lambda-proxy mode; the dispatcher
  validates each body per-field, request validators add nothing for opaque
  proxy payloads.
- Various **DDB-002 / S3-008 / KMS-007 / EC2-002 / LAMBDA-*** in built
  `.aws-sam/*.yaml` and the bastion/KB stacks — reviewed accepted risks.
