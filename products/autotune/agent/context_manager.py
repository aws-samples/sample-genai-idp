# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Proactive context management for long-running optimization agent.

Triggers summarization at a configurable threshold (default 50%) and forces
the agent to re-read the optimization log after context reduction.
"""

import logging
import os

from strands.agent.conversation_manager import SummarizingConversationManager

logger = logging.getLogger(__name__)

# TODO: After strands-agents > 1.37.0 (May 7 2026), replace with
# model.get_config().get("context_window_limit")
CONTEXT_WINDOW_TOKENS = 1_000_000  # Claude Opus 4-6-v1


class ProactiveContextManager(SummarizingConversationManager):
    """Triggers summarization proactively at a token threshold, then injects log re-read."""

    def __init__(self, threshold_pct: float = 50.0, **kwargs):
        kwargs.setdefault("summary_ratio", 0.5)
        kwargs.setdefault("preserve_recent_messages", 6)
        super().__init__(**kwargs)
        self.threshold_pct = threshold_pct

    def apply_management(self, agent, **kwargs):
        """After each agent cycle, check if we've crossed the threshold."""
        # Get context size from last assistant message metadata
        for msg in reversed(agent.messages):
            if msg.get("role") == "assistant":
                usage = msg.get("metadata", {}).get("usage", {})
                if usage:
                    context_tokens = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0)
                    pct = context_tokens / CONTEXT_WINDOW_TOKENS * 100
                    if pct >= self.threshold_pct:
                        logger.info(
                            "Context at %.1f%% (threshold %.1f%%) — summarizing and injecting log re-read",
                            pct, self.threshold_pct,
                        )
                        self.reduce_context(agent)
                        self._inject_log_reread(agent)
                    return

    def _inject_log_reread(self, agent):
        """Append a user message instructing the agent to re-read the optimization log."""
        log_path = os.path.join(os.environ["AUTOTUNE_WORKSPACE_DIR"], "OPTIMIZATION-LOG.md")
        with open(log_path) as f:
            log_content = f.read()
        agent.messages.append({
            "role": "user",
            "content": [{"text": (
                "Context was compressed. Here is the current optimization log — "
                "use it to recall what has been tried and the current state:\n\n"
                + log_content
            )}],
        })
