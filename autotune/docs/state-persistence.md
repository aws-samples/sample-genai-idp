# IDPAutoTune State Persistence

## Overview

The AutoTune agent runs on AgentCore for extended periods (1–3 hours per optimization run). It writes state to the filesystem — optimization logs, config YAML files, evaluation results — and needs that state to survive compute teardown, idle timeouts, and redeployments. Conversation history must also persist so the agent can resume where it left off.

## Storage Architecture

The agent uses three storage layers:

### `/mnt/workspace/{session_id}/` — Persistent NFS (1 GB, metadata-limited)

AgentCore Persistent Filesystem (Preview). Mounted via `FilesystemConfigurations` in CDK. Data is async-replicated to durable S3-backed storage. When the same session is resumed with the same `runtimeSessionId`, a new microVM mounts the same storage.

**What goes here (only this):**
- `OPTIMIZATION-LOG.md` — the agent's structured optimization journal. Read on resume to understand what was done. This is the single most critical file for session continuity.

**Nothing else.** See ENOSPC lessons learned below.

### S3 stream bucket — Durable, unlimited

The dedicated stream bucket (`AUTOTUNE_STREAM_BUCKET`) stores everything that needs durability but doesn't need local filesystem access:

- **Strands conversation history** (`autotune-sessions/`) — via `S3SessionManager`. One JSON file per message, stored as S3 objects. Loaded automatically by Strands on session resume.
- **Agent event stream** (`autotune-streams/{session_id}/stream.jsonl`) — synced from scratch every 10s. Frontend polls this via `GET /stream`.
- **Optimization log mirror** (`autotune-streams/{session_id}/OPTIMIZATION-LOG.md`) — synced from `/mnt/workspace` every 10s. Frontend polls this via `GET /log`.
- **Disk usage diagnostics** (`autotune-streams/{session_id}/disk-usage.jsonl`) — monitoring data.

### `/tmp/autotune-data/{session_id}/` — Ephemeral scratch (8.8 GB overlay)

The container's root overlay filesystem. Large, fast, no NFS issues — but wiped when the microVM is torn down. That's fine because everything here is either re-downloadable from the IDP stack or synced to S3.

**What goes here:**
- Downloaded evaluation results (`download_evaluation_results`)
- Downloaded raw processing results (`download_raw_processing_results`)
- Config YAML files (created, downloaded, edited by the agent)
- `stream.jsonl` (local copy, synced to S3)
- `disk-usage.jsonl` (local copy, synced to S3)
- Any other bulk/temporary data the agent needs for analysis

The download tools hardcode this path — the agent doesn't choose where files go.

## ENOSPC Issue — Lessons Learned

### The problem

The agent consistently hit `[Errno 28] No space left on device` on `/mnt/workspace` after ~20-42 minutes, despite only 1.5 MB of actual data written (out of a reported 1 GB limit).

### Root cause: NFS metadata limit + Strands FileSessionManager

AgentCore's NFS mount has a **~50 MB metadata limit** (inodes, directory entries) separate from the 1 GB data limit. This limit is not adjustable and not visible via `df -h` (which always reports 0% used).

**Strands `FileSessionManager` was the primary culprit.** It writes **one JSON file per message** to `/mnt/workspace/.sessions/`. Each tool call generates 2 messages (tool use + tool result). An 8-iteration optimization run with ~20 tool calls per iteration creates:

- ~320 message JSON files
- ~320 temporary `.tmp` files (atomic write pattern: write `.tmp`, then `os.replace`)
- Directory entries for `session_*/agents/agent_*/messages/`
- `session.json` and `agent.json` metadata files

That's **~650 file creation operations**, each consuming NFS metadata. At ~4 KB per message file, the data was only 1.13 MB — but the metadata budget was exhausted.

Additionally, a **known AgentCore NFS bug** (reported by Walkley He, April 13, `#bedrock-agentcore-runtime-interest`) causes premature ENOSPC even with minimal writes. 96.8% NFS WRITE error rate observed. No resolution as of April 30.

### Investigation timeline

| Date | What | /mnt usage | Outcome |
|---|---|---|---|
| Apr 29 | All data on /mnt (results + sessions + configs) | ~46 MB | ENOSPC at ~20 min |
| Apr 30 AM | Moved bulk downloads to /tmp, kept sessions + configs on /mnt | ~1.59 MB | ENOSPC at ~42 min |
| Apr 30 PM | Moved sessions to S3, only OPTIMIZATION-LOG.md on /mnt | ~0.25 MB | **Pending verification** |

### The fix: S3SessionManager

Switched from `FileSessionManager` (local NFS) to `S3SessionManager` (S3 bucket):

```python
# Before — hundreds of files on NFS
session_manager = FileSessionManager(session_id=session_id, storage_dir="/mnt/workspace/.sessions")

# After — zero files on NFS, objects in S3
session_manager = S3SessionManager(session_id=session_id, bucket=stream_bucket, prefix="autotune-sessions")
```

Same per-message storage structure, but S3 objects instead of NFS files. S3 has no metadata limit. The stream bucket already existed for `stream.jsonl` and log syncing, so no new infrastructure was needed — just IAM permissions for `s3:GetObject`, `s3:DeleteObject`, and `s3:ListBucket` (in addition to existing `s3:PutObject`).

### Why not just disable session persistence?

The agent benefits from Strands conversation history on resume — it provides full context of what was said, what tools were called, and what results came back. Without it, the agent only has OPTIMIZATION-LOG.md (which it sometimes forgets to update). S3SessionManager gives us both: durable conversation history with zero NFS pressure.

### TODO: Revisit when AgentCore improves

- [ ] **AgentCore NFS bug fix** — Monitor `#bedrock-agentcore-runtime-interest` for resolution. Posted details in Slack thread, awaiting response from AgentCore team.
- [ ] **AgentCore Runtime Instances (June 2026 target)** — EC2-based persistent compute with full OS access. No NFS quota issues.
- [ ] **Storage limit increase at GA** — Customers have requested 10-30 GB. If metadata limit is also increased, could move sessions back to local filesystem for faster reads.
- [ ] **S3 Files mount** — Unlimited storage via S3 NFS mount. Requires VPC mode (~$32/month NAT gateway).

## Session Resume

When a run fails (ENOSPC or otherwise), the user can click "Resume" in the UI:

1. Frontend sends the same `runtimeSessionId` with `resume: "true"` in the payload
2. AgentCore spins up a new microVM with the same `/mnt/workspace` mount
3. Backend sets DynamoDB status back to `running`, skips state re-initialization
4. `S3SessionManager` loads full conversation history from S3
5. Agent receives a resume prompt: "Read OPTIMIZATION-LOG.md and continue where you left off"
6. Agent reads the log from `/mnt/workspace/{session_id}/OPTIMIZATION-LOG.md` and continues

Scratch data (`/tmp`) is gone on resume — the agent re-downloads evaluation results as needed.

## Infrastructure

Persistent filesystem configured via L1 escape hatch in CDK:

```typescript
const cfnRuntime = this.agentRuntime.node.defaultChild as cdk.CfnResource
cfnRuntime.addPropertyOverride("FilesystemConfigurations", [
  { SessionStorage: { MountPath: "/mnt/workspace" } },
])
```

The agent detects the mount at startup and falls back for local testing:

```python
WORKSPACE_DIR = "/mnt/workspace" if os.path.isdir("/mnt/workspace") else "/tmp/workspace"
SCRATCH_DIR = "/tmp/autotune-data"
```

## Limitations

- **Preview feature** — no SLA, API may change.
- **Per-session isolation** — each `runtimeSessionId` gets its own `/mnt/workspace`.
- **`df` is unreliable** — NFS mount always reports 0% used. Use Python `os.walk` for measurement.
- **14-day inactivity expiry** — storage cleaned up after 14 days of no access.
- **Deploy wipe risk** — storage may be wiped on container image changes.
- **Scratch data is ephemeral** — anything on `/tmp` is lost when the microVM is torn down.
