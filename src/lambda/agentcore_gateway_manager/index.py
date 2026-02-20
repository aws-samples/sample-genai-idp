# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
import cfnresponse
import time
import logging
import os
from typing import Any, Dict
from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

def handler(event, context):
    """CloudFormation custom resource handler for AgentCore Gateway"""
    logger.info(f"Received event: {json.dumps(event)}")

    props = event.get('ResourceProperties', {})
    gateway_name = f"{props.get('StackName', 'UNKNOWN')}-analytics-gateway"

    try:
        request_type = event['RequestType']

        if request_type == 'Delete':
            delete_gateway(props, gateway_name)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=gateway_name)
            return

        # Create or Update
        gateway_config = create_or_update_gateway(props, gateway_name)

        cfnresponse.send(event, context, cfnresponse.SUCCESS, {
            'GatewayUrl': gateway_config.get('gateway_url'),
            'GatewayId': gateway_config.get('gateway_id'),
            'GatewayArn': gateway_config.get('gateway_arn')
        }, physicalResourceId=gateway_name)

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        # Check if this is a bedrock-agentcore access issue
        if 'bedrock-agentcore' in str(e).lower() and ('access' in str(e).lower() or 'unauthorized' in str(e).lower()):
            logger.warning("bedrock-agentcore service appears unavailable - continuing without MCP gateway")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'GatewayUrl': 'N/A - Service not available',
                'GatewayId': 'N/A',
                'GatewayArn': 'N/A'
            }, physicalResourceId=gateway_name)
        else:
            cfnresponse.send(event, context, cfnresponse.FAILED, {},
                             physicalResourceId=gateway_name,
                             reason=str(e))


def create_or_update_gateway(props, gateway_name):
    """Create or update AgentCore Gateway using existing Cognito resources"""
    region = props['Region']
    
    # Initialize gateway client
    client = GatewayClient(region_name=region)
    
    # Check if gateway already exists
    try:
        control_client = boto3.client("bedrock-agentcore-control", region_name=region)
        resp = control_client.list_gateways(maxResults=10)
        existing_gateways = [g for g in resp.get("items", []) if g.get("name") == gateway_name]
        
        if existing_gateways:
            existing_gateway = existing_gateways[0]
            gateway_id = existing_gateway.get('gatewayId')
            
            if gateway_id:
                try:
                    gateway_details = control_client.get_gateway(gatewayIdentifier=gateway_id)
                    if gateway_details and gateway_details.get('gatewayUrl'):
                        return {
                            'gateway_url': gateway_details.get('gatewayUrl'),
                            'gateway_id': gateway_details.get('gatewayId'),
                            'gateway_arn': gateway_details.get('gatewayArn')
                        }
                except Exception as e:
                    logger.warning(f"Error getting gateway details: {e}")

    except Exception as e:
        logger.warning(f"Error checking for existing gateway: {e}")
    
    # Gateway doesn't exist, create it
    logger.info(f"Gateway {gateway_name} does not exist, creating new one")
    return create_gateway(props, gateway_name, client)


def create_gateway(props, gateway_name, client):
    """Create new AgentCore Gateway"""
    region = props['Region']
    lambda_arn = props['LambdaArn']
    user_pool_id = props['UserPoolId']
    client_id = props['ClientId']
    execution_role_arn = props['ExecutionRoleArn']

    # Create JWT authorizer config using existing Cognito resources
    authorizer_config = {
        "customJWTAuthorizer": {
            "discoveryUrl": f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration",
            "allowedClients": [client_id]
        }
    }

    # Create gateway
    gateway = client.create_mcp_gateway(
        name=gateway_name,
        role_arn=execution_role_arn,
        authorizer_config=authorizer_config,
        enable_semantic_search=True,
    )

    logger.info(f"Gateway created: {gateway.get('gatewayUrl')}")

    # Fix IAM permissions and wait for propagation
    logger.info("Fixing IAM permissions...")
    client.fix_iam_permissions(gateway)
    logger.info("Waiting for IAM propagation...")
    time.sleep(30)

    # Add IDP tools Lambda target with all tools
    logger.info("Adding IDP tools Lambda target...")
    client.create_mcp_gateway_target(
        gateway=gateway,
        name="IDPTools",
        target_type="lambda",
        target_payload={
            "lambdaArn": lambda_arn,
            "toolSchema": {
                "inlinePayload": [
                    {
                        "name": "search",
                        "description": "Search and query processed documents using natural language. Returns analytics, metrics, and document information from the IDP system.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Natural language query about processed documents, metrics, or system status"
                                }
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "name": "process",
                        "description": "Process documents through the IDP pipeline. Accepts S3 locations or base64-encoded content. Intelligently handles missing information by requesting specific details.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "S3 URI for batch processing (e.g., 's3://bucket/documents/'). Optional if content is provided."
                                },
                                "content": {
                                    "type": "string",
                                    "description": "Base64-encoded document content for single document processing. Optional if location is provided."
                                },
                                "name": {
                                    "type": "string",
                                    "description": "Document filename with extension (e.g., 'invoice.pdf', 'contract.docx'). Required if content is provided; optional for S3 locations."
                                },
                                "prefix": {
                                    "type": "string",
                                    "description": "Optional batch ID prefix (default: 'mcp-batch')"
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "name": "reprocess",
                        "description": "Reprocess documents from a specific pipeline step. Supports classification or extraction reprocessing. Returns batch ID for status tracking.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "step": {
                                    "type": "string",
                                    "description": "Pipeline step to reprocess from (classification or extraction)"
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
                            },
                            "required": ["step"]
                        }
                    },
                    {
                        "name": "status",
                        "description": "Get processing status for a batch of documents. Returns progress, timing, and error information.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
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
                            },
                            "required": ["batch_id"]
                        }
                    }
                ]
            },
        },
    )

    logger.info("Gateway setup complete")

    return {
        'gateway_url': gateway.get('gatewayUrl'),
        'gateway_id': gateway.get('gatewayId'),
        'gateway_arn': gateway.get('gatewayArn')
    }


def delete_gateway(props, gateway_name):
    """Delete AgentCore Gateway using toolkit"""
    try:
        region = props['Region']
        client = boto3.client(
            "bedrock-agentcore-control",
            region_name=region
        )
        name: str = gateway_name
        gateway_id = None
        kwargs: Dict[str, Any] = {"maxResults": 10}
        resp = client.list_gateways(**kwargs)
        items = [g for g in resp.get("items", []) if g.get("name") == name]

        if len(items) > 0:
            gateway_id = items[0].get("gatewayId")

        if gateway_id:
            logger.info(f"Attempting to delete gateway by ID: {gateway_id}")
            # Step 1: List and delete all targets
            logger.info("Finding targets for gateway: %s", gateway_id)
            try:
                response = client.list_gateway_targets(gatewayIdentifier=gateway_id)
                # API returns targets in 'items' field
                targets = response.get("items", [])
                logger.info("Found %s targets to delete", len(targets))
                for target in targets:
                    target_id = target["targetId"]
                    logger.info("Deleting target: %s", target_id)
                    try:
                        client.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
                        logger.info("Target deletion initiated: %s", target_id)
                        # Wait for deletion to complete
                        time.sleep(5)
                    except Exception as e:
                        logger.warning("Error deleting target %s: %s", target_id, str(e))

                # Verify all targets are deleted
                logger.info("Verifying targets deletion...")
                time.sleep(5)  # Additional wait
                verify_response = client.list_gateway_targets(gatewayIdentifier=gateway_id)
                remaining_targets = verify_response.get("items", [])
                if remaining_targets:
                    logger.warning("%s targets still remain", len(remaining_targets))
                else:
                    logger.info("All targets deleted")
            except Exception as e:
                logger.warning("Error managing targets: %s", str(e))

            client.delete_gateway(gatewayIdentifier=gateway_id)
            logger.info("Gateway deleted successfully using ID")

        else:
            logger.info("Gateway not found")

    except Exception as e:
        logger.error(f"Gateway deletion failed: {e}")

