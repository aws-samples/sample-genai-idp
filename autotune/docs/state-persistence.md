# IDPAutoTune State Persistence

## Overview

The AutoTune agent runs on AgentCore for extended periods (1–3 hours per optimization run). It writes state to the filesystem — optimization logs, config YAML files, evaluation results — and needs that state to survive compute teardown, idle timeouts, and redeployments. Conversation history must also persist so the agent can resume where it left off.

## How It Works

We use **AgentCore Persistent Filesystem** (Preview feature) to mount `/mnt/workspace` inside the agent's microVM. AgentCore async-replicates this storage to a durable S3-backed store. When the same session is resumed, a new microVM mounts the same storage — all files are still there.

### Two categories of state

The agent persists two kinds of state, both on `/mnt/workspace`, keyed by session ID:

**Conversation history** (`/mnt/workspace/.sessions/`)
Managed by Strands `FileSessionManager`. Stores all conversation messages (user prompts, assistant responses, tool calls and results) as JSON files. When a session resumes, Strands loads these and the agent has full context of what was said.

**Filesystem artifacts** (`/mnt/workspace/{session_id}/`)
Each session gets its own working directory. The agent `os.chdir()`s into it on startup. This is where tools write optimization logs, config YAMLs, evaluation result JSONs, and any other working files. These are the agent's "memory" of what it has done.

### Session lifecycle

1. Frontend sends a request with `runtimeSessionId: <uuid>`
2. AgentCore spins up a Firecracker microVM and mounts persistent storage for that session at `/mnt/workspace`
3. The agent runs — reads/writes files, has conversations, invokes tools
4. The microVM idles out and gets torn down (compute is ephemeral)
5. A later request with the same `runtimeSessionId` spins up a new microVM with the same storage mounted
6. `FileSessionManager` loads conversation history; working files are already in place
7. The agent continues as if nothing happened

No special resume logic is needed. The agent just reads files that are already there.

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
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, ".sessions")
```

### Frontend session management

The frontend stores session metadata (ID, name, message history) in `localStorage`. When a user switches to a previous session in the sidebar, the frontend sends requests with that session's ID — AgentCore mounts the corresponding storage, and the agent picks up the conversation.

## Limitations

- **Preview feature** — no SLA, API may change. Acceptable for a feature still in development.
- **Per-session isolation** — each session gets its own `/mnt/workspace`. Session A cannot see session B's files. This is fine for AutoTune (each optimization run is independent) but means you can't share results across sessions.
- **1 GB storage limit per session** — more than enough for optimization logs, config YAMLs, and evaluation summaries.
- **14-day inactivity expiry** — if a session isn't touched for 14 days, storage is cleaned up. Acceptable since optimization runs complete in hours.
- **Deploy wipe risk** — the docs warn that storage is wiped on "runtime version update." Testing confirmed that env var changes (which trigger `UpdateAgentRuntime`) do NOT wipe storage. The wipe likely only occurs when the container image itself changes. If it does happen, the agent can re-derive most state from the IDP stack (configs live in DynamoDB, evaluations in S3).

## Alternatives Considered

We evaluated five options before choosing AgentCore Persistent Filesystem. Full analysis is in [`autotune/planning-docs/session-persistence-research.md`](../planning-docs/session-persistence-research.md).

- **S3 Workspace Sync** — custom `WorkspaceManager` class (~100 lines) syncs the working directory to/from S3 at checkpoints. All GA services, survives everything, but requires writing and maintaining sync code. This is the fallback if the preview proves unreliable.
- **Agent State Dict + S3 Artifacts** — store structured state in the Strands `agent.state` dict, upload large artifacts to S3 separately. Lightest code but requires significant refactoring of how the agent tracks state.
- **S3 Files Mount** — mount an S3 bucket as a POSIX filesystem via S3 Files (GA). Technically ideal — unlimited storage, no custom sync code, confirmed working on AgentCore. But requires VPC mode (NAT gateway ~$32/month), complex Dockerfile (building `amazon-efs-utils` from source), and more infrastructure. Overkill for current needs.
- **Hybrid** — start with S3 Workspace Sync, migrate to S3 Files later. Clean migration path but two implementations to maintain.

We chose AgentCore Persistent Filesystem because it requires zero custom persistence code, no VPC, no Dockerfile changes, and no new infrastructure — just a config property on the runtime. The agent reads and writes files normally and AgentCore handles durability.
