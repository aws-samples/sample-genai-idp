# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the Bedrock session factory (cross-account AssumeRole)."""

from unittest.mock import patch

import boto3
import pytest
from botocore.credentials import DeferredRefreshableCredentials

from idp_common.bedrock import session as bedrock_session


@pytest.mark.unit
class TestGetBedrockSession:
    """Tests for ``get_bedrock_session``."""

    def setup_method(self):
        bedrock_session.reset_cached_session()

    def teardown_method(self):
        bedrock_session.reset_cached_session()

    def test_returns_default_session_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_ASSUME_ROLE_ARN", raising=False)

        sess = bedrock_session.get_bedrock_session(region="us-west-2")

        assert isinstance(sess, boto3.Session)
        # Default session does NOT use refreshable AssumeRole credentials.
        creds = sess.get_credentials()
        if creds is not None:
            assert not isinstance(creds, DeferredRefreshableCredentials)

    def test_returns_default_session_when_env_blank(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_ASSUME_ROLE_ARN", "   ")

        sess = bedrock_session.get_bedrock_session()

        assert isinstance(sess, boto3.Session)

    def test_returns_assume_role_session_when_env_set(self, monkeypatch):
        monkeypatch.setenv(
            "BEDROCK_ASSUME_ROLE_ARN", "arn:aws:iam::111122223333:role/HubBedrockRole"
        )
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "GENAIIDP-test-fn")

        with patch("idp_common.bedrock.session.boto3.client") as mock_boto_client:
            sess = bedrock_session.get_bedrock_session(region="us-east-1")

            # STS client constructed once for the refresher.
            mock_boto_client.assert_called_once_with("sts", region_name="us-east-1")

        assert isinstance(sess, boto3.Session)
        # The botocore session embedded in the boto3 session should hold
        # DeferredRefreshableCredentials.
        botocore_sess = sess._session
        assert isinstance(botocore_sess._credentials, DeferredRefreshableCredentials)

    def test_assume_role_includes_external_id_when_set(self, monkeypatch):
        monkeypatch.setenv(
            "BEDROCK_ASSUME_ROLE_ARN", "arn:aws:iam::111122223333:role/HubBedrockRole"
        )
        monkeypatch.setenv("BEDROCK_ASSUME_ROLE_EXTERNAL_ID", "my-external-id")

        captured = {}

        def fake_refresher(sts, params):
            captured.update(params)
            return lambda: {
                "access_key": "AKIA",
                "secret_key": "SECRET",  # nosec B105 - dummy test credential
                "token": "TOKEN",  # nosec B105 - dummy test credential
                "expiry_time": "2099-01-01T00:00:00Z",
            }

        with patch(
            "idp_common.bedrock.session.create_assume_role_refresher",
            side_effect=fake_refresher,
        ):
            bedrock_session.get_bedrock_session(region="us-east-1")

        assert captured.get("ExternalId") == "my-external-id"
        assert (
            captured.get("RoleArn") == "arn:aws:iam::111122223333:role/HubBedrockRole"
        )

    def test_session_name_defaults_to_lambda_function_name(self, monkeypatch):
        monkeypatch.setenv(
            "BEDROCK_ASSUME_ROLE_ARN", "arn:aws:iam::111122223333:role/HubBedrockRole"
        )
        monkeypatch.delenv("BEDROCK_ASSUME_ROLE_SESSION_NAME", raising=False)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "GENAIIDP-extraction")

        captured = {}

        def fake_refresher(sts, params):
            captured.update(params)
            return lambda: {
                "access_key": "AKIA",
                "secret_key": "SECRET",  # nosec B105 - dummy test credential
                "token": "TOKEN",  # nosec B105 - dummy test credential
                "expiry_time": "2099-01-01T00:00:00Z",
            }

        with patch(
            "idp_common.bedrock.session.create_assume_role_refresher",
            side_effect=fake_refresher,
        ):
            bedrock_session.get_bedrock_session()

        assert captured.get("RoleSessionName") == "GENAIIDP-extraction"

    def test_session_name_override(self, monkeypatch):
        monkeypatch.setenv(
            "BEDROCK_ASSUME_ROLE_ARN", "arn:aws:iam::111122223333:role/HubBedrockRole"
        )
        monkeypatch.setenv("BEDROCK_ASSUME_ROLE_SESSION_NAME", "my-custom-session")

        captured = {}

        def fake_refresher(sts, params):
            captured.update(params)
            return lambda: {
                "access_key": "AKIA",
                "secret_key": "SECRET",  # nosec B105 - dummy test credential
                "token": "TOKEN",  # nosec B105 - dummy test credential
                "expiry_time": "2099-01-01T00:00:00Z",
            }

        with patch(
            "idp_common.bedrock.session.create_assume_role_refresher",
            side_effect=fake_refresher,
        ):
            bedrock_session.get_bedrock_session()

        assert captured.get("RoleSessionName") == "my-custom-session"

    def test_session_name_truncated_to_64_chars(self, monkeypatch):
        long_name = "GENAIIDP-" + "x" * 100
        monkeypatch.setenv(
            "BEDROCK_ASSUME_ROLE_ARN", "arn:aws:iam::111122223333:role/HubBedrockRole"
        )
        monkeypatch.setenv("BEDROCK_ASSUME_ROLE_SESSION_NAME", long_name)

        captured = {}

        def fake_refresher(sts, params):
            captured.update(params)
            return lambda: {
                "access_key": "AKIA",
                "secret_key": "SECRET",  # nosec B105 - dummy test credential
                "token": "TOKEN",  # nosec B105 - dummy test credential
                "expiry_time": "2099-01-01T00:00:00Z",
            }

        with patch(
            "idp_common.bedrock.session.create_assume_role_refresher",
            side_effect=fake_refresher,
        ):
            bedrock_session.get_bedrock_session()

        assert len(captured["RoleSessionName"]) == 64

    def test_session_cached_per_region(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_ASSUME_ROLE_ARN", raising=False)

        sess1 = bedrock_session.get_bedrock_session(region="us-east-1")
        sess2 = bedrock_session.get_bedrock_session(region="us-east-1")
        assert sess1 is sess2

        # Different region invalidates cache and yields a new session.
        sess3 = bedrock_session.get_bedrock_session(region="us-west-2")
        assert sess3 is not sess1
