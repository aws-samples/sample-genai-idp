Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# MCP Integration

The GenAI IDP solution provides MCP (Model Context Protocol) integration that enables external applications like Amazon Quick Suite to access IDP functionality through AWS Bedrock AgentCore Gateway. This allows third-party applications to query processed document data and perform analytics operations through natural language interfaces.

## Overview

The MCP integration exposes IDP capabilities to external applications by:

- **Analytics Gateway**: Provides natural language access to processed document analytics data
- **Secure Authentication**: Uses AWS Cognito OAuth 2.0 for secure external application access
- **MCP Protocol**: Implements Model Context Protocol for standardized tool integration
- **Real-time Queries**: Enables external applications to query document processing results in real-time
- **Extensible Architecture**: Designed to support additional IDP functionality in future releases


https://github.com/user-attachments/assets/529ce6ad-1062-4af5-97c1-86c3a47ac12c


## External Application Integration

External applications can integrate with the IDP system through the AgentCore Gateway by:

1. **Authentication**: Obtaining OAuth tokens from the IDP's Cognito User Pool
2. **Gateway Connection**: Connecting to the AgentCore Gateway endpoint
3. **Tool Discovery**: Discovering available analytics tools via MCP protocol
4. **Query Execution**: Executing natural language queries against processed document data

### Integration Flow

```
External App → Cognito Auth → AgentCore Gateway → Analytics Lambda → IDP Data
```

## Enabling and Disabling the Feature

### During Stack Deployment

The MCP integration is controlled by the `EnableMCP` parameter:

**Enable MCP Integration:**
```yaml
EnableMCP: 'true'  # Default value
```

**Disable MCP Integration:**
```yaml
EnableMCP: 'false'
```

When enabled, the stack automatically creates:
- AgentCore Gateway Manager Lambda function
- AgentCore Analytics Lambda function
- External App Client in Cognito User Pool
- Required IAM roles and policies
- AgentCore Gateway resource
- MCP Content Bucket for document uploads

When disabled, these resources are not created, reducing deployment complexity and costs.

## Current Capabilities

The AgentCore Gateway provides four integrated tools for document processing and analytics:

### search

Natural language queries for document analytics and system information.

**Input Schema:**
```json
{
  "query": {
    "type": "string",
    "description": "Natural language question about processed documents or analytics data"
  }
}
```

**Output Schema:**
```json
{
  "success": "boolean",
  "query": "string",
  "result": "string"
}
```

**Example Request:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "query": "How many documents were processed last month?"
    }
  }
}
```

**Example Response:**
```json
{
  "success": true,
  "query": "How many documents were processed last month?",
  "result": "1,250 documents were processed in the last month with a 98.5% success rate."
}
```

### process

Process documents from S3 or base64 content. To process documents via S3:

1. Upload documents to the `MCPContentBucket` (available in CloudFormation stack outputs):
   ```bash
   aws s3 cp documents/ s3://<MCPContentBucket>/documents/ --recursive
   ```
2. Call the `process` tool with the S3 URI pointing to your uploaded documents
3. The tool queues documents for processing through the IDP pipeline

**Alternatively, process documents via base64 content** by providing the encoded content directly to the tool.

**Input Schema:**
```json
{
  "location": {
    "type": "string",
    "description": "S3 URI for batch processing (e.g., 's3://mcp-content-bucket/documents/'). Optional if content is provided."
  },
  "content": {
    "type": "string",
    "description": "Base64-encoded document content for single document processing. Optional if location is provided."
  },
  "name": {
    "type": "string",
    "description": "Document filename with extension (e.g., 'invoice.pdf'). Required if content is provided."
  },
  "prefix": {
    "type": "string",
    "description": "Optional batch ID prefix (default: 'mcp-batch')"
  }
}
```

**Output Schema:**
```json
{
  "success": "boolean",
  "batch_id": "string",
  "documents_queued": "integer",
  "message": "string"
}
```

**Example Request (S3 Location):**
```json
{
  "method": "tools/call",
  "params": {
    "name": "process",
    "arguments": {
      "location": "s3://mcp-content-bucket/documents/",
      "prefix": "batch-001"
    }
  }
}
```

**Example Request (Base64 Content):**
```json
{
  "method": "tools/call",
  "params": {
    "name": "process",
    "arguments": {
      "content": "JVBERi0xLjQKJeLjz9MNCjEgMCBvYmo...",
      "name": "invoice.pdf",
      "prefix": "mcp-batch"
    }
  }
}
```

**Example Response:**
```json
{
  "success": true,
  "batch_id": "mcp-batch-20250124-143000",
  "documents_queued": 5,
  "message": "Successfully queued 5 documents for processing"
}
```

### reprocess

Reprocess documents from classification or extraction steps.

**Input Schema:**
```json
{
  "step": {
    "type": "string",
    "enum": ["classification", "extraction"],
    "description": "Pipeline step to reprocess from"
  },
  "document_ids": {
    "type": "string",
    "description": "Comma-separated list of document IDs to reprocess (alternative to batch_id)"
  },
  "batch_id": {
    "type": "string",
    "description": "Batch ID to get document IDs from (alternative to document_ids)"
  },
  "region": {
    "type": "string",
    "description": "AWS region (optional)"
  }
}
```

**Output Schema:**
```json
{
  "success": "boolean",
  "batch_id": "string",
  "documents_queued": "integer",
  "step": "string",
  "message": "string"
}
```

**Example Request:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "reprocess",
    "arguments": {
      "step": "extraction",
      "batch_id": "mcp-batch-20250124-143000"
    }
  }
}
```

**Example Response:**
```json
{
  "success": true,
  "batch_id": "mcp-batch-20250124-143000",
  "documents_queued": 5,
  "step": "extraction",
  "message": "Successfully queued 5 documents for extraction reprocessing"
}
```

### status

Query batch and document processing status.

**Input Schema:**
```json
{
  "batch_id": {
    "type": "string",
    "description": "Batch identifier (e.g., 'mcp-batch-20250124-143000')"
  },
  "options": {
    "type": "object",
    "description": "Optional status parameters",
    "properties": {
      "detailed": {
        "type": "boolean",
        "description": "Include per-document details (default: false)"
      },
      "include_errors": {
        "type": "boolean",
        "description": "Include error details (default: true)"
      }
    }
  },
  "region": {
    "type": "string",
    "description": "AWS region (optional)"
  }
}
```

**Output Schema:**
```json
{
  "success": "boolean",
  "batch_id": "string",
  "status": {
    "total": "integer",
    "completed": "integer",
    "in_progress": "integer",
    "failed": "integer",
    "queued": "integer"
  },
  "progress": {
    "percentage": "number"
  },
  "all_complete": "boolean"
}
```

**Example Request:**
```json
{
  "method": "tools/call",
  "params": {
    "name": "status",
    "arguments": {
      "batch_id": "mcp-batch-20250124-143000",
      "options": {
        "detailed": true
      }
    }
  }
}
```

**Example Response:**
```json
{
  "success": true,
  "batch_id": "mcp-batch-20250124-143000",
  "status": {
    "total": 5,
    "completed": 3,
    "in_progress": 1,
    "failed": 0,
    "queued": 1
  },
  "progress": {
    "percentage": 60.0
  },
  "all_complete": false
}
```

## Implementation Details

### Architecture Components

1. **AgentCore Gateway Manager Lambda**
   - Creates and manages the AgentCore Gateway
   - Handles CloudFormation custom resource lifecycle
   - Configures JWT authorization using Cognito

2. **AgentCore Analytics Lambda**
   - Implements MCP protocol following AgentCore schema
   - Processes natural language queries via search_genaiidp tool
   - Translates queries to appropriate backend operations
   - Returns structured responses in natural language

3. **AgentCore Gateway**
   - AWS Bedrock AgentCore Gateway resource
   - Routes requests between external applications and analytics Lambda
   - Handles authentication and authorization

### Authentication Flow

1. **External Application** requests access token from Cognito
2. **Cognito User Pool** validates credentials and returns JWT token
3. **External Application** calls AgentCore Gateway with Bearer token
4. **AgentCore Gateway** validates JWT token against Cognito
5. **Analytics Lambda** processes the request and returns results

### Data Access

The Analytics Lambda has read-only access to:
- **Analytics Database**: Glue catalog with processed document metadata
- **Reporting Bucket**: S3 bucket containing analytics data and query results
- **Configuration Tables**: DynamoDB tables with system configuration
- **Tracking Tables**: DynamoDB tables with processing status

## Security

### Authentication & Authorization

The MCP Server uses AWS Cognito OAuth 2.0 for secure authentication:
- External applications obtain JWT tokens from the Cognito User Pool
- AgentCore Gateway validates JWT tokens on every request
- Tokens include scopes (openid, email, profile) for fine-grained access control
- Token expiration and refresh mechanisms prevent unauthorized access

### IAM Role-Based Access Control

The AgentCore Analytics Lambda operates with least-privilege IAM permissions:
- Read-only access to DynamoDB tracking and configuration tables
- Read-only access to S3 analytics and reporting buckets
- No write permissions to input or output buckets
- Scoped permissions prevent access to resources outside the IDP stack
- Service role restricts Lambda execution to authorized operations only

### S3 Bucket Access

Document processing through the MCP Server follows secure S3 access patterns:
- Input documents from S3 are processed through the standard IDP pipeline
- Base64-encoded documents are uploaded to a temporary MCP bucket with restricted access
- Temporary files are automatically cleaned up after processing
- All S3 operations use IAM role credentials (no long-lived access keys)
- Bucket policies restrict access to the IDP stack's execution roles

### Data Encryption

Data security is maintained throughout the MCP integration:
- **In Transit**: All communication between external applications and AgentCore Gateway uses HTTPS/TLS
- **At Rest**: DynamoDB tables and S3 buckets use AWS-managed encryption keys
- **JWT Tokens**: Signed with Cognito's private keys and validated using public keys
- **Sensitive Data**: Client secrets are stored securely in AWS Secrets Manager and rotated regularly

## MCP Content Bucket

The stack creates a dedicated S3 bucket for MCP document uploads:

- **Bucket Name**: `MCPContentBucket` (available in CloudFormation stack outputs)
- **Purpose**: Upload documents for processing via the `process` tool
- **Access**: Accessible through the MCP Server tools with proper authentication
- **Usage**: Provide the S3 URI (e.g., `s3://mcp-content-bucket/documents/`) to the `process` tool
- **Cleanup**: Temporary files are automatically managed by the IDP pipeline

**Example Workflow:**
1. Upload documents to MCPContentBucket via S3 console or AWS CLI
2. Use the `process` tool with the S3 URI pointing to MCPContentBucket
3. Documents are processed through the standard IDP pipeline
4. Results are available in the output bucket

## Cognito User Pool Utilization

### User Pool Configuration

The IDP solution creates a Cognito User Pool with:
- **Domain**: Auto-generated unique domain (e.g., `stack-name-timestamp.auth.region.amazoncognito.com`)
- **Password Policy**: Configurable security requirements
- **User Management**: Admin-managed user creation
- **OAuth Flows**: Authorization code flow for external applications

### External App Client

When MCP is enabled, an additional Cognito User Pool Client is created:

**Client Configuration:**
- **Client Name**: "External-App-Client"
- **Client Secret**: Generated automatically
- **Auth Flows**: USER_PASSWORD_AUTH, ADMIN_USER_PASSWORD_AUTH, REFRESH_TOKEN_AUTH
- **OAuth Flows**: Authorization code flow
- **OAuth Scopes**: openid, email, profile
- **Callback URLs**: 
  - CloudFront distribution URL
  - Quick Suite OAuth callback
  - Cognito User Pool domain

### Token Management

External applications can obtain tokens using:

**Client Credentials Flow:**
```bash
curl -X POST <MCPTokenURL> \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=<MCPClientId>&client_secret=<MCPClientSecret>"
```

**User Authentication Flow:**
```bash
# Step 1: Get authorization code
<MCPAuthorizationURL>?
  response_type=code&
  client_id=<MCPClientId>&
  redirect_uri=CALLBACK_URL&
  scope=openid+email+profile

# Step 2: Exchange code for tokens
curl -X POST <MCPTokenURL> \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code&client_id=<MCPClientId>&client_secret=<MCPClientSecret>&code=AUTH_CODE&redirect_uri=CALLBACK_URL"
```

## Output Parameters

When MCP integration is enabled, the CloudFormation stack provides the following outputs required for external application integration:

### MCP Content Bucket

- **`MCPContentBucket`**: S3 bucket for uploading documents to process via MCP tools
  - Use this bucket to upload documents before calling the `process` tool
  - Provide the S3 URI from this bucket to the `process` tool's `location` parameter

### MCP Server Endpoint

- **`MCPServerEndpoint`**: The HTTPS endpoint for the MCP Server
  - The AgentCore Gateway URL for MCP protocol communication
  - Required for external applications to connect to the gateway via MCP protocol

### Authentication Outputs

- **`MCPClientId`**: Cognito User Pool Client ID for MCP authentication
  - Required for OAuth authentication flows
  - Used in token requests and API calls

- **`MCPClientSecret`**: Cognito User Pool Client Secret for MCP authentication
  - Required for client authentication in OAuth flows
  - Should be securely stored and rotated regularly

- **`MCPUserPool`**: Cognito User Pool ID for MCP authentication
  - Required for token validation and user management
  - Used by external applications for authentication setup

- **`MCPTokenURL`**: OAuth token endpoint URL
  - Format: `https://domain-name.auth.region.amazoncognito.com/oauth2/token`
  - Used for obtaining access tokens via OAuth flows

- **`MCPAuthorizationURL`**: OAuth authorization endpoint URL
  - Format: `https://domain-name.auth.region.amazoncognito.com/oauth2/authorize`
  - Used for initiating OAuth authorization code flows

## Usage Examples

### External Application Setup

```python
import requests
import json

# Configuration from CloudFormation outputs
GATEWAY_URL = "<MCPServerEndpoint>"  # From stack outputs
CLIENT_ID = "<MCPClientId>"  # From stack outputs
CLIENT_SECRET = "<MCPClientSecret>"  # From stack outputs
TOKEN_URL = "<MCPTokenURL>"  # From stack outputs
MCP_BUCKET = "<MCPContentBucket>"  # From stack outputs

# Get access token
token_response = requests.post(
    TOKEN_URL,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
)
access_token = token_response.json()["access_token"]

# Process documents from MCP bucket
process_request = {
    "method": "tools/call",
    "params": {
        "name": "process",
        "arguments": {
            "location": f"s3://{MCP_BUCKET}/documents/",
            "prefix": "batch-001"
        }
    }
}

response = requests.post(
    GATEWAY_URL,
    headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    },
    json=process_request
)

result = response.json()
print(f"Processing result: {result}")
```

### Amazon Quick Suite Integration

For Amazon Quick Suite integration, configure the MCP connection using the CloudFormation stack outputs detailed in the [Output Parameters](#output-parameters) section.

- **MCP Server**: Use `MCPServerEndpoint` output value
- **Client ID**: Use `MCPClientId` output value
- **Client Secret**: Use `MCPClientSecret` output value
- **Token URL**: Use `MCPTokenURL` output value
- **Authorization URL**: Use `MCPAuthorizationURL` output value
- **Content Bucket**: Use `MCPContentBucket` output value for document uploads
