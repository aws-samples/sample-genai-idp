# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import boto3
import os
import cfnresponse
import logging
import time
from botocore.exceptions import ClientError

# Initialize logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event, context):
    """
    Lambda handler for updating Cognito User Pool Client with SageMaker workteam URLs.
    Ensures all exceptions are captured and proper CFN responses are sent.
    """
    # Initialize variables for exception handling
    physical_resource_id = f"CognitoClientUpdater-{context.log_stream_name}"

    try:
        logger.info(f"Event received: {json.dumps(event)}")

        # Validate required environment variables
        user_pool_id = os.environ["USER_POOL_ID"]
        client_id = os.environ["CLIENT_ID"]
        workteam_name = os.environ["WORKTEAM_NAME"]

        response_data = {}

        # Handle DELETE request
        if event.get("RequestType") == "Delete":
            logger.info("Delete request - no action needed")
            cfnresponse.send(
                event, context, cfnresponse.SUCCESS, response_data, physical_resource_id
            )
            return

        # Ignore the SourceCodeHash property as it's only used to force updates
        _ = event["ResourceProperties"].get("SourceCodeHash")

        # Get workteam subdomain
        sagemaker = boto3.client("sagemaker")
        workteam_response = sagemaker.describe_workteam(WorkteamName=workteam_name)

        subdomain = workteam_response["Workteam"].get("SubDomain", "")
        if not subdomain:
            raise ValueError(f"Could not find subdomain for workteam {workteam_name}")

        logger.info(f"Found workteam subdomain: {subdomain}")

        # Generate URLs
        callback_url = f"https://{subdomain}/oauth2/idpresponse"
        logout_url = f"https://{subdomain}/logout"
        workforce_login_url = f"https://{subdomain}/"

        logger.info(f"Setting callback URL: {callback_url}")
        logger.info(f"Setting logout URL: {logout_url}")

        # Update Cognito User Pool Client
        cognito = boto3.client("cognito-idp")

        # Get current client configuration
        client_response = cognito.describe_user_pool_client(
            UserPoolId=user_pool_id, ClientId=client_id
        )
        current_client = client_response["UserPoolClient"]

        # Prepare update parameters
        update_params = {
            "UserPoolId": user_pool_id,
            "ClientId": client_id,
            "ClientName": current_client.get("ClientName", ""),
            "RefreshTokenValidity": current_client.get("RefreshTokenValidity", 30),
            "AllowedOAuthFlowsUserPoolClient": True,
            "AllowedOAuthFlows": ["code", "implicit"],
            "AllowedOAuthScopes": ["email", "openid", "profile"],
            "CallbackURLs": [callback_url],
            "LogoutURLs": [logout_url],
            "SupportedIdentityProviders": ["COGNITO"],
        }

        # Add optional parameters if they exist in current config
        for param in [
            "ExplicitAuthFlows",
            "AccessTokenValidity",
            "IdTokenValidity",
            "TokenValidityUnits",
            "PreventUserExistenceErrors",
        ]:
            if param in current_client:
                update_params[param] = current_client[param]

        if "GenerateSecret" in current_client and current_client["GenerateSecret"]:
            update_params["GenerateSecret"] = True

        # Allow time for the private workteam to be fully created
        time.sleep(5)

        # Update the client
        cognito.update_user_pool_client(**update_params)

        logger.info("Successfully updated Cognito User Pool Client")

        response_data = {
            "ClientId": client_id,
            "CallbackURL": callback_url,
            "LogoutURL": logout_url,
            "WorkforceLogin": workforce_login_url,
        }

        cfnresponse.send(
            event, context, cfnresponse.SUCCESS, response_data, physical_resource_id
        )

    except KeyError as e:
        error_msg = f"Missing required environment variable: {str(e)}"
        logger.error(error_msg)
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Error": error_msg},
            physical_resource_id,
            reason=error_msg,
        )

    except ValueError as e:
        error_msg = f"Invalid configuration: {str(e)}"
        logger.error(error_msg)
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Error": error_msg},
            physical_resource_id,
            reason=error_msg,
        )

    except ClientError as e:
        error_msg = f"AWS service error: {str(e)}"
        logger.error(error_msg)
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Error": error_msg},
            physical_resource_id,
            reason=error_msg,
        )

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Error": error_msg},
            physical_resource_id,
            reason=error_msg,
        )
