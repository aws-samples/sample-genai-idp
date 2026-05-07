# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDPMonitor CLI plugin — ``idp monitoring`` command group.

Registered via the ``idp_cli.plugins`` entry point in ``setup.py``.
The open-source ``idp_cli`` calls ``discover_cli_plugins(cli)`` at startup,
which calls ``register(cli)`` here — adding the ``monitoring`` command group
to the IDP CLI automatically when ``idp_common_ext`` is installed.

Commands added::

    idp monitoring dashboard    Full dashboard (all sections)
    idp monitoring volume       Volume and status metrics
    idp monitoring costs        Cost / token metrics (auto-Athena)
    idp monitoring failures     Recently failed documents
    idp monitoring throttles    CloudWatch throttle report
    idp monitoring performance  X-Ray latency percentiles (P50/P90/P99)
    idp monitoring config       Active config version and doc type list

Analytics sub-group (Athena-backed, premium)::

    idp monitoring analytics token-usage      Token usage by model + context
    idp monitoring analytics cost-trends      Cost time-series
    idp monitoring analytics cost-by-version  Cost per config version
    idp monitoring analytics model-usage      Per-model cost breakdown

All commands support ``--stack STACK`` and ``--output json|table``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import click

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: resolve stack name
# ---------------------------------------------------------------------------


def _resolve_stack(stack: Optional[str]) -> str:
    """Return stack name from CLI arg or STACK_NAME env var."""
    resolved = stack or os.environ.get("STACK_NAME", "")
    if not resolved:
        raise click.ClickException(
            "Stack name is required. Use --stack STACK or set the STACK_NAME env var."
        )
    return resolved


def _output_result(data: dict, output_format: str) -> None:
    """Print data in the requested format."""
    if output_format == "json":
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        # Basic table — just pretty-print JSON for now; widgets format their own output
        click.echo(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("monitoring")
def monitoring_group() -> None:
    """Monitor IDP pipeline performance and health. (IDPMonitor — premium)"""
    pass


# ---------------------------------------------------------------------------
# Analytics sub-group
# ---------------------------------------------------------------------------


@monitoring_group.group("analytics")
def analytics_group() -> None:
    """Historical analytics powered by Athena. (IDPMonitor — premium)"""
    pass


# ---------------------------------------------------------------------------
# Core monitoring commands
# ---------------------------------------------------------------------------


@monitoring_group.command("dashboard")
@click.option("--hours", default=24, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option("--prefix", default=None, help="S3 key prefix filter.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def dashboard(
    hours: int, stack: Optional[str], prefix: Optional[str], output: str
) -> None:
    """Show full monitoring dashboard (all sections)."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_dashboard(hours=hours, doc_prefix=prefix)
    _output_result(result, output)


@monitoring_group.command("volume")
@click.option("--hours", default=24, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def volume(hours: int, stack: Optional[str], output: str) -> None:
    """Show document volume and status metrics."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_volume_metrics(hours=hours)
    _output_result(result, output)


@monitoring_group.command("costs")
@click.option("--hours", default=24, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def costs(hours: int, stack: Optional[str], output: str) -> None:
    """Show cost and token metrics (auto-routes to Athena when configured)."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_cost_metrics(hours=hours)
    _output_result(result, output)


@monitoring_group.command("failures")
@click.option("--hours", default=24, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def failures(hours: int, stack: Optional[str], output: str) -> None:
    """Show recently failed documents with error details."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_recent_failures(hours=hours)
    _output_result(result, output)


@monitoring_group.command("throttles")
@click.option("--hours", default=1, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def throttles(hours: int, stack: Optional[str], output: str) -> None:
    """Show CloudWatch throttle report with severity badges."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_throttle_report(hours=hours)
    _output_result(result, output)


@monitoring_group.command("performance")
@click.option("--hours", default=1, show_default=True, help="Time range in hours.")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def performance(hours: int, stack: Optional[str], output: str) -> None:
    """Show X-Ray latency percentiles (P50/P90/P99) by pipeline stage."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_latency_metrics(hours=hours)
    _output_result(result, output)


@monitoring_group.command("config")
@click.option("--stack", default=None, help="IDP Accelerator stack name.")
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
def config(stack: Optional[str], output: str) -> None:
    """Show active IDP config version and document type list."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_config_info()
    _output_result(result, output)


# ---------------------------------------------------------------------------
# Analytics sub-commands (Athena-backed)
# ---------------------------------------------------------------------------


@analytics_group.command("token-usage")
@click.option("--hours", default=24, show_default=True)
@click.option("--stack", default=None)
@click.option("--output", type=click.Choice(["table", "json"]), default="table")
def token_usage(hours: int, stack: Optional[str], output: str) -> None:
    """Token usage breakdown by model and processing context (Athena)."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_token_utilization(hours=hours)
    _output_result(
        result or {"message": "Athena not configured for this stack."}, output
    )


@analytics_group.command("cost-trends")
@click.option("--hours", default=168, show_default=True, help="Default: 7 days.")
@click.option("--bucket", type=click.Choice(["hour", "day", "week"]), default="day")
@click.option("--stack", default=None)
@click.option("--output", type=click.Choice(["table", "json"]), default="table")
def cost_trends(hours: int, bucket: str, stack: Optional[str], output: str) -> None:
    """Cost time-series data (Athena). Bucket by hour/day/week."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_cost_trends(hours=hours, bucket=bucket)
    _output_result(
        result or {"message": "Athena not configured for this stack."}, output
    )


@analytics_group.command("cost-by-version")
@click.option("--hours", default=720, show_default=True, help="Default: 30 days.")
@click.option("--stack", default=None)
@click.option("--output", type=click.Choice(["table", "json"]), default="table")
def cost_by_version(hours: int, stack: Optional[str], output: str) -> None:
    """Cost and document volume per config version (Athena)."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_cost_by_config_version(hours=hours)
    _output_result(
        result or {"message": "Athena not configured for this stack."}, output
    )


@analytics_group.command("model-usage")
@click.option("--hours", default=24, show_default=True)
@click.option("--stack", default=None)
@click.option("--output", type=click.Choice(["table", "json"]), default="table")
def model_usage(hours: int, stack: Optional[str], output: str) -> None:
    """Per-model cost breakdown and usage statistics (Athena)."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    ops = MonitoringOperations(_resolve_stack(stack))
    result = ops.get_model_usage(hours=hours)
    _output_result(
        result or {"message": "Athena not configured for this stack."}, output
    )


# ---------------------------------------------------------------------------
# Entry point called by open-source plugin discovery
# ---------------------------------------------------------------------------


def register(cli_group: click.Group) -> None:
    """
    Entry point called by ``idp_cli.discover_cli_plugins(cli)``.

    Adds the ``monitoring`` command group (and its ``analytics`` sub-group)
    to the open-source IDP CLI.
    """
    cli_group.add_command(monitoring_group)
    logger.debug("IDPMonitor CLI plugin registered: 'monitoring' command group added")
