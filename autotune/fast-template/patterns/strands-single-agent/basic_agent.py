"""IDPAutoTune agent — automated IDP Accelerator config optimization.

Runs as a Strands agent on AgentCore via the FAST BedrockAgentCoreApp entrypoint.
Operates autonomously: receives test_set_id + optional optimization_guidance,
runs iterative optimization to completion (or cancellation), and produces an
optimized IDP Accelerator config.

Architecture: Fire-and-forget. The entrypoint yields a single "started" event
and returns immediately. The agent runs in a background thread, writing its
full event stream to a JSONL file on /tmp and syncing to S3
periodically. The frontend polls three independent APIs:
  - GET /state  (DynamoDB) — status, phase, iteration, accuracy
  - GET /stream (S3 JSONL) — full agent thought process
  - GET /log    (S3 markdown) — OPTIMIZATION-LOG.md

All state lives on /tmp + S3 sync. /mnt/workspace (AgentCore persistent FS)
is NOT used due to a known ENOSPC bug in the NFS metadata layer.
"""

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp, PingStatus, RequestContext
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands.session import S3SessionManager
from strands_tools import file_read, image_reader
from utils.auth import extract_user_id_from_context

from code_interpreter_tools import execute_python_analysis
from idpac_tools import ALL_TOOLS as IDPAC_TOOLS, seed_eval_cost
from optimization_state import OptimizationState, TERMINAL_STATUSES
from optimization_hooks import CancelCheckHook, CostTrackingHook, FileReadSafetyHook, OptimizationCancelled, OptimizationLoopHook
from proactive_context_manager import ProactiveContextManager

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

# Background threads keyed by session_id. Checked by /ping to report HEALTHY_BUSY.
_active_sessions: dict[str, threading.Thread] = {}

AGENT_DIR = Path(__file__).parent
# TODO: Revisit /mnt/workspace once AgentCore persistent filesystem ENOSPC bug is fixed.
# The NFS mount triggers ENOSPC even with 0 bytes of data due to a metadata budget bug
# (known issue, reported April 2026). For now, all state lives on /tmp + S3 sync.
SCRATCH_DIR = "/tmp/autotune-data"
MAX_ITERATIONS = 10
MAX_COST_USD = float(os.environ.get("AUTOTUNE_MAX_COST_USD", "500"))

# S3 sync config
SYNC_INTERVAL = 10  # seconds between background sync cycles (heartbeat + S3)


@app.ping
def custom_ping_status():
    """Return HEALTHY_BUSY while any agent background thread is alive."""
    # Clean up dead threads
    for sid in list(_active_sessions):
        if not _active_sessions[sid].is_alive():
            del _active_sessions[sid]
    if _active_sessions:
        return PingStatus.HEALTHY_BUSY
    return PingStatus.HEALTHY


def _load_system_prompt() -> str:
    return (AGENT_DIR / "prompt.md").read_text()


def _build_initial_prompt(test_set_id: str, optimization_guidance: str) -> str:
    parts = [
        f"Begin autonomous optimization for test set: {test_set_id}",
        "\nRead OPTIMIZATION-LOG.md for the pre-filled run metadata, then run the "
        "test set to establish a baseline. Update the log after each step.",
    ]
    if optimization_guidance:
        parts.append(f"\nOptimization guidance from the user:\n{optimization_guidance}")
    return "\n".join(parts)


def _build_resume_prompt(test_set_id: str, optimization_guidance: str) -> str:
    parts = [
        f"You are resuming an interrupted optimization run for test set: {test_set_id}",
        "\nThe previous run was interrupted (likely by a disk space error). Your "
        "conversation history and OPTIMIZATION-LOG.md on the persistent filesystem "
        "contain everything from the previous run.",
        "\nRead OPTIMIZATION-LOG.md to understand what has been done so far, then "
        "continue the optimization from where it left off. Do NOT repeat work that "
        "was already completed — check the log for which iterations, configs, and "
        "evaluations have already been run.",
    ]
    if optimization_guidance:
        parts.append(f"\nOriginal optimization guidance from the user:\n{optimization_guidance}")
    return "\n".join(parts)


def _create_optimization_log(session_workspace: str, test_set_id: str, optimization_guidance: str) -> None:
    idp_stack = os.environ.get("IDP_STACK_NAME", "unknown")
    region = os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "unknown"))
    content = f"""# Optimization Log

This file documents the progress of the current optimization run.

## Run Metadata
IDP stack name and region: {idp_stack} ({region})
Input test set: {test_set_id}
Dataset mode: TBD (determine from test set analysis)
Optimization guidance: {optimization_guidance or "None provided"}

## Optimization Log
"""
    with open(os.path.join(session_workspace, "OPTIMIZATION-LOG.md"), "w") as f:
        f.write(content)


def _create_agent(user_id: str, session_id: str, state: OptimizationState,
                  test_set_id: str, optimization_guidance: str, is_resume: bool = False) -> Agent:
    # Prompt caching: system prompt cached via cachePoint, tools via cache_tools,
    # messages via CacheConfig(strategy="auto") which places a cache point at the
    # end of the last user message each turn. This is Claude-specific; for other
    # models see: https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/#caching
    from strands.models import CacheConfig
    from strands.types.content import SystemContentBlock

    model = BedrockModel(
        model_id=os.environ["AUTOTUNE_MODEL_ID"],
        max_tokens=16384,
        cache_tools="default",
        cache_config=CacheConfig(strategy="auto"),
    )
    # Session history on S3 — /mnt/workspace is disabled due to AgentCore NFS ENOSPC bug.
    s3_bucket = os.environ.get("AUTOTUNE_STREAM_BUCKET", "")
    session_manager = S3SessionManager(
        session_id=session_id,
        bucket=s3_bucket,
        prefix="autotune-sessions",
    ) if s3_bucket else None

    session_workspace = os.path.join(SCRATCH_DIR, session_id)
    os.makedirs(session_workspace, exist_ok=True)
    os.chdir(session_workspace)

    os.environ["AUTOTUNE_SCRATCH_DIR"] = session_workspace
    os.environ["AUTOTUNE_WORKSPACE_DIR"] = session_workspace

    if test_set_id and not is_resume:
        _create_optimization_log(session_workspace, test_set_id, optimization_guidance)

    skills_dir = AGENT_DIR / "skills"
    plugins = [AgentSkills(skills=str(skills_dir))] if skills_dir.exists() else []
    tools = IDPAC_TOOLS + [file_read, image_reader, execute_python_analysis]
    cost_hook = CostTrackingHook(state, max_cost_usd=MAX_COST_USD)
    hooks = [CancelCheckHook(state), FileReadSafetyHook(), cost_hook, OptimizationLoopHook(state, max_iterations=MAX_ITERATIONS, max_cost_usd=MAX_COST_USD)]

    agent = Agent(
        name="idp_autotune",
        model=model,
        system_prompt=[
            SystemContentBlock(text=_load_system_prompt()),
            SystemContentBlock(cachePoint={"type": "default"}),
        ],
        tools=tools,
        plugins=plugins,
        hooks=hooks,
        conversation_manager=ProactiveContextManager(),
        session_manager=session_manager,
        trace_attributes={"user.id": user_id, "session.id": session_id},
    )
    cost_hook.metrics = agent.event_loop_metrics
    cost_hook.agent_messages = agent.messages
    return agent


def _snapshot_disk_usage(output_path: str) -> None:
    """Append a disk usage snapshot as a JSONL line."""
    import subprocess
    snapshot = {"ts": time.strftime("%H:%M:%S", time.gmtime()), "epoch": time.time()}

    # df for overall filesystem usage
    try:
        df = subprocess.run(["df", "-h"], capture_output=True, text=True, timeout=5)
        snapshot["df"] = df.stdout
    except Exception:
        pass

    # Pure-Python walk of /tmp
    for scan_root in ["/tmp"]:
        if not os.path.isdir(scan_root):
            continue
        key = scan_root.replace("/", "_").strip("_")
        dir_sizes: dict[str, int] = {}  # relative dir -> total bytes
        try:
            for root, dirs, fnames in os.walk(scan_root):
                rel = os.path.relpath(root, scan_root)
                # Track at depth 0 and 1 only
                parts = rel.split(os.sep)
                bucket = parts[0] if rel != "." else "."
                for fn in fnames:
                    try:
                        sz = os.path.getsize(os.path.join(root, fn))
                    except OSError:
                        sz = 0
                    dir_sizes[bucket] = dir_sizes.get(bucket, 0) + sz
            total = sum(dir_sizes.values())
            snapshot[f"{key}_total_mb"] = round(total / 1024 / 1024, 2)
            # Top dirs by size
            top = sorted(dir_sizes.items(), key=lambda x: -x[1])[:15]
            snapshot[f"{key}_dirs"] = {d: round(s / 1024 / 1024, 2) for d, s in top}
        except Exception:
            pass

    with open(output_path, "a") as f:
        f.write(json.dumps(snapshot, default=str) + "\n")


def _run_agent_thread(user_id: str, session_id: str, state: OptimizationState,
                      test_set_id: str, optimization_guidance: str, is_resume: bool = False) -> None:
    """Background thread: runs the agent, writes stream to JSONL, syncs to S3."""
    s3_bucket = os.environ.get("AUTOTUNE_STREAM_BUCKET", "")
    s3_prefix = f"autotune-streams/{session_id}"
    session_dir = os.path.join(SCRATCH_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    stream_path = os.path.join(session_dir, "stream.jsonl")
    log_path = os.path.join(session_dir, "OPTIMIZATION-LOG.md")

    s3 = boto3.client("s3") if s3_bucket else None

    def _sync_file(local_path: str, s3_key: str) -> None:
        if not s3 or not s3_bucket:
            return
        try:
            s3.upload_file(local_path, s3_bucket, s3_key)
        except Exception:
            logger.exception("S3 sync failed for %s", s3_key)

    async def _run():
        agent = _create_agent(user_id, session_id, state, test_set_id, optimization_guidance, is_resume)
        initial_prompt = _build_resume_prompt(test_set_id, optimization_guidance) if is_resume else _build_initial_prompt(test_set_id, optimization_guidance)

        # On resume: restore OPTIMIZATION-LOG.md from S3 and seed eval cost
        if is_resume:
            prev_state = state.get_state()
            seed_eval_cost(float(prev_state.get("eval_cost_usd", 0)), prev_state.get("eval_seen_batches", ""))
            if s3 and s3_bucket:
                try:
                    s3.download_file(s3_bucket, f"{s3_prefix}/OPTIMIZATION-LOG.md", log_path)
                    logger.info("Restored OPTIMIZATION-LOG.md from S3")
                except Exception:
                    logger.warning("Could not restore OPTIMIZATION-LOG.md from S3")

        # Background sync thread — heartbeat + S3 sync
        disk_usage_path = os.path.join(session_dir, "disk-usage.jsonl")
        sync_stop = threading.Event()
        def _sync_loop():
            while not sync_stop.wait(SYNC_INTERVAL):
                state.heartbeat()
                if os.path.exists(stream_path):
                    _sync_file(stream_path, f"{s3_prefix}/stream.jsonl")
                if os.path.exists(log_path):
                    _sync_file(log_path, f"{s3_prefix}/OPTIMIZATION-LOG.md")
                _snapshot_disk_usage(disk_usage_path)
                _sync_file(disk_usage_path, f"{s3_prefix}/disk-usage.jsonl")
        sync_thread = threading.Thread(target=_sync_loop, daemon=True)
        sync_thread.start()

        text_buf = ""
        tool_calls: dict[str, dict] = {}  # toolUseId -> {name, input}

        def _flush_text():
            nonlocal text_buf
            if text_buf:
                _write_line({"type": "text", "content": text_buf})
                text_buf = ""

        def _write_line(obj: dict):
            obj["ts"] = time.strftime("%H:%M:%S", time.gmtime())
            try:
                with open(stream_path, "a") as f:
                    f.write(json.dumps(obj, default=str) + "\n")
            except Exception:
                logger.exception("Failed to write stream event")

        async for event in agent.stream_async(initial_prompt):
            try:
                evt = json.loads(json.dumps(dict(event), default=str))
            except Exception:
                continue

            # Text delta — accumulate
            if isinstance(evt.get("data"), str) and evt["data"]:
                text_buf += evt["data"]

            # Tool use streaming — accumulate input by toolUseId
            elif evt.get("current_tool_use"):
                tool = evt["current_tool_use"]
                tid = tool.get("toolUseId", "")
                delta_input = (evt.get("delta") or {}).get("toolUse", {}).get("input", "")
                if tid not in tool_calls:
                    # New tool call — flush any pending text first
                    _flush_text()
                    tool_calls[tid] = {"name": tool.get("name", "unknown"), "input": ""}
                if delta_input:
                    tool_calls[tid]["input"] += delta_input

            # Complete message — contains final assistant text + toolUse, or user toolResult
            elif evt.get("message"):
                msg = evt["message"]
                if msg.get("role") == "assistant":
                    _flush_text()
                    # Extract any text blocks from the complete message
                    for block in (msg.get("content") or []):
                        if isinstance(block, dict) and block.get("text"):
                            pass  # Already captured via text deltas above
                        if isinstance(block, dict) and block.get("toolUse"):
                            tu = block["toolUse"]
                            tid = tu.get("toolUseId", "")
                            if tid in tool_calls:
                                # Write the consolidated tool call
                                tc = tool_calls.pop(tid)
                                _write_line({
                                    "type": "tool_use",
                                    "toolUseId": tid,
                                    "name": tc["name"],
                                    "input": tc["input"],
                                })
                elif msg.get("role") == "user":
                    for block in (msg.get("content") or []):
                        if isinstance(block, dict) and block.get("toolResult"):
                            tr = block["toolResult"]
                            tid = tr.get("toolUseId", "")
                            result_parts = []
                            for c in (tr.get("content") or []):
                                if isinstance(c, dict) and c.get("text"):
                                    result_parts.append(c["text"])
                            result_text = "\n".join(result_parts) if result_parts else json.dumps(tr.get("content", ""), default=str)
                            # Truncate large results
                            if len(result_text) > 2000:
                                result_text = result_text[:2000] + "\n... (truncated)"
                            _write_line({
                                "type": "tool_result",
                                "toolUseId": tid,
                                "result": result_text,
                            })

        # Stop sync thread
        sync_stop.set()

        # Flush remaining text
        _flush_text()
        # Flush any tool calls that didn't get a message event
        for tid, tc in tool_calls.items():
            _write_line({"type": "tool_use", "toolUseId": tid, "name": tc["name"], "input": tc["input"]})

        # Final sync
        if os.path.exists(stream_path):
            _sync_file(stream_path, f"{s3_prefix}/stream.jsonl")
        if os.path.exists(log_path):
            _sync_file(log_path, f"{s3_prefix}/OPTIMIZATION-LOG.md")

    try:
        asyncio.run(_run())
        if not state.is_terminal():
            state.set_status("complete", "Optimization finished")
    except OptimizationCancelled:
        logger.info("Agent stopped — optimization in terminal state")
    except Exception as e:
        logger.exception("Agent run failed")
        if not state.is_terminal():
            state.set_status("failed", str(e)[:500])
    finally:
        # Final sync of whatever we have
        if s3 and s3_bucket:
            for local, key in [(stream_path, f"{s3_prefix}/stream.jsonl"),
                               (log_path, f"{s3_prefix}/OPTIMIZATION-LOG.md")]:
                if os.path.exists(local):
                    try:
                        s3.upload_file(local, s3_bucket, key)
                    except Exception:
                        pass


@app.entrypoint
async def invocations(payload, context: RequestContext):
    """Fire-and-forget entrypoint. Starts agent in background thread, returns immediately."""
    user_query = payload.get("prompt")
    session_id = payload.get("runtimeSessionId")

    if not all([user_query, session_id]):
        yield {"status": "error", "error": "Missing required fields: prompt or runtimeSessionId"}
        return

    os.environ["AUTOTUNE_SESSION_ID"] = session_id
    state = OptimizationState(session_id)

    test_set_id = payload.get("test_set_id", "").strip()
    optimization_guidance = payload.get("optimization_guidance", "").strip()
    is_resume = payload.get("resume", "").strip().lower() == "true"

    if not test_set_id:
        yield {"status": "error", "error": "Missing required field: test_set_id"}
        return

    if is_resume:
        # Resume: don't re-initialize — just flip status back to active
        state.set_status("resuming", "Resuming after interruption")
    else:
        state.initialize(test_set_id, optimization_guidance, MAX_ITERATIONS)

    user_id = extract_user_id_from_context(context)

    thread = threading.Thread(
        target=_run_agent_thread,
        args=(user_id, session_id, state, test_set_id, optimization_guidance, is_resume),
        daemon=True,
        name=f"autotune-{session_id[:8]}",
    )
    _active_sessions[session_id] = thread
    thread.start()

    yield {"status": "started", "session_id": session_id}


if __name__ == "__main__":
    app.run()
