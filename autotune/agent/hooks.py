# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Strands hooks for autonomous optimization loop and cancel checking.

CancelCheckHook: Checks DynamoDB before every tool call; cancels if externally cancelled.
OptimizationLoopHook: Drives the optimization loop via AfterInvocationEvent.resume.

See autotune/planning-docs/full-autonomy-research.md section 6 for architecture.
"""

import logging

from strands.hooks import AfterInvocationEvent, BeforeToolCallEvent
from strands.hooks.registry import HookProvider, HookRegistry

try:
    from optimization_state import OptimizationState, STATUS_COMPLETE
except ImportError:
    from state import OptimizationState, STATUS_COMPLETE

logger = logging.getLogger(__name__)


class CancelCheckHook(HookProvider):
    """Check DynamoDB for cancel signal before every tool call."""

    def __init__(self, state: OptimizationState):
        self.state = state

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._check_cancel)

    def _check_cancel(self, event: BeforeToolCallEvent) -> None:
        if self.state.is_cancelled():
            logger.info("Optimization cancelled by user — stopping before tool call")
            self.state.update_phase("cancelled", "Cancelled by user")
            event.cancel_tool = "Optimization cancelled by user"


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

        current = self.state.get_state()
        iteration = int(current.get("iteration", 0))

        # Max iterations reached
        if iteration >= self.max_iterations:
            logger.info("Max iterations (%d) reached — completing", self.max_iterations)
            self.state.set_status(STATUS_COMPLETE)
            self.state.update_phase("complete", "Max iterations reached")
            # One final turn to produce summary
            event.resume = (
                "You have reached the maximum number of iterations. "
                "Write a final summary of the optimization run and copy the best "
                "config to idpac_config_final.yaml."
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
