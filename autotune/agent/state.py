# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Optimization state tracking via DynamoDB (control plane).

Provides a thin wrapper around a DynamoDB table for tracking optimization
run status, phase, and metrics. Read by hooks (cancel check) and frontend
(progress polling). Written by the agent and externally for cancel.

See autotune/planning-docs/full-autonomy-research.md section 6 for architecture.
"""

import logging
import os
import time
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

STATUS_RUNNING = "running"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"


class OptimizationState:
    """Manages optimization state in DynamoDB."""

    def __init__(self, session_id: str, table_name: Optional[str] = None):
        self.session_id = session_id
        self.table_name = table_name or os.environ.get("AUTOTUNE_STATE_TABLE")
        if not self.table_name:
            raise ValueError("AUTOTUNE_STATE_TABLE env var or table_name required")
        self._table = boto3.resource("dynamodb").Table(self.table_name)

    def initialize(
        self,
        test_set_id: str,
        optimization_guidance: str = "",
        max_iterations: int = 10,
    ) -> None:
        """Create the initial state item for a new optimization run."""
        try:
            self._table.put_item(
                Item={
                    "session_id": self.session_id,
                    "status": STATUS_RUNNING,
                    "phase": "initializing",
                    "phase_detail": "Starting optimization run",
                    "iteration": 0,
                    "max_iterations": max_iterations,
                    "best_accuracy": 0,
                    "best_config_version": "",
                    "current_config_version": "",
                    "test_set_id": test_set_id,
                    "optimization_guidance": optimization_guidance,
                    "started_at": _now(),
                    "updated_at": _now(),
                    "last_heartbeat_at": _now(),
                }
            )
        except Exception:
            logger.exception("Failed to initialize optimization state")

    def is_cancelled(self) -> bool:
        """Check if the run has been cancelled. Used by hooks."""
        return self.get_status() == STATUS_CANCELLED

    def get_status(self) -> str:
        """Read just the status field. Returns 'unknown' on error."""
        try:
            resp = self._table.get_item(
                Key={"session_id": self.session_id},
                ProjectionExpression="#s",
                ExpressionAttributeNames={"#s": "status"},
            )
            return resp.get("Item", {}).get("status", "unknown")
        except Exception:
            logger.exception("Failed to read optimization status")
            return "unknown"

    def get_state(self) -> dict:
        """Read the full state item. Returns empty dict on error."""
        try:
            resp = self._table.get_item(Key={"session_id": self.session_id})
            return resp.get("Item", {})
        except Exception:
            logger.exception("Failed to read optimization state")
            return {}

    def set_status(self, status: str) -> None:
        """Update the status field (use STATUS_* constants)."""
        self._update_expr(
            "SET #s = :s, updated_at = :t",
            {":s": status, ":t": _now()},
            {"#s": "status"},
        )

    def update_phase(self, phase: str, phase_detail: str = "") -> None:
        """Update phase and phase_detail."""
        self._update_expr(
            "SET phase = :p, phase_detail = :d, updated_at = :t",
            {":p": phase, ":d": phase_detail, ":t": _now()},
        )

    def heartbeat(self) -> None:
        """Touch last_heartbeat_at for stale session detection.

        Separate from updated_at, which tracks the last agent/tool state change.
        """
        self._update_expr("SET last_heartbeat_at = :t", {":t": _now()})

    def update_metrics(
        self,
        iteration: int,
        best_accuracy: float,
        best_config_version: str,
        current_config_version: str = "",
    ) -> None:
        """Update iteration metrics."""
        self._update_expr(
            "SET iteration = :i, best_accuracy = :a, best_config_version = :b, "
            "current_config_version = :c, updated_at = :t",
            {
                ":i": iteration,
                ":a": str(best_accuracy),
                ":b": best_config_version,
                ":c": current_config_version,
                ":t": _now(),
            },
        )

    def update_cost(
        self,
        agent_input_tokens: int = 0,
        agent_output_tokens: int = 0,
        agent_cache_read_tokens: int = 0,
        agent_cache_write_tokens: int = 0,
        agent_cost_usd: float = 0.0,
        eval_cost_usd: float = 0.0,
    ) -> None:
        """Update token usage and cost (agent + eval tracked separately)."""
        self._update_expr(
            "SET agent_input_tokens = :it, agent_output_tokens = :ot, "
            "agent_cache_read_tokens = :cr, agent_cache_write_tokens = :cw, "
            "agent_cost_usd = :ac, eval_cost_usd = :ec, updated_at = :t",
            {
                ":it": agent_input_tokens,
                ":ot": agent_output_tokens,
                ":cr": agent_cache_read_tokens,
                ":cw": agent_cache_write_tokens,
                ":ac": str(round(agent_cost_usd, 4)),
                ":ec": str(round(eval_cost_usd, 4)),
                ":t": _now(),
            },
        )

    def _update_expr(
        self, expr: str, values: dict, names: Optional[dict] = None
    ) -> None:
        """Run an UpdateItem with the given expression."""
        try:
            kwargs = {
                "Key": {"session_id": self.session_id},
                "UpdateExpression": expr,
                "ExpressionAttributeValues": values,
            }
            if names:
                kwargs["ExpressionAttributeNames"] = names
            self._table.update_item(**kwargs)
        except Exception:
            logger.exception("Failed to update optimization state")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
