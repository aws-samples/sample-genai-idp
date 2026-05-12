# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Proactive context management for long-running optimization agent.

Checks context usage before every model call. When threshold is exceeded,
summarizes the conversation via a single Bedrock Converse call (no agent/tools)
and re-injects the optimization log.
"""

import json
import logging
import os
import time

import boto3
from strands.agent.conversation_manager import ConversationManager
from strands.hooks import HookProvider, HookRegistry, BeforeModelCallEvent

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_TOKENS = 1_000_000  # Claude Opus/Sonnet context window

SUMMARIZATION_PROMPT = """You are a conversation summarizer. Provide a concise summary of the conversation history.

Format Requirements:
- You MUST create a structured and concise summary in bullet-point format.
- You MUST NOT respond conversationally.
- You MUST NOT address the user directly.

Task:
Create a structured summary document:
- Key topics and decisions made
- All significant tool executions and their results
- Any code or configuration changes made
- Key insights gained
- Current state and next steps

Format the summary in the third person."""


class ProactiveContextManager(ConversationManager):
    """No-op conversation manager passed to the Strands Agent constructor.

    Strands requires a ConversationManager but we handle context reduction ourselves
    via ContextCheckHook (which fires before every model call). This class exists only
    to satisfy the Agent interface — both methods are intentionally empty.
    """

    def apply_management(self, agent, **kwargs):
        pass

    def reduce_context(self, agent, **kwargs):
        pass


class ContextCheckHook(HookProvider):
    """Summarize conversation when context window usage exceeds threshold.

    Fires on BeforeModelCallEvent (before every LLM call). When context exceeds
    threshold_pct, summarizes older messages via a single Bedrock Converse call
    (no agent loop, no tools — avoids toolUse blocks in the summary), then
    re-injects OPTIMIZATION-LOG.md so the agent retains full optimization history.
    """

    def __init__(self, threshold_pct: float = 50.0, preserve_recent: int = 6):
        self.threshold_pct = threshold_pct
        self.preserve_recent = preserve_recent
        self._model_id = os.environ.get("AUTOTUNE_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
        self._bedrock = None

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeModelCallEvent, self._check)

    def _check(self, event: BeforeModelCallEvent) -> None:
        agent = event.agent
        for msg in reversed(agent.messages):
            if msg.get("role") == "assistant":
                usage = msg.get("metadata", {}).get("usage", {})
                if usage:
                    context_tokens = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0)
                    pct = context_tokens / CONTEXT_WINDOW_TOKENS * 100
                    if pct >= self.threshold_pct:
                        logger.info("Context at %.1f%% — summarizing", pct)
                        self._emit_stream_event("context_summarizing", pct)
                        self._summarize_and_replace(agent)
                        self._inject_log_reread(agent)
                        self._emit_stream_event("context_summarized", pct)
                return

    def _summarize_and_replace(self, agent):
        """Summarize older messages via a single Bedrock Converse call, keep recent ones."""
        messages = agent.messages
        if len(messages) <= self.preserve_recent:
            return

        # Find split point that doesn't break tool_use/tool_result pairs
        split = len(messages) - self.preserve_recent
        # Walk back if we'd split inside a tool pair
        while split > 0 and self._is_tool_result(messages[split]):
            split -= 1

        if split <= 0:
            return

        to_summarize = messages[:split]
        to_keep = messages[split:]

        # Build a converse-compatible message list from the messages to summarize
        converse_messages = self._to_converse_messages(to_summarize)
        converse_messages.append({"role": "user", "content": [{"text": "Please summarize this conversation."}]})

        # Single Bedrock call — no tools, just text
        if not self._bedrock:
            self._bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

        try:
            response = self._bedrock.converse(
                modelId=self._model_id,
                system=[{"text": SUMMARIZATION_PROMPT}],
                messages=converse_messages,
                inferenceConfig={"maxTokens": 4096},
            )
            summary_text = response["output"]["message"]["content"][0]["text"]
        except Exception as e:
            logger.error("Summarization call failed: %s", e)
            # Fallback: just truncate without summary
            summary_text = "(conversation history truncated)"

        # Replace messages: summary as user message + preserved recent messages
        agent.messages[:] = [
            {"role": "user", "content": [{"text": f"## Previous Conversation Summary\n\n{summary_text}"}]},
            {"role": "assistant", "content": [{"text": "Understood. I'll continue from where we left off."}]},
        ] + to_keep

    def _is_tool_result(self, msg):
        """Check if a message contains a toolResult block."""
        content = msg.get("content", [])
        if isinstance(content, list):
            return any(isinstance(b, dict) and "toolResult" in b for b in content)
        return False

    def _to_converse_messages(self, messages):
        """Convert agent messages to Bedrock Converse format (text-only, no tool blocks)."""
        result = []
        for msg in messages:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", [])
            if isinstance(content, str):
                result.append({"role": role, "content": [{"text": content}]})
                continue
            # Extract only text blocks — skip toolUse/toolResult
            text_blocks = []
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        text_blocks.append({"text": block["text"]})
                    elif "toolUse" in block:
                        tool = block["toolUse"]
                        text_blocks.append({"text": f"[Called tool: {tool.get('name', '?')}]"})
                    elif "toolResult" in block:
                        tr = block["toolResult"]
                        # Extract text from tool result content
                        tr_content = tr.get("content", [])
                        for trc in tr_content:
                            if isinstance(trc, dict) and "text" in trc:
                                text_blocks.append({"text": f"[Tool result: {trc['text'][:200]}]"})
                                break
                        else:
                            text_blocks.append({"text": "[Tool result received]"})
            if text_blocks:
                result.append({"role": role, "content": text_blocks})

        # Ensure alternating user/assistant (Bedrock requirement)
        cleaned = []
        for msg in result:
            if cleaned and cleaned[-1]["role"] == msg["role"]:
                # Merge consecutive same-role messages
                cleaned[-1]["content"].extend(msg["content"])
            else:
                cleaned.append(msg)

        # Ensure starts with user
        if cleaned and cleaned[0]["role"] == "assistant":
            cleaned.insert(0, {"role": "user", "content": [{"text": "(start of conversation)"}]})

        return cleaned

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
