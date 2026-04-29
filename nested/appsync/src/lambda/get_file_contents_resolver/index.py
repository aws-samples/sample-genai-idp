# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import html
import json
import logging
import mimetypes
import os
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

s3_client = boto3.client('s3')


# Bucket allow-list for get_file_contents.
# --------------------------------------------
# The AppSync schema for getFileContents accepts an arbitrary `s3Uri`
# argument from any authenticated Cognito user. In the default
# single-tenant deployment, all authenticated users are trusted to read
# any document processed by this stack — that is by design. However,
# the Lambda's execution role has S3Read permission on several IDP
# buckets (input, output, baseline, configuration, reporting), and if
# a user passed in a completely unrelated S3 URI (for example an
# object from another stack or a third-party bucket the execution
# role happens to be able to read via a cross-account policy), the
# resolver would happily proxy its contents.
#
# To prevent use of this resolver as a generic S3-read gadget, we
# restrict the accepted buckets to those explicitly passed in via
# environment variables (set by `nested/appsync/template.yaml` from
# the main stack's bucket refs). If the env vars are unset
# (unusual — older deployments that haven't been redeployed), we
# fail open with a warning to preserve functionality, and operators
# are expected to redeploy to pick up the new template.
_ALLOWED_BUCKETS_ENV = {
    "INPUT_BUCKET",
    "OUTPUT_BUCKET",
    "CONFIGURATION_BUCKET",
    "EVALUATION_BASELINE_BUCKET",
    "REPORTING_BUCKET",
    "TEST_SET_BUCKET",
    "DISCOVERY_BUCKET",
    "WORKING_BUCKET",
}
ALLOWED_BUCKETS = {
    os.environ[name]
    for name in _ALLOWED_BUCKETS_ENV
    if os.environ.get(name)
}


# --- inline log sanitizer ---------------------------------------------------
# Minimal inline redactor. Kept here rather than importing from idp_common to
# avoid adding a Lambda Layer dependency to this resolver. If this file grows
# to need idp_common anyway, promote to
# `from idp_common.utils.log_sanitizer import sanitize_event_for_logging`.
_LOG_SENSITIVE_KEYS = (
    "password", "secret", "token", "authorization", "apikey", "api_key",
    "cookie", "credential", "claims", "identity",
)


def _sanitize_for_log(obj):
    """Deep-copy `obj` redacting values whose keys match the denylist."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(s in k.lower() for s in _LOG_SENSITIVE_KEYS):
                out[k] = "***REDACTED***" if v is not None else None
            else:
                out[k] = _sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_log(v) for v in obj]
    return obj

def _validate_bucket(bucket: str) -> None:
    """Reject the request if `bucket` is not in the allow-list.

    No-op (with a warning log) when ALLOWED_BUCKETS is empty, which
    happens if none of the bucket env vars are set (legacy deployment
    path). Production template always sets at least INPUT_BUCKET and
    OUTPUT_BUCKET.
    """
    if not ALLOWED_BUCKETS:
        logger.warning(
            "get_file_contents_resolver: no bucket allow-list configured "
            "(all of %s are unset). Skipping bucket validation. Redeploy "
            "the stack to pick up the tightened template.",
            sorted(_ALLOWED_BUCKETS_ENV),
        )
        return
    if bucket not in ALLOWED_BUCKETS:
        # Avoid echoing the bucket name back to the client (minor
        # information-disclosure hardening).
        logger.warning(
            "get_file_contents_resolver: rejecting request for bucket "
            "%r (not in allow-list %s).",
            bucket,
            sorted(ALLOWED_BUCKETS),
        )
        raise Exception("Unauthorized: requested bucket is not accessible from this deployment.")


def handler(event, context):
    """
    Lambda function to fetch contents of a file from S3
    
    Parameters:
        event (dict): Lambda event data containing GraphQL arguments
        context (object): Lambda context
        
    Returns:
        dict: Dictionary containing file contents and metadata
        
    Raises:
        Exception: Various exceptions related to S3 operations or invalid input
    """
    try:
        logger.info(f"Received event: {json.dumps(_sanitize_for_log(event))}")
        
        # Extract S3 URI from arguments
        s3_uri = event['arguments']['s3Uri']
        logger.info(f"Processing S3 URI: {s3_uri}")
        
        # Parse S3 URI to get bucket and key. The URI must be of the
        # form `s3://<bucket>/<key>`. We intentionally do NOT accept
        # virtual-hosted-style HTTPS URIs here because they require a
        # completely different parsing path.
        parsed_uri = urlparse(s3_uri)
        if parsed_uri.scheme != "s3" or not parsed_uri.netloc:
            raise Exception("Invalid S3 URI: expected s3://<bucket>/<key>")
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip('/')  # Remove leading slash from path
        if not key:
            raise Exception("Invalid S3 URI: key is required")

        # Enforce that the requested bucket belongs to this IDP stack's
        # known bucket set — prevents use of this resolver as a generic
        # S3-read gadget.
        _validate_bucket(bucket)

        logger.info(f"Fetching from bucket: {bucket}, key: {key}")

        # Get object from S3
        response = s3_client.get_object(
            Bucket=bucket,
            Key=key
        )

        
        # Get content type from S3 response or infer from file extension
        content_type = response.get('ContentType', '')
        if not content_type or content_type == 'binary/octet-stream' or content_type == 'application/octet-stream':
            content_type = mimetypes.guess_type(key)[0] or 'text/plain'
        
        logger.info(f"File content type: {content_type}")
        logger.info(f"File size: {response['ContentLength']}")
        
        # Read file content with error handling for different encodings
        try:
            # First try UTF-8
            file_content = response['Body'].read().decode('utf-8')
        except UnicodeDecodeError:
            # If UTF-8 fails, try with error handling
            try:
                response['Body'].seek(0)  # Reset the file pointer
                file_content = response['Body'].read().decode('utf-8', errors='replace')
                logger.warning("File content contained invalid UTF-8 characters that were replaced")
            except Exception as decode_error:
                # Last resort - if it's a binary file format with text extension
                logger.error(f"Failed to decode content with error handling: {str(decode_error)}")
                return {
                    'content': "This file contains binary content that cannot be displayed as text.",
                    'contentType': content_type,
                    'size': response['ContentLength'],
                    'isBinary': True
                }
        
        # For HTML content, escape the HTML to prevent XSS
        if content_type.startswith('text/html') or content_type.startswith('application/xhtml+xml'):
            file_content = html.escape(file_content)
            
        # Return both content and metadata
        return {
            'content': file_content,
            'contentType': content_type,
            'size': response['ContentLength'],
            'isBinary': False
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"S3 ClientError: {error_code} - {error_message}")
        
        if error_code == 'NoSuchKey':
            raise Exception(f"File not found: {key}")
        elif error_code == 'NoSuchBucket':
            raise Exception(f"Bucket not found: {bucket}")
        else:
            raise Exception(f"Error accessing S3: {error_message}")
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise Exception(f"Error fetching file: {str(e)}")