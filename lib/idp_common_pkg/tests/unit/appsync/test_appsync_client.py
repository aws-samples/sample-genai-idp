# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the AppSyncClient class.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests
from botocore.awsrequest import AWSRequest
from idp_common.appsync.client import AppSyncClient, AppSyncError


@pytest.mark.unit
class TestAppSyncClient:
    """Tests for the AppSyncClient class."""

    def test_init_with_params(self):
        """Test initialization with explicit parameters."""
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )
        assert client.api_url == "https://test-api.com/graphql"
        assert client.region == "us-west-2"

    def test_init_with_env_vars(self, monkeypatch):
        """Test initialization with environment variables."""
        monkeypatch.setenv("APPSYNC_API_URL", "https://env-api.com/graphql")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        client = AppSyncClient()
        assert client.api_url == "https://env-api.com/graphql"
        assert client.region == "us-east-1"

    def test_init_missing_api_url(self, monkeypatch):
        """Test initialization fails when API URL is missing."""
        monkeypatch.delenv("APPSYNC_API_URL", raising=False)
        with pytest.raises(ValueError, match="AppSync API URL must be provided"):
            AppSyncClient(region="us-west-2")

    @patch("idp_common.appsync.client.boto3")
    def test_init_missing_region(self, mock_boto3, monkeypatch):
        """Test initialization fails when region is missing."""
        monkeypatch.delenv("AWS_REGION", raising=False)
        # Also mock boto3.Session().region_name to return None
        mock_session = MagicMock()
        mock_session.region_name = None
        mock_session.get_credentials.return_value = MagicMock()
        mock_boto3.Session.return_value = mock_session
        with pytest.raises(ValueError, match="AWS region must be provided"):
            AppSyncClient(api_url="https://test-api.com/graphql")

    @patch("idp_common.appsync.client.SigV4Auth")
    def test_sign_request(self, mock_sigv4):
        """Test request signing with SigV4."""
        # Setup
        mock_auth = MagicMock()
        mock_sigv4.return_value = mock_auth
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Create a request to sign
        request = AWSRequest(
            method="POST",
            url="https://test-api.com/graphql",
            data=b'{"query": "test"}',
            headers={"Content-Type": "application/json"},
        )

        # Mock the headers that would be added by SigV4Auth
        request.headers = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Test
        headers = client._sign_request(request)

        # Verify
        mock_auth.add_auth.assert_called_once_with(request)
        assert headers == request.headers
        assert "Content-Type" in headers
        assert "X-Amz-Date" in headers
        assert "Authorization" in headers

    @patch("idp_common.appsync.client.AppSyncClient._sign_request")
    def test_execute_mutation_success(self, mock_sign_request):
        """Test successful mutation execution."""
        # Setup
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Mock the signed headers
        mock_sign_request.return_value = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"createDocument": {"ObjectKey": "test-document.pdf"}}
        }

        # Mock the session's post method
        client.http_session.post = MagicMock(return_value=mock_response)

        # Test
        mutation = "mutation CreateDocument($input: CreateDocumentInput!) { createDocument(input: $input) { ObjectKey } }"
        variables = {"input": {"ObjectKey": "test-document.pdf"}}
        result = client.execute_mutation(mutation, variables)

        # Verify
        mock_sign_request.assert_called_once()
        client.http_session.post.assert_called_once_with(
            "https://test-api.com/graphql",
            json={"query": mutation, "variables": variables},
            headers=mock_sign_request.return_value,
            timeout=10,
        )
        assert result == {"createDocument": {"ObjectKey": "test-document.pdf"}}

    @patch("idp_common.appsync.client.AppSyncClient._sign_request")
    def test_execute_mutation_graphql_error(self, mock_sign_request):
        """Test handling of GraphQL errors in mutation response."""
        # Setup
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Mock the signed headers
        mock_sign_request.return_value = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Mock the response with GraphQL errors
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "errors": [
                {"message": "Invalid input format"},
                {"message": "Required field missing"},
            ],
            "data": None,
        }
        client.http_session.post = MagicMock(return_value=mock_response)

        # Test
        mutation = "mutation CreateDocument($input: CreateDocumentInput!) { createDocument(input: $input) { ObjectKey } }"
        variables = {"input": {"ObjectKey": "test-document.pdf"}}

        with pytest.raises(AppSyncError) as excinfo:
            client.execute_mutation(mutation, variables)

        # Verify
        assert "GraphQL operation failed" in str(excinfo.value)
        assert "Invalid input format; Required field missing" in str(excinfo.value)
        assert len(excinfo.value.errors) == 2
        assert excinfo.value.errors[0]["message"] == "Invalid input format"

    @patch("idp_common.appsync.client.AppSyncClient._sign_request")
    def test_execute_mutation_http_error(self, mock_sign_request):
        """Test handling of HTTP errors in mutation request."""
        # Setup
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Mock the signed headers
        mock_sign_request.return_value = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Mock the HTTP error
        client.http_session.post = MagicMock(
            side_effect=requests.RequestException("Connection error")
        )

        # Test
        mutation = "mutation CreateDocument($input: CreateDocumentInput!) { createDocument(input: $input) { ObjectKey } }"
        variables = {"input": {"ObjectKey": "test-document.pdf"}}

        with pytest.raises(requests.RequestException) as excinfo:
            client.execute_mutation(mutation, variables)

        # Verify
        assert "Connection error" in str(excinfo.value)

    @patch("idp_common.appsync.client.AppSyncClient._sign_request")
    def test_execute_mutation_no_data(self, mock_sign_request):
        """Test handling of response with no data."""
        # Setup
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Mock the signed headers
        mock_sign_request.return_value = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Mock the response with no data
        mock_response = MagicMock()
        mock_response.json.return_value = {}  # Empty response
        client.http_session.post = MagicMock(return_value=mock_response)

        # Test
        mutation = "mutation CreateDocument($input: CreateDocumentInput!) { createDocument(input: $input) { ObjectKey } }"
        variables = {"input": {"ObjectKey": "test-document.pdf"}}

        with pytest.raises(AppSyncError) as excinfo:
            client.execute_mutation(mutation, variables)

        # Verify
        assert "No data returned from AppSync" in str(excinfo.value)

    @patch("idp_common.appsync.client.AppSyncClient._sign_request")
    def test_execute_mutation_null_result(self, mock_sign_request):
        """Test handling of null mutation result."""
        # Setup
        client = AppSyncClient(
            api_url="https://test-api.com/graphql", region="us-west-2"
        )

        # Mock the signed headers
        mock_sign_request.return_value = {
            "Content-Type": "application/json",
            "X-Amz-Date": "20250508T143420Z",
            "Authorization": "AWS4-HMAC-SHA256 Credential=...",
        }

        # Mock the response with null mutation result
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"createDocument": None}}
        client.http_session.post = MagicMock(return_value=mock_response)

        # Test
        mutation = "mutation CreateDocument($input: CreateDocumentInput!) { createDocument(input: $input) { ObjectKey } }"
        variables = {"input": {"ObjectKey": "test-document.pdf"}}

        with pytest.raises(AppSyncError) as excinfo:
            client.execute_mutation(mutation, variables)

        # Verify
        assert "Mutation createDocument returned null" in str(excinfo.value)
