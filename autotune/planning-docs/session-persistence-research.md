# IDPAutoTune Session Persistence — Research & Options

**Date:** 2026-04-27
**Context:** The AutoTune agent runs on AgentCore for 1–3 hours per optimization run. It writes state to the filesystem (OPTIMIZATION-LOG.md, config YAMLs, evaluation results) and needs to survive runtime death, timeouts, and redeployments. Chat history must also persist so agents can pick up where they left off.

---

## The Problem (Precisely)

AutoTune has **two categories of state** that need to survive runtime death/timeout:

1. **Conversation state** — chat history, agent reasoning, tool call results. This is what lets the agent "remember" what it's done.
2. **Filesystem artifacts** — optimization logs, config YAML files, evaluation result JSONs, downloaded documents. These are the agent's working files.

The current setup handles (1) via `AgentCoreMemorySessionManager` (GA, works today), but (2) is completely ephemeral — if the runtime dies, all files are gone and the agent has no idea what configs it tried or what results it got.

---

## Research Sources

| Source | What We Learned |
|--------|----------------|
| FAST template code | Uses `AgentCoreMemorySessionManager` for chat history (GA). Stateless agent, cloud-persisted memory. No filesystem persistence. Frontend chat history is ephemeral (React state only — no localStorage). |
| Apex-build-agent | "Stateless agent, stateful filesystem" pattern. Markdown checklists + per-step reports in `.kiro/output/`. Agent reconstructs state from files on each invocation. No database for local state. S3 sync only for CI/CD archival. |
| AgentCore Persistent Filesystems | **Preview** feature. Mounts `/mnt/workspace` with async S3 replication. 1GB limit. **Wiped on runtime version update.** 14-day inactivity expiry. No CDK support yet. |
| AgentCore Memory | **GA**. Short-term = conversation events (chat history). Long-term = extracted insights via semantic strategies. NOT designed for arbitrary file storage (100KB max message). Good for chat history, bad for optimization logs/configs. |
| Strands SDK (v1.37.0) | Has native `S3SessionManager` and `FileSessionManager`. Persists conversation messages + agent `state` dict + conversation manager state. Does NOT persist filesystem artifacts. |
| S3 Files (NEW — GA) | Mount any S3 bucket as a POSIX filesystem via NFS. GA in all regions. Works on ECS/Fargate. Bi-directional sync. No storage limit (pay for active working set). |
| Community patterns | Three-tier memory (session/file/event-sourced). Checkpoint after every tool call. S3 as append-only state backend. Differential checkpointing. |

---

## Detailed Findings

### 1. FAST Template (Current State)

- Sessions are UUID-based, generated client-side
- `AgentCoreMemorySessionManager` stores conversation turns in AgentCore Memory (managed service)
- Memory configured with 30-day event expiry
- A new `Agent` instance is created per request — no server-side session state
- `ChatSidebar` component exists in the UI but is NOT wired up (no session list/switching yet)
- Long-term memory (semantic fact extraction) is available but optional (`USE_LONG_TERM_MEMORY=true`)
- **No filesystem persistence whatsoever** — container is fully stateless

### 2. Apex-Build-Agent Pattern

- Uses `.kiro/output/implementation-plan.md` as the central state document (markdown checkboxes)
- Per-step reports in `.kiro/output/<step-name>/navi-builder.md` serve as checkpoint records
- `project.md` is a living document for cross-session knowledge
- Resume protocol: read plan → find `[in progress]` step → read step report → continue
- S3 sync only happens post-hoc in CI/CD pipelines, not during agent execution
- **Key insight:** The agent is designed to be invoked fresh each time and reconstruct understanding from well-structured filesystem artifacts. This is exactly what AutoTune's OPTIMIZATION-LOG.md pattern does.

### 3. AgentCore Persistent Filesystems (Preview)

- Mounts a persistent directory (e.g., `/mnt/workspace`) inside the agent's microVM
- Standard POSIX filesystem — `ls`, `cat`, `mkdir`, `git`, `pip` all work
- Async-replicated to S3-backed durable storage during the session
- On resume with same `runtimeSessionId`, new compute mounts the same storage

**Limits:**
| Limit | Value |
|-------|-------|
| Max storage per session | 1 GB |
| Max files | ~100,000–200,000 |
| Max directory depth | 200 levels |
| Max filename length | 255 bytes |

**Critical risks:**
- **Preview** — no SLA, API may change, could be deprecated
- **Wiped on runtime version update** — every `cdk deploy` destroys ALL session state
- **No CDK construct** — requires API-level configuration (custom resource or post-deploy script)
- 14-day inactivity expiry
- Per-session isolation (no cross-session data sharing)

### 4. AgentCore Memory

- **Short-term memory:** Raw conversation events, keyed by `(memory_id, actor_id, session_id)`. 100KB max per message, 10MB max per event. 7–365 day expiry.
- **Long-term memory:** Extracted insights via configurable strategies (built-in, custom, or self-managed). Semantic search via `RetrieveMemoryRecords`. Max 6 strategies per memory resource.
- **NOT suitable for file storage** — designed for conversational data, not arbitrary artifacts. The 100KB message limit is too small for most log files or evaluation results.
- **Good for:** Chat history persistence, extracted optimization insights across sessions.

### 5. Strands SDK Session Management

Strands v1.37.0 has first-class session persistence:

```python
# S3-backed session persistence (conversation + agent state)
from strands.session import S3SessionManager

session_manager = S3SessionManager(
    session_id="my-session",
    bucket="my-bucket",
    prefix="autotune/sessions"
)
agent = Agent(model=model, tools=tools, session_manager=session_manager)
```

**What it persists:**
- All conversation messages (user, assistant, tool calls/results)
- Agent `state` dict (arbitrary key-value data you set on `agent.state`)
- Conversation manager state (sliding window position, etc.)
- Interrupt state

**What it does NOT persist:**
- Filesystem artifacts (files the agent wrote to disk)
- Tool-specific state outside the agent

**Key insight:** The `agent.state` dict is the bridge. You can store structured metadata there (configs tried, scores achieved, iteration count) even if the actual files are gone. Combined with S3 for artifact storage, this covers both categories of state.

### 6. Amazon S3 Files (NEW — GA)

Launched April 2026. Turns any S3 general-purpose bucket into a shared POSIX filesystem via NFS v4.1+.

**How it works:**
- Create an S3 file system linked to a bucket (or prefix within a bucket)
- Mount it on compute resources (EC2, ECS, EKS, Lambda, Fargate) via NFS
- Reads/writes go through a high-performance storage layer (EFS-backed, ~1ms latency for active data)
- Changes sync bidirectionally: filesystem writes → S3 objects, S3 changes → filesystem view
- Only active working set is cached on high-performance storage; large reads stream directly from S3

**Key characteristics:**
| Feature | Detail |
|---------|--------|
| Maturity | **GA** — all commercial AWS regions |
| Compute support | EC2, ECS, EKS, Fargate, Lambda |
| Consistency | NFS close-to-open |
| Max connections | 25,000 per file system |
| Max file size | 48 TiB |
| Storage limit | None (S3 bucket is the backing store) |
| Latency | Sub-ms to single-digit ms for cached data |
| Throughput | Multiple TB/s aggregate read |
| Sync latency | Writes → S3: within minutes. S3 → filesystem: seconds to ~1 minute |
| Data expiry from cache | Configurable 1–365 days (default 30) |
| Encryption | TLS in transit, KMS at rest |
| POSIX permissions | Yes (UID/GID stored as S3 object metadata) |

**Pricing (us-east-1):**
- High-performance storage: $0.30/GB/month (only for cached active data, not full dataset)
- Write access: $0.06/GB
- Read access from FS: $0.03/GB
- Sync operations: $0.03–$0.06/GB
- Large reads (≥1 MiB): streamed from S3 at standard S3 GET rates, no FS charge

**For AutoTune's workload** (~10MB of configs/logs/results per session): estimated cost is pennies per month.

**Limitations:**
- No hard links
- No extended attributes (xattr)
- Custom S3 object metadata not preserved after filesystem changes
- S3 ACLs not preserved after filesystem changes
- Requires VPC (mount target must be in same VPC as compute)
- Object keys > 1024 bytes can't be exported to S3

**Critical finding: S3 Files WORKS with AgentCore Runtime today.**

AgentCore Runtime uses **Firecracker microVMs**, not regular ECS containers. Each session gets a dedicated microVM with full kernel access — there's no seccomp profile blocking the `mount` syscall. This means you can run `mount -t s3files` directly from the container entrypoint, without needing ECS task definition volume mounts.

Source: [Doron Bleiberg's Builder.aws article](https://builder.aws.com/content/2yHZdNBPpoWVzg0DbI3LeUcmreu/using-s3-files-with-agentcore-runtime-shared-persistent-storage-for-ai-agents) — a complete working implementation of S3 Files + AgentCore + Strands FileSessionManager.

**How it works:**
1. Install `amazon-efs-utils` v3.0.0+ in the Dockerfile (multi-stage build — needs Rust + Go for efs-proxy)
2. Pass `S3_FILES_FS_ID` as an env var to the runtime
3. In the entrypoint script, run `mount -t s3files "${S3_FILES_FS_ID}:/" /mnt/s3files` before starting the app
4. Configure AgentCore Runtime with `NetworkMode: VPC` so the container can reach the S3 Files mount target
5. Use Strands `FileSessionManager(storage_dir="/mnt/s3files/sessions")` — it writes JSON files that S3 Files syncs to S3 automatically

**Key details from the article:**
- Mount helper handles TLS and IAM auth automatically
- S3 Files batches writes for up to 60 seconds before syncing to S3 (rapid writes → single S3 PUT)
- Data on high-performance storage has same durability as S3 (multi-AZ redundant)
- For critical data, `os.fsync()` ensures data reaches high-performance storage immediately
- Each session writes to `sessions/{session_id}/` — no concurrent write conflicts
- NFS close-to-open consistency for all operations through the mount
- Same agent code runs locally (writing to local dir) and on AgentCore (writing to S3 Files mount)

**IAM permissions needed on AgentCore execution role:**
- `s3files:ClientMount`, `s3files:ClientWrite`, `s3files:ClientRootAccess`
- `s3:GetObject`, `s3:GetObjectVersion`, `s3:ListBucket` (for S3 Files intelligent read routing)

**Infrastructure needed (CloudFormation):**
- S3 bucket (backing store)
- IAM role for S3 Files service → bucket access
- `AWS::S3Files::FileSystem` linked to bucket
- Security group allowing NFS port 2049 from VPC
- `AWS::S3Files::MountTarget` in private subnet
- `AWS::S3Files::AccessPoint`

**Dockerfile challenge:** The base image is Debian-based (`python:3.13-slim`), so `amazon-efs-utils` must be built from source (requires Rust, Go, C toolchain). Multi-stage Docker build keeps the runtime image clean. There's also a dual-Python issue: `mount.s3files` uses `/usr/bin/env python3` (system Python) but `botocore` is installed in Docker Python's site-packages — fixed with a `.pth` file.

**Verdict:** S3 Files is the clear winner. GA, unlimited storage, POSIX, bi-directional sync, works with AgentCore today via Firecracker's kernel access. The only tradeoff vs. the simpler S3 sync approach is more Dockerfile complexity (building efs-utils) and requiring VPC mode.

---

## Options

### Option A: AgentCore Persistent Filesystem (Simplest, but Preview)

Configure `sessionStorage` on the AgentCore Runtime to mount `/mnt/workspace`. The agent writes everything there. AgentCore handles persistence transparently.

**Implementation:**
- Add `filesystemConfigurations` to runtime via API call (no CDK support — needs custom resource or post-deploy script)
- Point agent working directory to `/mnt/workspace`
- Use `FileSessionManager` at `/mnt/workspace/.sessions` for conversation state
- Everything "just works" — agent reads/writes files normally

**Pros:**
- Zero custom persistence code
- POSIX filesystem — `idp-cli` subprocess, YAML files, JSON results all work naturally
- Conversation + filesystem artifacts in one place

**Cons:**
- **Preview** — no SLA, API may change, could be deprecated
- **Wiped on runtime version update** — every `cdk deploy` destroys all session state
- **No CDK construct** — requires API-level configuration
- 1GB limit per session
- 14-day inactivity expiry
- Per-session isolation (can't share state across sessions)

**Risk mitigation:** Implement a "backup to S3" step before any runtime update. But this is manual/fragile.

---

### Option B: S3 Workspace Sync (Most Robust, Moderate Effort)

The agent works on the local ephemeral filesystem as it does today, but a thin persistence layer syncs the workspace to/from S3 at key checkpoints.

**Implementation:**
- Create an S3 prefix per session: `s3://{autotune-bucket}/sessions/{session_id}/workspace/`
- Use Strands `S3SessionManager` for conversation state (replaces `AgentCoreMemorySessionManager`)
- Add a `WorkspaceManager` class (~100 lines) with `save()` and `restore()` that syncs the agent's working directory to/from S3
- Call `save()` after each major tool call (config upload, evaluation run, etc.)
- On agent init, call `restore()` to pull down the workspace if it exists
- Store structured `session_state.json` in agent's `state` dict as lightweight index

**What gets synced to S3:**
- `OPTIMIZATION-LOG.md` (running state document)
- Config YAML snapshots (small, <100KB each)
- Evaluation result summaries
- `session_state.json` (iteration count, best config, metrics history)

**What does NOT need syncing:**
- Raw documents (already in IDP stack's S3 buckets)
- Full evaluation outputs (already in IDP stack's output bucket)
- idp-cli temporary files

**Pros:**
- All GA services — S3 + Strands `S3SessionManager`
- Survives runtime death, `cdk deploy`, account migration
- No dependency on preview features
- Works identically in local Docker testing and AgentCore
- Natural checkpoint boundaries (after each optimization iteration)

**Cons:**
- Requires implementing `WorkspaceManager` (~100 lines)
- Slight latency on session restore (S3 download, but workspace is small — <10MB)
- Need to decide checkpoint granularity
- Two persistence mechanisms (S3SessionManager for conversation, WorkspaceManager for files)

---

### Option C: Agent State Dict + S3 Artifacts (Lightest Code)

Instead of syncing the filesystem, restructure the agent to keep critical state in the Strands `agent.state` dict (persisted automatically by `S3SessionManager`) and use S3 only for large artifacts.

**Implementation:**
- Use Strands `S3SessionManager` for conversation + state persistence
- Store in `agent.state`: iteration history, config versions tried, evaluation scores, current best config, optimization log entries (as structured data, not markdown)
- For large artifacts (config YAMLs, eval results), upload to a known S3 prefix and store the S3 key in `agent.state`
- On resume, agent has full context from `state` + can fetch any artifact from S3 by key
- `OPTIMIZATION-LOG.md` becomes a derived view generated from `agent.state`, not the source of truth

**Pros:**
- Minimal new code — `S3SessionManager` handles the heavy lifting
- Agent state is always consistent (atomic with conversation history)
- No filesystem sync complexity
- Clean separation: structured state in agent, blobs in S3

**Cons:**
- Requires refactoring how the agent thinks about state (currently writes markdown files)
- `agent.state` has practical size limits (serialized to JSON — should stay under a few MB)
- Agent prompt currently instructs "update OPTIMIZATION-LOG.md after every action" — needs rewriting
- Artifacts in S3 need explicit upload/download code in tools

---

### Option D: S3 Files Mount (Ideal — Now Confirmed Working on AgentCore)

Mount an S3 bucket as a POSIX filesystem via S3 Files. The agent reads/writes files normally; S3 is the durable backing store. **Confirmed working on AgentCore Runtime** via Firecracker microVM kernel access (see Doron Bleiberg's Builder.aws article).

**Implementation:**
- Create S3 file system linked to the AutoTune bucket (or a prefix like `sessions/`)
- Build `amazon-efs-utils` v3.0.0+ in a multi-stage Dockerfile (Rust + Go + C toolchain in builder stage)
- In entrypoint script: `mount -t s3files "${S3_FILES_FS_ID}:/" /mnt/s3files` before starting the app
- Configure AgentCore Runtime with `NetworkMode: VPC` (private subnet with mount target)
- Use `FileSessionManager(storage_dir="/mnt/s3files/sessions")` for conversation state
- Agent writes all artifacts to `/mnt/s3files/sessions/{session_id}/` — they automatically sync to S3
- On session resume, all files are already there (served from S3 via the filesystem)

**Pros:**
- **GA** — production-ready, all regions, SLA-backed
- **Confirmed working on AgentCore** — Firecracker microVMs have full kernel access for `mount` syscall
- No storage limit (S3 is the backing store)
- No custom sync code — filesystem operations are the API
- Bi-directional sync (can also write to S3 directly and see it in the filesystem)
- Pennies per month for AutoTune's workload
- Survives redeployments (data lives in S3, not tied to compute lifecycle)
- 25,000 concurrent connections (future multi-agent scenarios)
- Same agent code runs locally and on AgentCore — only the mount differs
- Session data is standard S3 objects — use lifecycle policies, analytics, cross-region replication
- No agent code changes needed vs. current implementation

**Cons:**
- Dockerfile complexity: multi-stage build to compile `amazon-efs-utils` from source (Rust + Go + C)
- Dual-Python issue requires `.pth` file workaround
- Requires VPC mode (mount target must be in same VPC as compute)
- Write-to-S3 sync latency is up to 60 seconds (batched writes)
- NFS close-to-open consistency (not strong consistency)
- More infrastructure to provision (S3 bucket, filesystem, mount target, security group, IAM role)

**When this doesn't work:**
- Local Docker testing without VPC access (falls back to local directory — same code, different mount)

---

### Option E: Hybrid — Option B Now, Option D Later

Start with Option B (S3 workspace sync) for immediate robustness, but design the workspace directory structure to be S3 Files-compatible. When AgentCore adds S3 Files support (or we move to self-managed ECS), swap the `WorkspaceManager` sync layer for a native S3 Files mount with minimal code changes.

**Implementation:**
- Phase 1 (now): Implement Option B with workspace at `/app/workspace/{session_id}/`
- Phase 2 (when available): Mount S3 Files at `/app/workspace/`, remove `WorkspaceManager`
- The agent code doesn't change — it always reads/writes to `/app/workspace/{session_id}/`

**Pros:**
- Immediate robustness with all GA services
- Clear migration path to the ideal solution
- Agent code is persistence-layer agnostic

**Cons:**
- Slightly more upfront design work to ensure directory structure is S3-compatible
- Two implementations to maintain temporarily

---

## Comparison Matrix

| Criterion | A: AgentCore FS | B: S3 Sync | C: State Dict | D: S3 Files | E: Hybrid B→D |
|-----------|:-:|:-:|:-:|:-:|:-:|
| Maturity | Preview ⚠️ | GA ✅ | GA ✅ | GA ✅ | GA ✅ |
| Survives `cdk deploy` | ❌ | ✅ | ✅ | ✅ | ✅ |
| Survives runtime death | ✅ | ✅ | ✅ | ✅ | ✅ |
| Custom code needed | None | ~100 lines | ~50 lines + refactor | None (Dockerfile work) | ~100 lines |
| Agent code changes | None | Minimal | Significant | Minimal (FileSessionMgr) | Minimal |
| Works in local Docker | ❌ | ✅ | ✅ | ❌ (local fallback) | ✅ |
| Storage limit | 1 GB | Unlimited | ~few MB state | Unlimited | Unlimited |
| AgentCore compatible | ✅ | ✅ | ✅ | ✅ (**confirmed**) | ✅ |
| Chat history | FileSessionMgr | S3SessionMgr | S3SessionMgr | FileSessionMgr | S3SessionMgr |
| Cross-session sharing | ❌ | ✅ (same S3) | ✅ (same S3) | ✅ (shared mount) | ✅ |
| Dockerfile complexity | Low | Low | Low | **High** (efs-utils build) | Low |
| Infra complexity | Low (API call) | Low (S3 bucket) | Low (S3 bucket) | **Medium** (VPC, mount target, SG) | Low |
| **Requires VPC** | **No** | **No** | **No** | **Yes** ⚠️ | **No** |
| **Monthly infra cost** | ~$0 | ~$0 | ~$0 | **~$32+** (NAT GW) | ~$0 |

---

## Recommendation

**UPDATE (2026-04-27 18:37): Decision — Option A (AgentCore Persistent Filesystem, Preview) with custom resource.**

### Rationale

Option D (S3 Files) is technically ideal but requires a dedicated VPC (NAT gateway ~$32/month, subnets, endpoints). The IDP Accelerator does NOT create or use a VPC by default — creating one solely for agent file persistence is overkill.

Option B (S3 Workspace Sync) is robust but requires ~100 lines of custom sync code.

Option A (AgentCore Persistent FS) is the simplest path:
- **Zero custom persistence code** — agent reads/writes files normally at `/mnt/workspace`
- **No VPC required** — works in PUBLIC mode
- **No Dockerfile changes** — standard POSIX filesystem, managed by AgentCore
- **No new infrastructure** — just a `filesystemConfigurations` property on the runtime
- **CDK gap solvable** — use a custom resource (Lambda) to call `UpdateAgentRuntime` API with `filesystemConfigurations`

### Known risks (Preview)
- **Wiped on runtime version update** — every `cdk deploy` that changes the runtime destroys all session state. Mitigation: the agent can re-derive state from IDP stack resources (configs are in DynamoDB, evaluations in S3). The optimization log is the main thing at risk.
- **14-day inactivity expiry** — acceptable for optimization runs (they complete in hours, not weeks)
- **1GB limit per session** — more than enough for optimization logs, config YAMLs, and eval summaries
- **No SLA** — acceptable for a feature still in development; re-evaluate before GA
- **Per-session isolation** — each session gets its own storage, no cross-session sharing. This is fine for AutoTune (each optimization run is independent).

### Fallback plan
If the preview proves unreliable during testing, fall back to **Option B (S3 Workspace Sync)** — the agent code barely changes since both options use the local filesystem. The only difference is whether persistence is managed by AgentCore or by a custom `WorkspaceManager`.

### Session manager decision
Use Strands `FileSessionManager(storage_dir="/mnt/workspace/.sessions")` for conversation history. This replaces `AgentCoreMemorySessionManager` and keeps everything on the persistent filesystem — conversation state and workspace artifacts in one place. If long-term semantic memory is needed later, AgentCore Memory can be re-added as a separate concern.

---

## References

- **[Using S3 Files with AgentCore Runtime (Doron Bleiberg, Builder.aws)](https://builder.aws.com/content/2yHZdNBPpoWVzg0DbI3LeUcmreu/using-s3-files-with-agentcore-runtime-shared-persistent-storage-for-ai-agents)** — Complete working implementation of S3 Files + AgentCore + Strands FileSessionManager. Includes Dockerfile, entrypoint, CloudFormation, IAM, and agent code. **This is the reference implementation for Option D.**
- [AgentCore Persistent Filesystems (Preview)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-persistent-filesystems.html)
- [AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)
- [AgentCore Runtime Sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
- [S3 Files Launch Blog](https://aws.amazon.com/blogs/aws/launching-s3-files-making-s3-buckets-accessible-as-file-systems/)
- [S3 Files Documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html)
- [S3 Files on ECS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting-ecs.html)
- [S3 Files Limits & Quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html)
- [Strands SDK S3SessionManager](https://github.com/strands-agents/sdk-python) (v1.37.0)
- FAST template: `autotune/fast-template/` in this repo
- Apex-build-agent: `~/gitlab/proserve-apex/delivery-agent/apex-build-agent/`
