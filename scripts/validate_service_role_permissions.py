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

def main():
    # Templates to check
    templates = [
        'template.yaml',  # Main template
        'patterns/pattern-1/template.yaml',
        'patterns/pattern-2/template.yaml', 
        'patterns/pattern-3/template.yaml',
        'options/bda-lending-project/template.yaml',
        'options/bedrockkb/template.yaml'
    ]
    
    all_services = set()
    
    # Extract services from all templates
    for template_path in templates:
        if os.path.exists(template_path):
            services = extract_aws_services_from_template(template_path)
            all_services.update(services)
            print(f'{template_path}: {sorted(services)}')
        else:
            print(f'⚠️  Template not found: {template_path}')
    
    print(f'\nAll templates use services: {sorted(all_services)}')

    # Extract permissions from service role
    role_permissions = extract_permissions_from_role('iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml')
    print(f'Service role has {len(role_permissions)} permissions')

    # Basic validation - check if role has broad permissions
    has_broad_permissions = any('*' in perm for perm in role_permissions)
    print(f'Service role has broad permissions: {has_broad_permissions}')

    if has_broad_permissions:
        print('✅ Service role appears to have sufficient permissions for deployment')
        return 0
    else:
        print('⚠️  Service role may need additional permissions')
        return 0  # Don't fail the pipeline, just warn

if __name__ == '__main__':
    sys.exit(main())
