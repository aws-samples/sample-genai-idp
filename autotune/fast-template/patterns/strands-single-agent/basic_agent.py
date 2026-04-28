"""IDPAutoTune agent — automated IDP Accelerator config optimization.

Runs as a Strands agent on AgentCore via the FAST BedrockAgentCoreApp entrypoint.
Operates autonomously: receives test_set_id + optional optimization_guidance,
runs iterative optimization to completion (or cancellation), and produces an
optimized IDP Accelerator config.
"""

import json
import logging
import os
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
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
    ]
    if optimization_guidance:
        parts.append(f"\nOptimization guidance from the user:\n{optimization_guidance}")
    parts.append(
        "\nStart by reading the current IDP config, then run the test set to "
        "establish a baseline. Log everything to OPTIMIZATION-LOG.md."
    )
    return "\n".join(parts)


def create_autotune_agent(
    user_id: str,
    session_id: str,
    state: OptimizationState,
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
    """Main entrypoint — called by AgentCore Runtime on each request."""
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

    # Parse test_set_id from payload or prompt
    test_set_id = payload.get("test_set_id", "").strip()
    optimization_guidance = payload.get("optimization_guidance", "").strip()

    if test_set_id:
        # Autonomous mode: test_set_id provided explicitly
        state.initialize(test_set_id, optimization_guidance, MAX_ITERATIONS)
        initial_prompt = _build_initial_prompt(test_set_id, optimization_guidance)
    else:
        # Interactive/dev mode: pass through user query, initialize with placeholder
        state.initialize("interactive", "", MAX_ITERATIONS)
        initial_prompt = user_query

    try:
        user_id = extract_user_id_from_context(context)
        agent = create_autotune_agent(user_id, session_id, state)

        async for event in agent.stream_async(initial_prompt):
            yield json.loads(json.dumps(dict(event), default=str))

        # If we get here without cancel/failure, mark complete
        if state.get_status() == STATUS_RUNNING:
            state.set_status(STATUS_COMPLETE)
            state.update_phase("complete", "Optimization finished")

    except Exception as e:
        logger.exception("Agent run failed")
        state.set_status(STATUS_FAILED)
        state.update_phase("failed", str(e)[:500])
        yield {"status": "error", "error": str(e)}


if __name__ == "__main__":
    app.run()
