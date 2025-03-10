import os
import io
from typing import Dict
import boto3
import json
import zipfile
import tempfile
from botocore.exceptions import ClientError
from loguru import logger

# Let's make jsonlines optional
try:
    import jsonlines
except ImportError:
    # Code to handle the case where module_name is not available
    logger.trace("Module 'jsonlines' is not installed.")
    jsonlines = None


class S3Util:

    @staticmethod
    def put_bytes(bytes_data: bytes, bucket_name: str, key: str):
        # Saves bytes data to S3
        s3_client = boto3.client('s3')
        try:
            s3_client.put_object(Body=bytes_data, Bucket=bucket_name, Key=key)
            # print(f"Successfully uploaded bytes to {bucket_name}/{key}")
        except ClientError as e:
            print(f"Error uploading bytes to S3: {e}")

    @staticmethod
    def get_bytes(bucket_name: str, key: str) -> bytes:
        # Gets bytes data from S3
        s3_client = boto3.client('s3')
        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=key)
            bytes_data = response['Body'].read()
            return bytes_data
        except ClientError as e:
            print(f"Error retrieving bytes from S3: {e}")
            return None

    @staticmethod
    def delete_object(self, bucket_name: str, object_name: str):
        s3Resource = boto3.resource('s3')
        try:
            s3Resource.Object(bucket_name, object_name).delete()
            logger.debug(f"Object '{object_name}' deleted from bucket '{bucket_name}'.")
        except Exception as e:
            logger.error(f"Failed to delete object '{object_name}': {e}")

    @staticmethod
    def put_object(self, bucket_name: str, object_name: str, data):
        s3Resource = boto3.resource('s3')
        try:
            s3Resource.Bucket(bucket_name).put_object(Key=object_name, Body=data)
            logger.debug(f"Object '{object_name}' uploaded to bucket '{bucket_name}'.")
        except Exception as e:
            logger.error(f"Failed to upload object '{object_name}': {e}")

    @staticmethod
    def get_object(bucket_name: str, object_name: str):
        s3Resource = boto3.resource('s3')
        try:
            obj = s3Resource.Object(bucket_name, object_name).get()
            return obj['Body'].read()
        except Exception as e:
            logger.error(f"Failed to retrieve object '{object_name}': {e}")
            return None

    @staticmethod
    def get_object_stream(bucket_name: str, object_name: str):
        s3Resource = boto3.resource('s3')
        try:
            obj = s3Resource.Object(bucket_name, object_name).get()
            return obj['Body']
        except Exception as e:
            logger.error(f"Failed to retrieve object stream for '{object_name}': {e}")
            return None

    @staticmethod
    def query_json_objects_stream(bucket_name: str, sql_expression: str, path: str = ""):
        for result in S3Util.query_json_objects(bucket_name=bucket_name,
                                              sql_expression=sql_expression,
                                              path=path):
            yield json.loads(result)

    @staticmethod
    def query_json_objects(bucket_name: str, sql_expression: str, path: str = ""):
        input_serialization = {
            'JSON': {'Type': 'DOCUMENT'}
        }
        output_serialization = {
            'JSON': {'RecordDelimiter': '\n'}
        }
        s3_client = boto3.client('s3')
        objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=path).get('Contents', [])

        for obj in objects:
            object_key = obj['Key']
            logger.debug(f"Querying object: {object_key}")

            try:
                response = s3_client.select_object_content(
                    Bucket=bucket_name,
                    Key=object_key,
                    ExpressionType='SQL',
                    Expression=sql_expression,
                    InputSerialization=input_serialization,
                    OutputSerialization=output_serialization,
                    RequestProgress={'Enabled': True}
                )

                for event in response['Payload']:
                    if 'Records' in event:
                        yield json.loads(event['Records']['Payload'].decode('utf-8'))

                    elif 'Stats' in event:
                        stats = event['Stats']['Details']
                        logger.debug(f"Bytes Scanned: {stats['BytesScanned']}, Bytes Returned: {stats['BytesReturned']}")

            except Exception as e:
                logger.debug(f"Error querying object {object_key}: {e}")

    @staticmethod
    def query_jsonl_objects_stream(bucket_name: str, sql_expression: str, path: str = ""):
        for result in S3Util.query_jsonl_objects(bucket_name=bucket_name, sql_expression=sql_expression, path=path):
            # Split the result into individual JSON lines
            for line in result.splitlines():
                if line.strip():  # Ignore empty lines
                    yield json.loads(line)

    @staticmethod
    def query_jsonl_objects(bucket_name: str, sql_expression: str, path: str = ""):
        input_serialization = {
            'JSON': {'Type': 'LINES'}  # Adjusted for JSONL (newline-delimited JSON)
        }
        output_serialization = {
            'JSON': {'RecordDelimiter': '\n'}
        }

        s3_client = boto3.client('s3')
        objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=path).get('Contents', [])

        for obj in objects:
            object_key = obj['Key']
            logger.debug(f"Querying object: {object_key}")

            try:
                response = s3_client.select_object_content(
                    Bucket=bucket_name,
                    Key=object_key,
                    ExpressionType='SQL',
                    Expression=sql_expression,
                    InputSerialization=input_serialization,
                    OutputSerialization=output_serialization,
                    RequestProgress={'Enabled': True}
                )

                for event in response['Payload']:
                    if 'Records' in event:
                        yield event['Records']['Payload'].decode('utf-8')

                    elif 'Stats' in event:
                        stats = event['Stats']['Details']
                        logger.debug(f"Bytes Scanned: {stats['BytesScanned']}, Bytes Returned: {stats['BytesReturned']}")

            except Exception as e:
                logger.error(f"Error querying object {object_key}: {e}")


    @staticmethod
    def put_text(bucket_name: str, object_name: str, text: str, concat: bool = False):
        if concat:
            try:
                existing_text = S3Util.get_text(bucket_name, object_name)
                if existing_text:
                    if not existing_text.endswith('\n'):
                        existing_text += '\n'
                    text = existing_text + text
            except:
                pass
        S3Util.put_object(bucket_name, object_name, text.encode('utf-8'))

    @staticmethod
    def get_text(bucket_name: str, object_name: str):
        data = S3Util.get_object(bucket_name, object_name)
        return data.decode('utf-8') if data else None


    @staticmethod
    def put_json(bucket_name: str, object_name: str, json_data):
        """
        Upload JSON data to S3 with proper escaping and validation
        """
        try:
            # Validate JSON serialization first
            json_str = json.dumps(
                json_data,
                ensure_ascii=True,
                default=str,
                allow_nan=False  # Prevents invalid JSON with NaN/Infinity
            )
            S3Util.put_text(bucket_name, object_name, json_str)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid JSON data: {e}")
            raise

    @staticmethod
    def get_json(bucket_name: str, object_name: str):
        import json
        data = S3Util.get_text(bucket_name, object_name)
        return json.loads(data) if data else None
   
    @staticmethod
    def put_jsonl(bucket_name: str, object_name: str, jsonl_data: list, concat: bool = False):
        """Upload JSONL data with proper Unicode and multiline handling"""
        try:
            with io.StringIO() as f:
                writer = jsonlines.Writer(f)
                writer.write_all(jsonl_data)
                jsonl_text = f.getvalue()

            if concat:
                existing_text = S3Util.get_text(bucket_name, object_name)
                if existing_text and not existing_text.endswith('\n'):
                    existing_text += '\n'
                jsonl_text = (existing_text or '') + jsonl_text
                
            S3Util.put_text(bucket_name, object_name, jsonl_text)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid JSONL data: {e}")
            raise

    @staticmethod
    def get_jsonl(bucket_name: str, object_name: str):
        """
        Retrieve and parse a JSONL file from the specified bucket.
        :param bucket_name: The bucket name.
        :param object_name: The object key.
        :return: A list of dictionaries representing the JSONL data.
        """
        try:
            jsonl_text = S3Util.get_text(bucket_name, object_name)
            if jsonl_text:
                return [json.loads(line) for line in jsonl_text.strip().split("\n") if line]
            else:
                logger.debug(f"No content found in JSONL object '{object_name}'.")
                return []
        except Exception as e:
            logger.error(f"Failed to retrieve or parse JSONL data from '{object_name}': {e}")
            return []


    @staticmethod
    def put_dict(bucket_name: str, object_name: str, data_dict: Dict):
        S3Util.put_json(bucket_name, object_name, data_dict)

    @staticmethod
    def get_dict(bucket_name: str, object_name: str):
        return S3Util.get_json(bucket_name, object_name)
    
    @staticmethod
    def put_zip(bucket_name: str, object_name: str, relative_path: str):
        absolute_path = os.path.abspath(relative_path)
        if not os.path.exists(absolute_path):
            raise FileNotFoundError(f"Local path '{absolute_path}' does not exist")
       
        try:
            # Create a temporary ZIP file
            with tempfile.NamedTemporaryFile(delete=False) as temp_zip:
                with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(absolute_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, os.path.relpath(file_path, absolute_path))
                
                temp_zip_path = temp_zip.name

            # Upload the ZIP file
            with open(temp_zip_path, 'rb') as f:
                S3Util.put_object(bucket_name, object_name, f.read())
            
            logger.debug(f"ZIP archive '{object_name}' uploaded to bucket '{bucket_name}'.")
        except Exception as e:
            logger.error(f"Failed to upload ZIP archive '{object_name}': {e}")
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)

    @staticmethod
    def get_zip(bucket_name: str, object_name: str, local_filename: str = "archive.zip"):
        try:
            # Download the ZIP file
            zip_data = S3Util.get_object(bucket_name, object_name)
            if not zip_data:
                logger.debug(f"Failed to retrieve ZIP archive '{object_name}' from bucket '{bucket_name}'.")
                return None

            # Create a temporary directory
            temp_dir = tempfile.mkdtemp()

            # Save and extract the ZIP file
            zip_path = os.path.join(temp_dir, local_filename)
            with open(zip_path, 'wb') as f:
                f.write(zip_data)

            with zipfile.ZipFile(zip_path, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            logger.debug(f"ZIP archive '{object_name}' extracted to '{temp_dir}'.")
            return temp_dir
        except Exception as e:
            logger.error(f"Failed to retrieve or extract ZIP archive '{object_name}': {e}")
            return None

    @staticmethod
    def put_dataframe(self, bucket_name: str, object_name: str, df):
        """
        Upload a pandas DataFrame as JSONL to the specified bucket.
        :param bucket_name: The bucket name
        :param object_name: The object key
        :param df: pandas DataFrame to upload
        """
        jsonl_data = df.to_dict('records')
        S3Util.put_jsonl(bucket_name, object_name, jsonl_data)
        
    @staticmethod
    def get_dataframe(self, bucket_name: str, object_name: str):
        """
        Retrieve a pandas DataFrame from JSONL in the specified bucket.
        :param bucket_name: The bucket name
        :param object_name: The object key
        :return: pandas DataFrame
        """
        import pandas as pd
        jsonl_data = S3Util.get_jsonl(bucket_name, object_name)
        return pd.DataFrame(jsonl_data) if jsonl_data else pd.DataFrame()
    
    @staticmethod
    def empty_bucket(bucket_name: str):
        """
        Empty an S3 bucket completely, including all versioned objects.
        This will permanently delete all objects and their versions from the bucket.
        
        SAFETY: Requires environment variable S3UTIL_ALLOW_EMPTY_BUCKET=true
        
        :param bucket_name: The name of the bucket to empty
        :raises PermissionError: If the required environment variable is not set to "true"
        """
        # Safety check - require explicit environment variable to allow emptying buckets
        allow_empty = os.environ.get('S3UTIL_ALLOW_BUCKET_DESTRUCT', '').lower()
        if allow_empty != 'true':
            error_msg = "Safety check failed: Environment variable S3UTIL_ALLOW_EMPTY_BUCKET must be set to exactly 'true' to empty buckets"
            logger.error(error_msg)
            raise PermissionError(error_msg)
        
        try:
            s3_resource = boto3.resource('s3')
            bucket = s3_resource.Bucket(bucket_name)
            
            # Check if bucket versioning is enabled
            versioning = boto3.client('s3').get_bucket_versioning(Bucket=bucket_name)
            is_versioned = versioning.get('Status') == 'Enabled'
            
            if is_versioned:
                logger.info(f"Emptying versioned bucket '{bucket_name}' (including all object versions)")
                # Delete all versions of all objects
                bucket.object_versions.delete()
            else:
                logger.info(f"Emptying bucket '{bucket_name}'")
                # Delete all objects
                bucket.objects.all().delete()
                
            logger.info(f"Successfully emptied bucket '{bucket_name}'")
        except ClientError as e:
            logger.error(f"Failed to empty bucket '{bucket_name}': {e}")
            raise

    @staticmethod
    def delete_bucket(bucket_name: str, empty_first: bool = True):
        """
        Delete an S3 bucket. By default, empties the bucket first.
        
        SAFETY: Requires environment variable S3UTIL_ALLOW_BUCKET_DESTRUCT=true
        
        :param bucket_name: The name of the bucket to delete
        :param empty_first: Whether to empty the bucket before deletion (default: True)
        :raises PermissionError: If the required environment variable is not set to "true"
        """
        # Safety check - require explicit environment variable to allow bucket destruction
        allow_destruct = os.environ.get('S3UTIL_ALLOW_BUCKET_DESTRUCT', '').lower()
        if allow_destruct != 'true':
            error_msg = "Safety check failed: Environment variable S3UTIL_ALLOW_BUCKET_DESTRUCT must be set to exactly 'true' to delete buckets"
            logger.error(error_msg)
            raise PermissionError(error_msg)
        
        try:
            # First empty the bucket if requested
            if empty_first:
                logger.info(f"Emptying bucket '{bucket_name}' before deletion")
                S3Util.empty_bucket(bucket_name)
            
            # Now delete the bucket
            s3_client = boto3.client('s3')
            s3_client.delete_bucket(Bucket=bucket_name)
            
            logger.info(f"Successfully deleted bucket '{bucket_name}'")
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketNotEmpty':
                logger.error(f"Cannot delete non-empty bucket '{bucket_name}'. Set empty_first=True or empty the bucket manually.")
            else:
                logger.error(f"Failed to delete bucket '{bucket_name}': {e}")
            raise

    @staticmethod
    def list_objects(bucket_name: str, prefix: str = "", max_keys: int = 1000, continuation_token: str = None):
        """
        List objects in an S3 bucket with optional prefix filtering.
        
        :param bucket_name: The name of the bucket to list objects from
        :param prefix: Optional prefix to filter objects (default: "")
        :param max_keys: Maximum number of keys to return in one request (default: 1000)
        :param continuation_token: Token for pagination (default: None)
        :return: Dictionary containing 'Contents' (list of objects), 'IsTruncated' (boolean),
                and 'NextContinuationToken' (if results are truncated)
        """
        try:
            s3_client = boto3.client('s3')
            params = {
                'Bucket': bucket_name,
                'MaxKeys': max_keys,
                'Prefix': prefix
            }
            
            if continuation_token:
                params['ContinuationToken'] = continuation_token
                
            response = s3_client.list_objects_v2(**params)
            
            result = {
                'Contents': response.get('Contents', []),
                'IsTruncated': response.get('IsTruncated', False)
            }
            
            if response.get('IsTruncated'):
                result['NextContinuationToken'] = response.get('NextContinuationToken')
                
            logger.debug(f"Listed {len(result['Contents'])} objects from bucket '{bucket_name}' with prefix '{prefix}'")
            return result
        
        except ClientError as e:
            logger.error(f"Failed to list objects in bucket '{bucket_name}': {e}")
            raise