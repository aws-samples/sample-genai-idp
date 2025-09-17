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

    def create_index(self, vector_bucket_name: str, vector_index_name: str, dimension: int, distance_metric: str) -> None:
        """
        Idempotently creates an S3 Vector index in an existing bucket.

        Args:
            vector_bucket_name: The name of the vector bucket.
            vector_index_name: The name for the vector index.
            dimension: The dimension of the vectors for the index.
            distance_metric: The distance metric (e.g., 'cosine').
        """
        try:
            self.s3vectors.create_index(
                vectorBucketName=vector_bucket_name,
                indexName=vector_index_name,
                dataType='float32',
                dimension=dimension,
                distanceMetric=distance_metric,
                metadataConfiguration={"nonFilterableMetadataKeys": ["text_content", "s3_uri"]},
            )
            logger.info(f"Index '{vector_index_name}' created in bucket '{vector_bucket_name}'.")
        except Exception as e:
            if self._is_already_exists_error(e):
                logger.warning(f"Index '{vector_index_name}' already exists in bucket '{vector_bucket_name}'.")
            else:
                logger.error(f"Failed to create index '{vector_index_name}': {e}")
                raise

    def put_vectors(self, vectorBucketName: str, indexName: str, vectors: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Puts a batch of vector objects into an index.

        Args:
            vectorBucketName: The name of the vector bucket.
            indexName: The name of the index.
            vectors: A list of vector objects to upload. Each dict in the list
                     should conform to the structure expected by put_vectors,
                     e.g., {'objectId': str, 'vector': List[float], 'metadata': dict}.

        Returns:
            The response from the put_vectors API call.
        """
        try:
            # Transform the input vectors to match the S3 Vectors API format
            formatted_vectors = []
            for vector_obj in vectors:
                formatted_vector = {
                    'key': vector_obj.get("objectId"),
                    'data': {
                        'float32': vector_obj.get("vector")
                    },
                    'metadata': vector_obj.get("metadata", {})
                }
                formatted_vectors.append(formatted_vector)
            
            response = self.s3vectors.put_vectors(
                vectorBucketName=vectorBucketName,
                indexName=indexName,
                vectors=formatted_vectors
            )
            logger.info(f"Successfully put {len(vectors)} vectors into index '{indexName}'.")
            return response
        except Exception as e:
            logger.error(f"Failed to put vectors into index '{indexName}': {e}")
            raise

    def query_vectors(self, **query_params: Any) -> Dict[str, Any]:
        """
        Searches a vector index using the provided query parameters.

        This method is a direct pass-through to the `query_vectors` boto3 call.

        Args:
            **query_params: Keyword arguments to be passed directly to the
                            s3vectors.query_vectors() method. Expected params
                            include vectorBucketName, indexName, queryVector, and topK.
                            Note: queryVector should be provided as a List[float] and will
                            be automatically formatted as VectorData with float32.

        Returns:
            The response from the query_vectors API call.
        """
        try:
            # If queryVector is provided as a list, format it as VectorData
            if 'queryVector' in query_params and isinstance(query_params['queryVector'], list):
                query_params['queryVector'] = {
                    'float32': query_params['queryVector']
                }
            
            response = self.s3vectors.query_vectors(**query_params)
            count = len(response.get('vectors', []))
            logger.info(f"Query returned {count} results from index '{query_params.get('indexName')}'.")
            return response
        except Exception as e:
            logger.error(f"Failed to query index '{query_params.get('indexName')}': {e}")
            raise

    def list_vectors(self, vectorBucketName: Optional[str] = None, indexName: Optional[str] = None, 
                     indexArn: Optional[str] = None, maxResults: Optional[int] = None, 
                     nextToken: Optional[str] = None, segmentCount: Optional[int] = None, 
                     segmentIndex: Optional[int] = None, returnData: Optional[bool] = None, 
                     returnMetadata: Optional[bool] = None) -> Dict[str, Any]:
        """
        Lists vectors in the specified vector index.

        Args:
            vectorBucketName: The name of the vector bucket.
            indexName: The name of the vector index.
            indexArn: The Amazon Resource Name (ARN) of the vector index.
            maxResults: The maximum number of vectors to return on a page (default: 500).
            nextToken: Pagination token from a previous request.
            segmentCount: Total number of segments for parallel ListVectors operation.
            segmentIndex: Index of the segment for parallel ListVectors operation.
            returnData: If true, vector data will be included in the response (default: false).
            returnMetadata: If true, metadata will be included in the response (default: false).

        Returns:
            The response from the list_vectors API call containing vectors and pagination info.

        Raises:
            ValueError: If neither (vectorBucketName and indexName) nor indexArn is provided.
            Exception: If the API call fails.
        """
        try:
            # Validate input parameters
            if not indexArn and not (vectorBucketName and indexName):
                raise ValueError("Must provide either indexArn or both vectorBucketName and indexName")
            
            if segmentCount is not None and segmentIndex is None:
                raise ValueError("segmentIndex must be provided when segmentCount is specified")
            
            if segmentIndex is not None and segmentCount is None:
                raise ValueError("segmentCount must be provided when segmentIndex is specified")
            
            if segmentIndex is not None and segmentCount is not None:
                if segmentIndex >= segmentCount:
                    raise ValueError("segmentIndex must be less than segmentCount")

            # Build the request parameters, only including non-None values
            params = {}
            
            if vectorBucketName is not None:
                params['vectorBucketName'] = vectorBucketName
            if indexName is not None:
                params['indexName'] = indexName
            if indexArn is not None:
                params['indexArn'] = indexArn
            if maxResults is not None:
                params['maxResults'] = maxResults
            if nextToken is not None:
                params['nextToken'] = nextToken
            if segmentCount is not None:
                params['segmentCount'] = segmentCount
            if segmentIndex is not None:
                params['segmentIndex'] = segmentIndex
            if returnData is not None:
                params['returnData'] = returnData
            if returnMetadata is not None:
                params['returnMetadata'] = returnMetadata

            response = self.s3vectors.list_vectors(**params)
            
            vector_count = len(response.get('vectors', []))
            index_identifier = indexArn or f"{vectorBucketName}/{indexName}"
            logger.info(f"Listed {vector_count} vectors from index '{index_identifier}'.")
            
            return response
            
        except Exception as e:
            index_identifier = indexArn or f"{vectorBucketName}/{indexName}"
            logger.error(f"Failed to list vectors from index '{index_identifier}': {e}")
            raise

