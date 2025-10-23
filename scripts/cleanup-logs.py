#!/usr/bin/env python3
"""
CloudWatch Logs cleanup for IDP deployments.
Prevents Step Functions deployment failures by cleaning up stale resource policy entries.
"""
import boto3
import json
import re
import sys

def cleanup_resource_policy(region='us-east-1'):
    logs_client = boto3.client('logs', region_name=region)
    
    # Get existing log groups
    existing_groups = set()
    paginator = logs_client.get_paginator('describe_log_groups')
    for page in paginator.paginate(logGroupNamePrefix='/aws/vendedlogs/states'):
        for lg in page['logGroups']:
            existing_groups.add(lg['logGroupName'])
    
    # Clean resource policy
    response = logs_client.describe_resource_policies()
    if not response['resourcePolicies']:
        print("No resource policy found")
        return
        
    policy = response['resourcePolicies'][0]
    policy_doc = json.loads(policy['policyDocument'])
    original_count = len(policy_doc['Statement'])
    
    cleaned_statements = []
    for stmt in policy_doc['Statement']:
        resource = stmt.get('Resource', '')
        if '/aws/vendedlogs/states/' in resource:
            match = re.search(r'log-group:([^:]+)', resource)
            if match and match.group(1) in existing_groups:
                cleaned_statements.append(stmt)
        else:
            cleaned_statements.append(stmt)
    
    if len(cleaned_statements) < original_count:
        policy_doc['Statement'] = cleaned_statements
        logs_client.put_resource_policy(
            policyName=policy['policyName'],
            policyDocument=json.dumps(policy_doc)
        )
        print(f"Cleaned resource policy: {original_count} -> {len(cleaned_statements)} statements")
    else:
        print("No cleanup needed")

if __name__ == '__main__':
    region = sys.argv[1] if len(sys.argv) > 1 else 'us-east-1'
    cleanup_resource_policy(region)
