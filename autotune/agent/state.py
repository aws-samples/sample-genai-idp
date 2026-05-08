# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Optimization state tracking via DynamoDB (control plane).

Single `status` field controls both lifecycle and UI display.
Terminal statuses (agent stops): complete, failed, cancelled
Active statuses (agent runs): initializing, evaluating, analyzing, configuring,
    discovering, downloading, finalizing, resuming
"""

import logging
import os
import time
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled"})


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
        max_cost_per_page_usd: float = 0.0,
    ) -> None:
        """Create the initial state item for a new optimization run."""
        self._table.put_item(
            Item={
                "session_id": self.session_id,
                "status": "initializing",
                "status_detail": "Starting optimization run",
                "iteration": 0,
                "max_iterations": max_iterations,
                "max_cost_per_page_usd": str(round(max_cost_per_page_usd, 5)),
                "best_accuracy_within_budget": 0,
                "best_config_version_within_budget": "",
                "current_config_version": "",
                "test_set_id": test_set_id,
                "optimization_guidance": optimization_guidance,
                "started_at": _now(),
                "updated_at": _now(),
                "last_heartbeat_at": _now(),
            }
        )

    def get_status(self) -> str:
        """Read the status field."""
        resp = self._table.get_item(
            Key={"session_id": self.session_id},
            ProjectionExpression="#s",
            ExpressionAttributeNames={"#s": "status"},
        )
        return resp.get("Item", {}).get("status", "unknown")

    def is_terminal(self) -> bool:
        """Check if the run is in a terminal state (complete/failed/cancelled)."""
        return self.get_status() in TERMINAL_STATUSES

    def get_state(self) -> dict:
        """Read the full state item."""
        resp = self._table.get_item(Key={"session_id": self.session_id})
        return resp.get("Item", {})

    def set_status(self, status: str, detail: str = "") -> None:
        """Set the status and optional detail."""
        self._update_expr(
            "SET #s = :s, status_detail = :d, updated_at = :t",
            {":s": status, ":d": detail, ":t": _now()},
            {"#s": "status"},
        )

    def heartbeat(self) -> None:
        """Touch last_heartbeat_at for stale session detection."""
        self._update_expr("SET last_heartbeat_at = :t", {":t": _now()})

    def update_metrics(
        self,
        iteration: int,
        best_accuracy_within_budget: float,
        best_config_version_within_budget: str,
        current_config_version: str = "",
        best_cost_per_page_usd: float = 0.0,
    ) -> None:
        """Update iteration metrics."""
        self._update_expr(
            "SET iteration = :i, best_accuracy_within_budget = :a, best_config_version_within_budget = :b, "
            "current_config_version = :c, best_cost_per_page_usd = :cpp, updated_at = :t",
            {
                ":i": iteration,
                ":a": str(best_accuracy_within_budget),
                ":b": best_config_version_within_budget,
                ":c": current_config_version,
                ":cpp": str(round(best_cost_per_page_usd, 5)),
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
        eval_seen_batches: str = "",
        context_window_pct: float = 0.0,
    ) -> None:
        """Update token usage and cost (agent + eval tracked separately)."""
        self._update_expr(
            "SET agent_input_tokens = :it, agent_output_tokens = :ot, "
            "agent_cache_read_tokens = :cr, agent_cache_write_tokens = :cw, "
            "agent_cost_usd = :ac, eval_cost_usd = :ec, eval_seen_batches = :esb, "
            "context_window_pct = :cwp, updated_at = :t",
            {
                ":it": agent_input_tokens,
                ":ot": agent_output_tokens,
                ":cr": agent_cache_read_tokens,
                ":cw": agent_cache_write_tokens,
                ":ac": str(round(agent_cost_usd, 4)),
                ":ec": str(round(eval_cost_usd, 4)),
                ":esb": eval_seen_batches,
                ":cwp": str(round(context_window_pct, 1)),
                ":t": _now(),
            },
        )

    def _update_expr(
        self, expr: str, values: dict, names: Optional[dict] = None
    ) -> None:
        """Run an UpdateItem with the given expression."""
        kwargs = {
            "Key": {"session_id": self.session_id},
            "UpdateExpression": expr,
            "ExpressionAttributeValues": values,
        }
        if names:
            kwargs["ExpressionAttributeNames"] = names
        self._table.update_item(**kwargs)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
