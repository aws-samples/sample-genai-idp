# IDP AppSync Helper

A utility package for the IDP Accelerator that provides a simplified interface for interacting with AWS AppSync GraphQL APIs.

## Features

- Authentication with AWS SigV4
- Simplified mutation execution
- Error handling for GraphQL operations
- Predefined common mutations for document processing

## Installation

```bash
pip install idp-appsync-helper
```

## Usage

```python
import os
from appsync_helper import AppSyncClient, CREATE_DOCUMENT

# Set required environment variables
os.environ['APPSYNC_API_URL'] = 'https://your-appsync-api-endpoint.amazonaws.com/graphql'
os.environ['AWS_REGION'] = 'us-east-1'

# Create client
client = AppSyncClient()

# Execute a mutation
result = client.execute_mutation(
    CREATE_DOCUMENT, 
    {
        "input": {
            "ObjectKey": "documents/example.pdf"
        }
    }
)
```