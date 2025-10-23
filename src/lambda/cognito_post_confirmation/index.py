# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Cognito Post Confirmation Lambda Trigger
Automatically adds new users to the "Users" group
"""

import json
import boto3
from botocore.exceptions import ClientError

cognito = boto3.client('cognito-idp')


def handler(event, context):
    """
    Automatically assign new users to the Users group after account confirmation
    
    Args:
        event: Cognito PostConfirmation trigger event
        context: Lambda context
        
    Returns:
        event: Unmodified event (required by Cognito)
    """
    print(f"PostConfirmation Event: {json.dumps(event)}")
    
    user_pool_id = event.get('userPoolId')
    username = event.get('userName')
    trigger_source = event.get('triggerSource')
    
    # Only process PostConfirmation_ConfirmSignUp (not PostConfirmation_ConfirmForgotPassword)
    if trigger_source != 'PostConfirmation_ConfirmSignUp':
        print(f"Skipping - trigger source is {trigger_source}")
        return event
    
    # Add user to the Users group
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName='Users'
        )
        print(f"Successfully added user {username} to Users group")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            print(f"ERROR: Users group does not exist in user pool {user_pool_id}")
            # Don't fail the confirmation - just log the error
        else:
            print(f"ERROR adding user to group: {e}")
            # Don't fail the confirmation - just log the error
    except Exception as e:
        print(f"Unexpected error: {e}")
        # Don't fail the confirmation - just log the error
    
    return event
