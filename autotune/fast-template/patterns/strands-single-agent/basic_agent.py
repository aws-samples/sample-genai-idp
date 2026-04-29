"""IDPAutoTune agent — automated IDP Accelerator config optimization.

Runs as a Strands agent on AgentCore via the FAST BedrockAgentCoreApp entrypoint.
Operates autonomously: receives test_set_id + optional optimization_guidance,
runs iterative optimization to completion (or cancellation), and produces an
optimized IDP Accelerator config.

Session keepalive: AgentCore has a 15-minute idle timeout. During long tool calls
(e.g. run_evaluation taking 3+ minutes), no SSE events are yielded, which can
trigger the timeout. We prevent this with:
  1. @app.ping handler returning HEALTHY_BUSY while the agent is running
  2. Heartbeat events yielded every 30s from a background asyncio task
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp, PingStatus, RequestContext
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands.session import FileSessionManager
from strands_tools import editor, file_read, file_write, shell
from utils.auth import extract_user_id_from_context

from idpac_tools import ALL_TOOLS as IDPAC_TOOLS
from optimization_state import OptimizationState, STATUS_RUNNING, STATUS_COMPLETE, STATUS_FAILED
from optimization_hooks import CancelCheckHook, OptimizationLoopHook

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

# Track whether the agent is actively running (for ping handler)
_agent_running = False

HEARTBEAT_INTERVAL_SECONDS = 30


@app.ping
def custom_ping_status():
    """Return HEALTHY_BUSY while agent is running to prevent idle timeout."""
    if _agent_running:
        return PingStatus.HEALTHY_BUSY
    return PingStatus.HEALTHY


AGENT_DIR = Path(__file__).parent

# Persistent filesystem mounted by AgentCore (Preview feature).
# Falls back to /tmp for local Docker testing.
WORKSPACE_DIR = "/mnt/workspace" if os.path.isdir("/mnt/workspace") else "/tmp/workspace"
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, ".sessions")

MAX_ITERATIONS = 10


def _load_system_prompt() -> str:
    return (AGENT_DIR / "prompt.md").read_text()


def _build_initial_prompt(test_set_id: str, optimization_guidance: str) -> str:
    """Construct the first user message that kicks off autonomous optimization."""
    parts = [
        f"Begin autonomous optimization for test set: {test_set_id}",
        "\nRead OPTIMIZATION-LOG.md for the pre-filled run metadata, then run the "
        "test set to establish a baseline. Update the log after each step.",
    ]
    if optimization_guidance:
        parts.append(f"\nOptimization guidance from the user:\n{optimization_guidance}")
    return "\n".join(parts)


def _create_optimization_log(
    session_workspace: str,
    test_set_id: str,
    optimization_guidance: str,
) -> None:
    """Pre-create OPTIMIZATION-LOG.md with run metadata filled in."""
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
    log_path = os.path.join(session_workspace, "OPTIMIZATION-LOG.md")
    with open(log_path, "w") as f:
        f.write(content)


def create_autotune_agent(
    user_id: str,
    session_id: str,
    state: OptimizationState,
    test_set_id: str = "",
    optimization_guidance: str = "",
) -> Agent:
    """Create the IDPAutoTune Strands agent with hooks for autonomous operation."""
    model = BedrockModel(
        model_id=os.environ.get(
            "AUTOTUNE_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
        ),
        max_tokens=16384,
    )

    # Persistent session storage on /mnt/workspace (AgentCore) or /tmp (local)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_manager = FileSessionManager(
        session_id=session_id,
        storage_dir=SESSIONS_DIR,
    )

    # Set agent working directory to persistent workspace
    session_workspace = os.path.join(WORKSPACE_DIR, session_id)
    os.makedirs(session_workspace, exist_ok=True)
    os.chdir(session_workspace)

    # Pre-create OPTIMIZATION-LOG.md with metadata filled in
    if test_set_id:
        _create_optimization_log(session_workspace, test_set_id, optimization_guidance)

    # Skills plugin — auto-discovers SKILL.md files
    skills_dir = AGENT_DIR / "skills"
    plugins = []
    if skills_dir.exists():
        plugins.append(AgentSkills(skills=str(skills_dir)))

    # IDPAC-specific tools + general-purpose community tools
    tools = IDPAC_TOOLS + [file_read, file_write, editor, shell]

    # Autonomous hooks
    hooks = [
        CancelCheckHook(state),
        OptimizationLoopHook(state, max_iterations=MAX_ITERATIONS),
    ]

    # TODO: Add SummarizingConversationManager when context overflow is observed
    return Agent(
        name="idp_autotune",
        model=model,
        system_prompt=_load_system_prompt(),
        tools=tools,
        plugins=plugins,
        hooks=hooks,
        session_manager=session_manager,
        trace_attributes={"user.id": user_id, "session.id": session_id},
    )


@app.entrypoint
async def invocations(payload, context: RequestContext):
    """Main entrypoint — called by AgentCore Runtime on each request.

    Uses an asyncio.Queue to merge agent stream events with periodic heartbeats.
    This ensures AgentCore always receives events within its idle timeout window,
    even during long tool calls that produce no streaming output.
    """
    global _agent_running

    user_query = payload.get("prompt")
    session_id = payload.get("runtimeSessionId")

    if not all([user_query, session_id]):
        yield {
            "status": "error",
            "error": "Missing required fields: prompt or runtimeSessionId",
        }
        return

    # Make session_id available to the update_optimization_state tool
    os.environ["AUTOTUNE_SESSION_ID"] = session_id

    # Initialize DynamoDB state before the agent starts
    state = OptimizationState(session_id)

    # Parse test_set_id from payload
    test_set_id = payload.get("test_set_id", "").strip()
    optimization_guidance = payload.get("optimization_guidance", "").strip()

    if not test_set_id:
        yield {
            "status": "error",
            "error": "Missing required field: test_set_id",
        }
        return

    state.initialize(test_set_id, optimization_guidance, MAX_ITERATIONS)
    initial_prompt = _build_initial_prompt(test_set_id, optimization_guidance)

    # Queue merges agent events + heartbeats into a single stream.
    # None sentinel signals the agent stream is done.
    queue = asyncio.Queue()

    async def _heartbeat_producer():
        """Yield heartbeat events every HEARTBEAT_INTERVAL_SECONDS.

        Also updates DynamoDB updated_at so the frontend can detect stale/crashed sessions.
        """
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            state.heartbeat()
            await queue.put({"event": "heartbeat", "timestamp": time.time()})

    async def _agent_producer():
        """Run the agent and push events into the queue."""
        try:
            user_id = extract_user_id_from_context(context)
            agent = create_autotune_agent(
                user_id, session_id, state, test_set_id, optimization_guidance
            )
            async for event in agent.stream_async(initial_prompt):
                await queue.put(json.loads(json.dumps(dict(event), default=str)))

            # Agent finished normally
            if state.get_status() == STATUS_RUNNING:
                state.set_status(STATUS_COMPLETE)
                state.update_phase("complete", "Optimization finished")

        except Exception as e:
            logger.exception("Agent run failed")
            state.set_status(STATUS_FAILED)
            state.update_phase("failed", str(e)[:500])
            await queue.put({"status": "error", "error": str(e)})
        finally:
            await queue.put(None)  # sentinel

    _agent_running = True
    heartbeat_task = asyncio.create_task(_heartbeat_producer())
    agent_task = asyncio.create_task(_agent_producer())

    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        _agent_running = False
        heartbeat_task.cancel()
        # Ensure agent_task exceptions are surfaced, not silently swallowed
        if agent_task.done() and agent_task.exception():
            logger.error("Agent task exception: %s", agent_task.exception())


if __name__ == "__main__":
    app.run()
