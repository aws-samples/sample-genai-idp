"""IDPAutoTune agent — automated IDP Accelerator config optimization.

Runs as a Strands agent on AgentCore via the FAST BedrockAgentCoreApp entrypoint.
"""

import json
import logging
import os
from pathlib import Path

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import editor, file_read, file_write, shell
from utils.auth import extract_user_id_from_context

from idpac_tools import ALL_TOOLS as IDPAC_TOOLS

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

AGENT_DIR = Path(__file__).parent


def _load_system_prompt() -> str:
    return (AGENT_DIR / "prompt.md").read_text()


def _create_session_manager(
    user_id: str, session_id: str
) -> AgentCoreMemorySessionManager:
    """Create an AgentCore memory session manager."""
    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        raise ValueError("MEMORY_ID environment variable is required")

    use_ltm = os.environ.get("USE_LONG_TERM_MEMORY", "false").lower() == "true"
    top_k = int(os.environ.get("LTM_TOP_K", "10"))
    relevance_score = float(os.environ.get("LTM_RELEVANCE_SCORE", "0.3"))

    retrieval_config = (
        {
            "/facts/{actorId}": RetrievalConfig(
                top_k=top_k,
                relevance_score=relevance_score,
            )
        }
        if use_ltm
        else None
    )

    config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=user_id,
        retrieval_config=retrieval_config,
    )
    return AgentCoreMemorySessionManager(
        agentcore_memory_config=config,
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def create_autotune_agent(user_id: str, session_id: str) -> Agent:
    """Create the IDPAutoTune Strands agent with IDPAC tools and skills."""
    model = BedrockModel(
        model_id=os.environ.get(
            "AUTOTUNE_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
        ),
        max_tokens=16384,
    )

    session_manager = _create_session_manager(user_id, session_id)

    # Skills plugin — auto-discovers SKILL.md files
    skills_dir = AGENT_DIR / "skills"
    plugins = []
    if skills_dir.exists():
        plugins.append(AgentSkills(skills=str(skills_dir)))

    # IDPAC-specific tools + general-purpose community tools
    tools = IDPAC_TOOLS + [file_read, file_write, editor, shell]

    return Agent(
        name="idp_autotune",
        model=model,
        system_prompt=_load_system_prompt(),
        tools=tools,
        plugins=plugins,
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

    try:
        user_id = extract_user_id_from_context(context)
        agent = create_autotune_agent(user_id, session_id)

        async for event in agent.stream_async(user_query):
            yield json.loads(json.dumps(dict(event), default=str))

    except Exception as e:
        logger.exception("Agent run failed")
        yield {"status": "error", "error": str(e)}


if __name__ == "__main__":
    app.run()
