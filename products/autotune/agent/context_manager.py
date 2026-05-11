# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Proactive context management for long-running optimization agent.

Checks context usage before every model call. When threshold is exceeded,
summarizes the conversation and re-injects the optimization log.
"""

import json
import logging
import os
import time

from strands.agent.conversation_manager import SummarizingConversationManager
from strands.hooks import HookProvider, HookRegistry, BeforeModelCallEvent

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_TOKENS = 1_000_000  # Claude Opus/Sonnet context window


class ProactiveContextManager(SummarizingConversationManager):
    """Conversation manager that never triggers on its own — driven by the hook."""

    def __init__(self, **kwargs):
        kwargs.setdefault("summary_ratio", 0.5)
        kwargs.setdefault("preserve_recent_messages", 6)
        super().__init__(**kwargs)

    def apply_management(self, agent, **kwargs):
        """No-op — context check is done by ContextCheckHook before each model call."""
        pass


class ContextCheckHook(HookProvider):
    """Check context usage before every model call and summarize if over threshold."""

    def __init__(self, threshold_pct: float = 50.0):
        self.threshold_pct = threshold_pct

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeModelCallEvent, self._check)

    def _check(self, event: BeforeModelCallEvent) -> None:
        agent = event.agent
        # Find last assistant message with usage metadata
        for msg in reversed(agent.messages):
            if msg.get("role") == "assistant":
                usage = msg.get("metadata", {}).get("usage", {})
                if usage:
                    context_tokens = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0)
                    pct = context_tokens / CONTEXT_WINDOW_TOKENS * 100
                    if pct >= self.threshold_pct:
                        logger.info("Context at %.1f%% — summarizing", pct)
                        self._emit_stream_event("context_summarizing", pct)
                        agent.conversation_manager.reduce_context(agent)
                        self._inject_log_reread(agent)
                        self._emit_stream_event("context_summarized", pct)
                return

    def _inject_log_reread(self, agent):
        log_path = os.path.join(os.environ.get("AUTOTUNE_WORKSPACE_DIR", "/tmp"), "OPTIMIZATION-LOG.md")
        try:
            with open(log_path) as f:
                log_content = f.read()
        except FileNotFoundError:
            return
        agent.messages.append({
            "role": "user",
            "content": [{"text": (
                "Context was compressed. Here is the current optimization log — "
                "use it to recall what has been tried and the current state:\n\n"
                + log_content
            )}],
        })

    def _emit_stream_event(self, event_type: str, pct: float):
        scratch = os.environ.get("AUTOTUNE_SCRATCH_DIR", "")
        if not scratch:
            return
        stream_path = os.path.join(scratch, "stream.jsonl")
        event = {
            "type": event_type,
            "pct": round(pct, 1),
            "threshold_pct": self.threshold_pct,
            "ts": time.strftime("%H:%M:%S", time.gmtime()),
        }
        try:
            with open(stream_path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass
