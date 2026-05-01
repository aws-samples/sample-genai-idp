# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
CloudWatch Metrics service for reading infrastructure performance metrics.

Covers Lambda, Bedrock, Textract, Step Functions, SQS, and custom IDP metrics.
This is a new service added in MR-03 to power the monitoring dashboard.

Usage::

    from idp_common_ext.monitoring import CloudWatchMetricsService, TimeRange

    svc = CloudWatchMetricsService()
    tr = TimeRange.last_n_hours(24)
    report = svc.get_throttle_report(
        services=["bedrock", "textract"],
        time_range=tr,
        model_ids=["anthropic.claude-3-5-sonnet-20241022-v2:0"],
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import boto3

from idp_common_ext.monitoring.models import TimeRange

logger = logging.getLogger(__name__)

# Number of throttle events above which a service is considered flagged.
_THROTTLE_THRESHOLD: int = 10


class CloudWatchMetricsService:
    """Reads CloudWatch Metrics for IDP infrastructure components."""

    def __init__(self, region: Optional[str] = None) -> None:
        self._region = region
        self._cw: Optional[Any] = None

    def _get_cw(self) -> Any:
        """Return (and lazily create) the CloudWatch boto3 client."""
        if self._cw is None:
            self._cw = boto3.client("cloudwatch", region_name=self._region)
        return self._cw

    # -------------------------------------------------------------------------
    # Low-level helper
    # -------------------------------------------------------------------------

    def _get_metric_data(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        time_range: TimeRange,
        stat: str = "Sum",
        period_seconds: int = 3600,
    ) -> List[Dict[str, Any]]:
        """
        Low-level metric data fetch using the GetMetricData API.

        Returns a list of ``{"timestamp": str, "value": float}`` dicts.
        """
        start, end = time_range.to_datetimes()
        response = self._get_cw().get_metric_data(
            MetricDataQueries=[
                {
                    "Id": "m1",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": namespace,
                            "MetricName": metric_name,
                            "Dimensions": dimensions,
                        },
                        "Period": period_seconds,
                        "Stat": stat,
                    },
                    "ReturnData": True,
                }
            ],
            StartTime=start,
            EndTime=end,
        )
        results = response.get("MetricDataResults", [{}])[0]
        timestamps = results.get("Timestamps", [])
        values = results.get("Values", [])
        return [
            {"timestamp": ts.isoformat(), "value": val}
            for ts, val in zip(timestamps, values)
        ]

    # -------------------------------------------------------------------------
    # Lambda metrics
    # -------------------------------------------------------------------------

    def get_lambda_metrics(
        self,
        function_names: List[str],
        time_range: TimeRange,
        period_seconds: int = 3600,
    ) -> Dict[str, Any]:
        """
        Get Duration (P50/P90/P99), Errors, Throttles, and Invocations per Lambda function.

        Returns::

            {
                "functions": {
                    "FunctionName": {
                        "duration_p50_ms": float,
                        "duration_p90_ms": float,
                        "duration_p99_ms": float,
                        "error_count": int,
                        "throttle_count": int,
                        "invocation_count": int,
                    }
                },
                "totals": {"errors": int, "throttles": int, "invocations": int}
            }
        """
        results: Dict[str, Any] = {
            "functions": {},
            "totals": {"errors": 0, "throttles": 0, "invocations": 0},
        }

        for fn_name in function_names:
            dims = [{"Name": "FunctionName", "Value": fn_name}]
            try:
                errors = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Lambda", "Errors", dims, time_range
                        )
                    )
                )
                throttles = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Lambda", "Throttles", dims, time_range
                        )
                    )
                )
                invocations = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Lambda", "Invocations", dims, time_range
                        )
                    )
                )
                duration_p50 = self._get_lambda_duration_percentile(
                    fn_name, time_range, "p50"
                )
                duration_p90 = self._get_lambda_duration_percentile(
                    fn_name, time_range, "p90"
                )
                duration_p99 = self._get_lambda_duration_percentile(
                    fn_name, time_range, "p99"
                )

                results["functions"][fn_name] = {
                    "duration_p50_ms": duration_p50,
                    "duration_p90_ms": duration_p90,
                    "duration_p99_ms": duration_p99,
                    "error_count": errors,
                    "throttle_count": throttles,
                    "invocation_count": invocations,
                }
                results["totals"]["errors"] += errors
                results["totals"]["throttles"] += throttles
                results["totals"]["invocations"] += invocations

            except Exception as exc:
                logger.warning("Failed to get Lambda metrics for %s: %s", fn_name, exc)
                results["functions"][fn_name] = None

        return results

    def _get_lambda_duration_percentile(
        self,
        function_name: str,
        time_range: TimeRange,
        percentile: str,
    ) -> float:
        """Get Lambda Duration at a specific percentile (p50, p90, p99)."""
        start, end = time_range.to_datetimes()
        total_seconds = int((end - start).total_seconds())
        try:
            response = self._get_cw().get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName="Duration",
                Dimensions=[{"Name": "FunctionName", "Value": function_name}],
                StartTime=start,
                EndTime=end,
                Period=total_seconds,
                ExtendedStatistics=[percentile],
            )
            datapoints = response.get("Datapoints", [])
            if datapoints:
                return float(
                    datapoints[0].get("ExtendedStatistics", {}).get(percentile, 0.0)
                )
        except Exception as exc:
            logger.warning(
                "Failed to get %s duration for %s: %s", percentile, function_name, exc
            )
        return 0.0

    # -------------------------------------------------------------------------
    # Bedrock metrics
    # -------------------------------------------------------------------------

    def get_bedrock_metrics(
        self,
        model_ids: List[str],
        time_range: TimeRange,
    ) -> Dict[str, Any]:
        """
        Get InvocationThrottles, InputTokenCount, and OutputTokenCount per Bedrock model.

        Returns::

            {
                "models": {
                    "model-id": {
                        "throttle_count": int,
                        "input_tokens": int,
                        "output_tokens": int,
                    }
                },
                "totals": {"throttles": int, "input_tokens": int, "output_tokens": int}
            }
        """
        results: Dict[str, Any] = {
            "models": {},
            "totals": {"throttles": 0, "input_tokens": 0, "output_tokens": 0},
        }

        for model_id in model_ids:
            dims = [{"Name": "ModelId", "Value": model_id}]
            try:
                throttles = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Bedrock", "InvocationThrottles", dims, time_range
                        )
                    )
                )
                input_tokens = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Bedrock", "InputTokenCount", dims, time_range
                        )
                    )
                )
                output_tokens = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "AWS/Bedrock", "OutputTokenCount", dims, time_range
                        )
                    )
                )

                results["models"][model_id] = {
                    "throttle_count": throttles,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }
                results["totals"]["throttles"] += throttles
                results["totals"]["input_tokens"] += input_tokens
                results["totals"]["output_tokens"] += output_tokens

            except Exception as exc:
                logger.warning(
                    "Failed to get Bedrock metrics for %s: %s", model_id, exc
                )

        return results

    # -------------------------------------------------------------------------
    # Textract metrics
    # -------------------------------------------------------------------------

    def get_textract_metrics(self, time_range: TimeRange) -> Dict[str, Any]:
        """
        Get Textract ThrottledCount and ServerErrorCount (account-level, no dimensions).

        Returns::

            {"throttle_count": int, "server_error_count": int}
        """
        results: Dict[str, Any] = {"throttle_count": 0, "server_error_count": 0}
        dims: List[
            Dict[str, str]
        ] = []  # Account-level Textract metrics have no dimensions
        try:
            results["throttle_count"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/Textract", "ThrottledCount", dims, time_range
                    )
                )
            )
            results["server_error_count"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/Textract", "ServerErrorCount", dims, time_range
                    )
                )
            )
        except Exception as exc:
            logger.warning("Failed to get Textract metrics: %s", exc)
        return results

    # -------------------------------------------------------------------------
    # Step Functions metrics
    # -------------------------------------------------------------------------

    def get_stepfunctions_metrics(
        self,
        state_machine_arn: str,
        time_range: TimeRange,
    ) -> Dict[str, Any]:
        """
        Get Step Functions ExecutionsFailed, ExecutionsThrottled, ExecutionsTimedOut,
        and average ExecutionTime.

        Returns::

            {
                "executions_failed": int,
                "executions_throttled": int,
                "executions_timed_out": int,
                "avg_execution_time_ms": float,
            }
        """
        dims = [{"Name": "StateMachineArn", "Value": state_machine_arn}]
        results: Dict[str, Any] = {
            "executions_failed": 0,
            "executions_throttled": 0,
            "executions_timed_out": 0,
            "avg_execution_time_ms": 0.0,
        }
        try:
            results["executions_failed"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/States", "ExecutionsFailed", dims, time_range
                    )
                )
            )
            results["executions_throttled"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/States", "ExecutionsThrottled", dims, time_range
                    )
                )
            )
            results["executions_timed_out"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/States", "ExecutionsTimedOut", dims, time_range
                    )
                )
            )
            # ExecutionTime is in milliseconds; use Average stat
            time_points = self._get_metric_data(
                "AWS/States", "ExecutionTime", dims, time_range, stat="Average"
            )
            if time_points:
                results["avg_execution_time_ms"] = sum(
                    p["value"] for p in time_points
                ) / len(time_points)
        except Exception as exc:
            logger.warning(
                "Failed to get Step Functions metrics for %s: %s",
                state_machine_arn,
                exc,
            )
        return results

    # -------------------------------------------------------------------------
    # SQS metrics
    # -------------------------------------------------------------------------

    def get_sqs_metrics(
        self,
        queue_url: str,
        time_range: TimeRange,
    ) -> Dict[str, Any]:
        """
        Get SQS queue depth and throughput metrics.

        Returns::

            {"messages_visible": int, "messages_sent": int, "messages_deleted": int}
        """
        queue_name = queue_url.split("/")[-1]
        dims = [{"Name": "QueueName", "Value": queue_name}]
        results: Dict[str, Any] = {
            "messages_visible": 0,
            "messages_sent": 0,
            "messages_deleted": 0,
        }
        try:
            visible = self._get_metric_data(
                "AWS/SQS",
                "ApproximateNumberOfMessagesVisible",
                dims,
                time_range,
                stat="Maximum",
            )
            results["messages_visible"] = int(visible[-1]["value"]) if visible else 0
            results["messages_sent"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/SQS", "NumberOfMessagesSent", dims, time_range
                    )
                )
            )
            results["messages_deleted"] = int(
                sum(
                    p["value"]
                    for p in self._get_metric_data(
                        "AWS/SQS", "NumberOfMessagesDeleted", dims, time_range
                    )
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to get SQS metrics for queue %s: %s", queue_name, exc
            )
        return results

    # -------------------------------------------------------------------------
    # Custom IDP (GENAIDP namespace) metrics
    # -------------------------------------------------------------------------

    def get_custom_idp_metrics(self, time_range: TimeRange) -> Dict[str, Any]:
        """
        Aggregate all metrics published to the ``GENAIDP`` namespace.

        These are written by ``idp_common/metrics/__init__.py`` ``put_metric()``
        calls.

        Returns::

            {"<MetricName>": int, ...}
        """
        results: Dict[str, Any] = {}
        try:
            cw = self._get_cw()
            paginator = cw.get_paginator("list_metrics")
            metric_names: set[str] = set()
            for page in paginator.paginate(Namespace="GENAIDP"):
                for m in page.get("Metrics", []):
                    metric_names.add(m["MetricName"])

            for metric_name in metric_names:
                total = int(
                    sum(
                        p["value"]
                        for p in self._get_metric_data(
                            "GENAIDP", metric_name, [], time_range
                        )
                    )
                )
                results[metric_name] = total
        except Exception as exc:
            logger.warning("Failed to get custom GENAIDP metrics: %s", exc)
        return results

    # -------------------------------------------------------------------------
    # Throttle report
    # -------------------------------------------------------------------------

    def get_throttle_report(
        self,
        services: List[str],
        time_range: TimeRange,
        model_ids: Optional[List[str]] = None,
        function_names: Optional[List[str]] = None,
        state_machine_arn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate throttle data across the requested services and return a
        structured report with flagged services and recommendations.

        Args:
            services:           Service names to check — any of
                                ``"bedrock"``, ``"textract"``, ``"lambda"``,
                                ``"stepfunctions"``.
            time_range:         Time range to analyse.
            model_ids:          Bedrock model IDs (required when ``"bedrock"``
                                is in *services*).
            function_names:     Lambda function names (required when
                                ``"lambda"`` is in *services*).
            state_machine_arn:  Step Functions ARN (required when
                                ``"stepfunctions"`` is in *services*).

        Returns::

            {
                "total_throttle_events": int,
                "by_service": {"bedrock": N, "textract": N, "lambda": N, ...},
                "flagged_services": ["bedrock"],
                "recommendations": ["Consider requesting quota increase for ..."],
                "time_range_hours": float,
            }
        """
        total = 0
        by_service: Dict[str, int] = {}
        flagged: List[str] = []
        recommendations: List[str] = []

        if "bedrock" in services and model_ids:
            bedrock = self.get_bedrock_metrics(model_ids, time_range)
            bedrock_throttles = bedrock["totals"]["throttles"]
            by_service["bedrock"] = bedrock_throttles
            total += bedrock_throttles
            if bedrock_throttles > _THROTTLE_THRESHOLD:
                flagged.append("bedrock")
                top_model = max(
                    bedrock["models"].items(),
                    key=lambda x: (
                        x[1].get("throttle_count", 0) if x[1] else 0  # type: ignore[union-attr]
                    ),
                    default=(None, None),
                )
                if top_model[0]:
                    recommendations.append(
                        f"Request Bedrock quota increase for model '{top_model[0]}' "
                        f"({bedrock_throttles} throttle events)"
                    )

        if "textract" in services:
            textract = self.get_textract_metrics(time_range)
            textract_throttles = textract["throttle_count"]
            by_service["textract"] = textract_throttles
            total += textract_throttles
            if textract_throttles > _THROTTLE_THRESHOLD:
                flagged.append("textract")
                recommendations.append(
                    f"Request Textract quota increase ({textract_throttles} throttle events)"
                )

        if "lambda" in services and function_names:
            lambda_metrics = self.get_lambda_metrics(function_names, time_range)
            lambda_throttles = lambda_metrics["totals"]["throttles"]
            by_service["lambda"] = lambda_throttles
            total += lambda_throttles
            if lambda_throttles > _THROTTLE_THRESHOLD:
                flagged.append("lambda")
                recommendations.append(
                    f"Review Lambda concurrency limits ({lambda_throttles} throttle events)"
                )

        if "stepfunctions" in services and state_machine_arn:
            sf_metrics = self.get_stepfunctions_metrics(state_machine_arn, time_range)
            sf_throttles = sf_metrics["executions_throttled"]
            by_service["stepfunctions"] = sf_throttles
            total += sf_throttles
            if sf_throttles > _THROTTLE_THRESHOLD:
                flagged.append("stepfunctions")
                recommendations.append(
                    f"Review Step Functions throttle limits ({sf_throttles} throttled executions)"
                )

        return {
            "total_throttle_events": total,
            "by_service": by_service,
            "flagged_services": flagged,
            "recommendations": recommendations,
            "time_range_hours": time_range.duration_hours(),
        }
