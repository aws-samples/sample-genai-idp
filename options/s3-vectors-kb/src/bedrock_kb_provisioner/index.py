import os
import json
import logging
import cfnresponse
from typing import Dict, Any
from idp_common.s3vectors.client import S3VectorsClient

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

def provision_s3_vector_resources(
    vector_bucket_name: str, vector_index_name: str, dimension: int, distance_metric: str, filterable_metadata_keys: list = None
) -> Dict[str, str]:
    """
    Idempotently creates an S3 Vector bucket and index for Bedrock Knowledge Base backend.

    Args:
        vector_bucket_name: The name of the S3 vector bucket to create.
        vector_index_name: The name of the vector index to create within the bucket.
        dimension: The dimensionality of the vectors that will be stored.
        distance_metric: The metric used to measure vector similarity (e.g., 'cosine').

    Returns:
        A dictionary containing the names of the created bucket and index.
    """
    logger.info(f"Provisioning S3 vectors resources for Bedrock KB: bucket='{vector_bucket_name}', index='{vector_index_name}'")
    
    client = S3VectorsClient()
    kms_key_arn = os.environ.get("KMS_KEY_ARN")
    
    # Create S3 vector bucket
    if kms_key_arn:
        client.create_bucket(vector_bucket_name, kms_key_arn)
    else:
        client.create_bucket(vector_bucket_name)
    
    # Create vector index with metadata configuration for Bedrock KB
    # Configure filterable vs non-filterable metadata keys
    non_filterable_keys = ["text_content", "s3_uri", "AMAZON_BEDROCK_TEXT_CHUNK"]
    
    # Add any custom filterable keys while keeping large content fields non-filterable
    if filterable_metadata_keys:
        logger.info(f"Configuring filterable metadata keys: {filterable_metadata_keys}")
        # Ensure we don't accidentally make large content fields filterable
        safe_filterable_keys = [key for key in filterable_metadata_keys if key not in non_filterable_keys]
        if safe_filterable_keys:
            logger.info(f"Safe filterable keys: {safe_filterable_keys}")
    
    client.create_index(
        vector_bucket_name,
        vector_index_name,
        dimension,
        distance_metric,
        non_filterable_metadata_keys=non_filterable_keys
    )
    
    logger.info(f"Successfully provisioned S3 vectors resources for Bedrock KB")
    return {"reason": "S3 Vector resources created for Bedrock Knowledge Base"}


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
            
            result = provision_s3_vector_resources(bucket, index, dimension, distance_metric)
            
            response_data = {
                'VectorBucketName': bucket,
                'VectorIndexName': index,
                'VectorDimension': dimension,
                'DistanceMetric': distance_metric
            }
            
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_resource_id)
            
        elif event['RequestType'] == 'Delete':
            # For delete operations, we don't actually delete the S3 vectors resources
            # as they may contain important data. Let Bedrock KB manage the lifecycle.
            logger.info("Delete operation - S3 vectors resources retained")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physical_resource_id)
            
    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, physical_resource_id, str(e))