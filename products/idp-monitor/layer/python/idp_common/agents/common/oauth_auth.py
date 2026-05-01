# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
OAuth authentication utilities for IDP agents.
"""

import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def get_cognito_bearer_token(
    user_pool_id: str,
    client_id: str,
    username: str,
    password: str,
    session: boto3.Session,
) -> str:
    """
    Get bearer token from AWS Cognito using USER_PASSWORD_AUTH flow.

    Args:
        user_pool_id: Cognito User Pool ID
        client_id: Cognito App Client ID
        username: Cognito username
        password: Cognito password
        session: Boto3 session for AWS operations

    Returns:
        Bearer token string

    Raises:
        Exception: If authentication fails
    """
    try:
        cognito_client = session.client("cognito-idp")

        response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )

        access_token = response["AuthenticationResult"]["AccessToken"]
        logger.info(f"Successfully obtained Cognito bearer token for user: {username}")
        return access_token

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = f"Cognito authentication failed: {error_code} - {e.response['Error']['Message']}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except KeyError as e:
        error_msg = f"Unexpected Cognito response structure: missing {e}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Failed to get Cognito bearer token: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
