# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Strands hooks for autonomous optimization loop and cancel checking.

CancelCheckHook: Checks DynamoDB before every tool call; cancels if externally cancelled.
OptimizationLoopHook: Drives the optimization loop via AfterInvocationEvent.resume.

See autotune/planning-docs/full-autonomy-research.md section 6 for architecture.
"""

import logging
import os

from strands.hooks import AfterInvocationEvent, AfterModelCallEvent, BeforeToolCallEvent
from strands.hooks.registry import HookProvider, HookRegistry

try:
    from optimization_state import OptimizationState, STATUS_COMPLETE
    from pricing import calculate_agent_cost
    from idpac_tools import get_eval_cost_usd
except ImportError:
    from state import OptimizationState, STATUS_COMPLETE
    from pricing import calculate_agent_cost
    from tools import get_eval_cost_usd

logger = logging.getLogger(__name__)


class OptimizationCancelled(Exception):
    """Raised when the user cancels the optimization run."""
    pass


class CancelCheckHook(HookProvider):
    """Check DynamoDB for cancel signal before every tool call.

    Raises OptimizationCancelled to immediately halt the agent.
    """

    def __init__(self, state: OptimizationState):
        self.state = state

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._check_cancel)

    def _check_cancel(self, event: BeforeToolCallEvent) -> None:
        if self.state.is_cancelled():
            logger.info("Optimization cancelled by user — raising to stop agent")
            self.state.update_phase("cancelled", "Cancelled by user")
            raise OptimizationCancelled("Optimization cancelled by user")


class FileReadSafetyHook(HookProvider):
    """Force file_read to always use mode='view' to prevent document-mode crashes on images."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._enforce_view_mode)

    def _enforce_view_mode(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use.get("name") == "file_read":
            tool_input = event.tool_use.get("input", {})
            if tool_input.get("mode") != "view":
                logger.info("FileReadSafetyHook: overriding mode=%s to view", tool_input.get("mode"))
                tool_input["mode"] = "view"


class CostTrackingHook(HookProvider):
    """Update DynamoDB with token cost after every model call."""

    def __init__(self, state: OptimizationState):
        self.state = state
        self.metrics = None  # Set to agent.event_loop_metrics after Agent() construction
        self.model_id = os.environ.get("AUTOTUNE_MODEL_ID", "")

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterModelCallEvent, self._update_cost)

    def _update_cost(self, event: AfterModelCallEvent) -> None:
        if not self.metrics:
            return
        usage = self.metrics.accumulated_usage
        it = usage.get("inputTokens", 0)
        ot = usage.get("outputTokens", 0)
        cr = usage.get("cacheReadInputTokens", 0)
        cw = usage.get("cacheWriteInputTokens", 0)
        agent_cost = calculate_agent_cost(self.model_id, it, ot, cr, cw)
        self.state.update_cost(
            agent_input_tokens=it, agent_output_tokens=ot,
            agent_cache_read_tokens=cr, agent_cache_write_tokens=cw,
            agent_cost_usd=agent_cost, eval_cost_usd=get_eval_cost_usd(),
        )


class OptimizationLoopHook(HookProvider):
    """Drive the optimization loop and enforce stopping criteria."""

    def __init__(self, state: OptimizationState, max_iterations: int = 10, patience: int = 3):
        self.state = state
        self.max_iterations = max_iterations
        self.patience = patience

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterInvocationEvent, self._check_and_resume)

    def _check_and_resume(self, event: AfterInvocationEvent) -> None:
        if self.state.is_cancelled():
            logger.info("Optimization cancelled — not resuming")
            return

        status = self.state.get_status()
        if status == STATUS_COMPLETE:
            logger.info("Optimization already complete — not resuming")
            return

        current = self.state.get_state()
        iteration = int(current.get("iteration", 0))

        # Max iterations reached — one final turn for summary, then stop
        if iteration >= self.max_iterations:
            logger.info("Max iterations (%d) reached — completing", self.max_iterations)
            self.state.set_status(STATUS_COMPLETE)
            self.state.update_phase("complete", "Max iterations reached")
            event.resume = (
                "You have reached the maximum number of iterations. "
                "Write a final summary of the optimization run and copy the best "
                "config to idpac_config_final.yaml. This is your last turn."
            )
            return

        # Accuracy plateau detection
        # TODO: Track no_improvement_count in DynamoDB once the agent reports
        # accuracy per iteration. For now, rely on the agent's own judgment
        # via OPTIMIZATION-LOG.md and prompt instructions.

        # Continue optimization
        best_accuracy = current.get("best_accuracy", 0)
        best_version = current.get("best_config_version", "none")
        event.resume = (
            f"Continue optimization. Iteration {iteration}/{self.max_iterations}. "
            f"Best accuracy so far: {best_accuracy}% (config {best_version}). "
            "Read OPTIMIZATION-LOG.md if you need to recall what has been tried. "
            "Proceed with the next optimization iteration."
        )
