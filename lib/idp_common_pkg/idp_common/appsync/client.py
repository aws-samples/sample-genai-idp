"""
AppSync client for executing GraphQL queries and mutations.
"""

import boto3
import json
import os
import logging
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class AppSyncError(Exception):
    """Custom exception for AppSync errors"""
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []

class AppSyncClient:
    """
    Client for executing GraphQL operations against AWS AppSync.
    
    This client handles authentication, request signing, and error handling
    for AWS AppSync GraphQL API calls.
    """
    def __init__(self, api_url: Optional[str] = None, region: Optional[str] = None):
        """
        Initialize the AppSync client.
        
        Args:
            api_url: Optional AppSync API URL. If not provided, will be read from APPSYNC_API_URL env var.
            region: Optional AWS region. If not provided, will be read from AWS_REGION env var.
        """
        self.session = boto3.Session()
        self.credentials = self.session.get_credentials()
        self.api_url = api_url or os.environ.get('APPSYNC_API_URL')
        self.region = region or os.environ.get('AWS_REGION')
        
        if not self.api_url:
            raise ValueError("AppSync API URL must be provided or set in APPSYNC_API_URL environment variable")
        
        if not self.region:
            raise ValueError("AWS region must be provided or set in AWS_REGION environment variable")

    def _sign_request(self, request: AWSRequest) -> Dict[str, str]:
        """
        Sign a request with SigV4 authentication.
        
        Args:
            request: The AWS request to sign
            
        Returns:
            Dictionary of signed headers
        """
        auth = SigV4Auth(self.credentials, 'appsync', self.region)
        auth.add_auth(request)
        return dict(request.headers)

    def execute_mutation(self, mutation: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a GraphQL mutation with error handling
        
        Args:
            mutation: The GraphQL mutation string
            variables: Variables for the mutation
            
        Returns:
            Dict containing the mutation result data
            
        Raises:
            AppSyncError: If the GraphQL operation fails
            requests.RequestException: If the HTTP request fails
        """
        data = {
            'query': mutation,
            'variables': variables
        }
        
        request = AWSRequest(
            method='POST',
            url=self.api_url,
            data=json.dumps(data).encode(),
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }
        )
        
        signed_headers = self._sign_request(request)
        
        try:
            response = requests.post(
                self.api_url,
                json=data,
                headers=signed_headers,
                timeout=30
            )
            response.raise_for_status()  # Raises HTTPError for bad status codes
            
            result = response.json()
            logger.debug(f"AppSync raw response: {result}")
            
            # Check for GraphQL errors
            if 'errors' in result:
                error_messages = [error.get('message', 'Unknown error') for error in result['errors']]
                error_msg = '; '.join(error_messages)
                logger.error(f"GraphQL errors: {error_msg}")
                logger.error(f"Full error response: {json.dumps(result['errors'])}")
                raise AppSyncError(f"GraphQL operation failed: {error_msg}", result['errors'])
            
            # Verify we got data back
            if 'data' not in result:
                raise AppSyncError("No data returned from AppSync")
                
            # Check if the specific mutation returned null
            operation_name = list(result['data'].keys())[0]
            if result['data'][operation_name] is None:
                error_msg = f"Mutation {operation_name} returned null"
                logger.error(error_msg)
                raise AppSyncError(error_msg)
                
            return result['data']
            
        except requests.RequestException as e:
            logger.error(f"HTTP request to AppSync failed: {str(e)}")
            raise