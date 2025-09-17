import os
import json
import logging
import cfnresponse
from typing import Dict, Any
from idp_common.s3vectors.client import S3VectorsClient

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

def provision_s3_vector_resources_and_knowledge_base(
    vector_bucket_name: str, vector_index_name: str, dimension: int, distance_metric: str, 
    kb_name: str, kb_description: str, embedding_model_arn: str, kb_role_arn: str
) -> Dict[str, str]:
    """
    Idempotently creates S3 Vector resources and Bedrock Knowledge Base.

    Args:
        vector_bucket_name: The name of the S3 vector bucket to create.
        vector_index_name: The name of the vector index to create within the bucket.
        dimension: The dimensionality of the vectors that will be stored.
        distance_metric: The metric used to measure vector similarity (e.g., 'cosine').
        kb_name: Name for the Bedrock Knowledge Base.
        kb_description: Description for the Bedrock Knowledge Base.
        embedding_model_arn: ARN of the embedding model to use.
        kb_role_arn: ARN of the IAM role for the Knowledge Base.

    Returns:
        A dictionary containing the created resource information.
    """
    logger.info(f"Provisioning S3 vectors resources and Bedrock KB: bucket='{vector_bucket_name}', index='{vector_index_name}'")
    
    # Step 1: Create S3 vector resources
    s3vectors_client = S3VectorsClient()
    kms_key_arn = os.environ.get("KMS_KEY_ARN")
    
    # Create S3 vector bucket
    if kms_key_arn:
        s3vectors_client.create_bucket(vector_bucket_name, kms_key_arn)
    else:
        s3vectors_client.create_bucket(vector_bucket_name)
    
    # Create vector index with metadata configuration for Bedrock KB
    non_filterable_keys = ["text_content", "s3_uri", "AMAZON_BEDROCK_TEXT_CHUNK"]
    
    s3vectors_client.create_index(
        vector_bucket_name,
        vector_index_name,
        dimension,
        distance_metric,
        non_filterable_metadata_keys=non_filterable_keys
    )
    
    # Step 2: Create Bedrock Knowledge Base using boto3
    import boto3
    bedrock_client = boto3.client('bedrock-agent')
    
    # Construct S3 vectors ARNs
    aws_region = os.environ.get('AWS_REGION')
    aws_account_id = os.environ.get('AWS_ACCOUNT_ID')
    vector_bucket_arn = f"arn:aws:s3vectors:{aws_region}:{aws_account_id}:bucket/{vector_bucket_name}"
    index_arn = f"arn:aws:s3vectors:{aws_region}:{aws_account_id}:index/{vector_bucket_name}/{vector_index_name}"
    
    try:
        # Try to create the Knowledge Base
        kb_response = bedrock_client.create_knowledge_base(
            name=kb_name,
            description=kb_description,
            roleArn=kb_role_arn,
            knowledgeBaseConfiguration={
                'type': 'VECTOR',
                'vectorKnowledgeBaseConfiguration': {
                    'embeddingModelArn': embedding_model_arn
                }
            },
            storageConfiguration={
                'type': 'S3_VECTORS',
                's3VectorsConfiguration': {
                    'vectorBucketArn': vector_bucket_arn,
                    'indexArn': index_arn,
                    'indexName': vector_index_name
                }
            }
        )
        
        knowledge_base_id = kb_response['knowledgeBase']['knowledgeBaseId']
        logger.info(f"Successfully created Bedrock Knowledge Base: {knowledge_base_id}")
        
        return {
            "VectorBucketName": vector_bucket_name,
            "VectorIndexName": vector_index_name,
            "KnowledgeBaseId": knowledge_base_id,
            "KnowledgeBaseArn": kb_response['knowledgeBase']['knowledgeBaseArn']
        }
        
    except bedrock_client.exceptions.ConflictException:
        # Knowledge Base already exists - find it and return its details
        logger.info(f"Knowledge Base {kb_name} already exists, finding existing one")
        
        # Simple approach: list all KBs and find the one with matching name
        list_response = bedrock_client.list_knowledge_bases()
        for kb in list_response.get('knowledgeBaseSummaries', []):
            if kb['name'] == kb_name:
                logger.info(f"Found existing Knowledge Base: {kb['knowledgeBaseId']}")
                return {
                    "VectorBucketName": vector_bucket_name,
                    "VectorIndexName": vector_index_name,
                    "KnowledgeBaseId": kb['knowledgeBaseId'],
                    "KnowledgeBaseArn": kb['knowledgeBaseArn']
                }
        
        # If we can't find it, something is wrong
        raise Exception(f"Knowledge Base {kb_name} should exist but was not found in list")
    
    except Exception as e:
        logger.error(f"Failed to create Bedrock Knowledge Base: {e}")
        raise


def handler(event: Dict[str, Any], context: Any):
    """
    CloudFormation Custom Resource handler for provisioning S3 Vector resources for Bedrock KB.
    """
    logger.info(f"Received event: {json.dumps(event, default=str)}")
    
    request_id = event["RequestId"]
    props = event.get('ResourceProperties', {})
    physical_resource_id = f"{props.get('VectorBucketName', 'unknown')}-{props.get('VectorIndexName', 'unknown')}"
    
    try:
        if event['RequestType'] in ['Create', 'Update']:
            bucket = props['VectorBucketName']
            index = props['VectorIndexName']
            dimension = int(props.get('VectorDimension', 1024))
            distance_metric = props.get('DistanceMetric', 'cosine')
            kb_name = props['KnowledgeBaseName']
            kb_description = props['KnowledgeBaseDescription']
            embedding_model_arn = props['EmbeddingModelArn']
            kb_role_arn = props['KnowledgeBaseRoleArn']
            
            result = provision_s3_vector_resources_and_knowledge_base(
                bucket, index, dimension, distance_metric,
                kb_name, kb_description, embedding_model_arn, kb_role_arn
            )
            
            response_data = result
            
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_resource_id)
            
        elif event['RequestType'] == 'Delete':
            # For delete operations, we don't actually delete the S3 vectors resources
            # as they may contain important data. Let Bedrock KB manage the lifecycle.
            logger.info("Delete operation - S3 vectors resources retained")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physical_resource_id)
            
    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, physical_resource_id, str(e))