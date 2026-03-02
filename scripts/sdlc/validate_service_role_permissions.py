#!/usr/bin/env python3
"""
Validate CloudFormation service role has sufficient permissions for IDP deployment
"""

import yaml
import sys
import os

# Custom YAML loader that ignores CloudFormation intrinsic functions
class CFNLoader(yaml.SafeLoader):
    pass

def cfn_constructor(loader, tag_suffix, node):
    return None  # Ignore CloudFormation functions

# Register constructors for CloudFormation intrinsic functions
CFNLoader.add_multi_constructor('!', cfn_constructor)

def extract_aws_services_from_template(template_path):
    """Extract AWS services used in a CloudFormation template"""
    try:
        with open(template_path, 'r') as f:
            template = yaml.load(f, Loader=CFNLoader)
        
        services = set()
        if template and 'Resources' in template:
            for resource in template['Resources'].values():
                if resource and 'Type' in resource:
                    resource_type = resource['Type']
                    if resource_type and resource_type.startswith('AWS::'):
                        service = resource_type.split('::')[1].lower()
                        services.add(service)
        return services
    except Exception as e:
        print(f'Error parsing {template_path}: {e}')
        return set()

def extract_permissions_from_role(role_template_path):
    """Extract permissions from CloudFormation service role template"""
    try:
        with open(role_template_path, 'r') as f:
            role_template = yaml.load(f, Loader=CFNLoader)
        
        permissions = set()
        if role_template and 'Resources' in role_template:
            for resource in role_template['Resources'].values():
                if resource and resource.get('Type') == 'AWS::IAM::Role':
                    policies = resource.get('Properties', {}).get('Policies', [])
                    for policy in policies:
                        statements = policy.get('PolicyDocument', {}).get('Statement', [])
                        for statement in statements:
                            actions = statement.get('Action', [])
                            if isinstance(actions, str):
                                actions = [actions]
                            for action in actions:
                                if '*' in action:
                                    service = action.split(':')[0]
                                    permissions.add(f'{service}:*')
                                else:
                                    permissions.add(action)
        return permissions
    except Exception as e:
        print(f'Error parsing role template: {e}')
        return set()

def extract_iam_actions_from_template(template_path):
    """Extract IAM actions used in a CloudFormation template"""
    try:
        with open(template_path, 'r') as f:
            template = yaml.load(f, Loader=CFNLoader)
        
        iam_actions = set()
        if template and 'Resources' in template:
            for resource in template['Resources'].values():
                if resource and 'Properties' in resource:
                    # Check IAM roles and policies
                    if resource.get('Type') == 'AWS::IAM::Role':
                        policies = resource.get('Properties', {}).get('Policies', [])
                        for policy in policies:
                            statements = policy.get('PolicyDocument', {}).get('Statement', [])
                            for statement in statements:
                                actions = statement.get('Action', [])
                                if isinstance(actions, str):
                                    actions = [actions]
                                for action in actions:
                                    if isinstance(action, str) and ':' in action:
                                        iam_actions.add(action)
                    
                    # Check managed policies
                    elif resource.get('Type') == 'AWS::IAM::ManagedPolicy':
                        statements = resource.get('Properties', {}).get('PolicyDocument', {}).get('Statement', [])
                        for statement in statements:
                            actions = statement.get('Action', [])
                            if isinstance(actions, str):
                                actions = [actions]
                            for action in actions:
                                if isinstance(action, str) and ':' in action:
                                    iam_actions.add(action)
        
        return iam_actions
    except Exception as e:
        print(f'Error extracting IAM actions from {template_path}: {e}')
        return set()

def extract_required_permissions_from_templates(templates):
    """Extract all required permissions from templates"""
    wildcard_permissions = set()
    required_iam_actions = set()
    
    # Services to ignore (not real AWS services)
    ignore_services = {'serverless', 'opensearchserverless', 'cognito'}
    
    for template_path in templates:
        if os.path.exists(template_path):
            services = extract_aws_services_from_template(template_path)
            iam_actions = extract_iam_actions_from_template(template_path)
            
            for service in services:
                if service != 'iam' and service not in ignore_services:
                    wildcard_permissions.add(f'{service}:*')
            
            # Only add IAM actions to required_iam_actions
            for action in iam_actions:
                if action.startswith('iam:'):
                    required_iam_actions.add(action)
    
    return wildcard_permissions, required_iam_actions

def extract_iam_permissions_from_role(role_template_path):
    """Extract actual IAM permissions from service role template"""
    try:
        with open(role_template_path, 'r') as f:
            role_template = yaml.load(f, Loader=CFNLoader)
        
        iam_permissions = set()
        if role_template and 'Resources' in role_template:
            for resource in role_template['Resources'].values():
                if resource and resource.get('Type') == 'AWS::IAM::Role':
                    policies = resource.get('Properties', {}).get('Policies', [])
                    for policy in policies:
                        statements = policy.get('PolicyDocument', {}).get('Statement', [])
                        for statement in statements:
                            actions = statement.get('Action', [])
                            if isinstance(actions, str):
                                actions = [actions]
                            for action in actions:
                                if action.startswith('iam:'):
                                    iam_permissions.add(action)
        return iam_permissions
    except Exception as e:
        print(f'Error extracting IAM permissions: {e}')
        return set()

def validate_permissions(role_permissions, required_wildcards, required_iam_actions, role_iam_permissions):
    """Validate if service role has required permissions"""
    missing_wildcards = []
    
    # Check wildcard permissions for non-IAM services
    for required in required_wildcards:
        if required not in role_permissions:
            missing_wildcards.append(required)
    
    # Check specific IAM actions
    missing_iam = required_iam_actions - role_iam_permissions
    
    return missing_wildcards, missing_iam

def main():
    # Templates to check
    templates = [
        'template.yaml',  # Main template
        'patterns/unified/template.yaml',
        'nested/bda-lending-project/template.yaml',
        'nested/bedrockkb/template.yaml'
    ]
    
    # Extract required permissions from templates
    required_wildcards, required_iam_actions = extract_required_permissions_from_templates(templates)
    print(f'Required wildcard permissions: {sorted(required_wildcards)}')
    print(f'Required IAM actions: {sorted(required_iam_actions)}')

    # Extract permissions from service role
    role_permissions = extract_permissions_from_role('iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml')
    role_iam_permissions = extract_iam_permissions_from_role('iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml')
    
    print(f'Service role has {len(role_permissions)} total permissions')
    print(f'Service role has {len(role_iam_permissions)} IAM permissions: {sorted(role_iam_permissions)}')

    # Validate permissions
    missing_wildcards, missing_iam = validate_permissions(
        role_permissions, required_wildcards, required_iam_actions, role_iam_permissions
    )

    # Report results
    exit_code = 0
    
    if missing_wildcards:
        print(f'❌ Missing wildcard permissions: {missing_wildcards}')
        exit_code = 1
    
    if missing_iam:
        print(f'❌ Missing IAM permissions: {sorted(missing_iam)}')
        exit_code = 1
    
    if exit_code == 0:
        print('✅ Service role has sufficient permissions for deployment')
    
    return exit_code

if __name__ == '__main__':
    sys.exit(main())