# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Test Studio operations processor."""

import json
import logging
import time
from typing import Dict, List, Optional

import boto3

from idp_sdk._core.stack_info import StackInfo
from idp_sdk.exceptions import IDPProcessingError, IDPResourceNotFoundError

logger = logging.getLogger(__name__)


class TestStudioProcessor:
    """Processes Test Studio operations (test result retrieval and comparison)."""

    # Tell pytest not to collect this class as a test (name starts with "Test").
    __test__ = False

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """Initialize Test Studio processor.

        Args:
            stack_name: CloudFormation stack name
            region: AWS region (defaults to session region)
        """
        self.stack_info = StackInfo(stack_name=stack_name, region=region)
        self.lambda_client = boto3.client("lambda", region_name=self.stack_info.region)
        self._resolver_arn = None

    def _get_api_resolver_stack_output(self, output_key: str) -> Optional[str]:
        """Get an output from the nested API resolver stack.

        The stack's logical id is APIRESOLVERSTACK on current templates and
        was APPSYNCSTACK before the AppSync removal — try both so the SDK
        keeps working against stacks deployed from older templates.

        Raises:
            ValueError: If neither nested stack (or the output) is found.
        """
        try:
            return self.stack_info.get_nested_stack_output(
                nested_stack_pattern="apiresolver",
                output_key=output_key,
            )
        except ValueError:
            return self.stack_info.get_nested_stack_output(
                nested_stack_pattern="appsync",
                output_key=output_key,
            )

    def _get_resolver_function_arn(self) -> str:
        """Get TestResultsResolverFunction ARN from nested AppSync stack outputs.

        Returns:
            Lambda function ARN

        Raises:
            IDPResourceNotFoundError: If function not found in stack
        """
        if self._resolver_arn:
            return self._resolver_arn

        try:
            # TestResultsResolverFunctionArn is in the nested API resolver
            # stack (APIRESOLVERSTACK), not the main stack
            resolver_arn = self._get_api_resolver_stack_output(
                "TestResultsResolverFunctionArn"
            )

            if not resolver_arn:
                raise IDPResourceNotFoundError(
                    "TestResultsResolverFunctionArn not found in nested API resolver stack. "
                    "Ensure Test Studio is enabled in your stack."
                )

            self._resolver_arn = resolver_arn
            logger.debug(f"Found TestResultsResolverFunction: {resolver_arn}")
            return resolver_arn

        except ValueError as e:
            # Convert ValueError from get_nested_stack_output to IDPResourceNotFoundError
            raise IDPResourceNotFoundError(
                f"Failed to get TestResultsResolverFunction ARN: {e}. "
                "Ensure Test Studio is enabled in your stack."
            ) from e
        except Exception as e:
            raise IDPResourceNotFoundError(
                f"Failed to get TestResultsResolverFunction ARN: {e}"
            ) from e

    def get_test_run_status(self, test_run_id: str) -> str:
        """Get current status of a test run.

        Args:
            test_run_id: Test run identifier

        Returns:
            Status string (QUEUED, RUNNING, EVALUATING, COMPLETE, PARTIAL_COMPLETE, FAILED, CANCELED)

        Raises:
            IDPProcessingError: If status check fails
        """
        resolver_arn = self._get_resolver_function_arn()

        try:
            payload = {
                "info": {"fieldName": "getTestRunStatus"},
                "arguments": {"testRunId": test_run_id},
            }

            response = self.lambda_client.invoke(
                FunctionName=resolver_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            result = json.loads(response["Payload"].read())

            if "errorMessage" in result:
                raise IDPProcessingError(
                    f"Failed to get test run status: {result['errorMessage']}"
                )

            status = result.get("status", "UNKNOWN")
            logger.debug(f"Test run {test_run_id} status: {status}")
            return status

        except Exception as e:
            raise IDPProcessingError(f"Failed to get test run status: {e}") from e

    def get_test_result(
        self,
        test_run_id: str,
        wait: bool = False,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> Dict:
        """Get test result for a test run.

        Args:
            test_run_id: Test run identifier
            wait: Wait for test run to complete if still in progress
            timeout: Maximum wait time in seconds (default: 300)
            poll_interval: Polling interval in seconds (default: 5)

        Returns:
            Dictionary with test result data

        Raises:
            IDPProcessingError: If retrieval fails or timeout occurs
        """
        resolver_arn = self._get_resolver_function_arn()

        # Wait for completion if requested
        if wait:
            logger.info(f"Waiting for test run {test_run_id} to complete...")
            start_time = time.time()

            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise IDPProcessingError(
                        f"Timeout waiting for test run {test_run_id} to complete after {timeout}s"
                    )

                status = self.get_test_run_status(test_run_id)

                # Final states
                if status in ["COMPLETE", "PARTIAL_COMPLETE", "FAILED", "CANCELED"]:
                    logger.info(
                        f"Test run {test_run_id} finished with status: {status}"
                    )
                    break

                # Still in progress
                logger.debug(
                    f"Test run {test_run_id} still in progress (status: {status}), "
                    f"elapsed: {elapsed:.0f}s"
                )
                time.sleep(poll_interval)

        # Get full test results
        try:
            payload = {
                "info": {"fieldName": "getTestRun"},
                "arguments": {"testRunId": test_run_id},
            }

            response = self.lambda_client.invoke(
                FunctionName=resolver_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            result = json.loads(response["Payload"].read())

            if "errorMessage" in result:
                error_msg = result["errorMessage"]
                if "evaluating" in error_msg.lower():
                    raise IDPProcessingError(
                        f"Test run {test_run_id} is still evaluating. Use wait=True to wait for completion."
                    )
                raise IDPProcessingError(f"Failed to get test result: {error_msg}")

            logger.info(f"Retrieved test result for {test_run_id}")
            return result

        except Exception as e:
            raise IDPProcessingError(f"Failed to get test result: {e}") from e

    def compare_test_runs(self, test_run_ids: List[str]) -> Dict:
        """Compare multiple test runs.

        Args:
            test_run_ids: List of test run identifiers to compare

        Returns:
            Dictionary with comparison metrics for each test run

        Raises:
            IDPProcessingError: If comparison fails
        """
        if len(test_run_ids) < 2:
            raise ValueError("At least 2 test run IDs required for comparison")

        resolver_arn = self._get_resolver_function_arn()

        try:
            # Fetch all test runs
            metrics = {}
            for test_run_id in test_run_ids:
                payload = {
                    "info": {"fieldName": "getTestRun"},
                    "arguments": {"testRunId": test_run_id},
                }

                response = self.lambda_client.invoke(
                    FunctionName=resolver_arn,
                    InvocationType="RequestResponse",
                    Payload=json.dumps(payload),
                )

                result = json.loads(response["Payload"].read())

                if "errorMessage" in result:
                    logger.warning(
                        f"Failed to get test run {test_run_id}: {result['errorMessage']}"
                    )
                    continue

                # Extract key metrics
                metrics[test_run_id] = {
                    "testRunId": result.get("testRunId"),
                    "testSetName": result.get("testSetName"),
                    "status": result.get("status"),
                    "filesCount": result.get("filesCount", 0),
                    "completedFiles": result.get("completedFiles", 0),
                    "failedFiles": result.get("failedFiles", 0),
                    "overallAccuracy": result.get("overallAccuracy"),
                    "accuracyBreakdown": result.get("accuracyBreakdown", {}),
                    "totalCost": result.get("totalCost", 0.0),
                    "createdAt": result.get("createdAt"),
                    "completedAt": result.get("completedAt"),
                }

            if not metrics:
                raise IDPProcessingError(
                    "No test runs could be retrieved for comparison"
                )

            logger.info(f"Compared {len(metrics)} test runs")
            return {"metrics": metrics}

        except Exception as e:
            raise IDPProcessingError(f"Failed to compare test runs: {e}") from e

    def abort_test_runs(self, test_run_ids: List[str]) -> Dict:
        """Abort one or more test runs.

        Args:
            test_run_ids: List of test run identifiers to abort

        Returns:
            Dictionary with abort results including counts and errors

        Raises:
            IDPProcessingError: If abort operation fails
        """
        # Get AbortTestRunsResolverFunction ARN from nested API resolver stack.
        # get_nested_stack_output raises ValueError when the stack or output
        # is missing (the previous `except IDPResourceNotFoundError` never
        # matched, so the friendly message below was dead code).
        try:
            abort_function_arn = self._get_api_resolver_stack_output(
                "AbortTestRunsResolverFunctionArn"
            )
        except ValueError as e:
            raise IDPResourceNotFoundError(
                "AbortTestRunsResolverFunction not found. "
                "Ensure you are using a stack version that supports test run abort."
            ) from e

        try:
            # Invoke the abort resolver
            payload = {
                "info": {"fieldName": "abortTestRuns"},
                "arguments": {"testRunIds": test_run_ids},
            }

            response = self.lambda_client.invoke(
                FunctionName=abort_function_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            result = json.loads(response["Payload"].read())

            if "errorMessage" in result:
                raise IDPProcessingError(f"Abort failed: {result['errorMessage']}")

            logger.info(
                f"Aborted {result.get('abortedCount', 0)} test runs, "
                f"{result.get('failedCount', 0)} failed"
            )
            return result

        except Exception as e:
            raise IDPProcessingError(f"Failed to abort test runs: {e}") from e
