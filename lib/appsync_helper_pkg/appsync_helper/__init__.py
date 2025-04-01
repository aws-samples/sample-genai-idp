import boto3
import json
import os
import logging
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger()

class AppSyncError(Exception):
    """Custom exception for AppSync errors"""
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []

class AppSyncClient:
    def __init__(self):
        self.session = boto3.Session()
        self.credentials = self.session.get_credentials()
        self.api_url = os.environ['APPSYNC_API_URL']
        self.region = os.environ['AWS_REGION']

    def _sign_request(self, request: AWSRequest) -> Dict[str, str]:
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

# GraphQL Mutations
CREATE_DOCUMENT = """
mutation CreateDocument($input: CreateDocumentInput!) {
    createDocument(input: $input) {
        ObjectKey
    }
}
"""

UPDATE_DOCUMENT = """
mutation UpdateDocument($input: UpdateDocumentInput!) {
    updateDocument(input: $input) {
        ObjectKey
        ObjectStatus
        InitialEventTime
        QueuedTime
        WorkflowStartTime
        CompletionTime
        WorkflowExecutionArn
        WorkflowStatus
        PageCount
        Sections {
            Id
            PageIds
            Class
            OutputJSONUri
        }
        Pages {
            Id
            Class
            ImageUri
            TextUri
        }
        Metering
        EvaluationReportUri
        ExpiresAfter
    }
}
"""