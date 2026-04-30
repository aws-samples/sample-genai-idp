# IDPAutoTune State Persistence

## Overview

The AutoTune agent runs on AgentCore for extended periods (1–3 hours per optimization run). It writes state to the filesystem — optimization logs, config YAML files, evaluation results — and needs that state to survive compute teardown, idle timeouts, and redeployments. Conversation history must also persist so the agent can resume where it left off.

## Storage Architecture: Two Filesystems

The agent uses two separate filesystems for different purposes:

### `/mnt/workspace` — Persistent, small files only (1 GB NFS mount)

AgentCore Persistent Filesystem (Preview). Mounted via `FilesystemConfigurations` in CDK. Data is async-replicated to durable S3-backed storage. When the same session is resumed with the same `runtimeSessionId`, a new microVM mounts the same storage.

**What goes here (only these):**
- Strands conversation history (`/mnt/workspace/.sessions/`) — needed for session resume
- `OPTIMIZATION-LOG.md` (`/mnt/workspace/{session_id}/`) — the agent reads this on resume to understand what it's done

### `/tmp/autotune-data/{session_id}/` — Ephemeral scratch space (8.8 GB overlay)

The container's root overlay filesystem. Large, fast, no NFS issues — but wiped when the microVM is torn down. That's fine because everything here is either re-downloadable from the IDP stack or synced to S3.

**What goes here:**
- Downloaded evaluation results (`download_evaluation_results`)
- Downloaded raw processing results (`download_raw_processing_results`)
- Downloaded ground truth files
- Config YAML files (created, downloaded, edited by the agent)
- `stream.jsonl` — synced to S3 every 10s, frontend reads from S3 not filesystem
- `disk-usage.jsonl` — diagnostic monitoring, synced to S3
- Any other bulk/temporary data the agent needs for analysis

The download tools hardcode this path — the agent doesn't choose where files go. Tool output tells the agent where files were saved so it can read them.

## ENOSPC Issue — Why Two Filesystems

### The problem

The agent consistently hits `[Errno 28] No space left on device` after ~20-30 minutes of operation, despite `/mnt/workspace` reporting only ~46 MB of data written (out of a reported 1 GB limit).

### Investigation (April 30, 2026)

We added disk usage monitoring to the background sync thread — a pure-Python `os.walk` snapshot every 10 seconds, uploaded to S3. Findings:

**Container filesystem layout (from `df -h` inside the container):**

| Filesystem | Size | Type | Purpose |
|---|---|---|---|
| `overlay` | 8.8 GB | overlay | Container root (`/app`, `/tmp`, etc.) |
| `127.0.0.1:/export` | 1.0 GB | NFS | Persistent session storage (`/mnt/workspace`) |
| `overlayfs:/overlay/root` | 9.7 GB | overlay | Hosts file overlay |
| `tmpfs` | 64 MB | tmpfs | `/dev`, `/dev/shm` |

**Key observations:**
1. `df -h` reports `/mnt/workspace` at **0% used the entire run** — even when our Python walk measures 46 MB of files. The NFS proxy does not expose accurate usage via `statfs`.
2. The overlay root filesystem stays at ~532 MB (7%) throughout — it's not filling up.
3. ENOSPC triggers at ~46 MB of measured data, well below the reported 1 GB limit.
4. The crash happens suddenly — one snapshot shows 46 MB, 12 seconds later the agent is dead.

**Disk usage progression from a typical failing run (session `bf81d1f3`):**

| Time | /mnt/workspace (walk) | .sessions | Overlay used | Event |
|---|---|---|---|---|
| 14:20 | 0.03 MB | 0 MB | 532M | Agent starts |
| 14:25 | 44.42 MB | ~0.5 MB | 532M | First eval results downloaded |
| 14:44 | 45.75 MB | 1.02 MB | 532M | Iteration 2 analysis |
| 14:51 | 46.10 MB | 1.16 MB | 532M | Polling eval status |
| 14:52 | — | — | — | **ENOSPC** |

### Root cause analysis

Based on internal Slack research and AgentCore documentation:

1. **~50 MB filesystem metadata limit (most likely).** AgentCore session storage has a separate, non-adjustable ~50 MB metadata quota (inodes, directory entries, file attributes). Downloading evaluation results creates hundreds of small files (586 files for 293 documents), each consuming metadata. The metadata budget exhausts before the 1 GB data limit is reached.

2. **Known NFS proxy bug (contributing factor).** An internal report (Walkley He, April 13, `#bedrock-agentcore-runtime-interest`) describes the exact same ENOSPC issue affecting multiple users — including brand-new users with zero data written. NFS WRITE error rate of 96.8%. No resolution posted.

3. **Async replication backpressure (possible).** The docs state data is "asynchronously replicated to durable storage." If replication falls behind, the local NFS buffer may reject writes even when `df` shows capacity.

### The fix: split storage by purpose

Instead of writing everything to `/mnt/workspace`, we split:
- **Small persistent files** → `/mnt/workspace/{session_id}/` (optimization log, stream, configs)
- **Bulk downloadable data** → `/tmp/autotune-data/{session_id}/` (eval results, processing output)

The download tools (`download_raw_processing_results`, `download_evaluation_results`) hardcode the scratch directory path. The agent doesn't get to choose — this prevents it from accidentally writing bulk data to `/mnt/workspace`.

### TODO: Revisit when AgentCore improves

- [ ] **AgentCore NFS bug fix** — Monitor `#bedrock-agentcore-runtime-interest` for resolution of the ENOSPC bug reported by Walkley He and confirmed by our testing. Even with only 1.59 MB on `/mnt/workspace`, ENOSPC triggers after ~42 minutes. This is a service-side bug, not a data volume issue. Posted details in the Slack thread — awaiting response from AgentCore team.
- [ ] **AgentCore Runtime Instances (June 2026 target)** — Rahul Gulati announced EC2-based persistent compute with full OS access. No NFS quota issues. If shipped, evaluate migrating from microVM-based runtimes.
- [ ] **Storage limit increase at GA** — Kosti Vasilakakis acknowledged plans to increase storage at GA. Customers have requested 10-30 GB. If increased to ≥5 GB, bulk downloads could move back to `/mnt/workspace`.
- [ ] **S3 Files mount** — Unlimited storage via S3 NFS mount, confirmed working on AgentCore (Doron Bleiberg's reference implementation). Requires VPC mode (~$32/month NAT gateway). Consider if VPC is added for other reasons.
- [ ] **Session resume after ENOSPC** — Implement "Resume" button in the UI for runs that fail with ENOSPC. Reuse the same `runtimeSessionId` to get a fresh microVM with the same persistent storage. The agent reads OPTIMIZATION-LOG.md on resume and continues where it left off. This pairs with the optimization run history feature (session IDs visible in UI).

## How Persistence Works

### Session lifecycle

1. Frontend sends a request with `runtimeSessionId: <uuid>`
2. AgentCore spins up a Firecracker microVM and mounts persistent storage at `/mnt/workspace`
3. Agent creates scratch dir at `/tmp/autotune-data/{session_id}/`
4. Agent runs — small files on `/mnt/workspace`, bulk downloads on `/tmp`
5. The microVM idles out and gets torn down (compute is ephemeral)
6. A later request with the same `runtimeSessionId` spins up a new microVM with the same `/mnt/workspace`
7. `FileSessionManager` loads conversation history; optimization log and configs are in place
8. Scratch data on `/tmp` is gone — agent re-downloads if needed

### Infrastructure

The persistent filesystem is configured via an L1 escape hatch in CDK (the L2 construct doesn't support `filesystemConfiguration` yet — tracked in [aws-cdk PR #35478](https://github.com/aws/aws-cdk/pull/35478)):

```typescript
const cfnRuntime = this.agentRuntime.node.defaultChild as cdk.CfnResource
cfnRuntime.addPropertyOverride("FilesystemConfigurations", [
  { SessionStorage: { MountPath: "/mnt/workspace" } },
])
```

The agent code detects the mount at startup and falls back to `/tmp/workspace` for local Docker testing:

```python
WORKSPACE_DIR = "/mnt/workspace" if os.path.isdir("/mnt/workspace") else "/tmp/workspace"
SCRATCH_DIR = "/tmp/autotune-data"  # Ephemeral, 8.8 GB, no NFS issues
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, ".sessions")
```

### Why FileSessionManager instead of AgentCoreMemorySessionManager

The FAST template originally used `AgentCoreMemorySessionManager` from the `bedrock-agentcore` SDK. We replaced it with Strands' built-in `FileSessionManager`, which stores conversation history as JSON files at `/mnt/workspace/.sessions/`.

**Rationale:**
- **Unified persistence** — conversation history and workspace artifacts all live on the same persistent mount.
- **Simpler** — no AgentCore Memory service dependency, no `MEMORY_ID` env var, no memory resource to provision.
- **Faster** — local file read on session resume vs. API call to a cloud service.

**What we gave up:**
- **Long-term memory (LTM)** — `AgentCoreMemorySessionManager` supports optional semantic fact extraction across sessions. We had this disabled (`USE_LONG_TERM_MEMORY=false`) so there was no practical loss.

## Limitations

- **Preview feature** — no SLA, API may change. Acceptable for a feature still in development.
- **Per-session isolation** — each session gets its own `/mnt/workspace`. Session A cannot see session B's files.
- **~50 MB effective metadata limit** — the real constraint, not the 1 GB data limit. Keep file count low on `/mnt/workspace`.
- **`df` is unreliable** — NFS mount always reports 0% used. Use Python `os.walk` for actual measurement.
- **14-day inactivity expiry** — storage cleaned up after 14 days of no access.
- **Deploy wipe risk** — storage may be wiped on container image changes (not env var changes).
- **Scratch data is ephemeral** — anything on `/tmp` is lost when the microVM is torn down. Only store re-downloadable data there.

## Alternatives Considered

Full analysis in [`autotune/planning-docs/session-persistence-research.md`](../planning-docs/session-persistence-research.md).

- **S3 Workspace Sync** — custom sync code (~100 lines). All GA services, survives everything. Fallback if preview proves unreliable.
- **S3 Files Mount** — unlimited storage, POSIX interface. Requires VPC mode (~$32/month NAT gateway).
- **Agent State Dict + S3 Artifacts** — lightest code but requires significant refactoring.
