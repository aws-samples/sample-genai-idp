# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Cognito Pre Token Generation Lambda Trigger (V2_0)
Adds user groups to ID and Access tokens by querying Cognito API
"""

import json
import boto3

cognito = boto3.client('cognito-idp')


def handler(event, context):
    """
    Add cognito:groups claim to ID token and Access token (V2_0 format)
    
    Since groups without IAM roles don't appear in groupsToOverride,
    we query Cognito directly to get the user's groups.
    
    Args:
        event: Cognito PreTokenGeneration V2_0 trigger event
        context: Lambda context
        
    Returns:
        Modified event with groups added to token claims
    """
    print(f"PreTokenGeneration V2 Event: {json.dumps(event)}")
    
    user_pool_id = event.get('userPoolId')
    username = event.get('userName')
    
    # Get user's groups directly from Cognito
    groups = []
    try:
        response = cognito.admin_list_groups_for_user(
            UserPoolId=user_pool_id,
            Username=username
        )
        groups = [group['GroupName'] for group in response.get('Groups', [])]
        print(f"User {username} is in groups: {groups}")
    except Exception as e:
        print(f"Error fetching groups for user {username}: {e}")
    
    if groups:
        # For V2_0, we use claimsAndScopeOverrideDetails
        event['response'] = {
            'claimsAndScopeOverrideDetails': {
                'idTokenGeneration': {
                    'claimsToAddOrOverride': {
                        'cognito:groups': groups
                    }
                },
                'accessTokenGeneration': {
                    'claimsToAddOrOverride': {
                        'cognito:groups': groups
                    }
                }
            }
        }
        print(f"Added groups to token: {groups}")
    else:
        print(f"No groups found for user {username}")
    
    return event
