# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import botocore
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class S3VectorsClient:
    """A client for interacting with the S3 Vectors service."""

    def __init__(self, s3vectors_client: Optional[boto3.client] = None):
        """
        Initializes the S3VectorsClient.

        Args:
            s3vectors_client: An optional pre-configured boto3 s3vectors client.
                              If None, a new client will be created.
        """
        if s3vectors_client:
            self.s3vectors = s3vectors_client
        else:
            # S3 Vectors is a preview service and requires explicit region configuration
            import os
            region = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
            self.s3vectors = boto3.client('s3vectors', region_name=region)

    def _is_already_exists_error(self, error: Exception) -> bool:
        """Checks if a boto3 client error is a resource already exists error."""
        if isinstance(error, botocore.exceptions.ClientError):
            return error.response.get('Error', {}).get('Code') == 'ConflictException'
        return False

    def create_bucket(self, vector_bucket_name: str, kms_key_arn: str = None) -> None:
        """
        Idempotently creates an S3 Vector bucket.

        Args:
            vector_bucket_name: The name for the vector bucket.
            kms_key_arn: Optional KMS key ARN for encryption.
        """
        try:
            if kms_key_arn:
                self.s3vectors.create_vector_bucket(
                    vectorBucketName=vector_bucket_name,
                    encryptionConfiguration={
                        'sseType': 'aws:kms',
                        'kmsKeyArn': kms_key_arn
                    }
                )
            else:
                self.s3vectors.create_vector_bucket(vectorBucketName=vector_bucket_name)
          
            logger.info(f"Vector bucket '{vector_bucket_name}' created.")
        except Exception as e:
            if self._is_already_exists_error(e):
                logger.warning(f"Vector bucket '{vector_bucket_name}' already exists.")
            else:
                logger.error(f"Failed to create vector bucket '{vector_bucket_name}': {e}")
                raise

    def create_index(self, vector_bucket_name: str, vector_index_name: str, dimension: int, distance_metric: str, non_filterable_metadata_keys: List[str] = None) -> None:
        """
        Idempotently creates an S3 Vector index in an existing bucket.

        Args:
            vector_bucket_name: The name of the vector bucket.
            vector_index_name: The name for the vector index.
            dimension: The dimension of the vectors for the index.
            distance_metric: The distance metric (e.g., 'cosine').
        """
        try:
            # Use provided non-filterable keys or default ones
            if non_filterable_metadata_keys is None:
                non_filterable_metadata_keys = ["text", "s3_uri"]
            
            self.s3vectors.create_index(
                vectorBucketName=vector_bucket_name,
                indexName=vector_index_name,
                dataType='float32',
                dimension=dimension,
                distanceMetric=distance_metric,
                metadataConfiguration={"nonFilterableMetadataKeys": non_filterable_metadata_keys},
            )
            logger.info(f"Index '{vector_index_name}' created in bucket '{vector_bucket_name}'.")
        except Exception as e:
            if self._is_already_exists_error(e):
                logger.warning(f"Index '{vector_index_name}' already exists in bucket '{vector_bucket_name}'.")
            else:
                logger.error(f"Failed to create index '{vector_index_name}': {e}")
                raise

