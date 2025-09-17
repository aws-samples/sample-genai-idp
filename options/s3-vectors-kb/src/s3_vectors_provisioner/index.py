import os
import json
import logging
import urllib3
from typing import Dict, Any
import cfnresponse

# Removed unused 'botocore' import
from idp_common.s3vectors.client import S3VectorsClient

# Initialize logger in the global scope for Lambda container reuse.
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

client = S3VectorsClient()

def provision_s3_vector_resources(
    vector_bucket_name: str, vector_index_name: str, dimension: int, distance_metric: str
) -> Dict[str, str]:
    """
    Idempotently creates an S3 Vector bucket and a corresponding index.

    Args:
        vector_bucket_name: The name of the S3 bucket to create.
        vector_index_name: The name of the vector index to create within the bucket.
        dimension: The dimensionality of the vectors that will be stored.
        distance_metric: The metric used to measure vector similarity (e.g., 'cosine').

    Returns:
        A dictionary containing the names of the created bucket and index.
    """
    logger.info(f"Provisioning resources: bucket='{vector_bucket_name}', index='{vector_index_name}'")
    
    kms_key_arn = os.environ.get("KMS_KEY_ARN")
    if kms_key_arn:
        client.create_bucket(vector_bucket_name, kms_key_arn)
    else:
        client.create_bucket(vector_bucket_name)
    
    
    # Define non-filterable metadata keys (large content that shouldn't be used for filtering)

    client.create_index(
        vector_bucket_name,
        vector_index_name,
        dimension,
        distance_metric
        )
    
    return {"reason": "s3 Vector Bucket Created"}


def handler(event: Dict[str, Any], context: Any):
    """
    CloudFormation Custom Resource handler for provisioning S3 Vector resources.
    """
    print('Started Provisioning')
    print(f'EVENT: {event}')
    request_id = event["RequestId"]
    props = event.get('ResourceProperties', {})
    logger.info(f"Received {request_id} request with properties: {json.dumps(props)}")
    new_physical_id = {"PhysicalResourceId": f"{props['VectorBucketName']}-{props['VectorIndexName']}"}
    try:
        bucket = props['VectorBucketName']
        index = props['VectorIndexName']
        dimension = int(props.get('VectorDimension', 1024))
        distance_metric = props.get('DistanceMetric', 'cosine')
        provision_s3_vector_resources(bucket, index, dimension, distance_metric)

        return cfnresponse.send(event, context, cfnresponse.SUCCESS, new_physical_id, request_id, "s3 Vector Bucket Created")

    except Exception as e:
        logger.error(f"Request failed: {e}", exc_info=True)
        return cfnresponse.send(event, context, cfnresponse.SUCCESS, new_physical_id, request_id, "s3 Vector Bucket Failed")
       