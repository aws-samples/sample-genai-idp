# IDPAutoTune State Persistence

## Overview

The AutoTune agent runs on AgentCore for extended periods (1–3 hours per optimization run). It writes state — optimization logs, config YAML files, evaluation results — and needs that state to survive for the duration of the run and be viewable by the frontend. On resume after a crash, state is restored from S3.

## Storage Architecture (Current)

All state lives on `/tmp` (ephemeral overlay) + S3 sync. **`/mnt/workspace` (AgentCore persistent filesystem) is NOT used** due to a known ENOSPC bug in the NFS metadata layer.

### `/tmp/autotune-data/{session_id}/` — All agent data (8.8 GB overlay)

The container's root overlay filesystem. Large, fast, no NFS issues — but wiped when the microVM is torn down.

**What goes here (everything):**
- `OPTIMIZATION-LOG.md` — the agent's structured optimization journal
- Downloaded evaluation results
- Config YAML files (created, downloaded, edited by the agent)
- `stream.jsonl` (agent event stream, synced to S3 every 10s)
- `disk-usage.jsonl` (monitoring data, synced to S3)
- Any other data the agent needs for analysis

### S3 stream bucket — Durable, unlimited

The dedicated stream bucket (`AUTOTUNE_STREAM_BUCKET`) stores everything that needs durability:

- **Strands conversation history** (`autotune-sessions/`) — via `S3SessionManager`. Loaded automatically by Strands on session resume.
- **Agent event stream** (`autotune-streams/{session_id}/stream.jsonl`) — synced from /tmp every 10s. Frontend polls via `GET /stream`.
- **Optimization log** (`autotune-streams/{session_id}/OPTIMIZATION-LOG.md`) — synced from /tmp every 10s. Frontend polls via `GET /log`. Downloaded back to /tmp on resume.
- **Disk usage diagnostics** (`autotune-streams/{session_id}/disk-usage.jsonl`)

### DynamoDB — Control plane

`IDPAutoTune-OptimizationState` table stores run metadata: status, phase, iteration, accuracy, cost, heartbeat. Polled by frontend via `GET /state`.

## Session Resume

When a run fails or is cancelled, the user can click "Resume" in the UI:

1. Frontend sends the same `runtimeSessionId` with `resume: "true"` in the payload
2. AgentCore spins up a new microVM (fresh `/tmp`)
3. Backend sets DynamoDB status back to `running`, skips state re-initialization
4. `S3SessionManager` loads full conversation history from S3
5. `OPTIMIZATION-LOG.md` is downloaded from S3 to `/tmp/autotune-data/{session_id}/`
6. Eval cost accumulator is seeded from DynamoDB
7. Agent receives a resume prompt: "Read OPTIMIZATION-LOG.md and continue where you left off"

Scratch data (downloaded eval results, configs) is gone on resume — the agent re-downloads as needed.

## ENOSPC Issue — Why /mnt/workspace Is Disabled

### The problem

The agent consistently hit `[Errno 28] No space left on device` on `/mnt/workspace` even with 0 bytes of actual data written. The NFS mount reports 0% used via `df` but still throws ENOSPC.

### Root cause

AgentCore's NFS mount has a **metadata budget** (~50 MB) that is exhausted by file creation operations. A **known AgentCore NFS bug** (reported by Walkley He, April 13, `#bedrock-agentcore-runtime-interest`) causes premature ENOSPC even with minimal writes. 96.8% NFS WRITE error rate observed. No resolution as of May 2026.

### Decision

Rather than working around a broken feature, we disabled `/mnt/workspace` entirely:
- Removed `FilesystemConfigurations` from CDK
- All files written to `/tmp` (ephemeral overlay, 8.8 GB, reliable)
- S3 sync provides durability for the optimization log and conversation history
- DynamoDB provides durability for run state/metrics

### TODO: Revisit when AgentCore improves

- [ ] **AgentCore NFS bug fix** — Monitor `#bedrock-agentcore-runtime-interest` for resolution
- [ ] **AgentCore Runtime Instances (June 2026 target)** — EC2-based, no NFS quota issues
- [ ] **S3 Files mount** — Unlimited storage via S3 NFS mount (requires VPC, ~$32/month NAT)
