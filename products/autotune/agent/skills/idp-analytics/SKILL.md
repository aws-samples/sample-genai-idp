---
name: idp-analytics
description: Query IDP document processing analytics via natural language using the AgentCore MCP server. Use when you need aggregate statistics, processing trends, confidence score analysis, or error pattern reports
---

# IDP Analytics MCP

## Purpose

Query processed document analytics using natural language via the IDP's AgentCore MCP server.

## Design Decision: Python vs Direct MCP

The IDP Analytics MCP server is accessed via Python code rather than configured as a direct MCP server in the agent JSON. This is because:

1. **Remote HTTP endpoint** - IDP's MCP server runs on AgentCore Gateway (HTTPS), not as a local stdio process
2. **OAuth authentication** - Requires Cognito token that expires and needs refresh logic
3. **Kiro MCP limitation** - Kiro custom agents easily support local stdio MCP servers (`command` + `args`), but remote MCP with dynamic auth headers is more complex

The Python approach in this skill handles token acquisition inline, avoiding the need for a wrapper script or static tokens in config.

## Prerequisites

- IDP stack deployed with `EnableMCP: 'true'`
- Stack outputs: `MCPServerEndpoint`, `MCPClientId`, `MCPClientSecret`, `MCPTokenURL`

## Available Tool

### search_genaiidp

Natural language queries about processed document data.

**Example queries:**
- "How many documents were processed last month?"
- "What are the most common document types?"
- "Show me the processing success rate by document type"
- "Which documents had the lowest confidence scores?"
- "Generate a report of processing errors from the last week"

## Setup

Get credentials from CloudFormation stack outputs:

```bash
STACK_NAME="your-idp-stack"
aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?starts_with(OutputKey, `MCP`)].{Key:OutputKey,Value:OutputValue}'
```

## Usage

```python
import requests

# From stack outputs
GATEWAY_URL = "<MCPServerEndpoint>"
CLIENT_ID = "<MCPClientId>"
CLIENT_SECRET = "<MCPClientSecret>"
TOKEN_URL = "<MCPTokenURL>"

# Get access token
token_resp = requests.post(
    TOKEN_URL,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data={
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
)
access_token = token_resp.json()["access_token"]

# Query analytics
response = requests.post(
    GATEWAY_URL,
    headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    },
    json={
        "method": "tools/call",
        "params": {
            "name": "search_genaiidp",
            "arguments": {"query": "Which documents had lowest confidence scores?"}
        }
    }
)
print(response.json())
```

## Use Cases for Config Optimization

- Identify document types with lowest accuracy
- Find patterns in processing failures
- Compare accuracy trends across evaluation runs
- Discover which fields have highest error rates
