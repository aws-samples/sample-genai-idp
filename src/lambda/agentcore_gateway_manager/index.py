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
            try:
                delete_gateway(props, gateway_name)
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=gateway_name)
            except Exception as e:
                logger.error(f"Delete failed: {e}", exc_info=True)
                cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physicalResourceId=gateway_name, reason=str(e))
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
                    },
                    {
                        "name": "get_results",
                        "description": "Retrieve processing results and extracted metadata for all documents in a batch. Use this tool when users ask for batch results, metadata, extracted fields, or processing outcomes. Returns document classification, extracted fields with values, field-level confidence scores, page counts, and processing status for each document. Includes batch-level summary with average confidence and document class distribution. Supports pagination for large batches.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "batch_id": {
                                    "type": "string",
                                    "description": "Batch identifier (e.g., 'mcp-batch-20250124-143022'). Required to identify which batch to retrieve metadata from."
                                },
                                "section_id": {
                                    "type": "integer",
                                    "description": "Section number within documents (default: 1). Use for multi-section documents like healthcare packages. Section 1 contains primary extraction, sections 2+ contain additional document types within the same file."
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum documents to return per page (default: 10, max: 100). Use lower values for faster responses, higher values to retrieve more documents in one call."
                                },
                                "next_token": {
                                    "type": "string",
                                    "description": "Pagination token from previous request for retrieving next page of results. Omit for first page."
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
    region = props['Region']
    client = boto3.client("bedrock-agentcore-control", region_name=region)
    
    # Paginate through all gateways
    all_gateways = []
    paginator = client.get_paginator("list_gateways")
    for page in paginator.paginate():
        all_gateways.extend(page.get("items", []))
    
    items = [g for g in all_gateways if g.get("name") == gateway_name]
    
    if not items:
        logger.info(f"Gateway {gateway_name} not found")
        return
    
    gateway_id = items[0].get("gatewayId")
    logger.info(f"Deleting gateway: {gateway_id}")
    
    # Delete all targets first (typically only one target per gateway)
    response = client.list_gateway_targets(gatewayIdentifier=gateway_id)
    targets = response.get("items", [])
    logger.info(f"Found {len(targets)} targets to delete")
    
    deletion_errors = []
    for target in targets:
        target_id = target["targetId"]
        logger.info(f"Deleting target: {target_id}")
        try:
            client.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
            time.sleep(2)
        except Exception as e:
            error_msg = f"target {target_id}: {str(e)}"
            logger.warning(f"Failed to delete {error_msg}")
            deletion_errors.append(error_msg)
    
    # Wait for targets to be fully deleted
    time.sleep(10)
    
    # Delete gateway
    try:
        client.delete_gateway(gatewayIdentifier=gateway_id)
        logger.info(f"Gateway deleted: {gateway_id}")
    except Exception as e:
        error_msg = f"gateway: {str(e)}"
        logger.warning(f"Failed to delete {error_msg}")
        deletion_errors.append(error_msg)
    
    # Wait for gateway deletion to complete
    time.sleep(5)
    
    if deletion_errors:
        raise Exception(f"Partial deletion errors: {'; '.join(deletion_errors)}")

