# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Batch run tool for processing documents"""

import logging
import base64
import boto3
import os
import uuid
from typing import Any, Dict, Optional
from datetime import datetime
from .base import IDPTool

logger = logging.getLogger(__name__)

# Version marker
TOOL_VERSION = "SDK-v2-enhanced"
TOOL_UPDATED = "2025-01-24T00:00:00Z"


class BatchRunTool(IDPTool):
    """Process documents through IDP pipeline"""

    def __init__(self):
        """Initialize with stack name from environment"""
        # Try AWS_STACK_NAME first, then extract from Lambda function name
        self.stack_name = os.environ.get('AWS_STACK_NAME')
        if not self.stack_name:
            lambda_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', '')
            # Extract stack name by removing -agentcore-analytics suffix
            if lambda_name.endswith('-agentcore-analytics'):
                self.stack_name = lambda_name.replace('-agentcore-analytics', '')
            else:
                self.stack_name = lambda_name
        logger.info(f"BatchRunTool initialized with stack_name: {self.stack_name}")

    def execute(
        self,
        location: Optional[str] = None,
        content: Optional[str] = None,
        name: Optional[str] = None,
        prefix: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute batch processing with intelligent parameter validation"""
        logger.info(f"=== Batch Run Tool ===")
        logger.info(f"Version: {TOOL_VERSION}")
        logger.info(f"Parameters: location={location}, content={'<base64>' if content else None}, name={name}, prefix={prefix}")
        
        # Validate parameters
        validation = self._validate_parameters(location, content, name)
        if not validation['valid']:
            return validation['error_response']
        
        # Route to appropriate handler
        if content:
            return self._process_base64_content(content, name, prefix)
        else:
            return self._process_s3_location(location, prefix)
    
    def _validate_parameters(self, location: Optional[str], content: Optional[str], name: Optional[str]) -> Dict[str, Any]:
        """Validate parameters and return validation result"""
        # Check if at least one source provided
        if not location and not content:
            return {
                'valid': False,
                'error_response': {
                    'success': False,
                    'error': 'missing_document_source',
                    'message': "Please provide either: (1) S3 location (e.g., 's3://bucket/documents/') or (2) base64-encoded document content"
                }
            }
        
        # Check if name provided when content provided
        if content and not name:
            return {
                'valid': False,
                'error_response': {
                    'success': False,
                    'error': 'missing_document_name',
                    'message': "When providing document content, please specify the filename with extension (e.g., 'invoice.pdf')"
                }
            }
        
        return {'valid': True}
    
    def _process_s3_location(self, location: str, prefix: Optional[str]) -> Dict[str, Any]:
        """Process S3 location using existing BatchProcessor"""
        try:
            from idp_sdk.core.batch_processor import BatchProcessor
            
            processor = BatchProcessor(stack_name=self.stack_name)
            result = processor.process_batch_from_s3_uri(
                s3_uri=location,
                file_pattern="*.pdf",
                recursive=True,
                output_prefix=prefix or 'mcp-batch'
            )
            
            return {
                'success': True,
                'batch_id': result['batch_id'],
                'documents_queued': result.get('queued', 0),
                'summary': {
                    'queued': result.get('queued', 0),
                    'skipped': result.get('skipped', 0),
                    'failed': result.get('failed', 0)
                },
                'message': f"Successfully queued {result.get('queued', 0)} documents for processing"
            }
        except Exception as e:
            logger.error(f"S3 processing failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': 'processing_failed',
                'message': f'Failed to queue documents for processing: {str(e)}'
            }
    
    def _process_base64_content(self, content: str, name: str, prefix: Optional[str]) -> Dict[str, Any]:
        """Process base64 content by uploading to MCP temp S3 first"""
        try:
            from idp_sdk.core.batch_processor import BatchProcessor
            
            logger.info(f"Base64 processing for: {name}")
            
            # Step 1: Decode base64
            try:
                document_binary = base64.b64decode(content)
                logger.info(f"Decoded base64 content: {len(document_binary)} bytes")
            except Exception as e:
                logger.error(f"Base64 decoding failed: {e}")
                return {
                    'success': False,
                    'error': 'invalid_base64',
                    'message': 'The provided content is not valid base64'
                }
            
            # Step 2: Generate batch ID and temp S3 key
            batch_id = self._generate_batch_id(prefix)
            temp_s3_key = f"mcp-temp/{batch_id}/{name}"
            logger.info(f"Generated batch_id: {batch_id}, temp_key: {temp_s3_key}")
            
            # Step 3: Get MCP content bucket
            mcp_bucket = os.environ.get('MCP_SERVER_BUCKET')
            if not mcp_bucket:
                logger.error("MCP_SERVER_BUCKET environment variable not set")
                return {
                    'success': False,
                    'error': 'missing_bucket_config',
                    'message': 'MCP server bucket not configured'
                }
            
            logger.info(f"Uploading to MCP bucket: {mcp_bucket}")
            
            # Step 4: Upload to MCP temp S3
            s3_client = boto3.client('s3')
            s3_client.put_object(
                Bucket=mcp_bucket,
                Key=temp_s3_key,
                Body=document_binary
            )
            logger.info(f"Uploaded to S3: s3://{mcp_bucket}/{temp_s3_key}")
            
            # Step 5: Use existing S3 processing logic with MCP bucket URI
            processor = BatchProcessor(stack_name=self.stack_name)
            temp_s3_uri = f"s3://{mcp_bucket}/{temp_s3_key}"
            result = processor.process_batch_from_s3_uri(
                s3_uri=temp_s3_uri,
                output_prefix=batch_id
            )
            logger.info(f"Batch processing completed: {result}")
            
            # Step 6: Return success
            return {
                'success': True,
                'batch_id': result['batch_id'],
                'documents_queued': 1,
                'document_name': name,
                'message': 'Document queued for processing'
            }
        
        except Exception as e:
            logger.error(f"Base64 processing failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': 'processing_failed',
                'message': f'Failed to queue document for processing: {str(e)}'
            }
    
    def _generate_batch_id(self, prefix: Optional[str]) -> str:
        """Generate batch ID with optional prefix"""
        prefix = prefix or 'mcp-batch'
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        return f"{prefix}-{timestamp}"
