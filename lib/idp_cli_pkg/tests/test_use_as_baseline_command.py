# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the `use-as-baseline` CLI command.
"""

from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from idp_cli.cli import cli
from idp_sdk.models import UseAsBaselineResult


@pytest.fixture
def runner():
    return CliRunner()


def test_use_as_baseline_success(runner):
    with patch("idp_sdk.IDPClient") as mock_client_cls:
        mock_client = Mock()
        mock_client.evaluation.use_as_baseline.return_value = UseAsBaselineResult(
            document_id="loan-123/package.pdf",
            files_copied=15,
            evaluation_status="BASELINE_AVAILABLE",
            timestamp="2024-01-01T00:00:00",
        )
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "use-as-baseline",
                "--stack-name",
                "my-stack",
                "--document-id",
                "loan-123/package.pdf",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Baseline created" in result.output
        assert "15" in result.output
        assert "BASELINE_AVAILABLE" in result.output
        mock_client.evaluation.use_as_baseline.assert_called_once_with(
            document_id="loan-123/package.pdf"
        )


def test_use_as_baseline_requires_document_id(runner):
    result = runner.invoke(cli, ["use-as-baseline", "--stack-name", "my-stack"])
    assert result.exit_code != 0
    assert "document-id" in result.output.lower()


def test_use_as_baseline_error_exit_code(runner):
    with patch("idp_sdk.IDPClient") as mock_client_cls:
        mock_client = Mock()
        mock_client.evaluation.use_as_baseline.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            cli,
            [
                "use-as-baseline",
                "--stack-name",
                "my-stack",
                "--document-id",
                "doc.pdf",
            ],
        )

        assert result.exit_code == 1
        assert "Error" in result.output
