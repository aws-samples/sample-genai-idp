# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""IDPAutoTune Strands agent — automated IDP Accelerator config optimization.

Usage (local):
    export IDP_STACK_NAME=MyIDPStack
    export AWS_DEFAULT_REGION=us-east-1
    export BYPASS_TOOL_CONSENT=true
    python agent.py
"""

import os
import sys
from pathlib import Path

from strands import Agent, AgentSkills
from strands.models import BedrockModel
from strands_tools import editor, file_read, file_write, shell

from tools import ALL_TOOLS

AGENT_DIR = Path(__file__).parent


def load_system_prompt() -> str:
    """Load the IDPAC optimizer system prompt."""
    prompt_path = AGENT_DIR / "prompt.md"
    return prompt_path.read_text()


def create_agent() -> Agent:
    """Create the IDPAutoTune Strands agent with all tools and skills."""
    model = BedrockModel(
        model_id=os.environ.get(
            "AUTOTUNE_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
        ),
        max_tokens=16384,
    )

    # Skills plugin — auto-discovers all SKILL.md files in skills/
    skills_dir = AGENT_DIR / "skills"
    plugins = []
    if skills_dir.exists():
        plugins.append(AgentSkills(skills=str(skills_dir)))

    # Combine IDPAC-specific tools with general-purpose community tools
    tools = ALL_TOOLS + [file_read, file_write, editor, shell]

    return Agent(
        model=model,
        system_prompt=load_system_prompt(),
        tools=tools,
        plugins=plugins,
    )


def main():
    """Run the agent in interactive mode for local testing."""
    os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")

    agent = create_agent()
    print("IDPAutoTune agent ready. Type your message (Ctrl+C to exit).\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            response = agent(user_input)
            print(f"\nAgent: {response}\n")
        except KeyboardInterrupt:
            print("\nExiting.")
            break


if __name__ == "__main__":
    main()
