# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import boto3
import logging
import botocore
import html
import mimetypes
import base64
import hashlib
import os
import re 
from urllib.parse import urlparse
from botocore.exceptions import ClientError
from idp_common.bedrock.client import BedrockClient

# Set up logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

def remove_text_between_brackets(text):
    # Find position of first opening bracket
    start = text.find('{')
    # Find position of last closing bracket
    end = text.rfind('}')
    
    # If both brackets exist, remove text between them including brackets
    if start != -1 and end != -1:
        return text[:start] + text[end+1:]
    # If brackets not found, return original string
    return text

# Get LOG_LEVEL from environment variable with INFO as default
def s3_object_exists(bucket, key):
    try:
        s3 = boto3.client('s3')
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        else:
            raise

def get_full_text(bucket, key):
    try:
        dynamodb = boto3.resource('dynamodb')
        tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE_NAME'])
        
        doc_pk = f"doc#{key}"
        response = tracking_table.get_item(
            Key={'PK': doc_pk, 'SK': 'none'}
        )
        
        if 'Item' not in response:
            logger.info(f"Document {key} not found")
            raise Exception(f"Document {key} not found")
            
        document = response['Item']
        pages = document.get('Pages', {})
        sorted_pages = sorted(pages, key=lambda x: x['Id'])

        s3 = boto3.client('s3')
        all_text = ""
        
        for page in sorted_pages:
            if 'TextUri' in page:
                # Extract S3 key from URI
                text_key = page['TextUri'].replace(f"s3://{bucket}/", "")
                
                try:
                    response = s3.get_object(Bucket=bucket, Key=text_key)
                    page_text = response['Body'].read().decode('utf-8')
                    all_text += f"<page-number>{page['Id']}</page-number>\n{page_text}\n\n"
                except Exception as e:
                    logger.warning(f"Failed to load page {page['Id']}: {e}")
                    
        return all_text
        
    except Exception as e:
        logger.error(f"Error getting document pages: {str(e)}")
        raise Exception(f"Error getting document pages: {str(e)}")


def get_summarization_model():
    """Get the summarization model from configuration table"""
    try:
        dynamodb = boto3.resource('dynamodb')
        config_table = dynamodb.Table(os.environ['CONFIGURATION_TABLE_NAME'])
        
        # Query for the Default configuration
        response = config_table.get_item(
            Key={'Configuration': 'Default'}
        )
        
        if 'Item' in response:
            config_data = response['Item']
            # Extract summarization model from the configuration
            if 'summarization' in config_data and 'model' in config_data['summarization']:
                return config_data['summarization']['model']
        
        # Fallback to a default model if not found in config
        return 'us.amazon.nova-pro-v1:0'
        
    except Exception as e:
        logger.error(f"Error getting summarization model from config: {str(e)}")
        return 'us.amazon.nova-pro-v1:0'  # Fallback default

def handler(event, context):
    response_data = {}

    try:
        # logger.info(f"Received event: {json.dumps(event)}")
        objectKey = event['arguments']['s3Uri']
        prompt = event['arguments']['prompt']
        history = event['arguments']['history']

        full_prompt = "The history JSON object is: " + json.dumps(history) + ".\n\n"
        full_prompt += "The user's question is: " + prompt + "\n\n"

        # this feature is not enabled until the model can be selected on the chat screen
        # selectedModelId = event['arguments']['modelId']
        selectedModelId = get_summarization_model()

        logger.info(f"Processing S3 URI: {objectKey}")
        logger.info(f"Region: {os.environ['AWS_REGION']}")

        output_bucket = os.environ['OUTPUT_BUCKET']

        if (len(objectKey)):
            fulltext_key = objectKey + '/summary/fulltext.txt'
            content_str = ""
            s3 = boto3.client('s3')

            if not s3_object_exists(output_bucket, fulltext_key):
                logger.info(f"Creating full text file: {fulltext_key}")
                content_str = get_full_text(output_bucket, objectKey)

                s3.put_object(
                    Bucket=output_bucket,
                    Key=fulltext_key,
                    Body=content_str.encode('utf-8')
                )
            else:
                # read full contents of the object as text
                response = s3.get_object(Bucket=output_bucket, Key=fulltext_key)
                content_str = response['Body'].read().decode('utf-8')

            logger.info(f"Model: {selectedModelId}")
            logger.info(f"Output Bucket: {output_bucket}")
            logger.info(f"Full Text Key: {fulltext_key}")

            # Content with cachepoint tags
            content = [
                {
                    "text": content_str + """
                    <<CACHEPOINT>>
                    """ + full_prompt
                }
            ]

            client = BedrockClient(
                region=os.environ['AWS_REGION'],
                max_retries=5,
                initial_backoff=1.5,
                max_backoff=300,
                metrics_enabled=True
            )

            # Invoke a model
            response = client.invoke_model(
                model_id=selectedModelId,
                system_prompt="You are an assistant that's responsible for getting details from document text attached here based on questions from the user.\n\nIf you don't know the answer, just say that you don't know. Don't try to make up an answer.\n\nAdditionally, use the user and assistant responses in the following JSON object to see what's been asked and what the resposes were in the past.\n\n",
                content=content,
                temperature=0.0
            )

            text = client.extract_text_from_response(response)
            logger.info(f"Full response: {text}")

            # right now, there is a JSON object before the full response when a guardrail is tripped
            # need to remove that JSON object first
            logger.info(f"New response: {remove_text_between_brackets(text).strip("\n")}")
            cleaned_up_text = remove_text_between_brackets(text).strip("\n")
            
            chat_response = {"cr": {"content": [{"text": cleaned_up_text}]}}
            
            return json.dumps(chat_response)

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"Error: {error_code} - {error_message}")
        
        if error_code == 'NoSuchKey':
            raise Exception(f"File not found: {fulltext_key}")
        elif error_code == 'NoSuchBucket':
            raise Exception(f"Bucket not found: {output_bucket}")
        else:
            raise Exception(error_message)
            
    except Exception as e:
        logger.error(f"{str(e)}")
        raise Exception(f"{str(e)}")
    
    return response_data