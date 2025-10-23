#!/usr/bin/env python3

"""
Complete GovCloud template generation and publication script.

This script orchestrates the complete GovCloud-compatible build process:
1. Runs the standard publish.py script to build all artifacts
2. Generates a GovCloud-compatible template that excludes unsupported services
3. Uploads the GovCloud template to S3 alongside the main template  
4. Provides deployment URLs and instructions for both templates

Usage:
    python scripts/generate_govcloud_template.py <cfn_bucket_basename> <cfn_prefix> <region> [public] [options]
"""

import argparse
import os
import re
import sys
import yaml
import subprocess
import boto3
from pathlib import Path
from typing import Dict, Any, List, Set
import logging


class GovCloudTemplateGenerator:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.setup_logging()
        
        # Resources to remove for GovCloud compatibility
        self.ui_resources = {
            'CloudFrontDistribution',
            'CloudFrontOriginAccessIdentity', 
            'SecurityHeadersPolicy',
            'WebUIBucket',
            'WebUIBucketPolicy',
            'UICodeBuildProject',
            'UICodeBuildServiceRole',
            'StartUICodeBuild',
            'StartUICodeBuildExecutionRole',
            'StartUICodeBuildLogGroup',
            'CodeBuildRun'
        }
        
        self.appsync_resources = {
            'GraphQLApi',
            'GraphQLSchema',
            'GraphQLApiLogGroup',
            'AppSyncCwlRole',
            'AppSyncServiceRole',
            'TrackingTableDataSource',
            'UpdateDocumentResolver',
            'GetDocumentResolver',
            'ListDocumentResolver',
            'ListDocumentDateHourResolver',
            'ListDocumentDateShardResolver',
            'GetFileContentsResolverFunction',
            'GetFileContentsResolverFunctionLogGroup',
            'GetFileContentsDataSource',
            'GetFileContentsResolver',
            'GetStepFunctionExecutionResolverFunction',
            'GetStepFunctionExecutionResolverFunctionLogGroup',
            'GetStepFunctionExecutionDataSource',
            'GetStepFunctionExecutionResolver',
            'PublishStepFunctionUpdateResolverFunction',
            'PublishStepFunctionUpdateResolverFunctionLogGroup',
            'PublishStepFunctionUpdateDataSource',
            'PublishStepFunctionUpdateResolver',
            'ConfigurationResolverFunction',
            'ConfigurationResolverFunctionLogGroup',
            'ConfigurationDataSource',
            'GetConfigurationResolver',
            'UpdateConfigurationResolver',
            'CopyToBaselineResolverFunction',
            'CopyToBaselineResolverFunctionLogGroup',
            'CopyToBaselineDataSource',
            'CopyToBaselineResolver',
            'DeleteDocumentResolverFunction',
            'DeleteDocumentResolverFunctionLogGroup',
            'DeleteDocumentDataSource',
            'DeleteDocumentResolver',
            'ReprocessDocumentResolverFunction',
            'ReprocessDocumentResolverFunctionLogGroup',
            'ReprocessDocumentDataSource',
            'ReprocessDocumentResolver',
            'UploadResolverFunction',
            'UploadResolverFunctionLogGroup',
            'UploadResolverDataSource',
            'UploadDocumentResolver',
            'QueryKnowledgeBaseResolverFunction',
            'QueryKnowledgeBaseResolverFunctionLogGroup',
            'QueryKnowledgeBaseDataSource',
            'QueryKnowledgeBaseResolver',
            'ChatWithDocumentResolverFunction',
            'ChatWithDocumentResolverFunctionLogGroup',
            'ChatWithDocumentDataSource',
            'ChatWithDocumentResolver',
            'CreateDocumentResolverFunction',
            'CreateDocumentResolverFunctionLogGroup',
            'CreateDocumentDataSource',
            'CreateDocumentResolver',
            'AgentTableDataSource',
            'SubmitAgentQueryResolver',
            'AgentRequestHandlerDataSource',
            'GetAgentJobStatusResolver',
            'ListAgentJobsResolver',
            'UpdateAgentJobStatusResolver',
            'DeleteAgentJobResolver',
            'ListAvailableAgentsResolver',
            'ListAvailableAgentsDataSource',
            'DiscoveryJobsResolver',
            'DiscoveryProcessorFunction',
            'DiscoveryTableDataSource',
            'DiscoveryUploadDocumentResolver',
            'DiscoveryUploadResolverDataSource',
            'UpdateDiscoveryJobStatusResolver',
            'ProcessChangesResolverFunction',
            'ProcessChangesResolverFunctionLogGroup',
            'ProcessChangesDataSource',
            'ProcessChangesResolver'
        }
        
        self.auth_resources = {
            'UserPool',
            'UserPoolClient',
            'UserPoolDomain',
            'IdentityPool',
            'CognitoIdentityPoolSetRole',
            'CognitoAuthorizedRole',
            'AdminUser',
            'AdminGroup',
            'AdminUserToGroupAttachment',
            'GetDomain',  # This depends on Cognito UserPoolDomain - remove it
            'CognitoUserPoolEmailDomainVerifyFunction',
            'CognitoUserPoolEmailDomainVerifyFunctionLogGroup',
            'CognitoUserPoolEmailDomainVerifyPermission',
            'CognitoUserPoolEmailDomainVerifyPermissionReady'
        }
          
        self.waf_resources = {
            'WAFIPV4Set',
            'WAFLambdaServiceIPSet',
            'WAFWebACL',
            'WAFWebACLAssociation',
            'IPSetUpdaterFunction',
            'IPSetUpdaterCustomResource'
        }
        
        self.agent_resources = {
            'AgentTable',
            'AgentRequestHandlerFunction',
            'AgentRequestHandlerLogGroup',
            'AgentProcessorFunction',
            'AgentProcessorLogGroup',
            'ExternalMCPAgentsSecret',
            'ListAvailableAgentsFunction',
            'ListAvailableAgentsLogGroup'
        }
        
        self.hitl_resources = {
            'UserPoolClienta2i',
            'PrivateWorkteam',
            'CognitoClientUpdaterRole',
            'CognitoClientUpdaterFunctionLogGroup',
            'CognitoClientUpdaterFunction',
            'CognitoClientCustomResource',
            'A2IFlowDefinitionRole',
            'A2IHumanTaskUILambdaRole',
            'CreateA2IResourcesLambda',
            'A2IResourcesCustomResource',
            'GetWorkforceURLFunction',
            'WorkforceURLResource'
        }
        
        # Functions that are purely AppSync-dependent and should be removed for headless GovCloud deployment
        self.appsync_dependent_resources = {
            'StepFunctionSubscriptionPublisher',  # AppSync subscription publisher
            'StepFunctionSubscriptionPublisherLogGroup',
            'StepFunctionSubscriptionRule',
            'StepFunctionSubscriptionPublisherPermission'
        }
        
        # Parameters to remove
        self.ui_parameters = {
            'AdminEmail',
            'AllowedSignUpEmailDomain',
            'CloudFrontPriceClass',
            'CloudFrontAllowedGeos',
            'WAFAllowedIPv4Ranges',
            'DocumentKnowledgeBase',
            'KnowledgeBaseModelId',
            'DocumentAnalysisAgentModelId',
            'EnableHITL',
            'ExistingPrivateWorkforceArn'
        }
        
        # Outputs to remove
        self.ui_outputs = {
            'ApplicationWebURL',
            'WebUIBucketName',
            'WebUITestEnvFile',
            'SageMakerA2IReviewPortalURL',
            'LabelingConsoleURL',
            'ExternalMCPAgentsSecretName',
            'PrivateWorkteamArn'
        }

    def setup_logging(self):
        """Setup logging based on verbose flag"""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(levelname)s: %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def run_publish_script(self, publish_args: List[str]) -> bool:
        """Run the original publish.py script with provided arguments"""
        project_root = Path(__file__).parent.parent
        publish_script = project_root / "publish.py"
        
        if not publish_script.exists():
            raise FileNotFoundError(f"publish.py not found at {publish_script}")
        
        # Build command to run publish.py
        cmd = [sys.executable, str(publish_script)] + publish_args
        
        self.logger.info(f"Running publish script: {' '.join(cmd)}")
        
        # Run publish script and stream output
        result = subprocess.run(cmd, cwd=project_root)
        
        if result.returncode != 0:
            self.logger.error("Publish script failed!")
            return False
        
        self.logger.info("✅ Publish script completed successfully")
        return True

    def validate_template_via_s3(self, template_url: str, region: str) -> bool:
        """Validate template using CloudFormation API with S3 URL (avoids size limitations)"""
        try:
            self.logger.info(f"Performing CloudFormation API validation via S3 URL in region {region}")
            cf_client = boto3.client('cloudformation', region_name=region)
            
            # Validate template using CloudFormation API with S3 URL
            response = cf_client.validate_template(TemplateURL=template_url)
            
            self.logger.info("✅ CloudFormation API validation passed")
            self.logger.debug(f"Template description: {response.get('Description', 'N/A')}")
            
            # Log any parameters or capabilities
            if response.get('Parameters'):
                self.logger.debug(f"Template has {len(response['Parameters'])} parameters")
            if response.get('Capabilities'):
                self.logger.debug(f"Template requires capabilities: {response['Capabilities']}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ CloudFormation API validation failed: {e}")
            # Try to extract specific error details
            if hasattr(e, 'response') and 'Error' in e.response:
                error_code = e.response['Error'].get('Code', 'Unknown')
                error_msg = e.response['Error'].get('Message', str(e))
                self.logger.error(f"Error Code: {error_code}")
                self.logger.error(f"Error Message: {error_msg}")
            return False

    def upload_govcloud_template_to_s3(self, template_file: str, bucket_name: str, prefix: str, region: str) -> str:
        """Upload GovCloud template to S3 and return the URL"""
        try:
            # Initialize S3 client
            s3_client = boto3.client('s3', region_name=region)
            
            # Generate S3 key
            s3_key = f"{prefix}/idp-govcloud.yaml"
            
            # Upload the template
            self.logger.info(f"Uploading GovCloud template to s3://{bucket_name}/{s3_key}")
            
            with open(template_file, 'rb') as f:
                s3_client.upload_fileobj(
                    f,
                    bucket_name,
                    s3_key,
                    ExtraArgs={'ContentType': 'text/yaml'}
                )
            
            # Generate URL (using standard format - works for both AWS and GovCloud)
            template_url = f"https://s3.{region}.amazonaws.com/{bucket_name}/{s3_key}"
            
            self.logger.info(f"✅ GovCloud template uploaded successfully")
            return template_url
            
        except Exception as e:
            self.logger.error(f"Failed to upload GovCloud template to S3: {e}")
            return ""

    def load_template(self, input_file: str) -> Dict[str, Any]:
        """Load CloudFormation template from YAML file"""
        self.logger.info(f"Loading template from {input_file}")
        
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input template file not found: {input_file}")
        
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                template = yaml.safe_load(f)
            
            self.logger.debug(f"Loaded template with {len(template.get('Resources', {}))} resources")
            return template
            
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML template: {e}")
        
    def save_template(self, template: Dict[str, Any], output_file: str):
        """Save CloudFormation template to YAML file"""
        self.logger.info(f"Saving GovCloud template to {output_file}")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                yaml.dump(template, f, default_flow_style=False, width=120, indent=2)
            
            self.logger.info(f"✅ GovCloud template saved successfully")
            
        except Exception as e:
            raise ValueError(f"Failed to save template: {e}")

    def remove_resources(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove resources that are not supported in GovCloud"""
        resources = template.get('Resources', {})
        original_count = len(resources)
        
        # Combine all resources to remove
        all_resources_to_remove = (
            self.ui_resources | 
            self.appsync_resources | 
            self.appsync_dependent_resources |
            self.auth_resources | 
            self.waf_resources | 
            self.agent_resources |
            self.hitl_resources
        )
        
        # Also collect conditions that will be removed for resource dependency checking
        ui_conditions_to_remove = {
            'ShouldAllowSignUpEmailDomain',
            'ShouldEnableGeoRestriction',
            'IsWafEnabled',
            'ShouldCreateDocumentKnowledgeBase',
            'ShouldUseDocumentKnowledgeBase',
            'IsHITLEnabled',
            'IsPattern1HITLEnabled',
            'IsPattern2HITLEnabled',
            'ShouldCreatePrivateWorkteam',
            'ShouldUseExistingPrivateWorkteam'
        }
        
        removed_resources = []
        for resource_name in list(resources.keys()):
            resource_def = resources[resource_name]
            
            # Remove if resource is in explicit removal list
            if resource_name in all_resources_to_remove:
                del resources[resource_name]
                removed_resources.append(resource_name)
                continue
                
            # Remove if resource depends on a condition that we're removing
            if isinstance(resource_def, dict) and 'Condition' in resource_def:
                condition_name = resource_def['Condition']
                if condition_name in ui_conditions_to_remove:
                    del resources[resource_name]
                    removed_resources.append(f"{resource_name} (depends on removed condition: {condition_name})")
                    continue
        
        self.logger.info(f"Removed {len(removed_resources)} unsupported resources")
        self.logger.debug(f"Removed resources: {', '.join(removed_resources)}")
        
        remaining_count = len(resources)
        self.logger.info(f"Resources: {original_count} → {remaining_count}")
        
        return template

    def remove_parameters(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove parameters related to unsupported services and restrict IDPPattern to Pattern-2"""
        parameters = template.get('Parameters', {})
        original_count = len(parameters)
        
        removed_parameters = []
        for param_name in list(parameters.keys()):
            if param_name in self.ui_parameters:
                del parameters[param_name]
                removed_parameters.append(param_name)
        
        # Modify IDPPattern parameter to only allow Pattern-2 as the default
        if 'IDPPattern' in parameters:
            parameters['IDPPattern'] = {
                'Type': 'String',
                'Default': 'Pattern2 - Packet processing with Textract and Bedrock',
                'Description': 'Document processing pattern (GovCloud version supports Pattern-2 only)',
                'AllowedValues': [
                    'Pattern2 - Packet processing with Textract and Bedrock'
                ]
            }
            self.logger.info("Modified IDPPattern parameter to only support Pattern-2")
        
        self.logger.info(f"Removed {len(removed_parameters)} UI-related parameters")
        self.logger.debug(f"Removed parameters: {', '.join(removed_parameters)}")
        
        remaining_count = len(parameters)
        self.logger.info(f"Parameters: {original_count} → {remaining_count}")
        
        return template

    def remove_outputs(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove outputs related to unsupported services"""
        outputs = template.get('Outputs', {})
        original_count = len(outputs)
        
        removed_outputs = []
        for output_name in list(outputs.keys()):
            if output_name in self.ui_outputs:
                del outputs[output_name]
                removed_outputs.append(output_name)
        
        self.logger.info(f"Removed {len(removed_outputs)} UI-related outputs")
        self.logger.debug(f"Removed outputs: {', '.join(removed_outputs)}")
        
        remaining_count = len(outputs)
        self.logger.info(f"Outputs: {original_count} → {remaining_count}")
        
        return template

    def remove_conditions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove conditions related to unsupported services"""
        conditions = template.get('Conditions', {})
        original_count = len(conditions)
        
        ui_conditions = {
            'ShouldAllowSignUpEmailDomain',
            'ShouldEnableGeoRestriction',
            'IsWafEnabled',
            'ShouldCreateDocumentKnowledgeBase',
            'ShouldUseDocumentKnowledgeBase',
            'IsHITLEnabled',
            'IsPattern1HITLEnabled',
            'IsPattern2HITLEnabled',
            'ShouldCreatePrivateWorkteam',
            'ShouldUseExistingPrivateWorkteam'
        }
        
        removed_conditions = []
        for condition_name in list(conditions.keys()):
            if condition_name in ui_conditions:
                del conditions[condition_name]
                removed_conditions.append(condition_name)
        
        if removed_conditions:
            self.logger.info(f"Removed {len(removed_conditions)} UI-related conditions")
            self.logger.debug(f"Removed conditions: {', '.join(removed_conditions)}")
        
        remaining_count = len(conditions)
        if remaining_count != original_count:
            self.logger.info(f"Conditions: {original_count} → {remaining_count}")
        
        return template

    def remove_rules(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove rules that validate removed parameters"""
        rules = template.get('Rules', {})
        if not rules:
            return template
            
        original_count = len(rules)
        
        hitl_rules = {
            'ValidateExistingPrivateWorkforceArn'  # Rule that validates ExistingPrivateWorkforceArn parameter
        }
        
        removed_rules = []
        for rule_name in list(rules.keys()):
            if rule_name in hitl_rules:
                del rules[rule_name]
                removed_rules.append(rule_name)
        
        if removed_rules:
            self.logger.info(f"Removed {len(removed_rules)} HITL-related rules")
            self.logger.debug(f"Removed rules: {', '.join(removed_rules)}")
        
        remaining_count = len(rules)
        if remaining_count != original_count:
            self.logger.info(f"Rules: {original_count} → {remaining_count}")
        
        # Remove Rules section entirely if empty
        if remaining_count == 0:
            del template['Rules']
            self.logger.debug("Removed empty Rules section")
        
        return template

    def update_arn_partitions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Check ARN partitions (templates should already be partition-aware)"""
        self.logger.info("Checking ARN partitions (templates should already be partition-aware)")
        
        # Convert template to string to check for any remaining hard-coded ARNs
        template_str = yaml.dump(template, default_flow_style=False)
        
        # Count any remaining hard-coded ARNs (should be zero)
        remaining_arns = len(re.findall(r'arn:aws:(?!\$\{AWS::Partition\})', template_str))
        
        if remaining_arns > 0:
            self.logger.warning(f"Found {remaining_arns} hard-coded ARN references that should use partition variable")
            # Still apply the fix as a safety measure
            template_str = re.sub(
                r'arn:aws:(?!\$\{AWS::Partition\})',
                'arn:${AWS::Partition}:',
                template_str
            )
            template = yaml.safe_load(template_str)
            self.logger.info(f"Fixed {remaining_arns} hard-coded ARN references")
        else:
            self.logger.info("✅ All ARN references are already partition-aware")
        
        return template

    def clean_cloudfront_policy_statements(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Remove CloudFront-related policy statements from remaining resources"""
        self.logger.info("Removing CloudFront policy statements from remaining resources")
        
        resources = template.get('Resources', {})
        
        for resource_name, resource_def in resources.items():
            if not isinstance(resource_def, dict):
                continue
                
            # Handle S3 Bucket Policies
            if resource_def.get('Type') == 'AWS::S3::BucketPolicy':
                policy_doc = resource_def.get('Properties', {}).get('PolicyDocument', {})
                if self._clean_policy_document(policy_doc, resource_name):
                    self.logger.debug(f"Cleaned CloudFront policy statements from {resource_name}")
            
            # Handle IAM Role policies
            elif resource_def.get('Type') == 'AWS::IAM::Role':
                policies = resource_def.get('Properties', {}).get('Policies', [])
                for policy in policies:
                    if isinstance(policy, dict) and 'PolicyDocument' in policy:
                        policy_name = policy.get('PolicyName', 'unnamed')
                        if self._clean_policy_document(policy['PolicyDocument'], f"{resource_name}.{policy_name}"):
                            self.logger.debug(f"Cleaned CloudFront policy statements from {resource_name}.{policy_name}")
        
        return template

    def _clean_policy_document(self, policy_doc: Dict[str, Any], resource_identifier: str) -> bool:
        """Clean CloudFront-related statements from a policy document. Returns True if changes were made."""
        if not isinstance(policy_doc, dict) or 'Statement' not in policy_doc:
            return False
        
        statements = policy_doc['Statement']
        if not isinstance(statements, list):
            return False
        
        original_count = len(statements)
        cleaned_statements = []
        
        for statement in statements:
            if not isinstance(statement, dict):
                cleaned_statements.append(statement)
                continue
            
            # Check if this statement has CloudFront service principal
            principal = statement.get('Principal', {})
            should_remove = False
            
            if isinstance(principal, dict):
                service = principal.get('Service')
                if isinstance(service, str):
                    # Check for cloudfront service reference
                    if 'cloudfront.' in service.lower():
                        should_remove = True
                        self.logger.debug(f"Removing CloudFront policy statement from {resource_identifier}: {statement.get('Sid', 'unnamed')}")
                elif isinstance(service, dict):
                    # Handle CloudFormation intrinsic functions like Fn::Sub
                    if 'Fn::Sub' in service:
                        fn_sub_value = service['Fn::Sub']
                        if isinstance(fn_sub_value, str) and 'cloudfront.' in fn_sub_value.lower():
                            should_remove = True
                            self.logger.debug(f"Removing CloudFront policy statement (Fn::Sub) from {resource_identifier}: {statement.get('Sid', 'unnamed')}")
                elif isinstance(service, list):
                    # Filter out cloudfront services from service list
                    filtered_services = []
                    for s in service:
                        should_filter = False
                        if isinstance(s, str) and 'cloudfront.' in s.lower():
                            should_filter = True
                        elif isinstance(s, dict) and 'Fn::Sub' in s:
                            fn_sub_value = s['Fn::Sub']
                            if isinstance(fn_sub_value, str) and 'cloudfront.' in fn_sub_value.lower():
                                should_filter = True
                        
                        if not should_filter:
                            filtered_services.append(s)
                    
                    if len(filtered_services) != len(service):
                        if len(filtered_services) == 0:
                            # If no services left, remove the entire statement
                            should_remove = True
                            self.logger.debug(f"Removing CloudFront-only policy statement from {resource_identifier}: {statement.get('Sid', 'unnamed')}")
                        else:
                            # Update the service list
                            statement = statement.copy()
                            statement['Principal'] = principal.copy()
                            statement['Principal']['Service'] = filtered_services
                            self.logger.debug(f"Filtered CloudFront services from policy statement in {resource_identifier}: {statement.get('Sid', 'unnamed')}")
            
            if not should_remove:
                cleaned_statements.append(statement)
        
        # Update the policy document with cleaned statements
        policy_doc['Statement'] = cleaned_statements
        
        # Return whether changes were made
        return len(cleaned_statements) != original_count

    def clean_template_for_headless_deployment(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Clean template for headless GovCloud deployment by working with parsed YAML directly"""
        self.logger.info("Cleaning template for headless GovCloud deployment")
        
        resources = template.get('Resources', {})
        
        # Remove CloudFront policy statements from remaining resources
        template = self.clean_cloudfront_policy_statements(template)
        
        # Remove CORS configurations from all S3 buckets since no web UI in GovCloud
        s3_bucket_types = ['AWS::S3::Bucket']
        for resource_name, resource_def in resources.items():
            if isinstance(resource_def, dict) and resource_def.get('Type') in s3_bucket_types:
                properties = resource_def.get('Properties', {})
                if 'CorsConfiguration' in properties:
                    del properties['CorsConfiguration']
                    self.logger.debug(f"Removed CORS configuration from {resource_name}")
               
        # Convert all backend functions from AppSync to DynamoDB tracking mode
        functions_to_convert = ['QueueSender', 'QueueProcessor', 'WorkflowTracker', 'EvaluationFunction']
        for func_name in functions_to_convert:
            if func_name in resources:
                func_def = resources[func_name]
                
                # Update environment variables for DynamoDB tracking
                env_vars = func_def.get('Properties', {}).get('Environment', {}).get('Variables', {})
                
                # Replace APPSYNC_API_URL with DynamoDB tracking variables
                if 'APPSYNC_API_URL' in env_vars:
                    del env_vars['APPSYNC_API_URL']
                    env_vars['DOCUMENT_TRACKING_MODE'] = 'dynamodb'
                    env_vars['TRACKING_TABLE'] = {'Ref': 'TrackingTable'}
                    self.logger.debug(f"Converted {func_name} from AppSync to DynamoDB tracking mode")
                
                # Remove AppSync policies and ensure DynamoDB policies are present
                policies = func_def.get('Properties', {}).get('Policies', [])
                
                # Add DynamoDB CRUD policy if not present
                dynamodb_policy_exists = False
                for policy in policies:
                    if isinstance(policy, dict) and 'DynamoDBCrudPolicy' in policy:
                        dynamodb_policy_exists = True
                        break
                
                if not dynamodb_policy_exists:
                    # Add DynamoDB CRUD policy for TrackingTable
                    policies.append({
                        'DynamoDBCrudPolicy': {
                            'TableName': {'Ref': 'TrackingTable'}
                        }
                    })
                    self.logger.debug(f"Added DynamoDB CRUD permissions for {func_name}")
                
                # Clean AppSync policies
                for policy in policies:
                    if isinstance(policy, dict) and 'Statement' in policy:
                        statements = policy['Statement']
                        if isinstance(statements, list):
                            # Remove AppSync permissions
                            policy['Statement'] = [
                                stmt for stmt in statements 
                                if not (isinstance(stmt, dict) and 
                                       isinstance(stmt.get('Action'), list) and 
                                       any('appsync:GraphQL' in str(action) for action in stmt.get('Action', [])))
                            ]
                            if len(policy['Statement']) != len(statements):
                                self.logger.debug(f"Removed AppSync permissions from {func_name}")
        
        # Clean nested stack parameters comprehensively (all patterns need AppSync params removed)
        pattern_stacks = ['PATTERN1STACK', 'PATTERN2STACK', 'PATTERN3STACK']
        for stack_name in pattern_stacks:
            if stack_name in resources:
                stack_params = resources[stack_name].get('Properties', {}).get('Parameters', {})
                
                # Replace HITL parameters with hardcoded values
                if 'EnableHITL' in stack_params:
                    stack_params['EnableHITL'] = 'false'
                    self.logger.debug(f"Hardcoded EnableHITL to false in {stack_name}")
                
                # Replace HITL portal URL with empty string
                if 'SageMakerA2IReviewPortalURL' in stack_params:
                    stack_params['SageMakerA2IReviewPortalURL'] = '""'
                    self.logger.debug(f"Hardcoded SageMakerA2IReviewPortalURL to empty in {stack_name}")
                
                # Remove AppSync parameters entirely for GovCloud headless deployment
                if 'AppSyncApiUrl' in stack_params:
                    del stack_params['AppSyncApiUrl']
                    self.logger.debug(f"Removed AppSyncApiUrl parameter from {stack_name}")
                    
                if 'AppSyncApiArn' in stack_params:
                    del stack_params['AppSyncApiArn']
                    self.logger.debug(f"Removed AppSyncApiArn parameter from {stack_name}")
                    
                # Remove dependencies on GraphQLApi
                stack_deps = resources[stack_name].get('DependsOn', [])
                if isinstance(stack_deps, list) and 'GraphQLApi' in stack_deps:
                    resources[stack_name]['DependsOn'] = [dep for dep in stack_deps if dep != 'GraphQLApi']
                    self.logger.debug(f"Removed GraphQLApi dependency from {stack_name}")
                elif stack_deps == 'GraphQLApi':
                    del resources[stack_name]['DependsOn']
                    self.logger.debug(f"Removed GraphQLApi dependency from {stack_name}")
        
        # Fix ShouldUseDocumentKnowledgeBase condition references (permanent fix)
        # Convert to string for pattern matching and replacement
        template_str = yaml.dump(template, default_flow_style=False)
        
        if 'ShouldUseDocumentKnowledgeBase' in template_str:
            # Replace the conditional reference with a hardcoded false value
            template_str = re.sub(
                r'ShouldUseDocumentKnowledgeBase:\s*\n\s*Fn::If:\s*\n\s*-\s*ShouldUseDocumentKnowledgeBase\s*\n\s*-\s*true\s*\n\s*-\s*false',
                'ShouldUseDocumentKnowledgeBase: false',
                template_str,
                flags=re.MULTILINE
            )
            template = yaml.safe_load(template_str)
            self.logger.warning("⚠️  Fixed ShouldUseDocumentKnowledgeBase condition reference")
            self.logger.warning("   Note: Knowledge Base functionality disabled for GovCloud compatibility")
        
        # Clean up outputs that reference removed resources
        outputs = template.get('Outputs', {})
        outputs_to_clean = []
        
        for output_name, output_def in outputs.items():
            if isinstance(output_def, dict):
                output_value = output_def.get('Value', {})
                
                # Remove outputs that reference analytics table (removed)
                if (isinstance(output_value, dict) and 
                    output_value.get('Ref') == 'AgentTable'):
                    outputs_to_clean.append(output_name)
                elif (isinstance(output_value, dict) and 
                      'AgentTable' in str(output_value)):
                    outputs_to_clean.append(output_name)
                # Remove outputs that reference WebUIBucket (removed)  
                elif (isinstance(output_value, dict) and
                      output_value.get('Ref') == 'WebUIBucket'):
                    outputs_to_clean.append(output_name)
        
        for output_name in outputs_to_clean:
            if output_name in outputs:
                del outputs[output_name]
                self.logger.debug(f"Removed output {output_name} (references removed resource)")
        
        return template

    def clean_parameter_groups(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Clean parameter groups in Metadata to remove references to deleted parameters"""
        metadata = template.get('Metadata', {})
        interface = metadata.get('AWS::CloudFormation::Interface', {})
        parameter_groups = interface.get('ParameterGroups', [])
        
        if not parameter_groups:
            return template
        
        self.logger.debug("Cleaning parameter groups")
        
        # Remove UI-related parameter groups and clean remaining groups
        cleaned_groups = []
        ui_group_names = {
            'User Authentication',
            'Security Configuration', 
            'Document Knowledge Base',
            'Agentic Analysis',
            'HITL (A2I) Configuration'
        }
        
        for group in parameter_groups:
            group_label = group.get('Label', {}).get('default', '')
            
            # Skip UI-related groups entirely
            if group_label in ui_group_names:
                self.logger.debug(f"Removing parameter group: {group_label}")
                continue
            
            # Clean parameters from remaining groups
            original_params = group.get('Parameters', [])
            cleaned_params = [p for p in original_params if p not in self.ui_parameters]
            
            if cleaned_params:  # Only keep groups that still have parameters
                group['Parameters'] = cleaned_params
                cleaned_groups.append(group)
                if len(cleaned_params) != len(original_params):
                    self.logger.debug(f"Cleaned {len(original_params) - len(cleaned_params)} params from group: {group_label}")
            else:
                self.logger.debug(f"Removing empty parameter group: {group_label}")
        
        interface['ParameterGroups'] = cleaned_groups
        
        # Clean parameter labels
        parameter_labels = interface.get('ParameterLabels', {})
        for param_name in list(parameter_labels.keys()):
            if param_name in self.ui_parameters:
                del parameter_labels[param_name]
        
        return template

    def update_description(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Update template description to indicate GovCloud version"""
        current_description = template.get('Description', '')
        
        if 'GovCloud' not in current_description:
            template['Description'] = current_description + ' (GovCloud Compatible)'
            self.logger.debug("Updated template description for GovCloud")
        
        return template

    def validate_template_basic(self, template: Dict[str, Any]) -> bool:
        """Perform basic template validation"""
        self.logger.info("Validating generated template")
        
        issues = []
        
        # Check required sections exist
        required_sections = ['AWSTemplateFormatVersion', 'Resources']
        for section in required_sections:
            if section not in template:
                issues.append(f"Missing required section: {section}")
        
        # Check that core resources are still present for GovCloud headless deployment
        resources = template.get('Resources', {})
        core_resources = {
            'InputBucket',
            'OutputBucket', 
            'WorkingBucket',
            'TrackingTable',
            'ConfigurationTable',
            'CustomerManagedEncryptionKey',
        }
        
        missing_core = core_resources - set(resources.keys())
        if missing_core:
            issues.append(f"Missing core resources: {', '.join(missing_core)}")
        
        # Check that pattern nested stacks are still present
        pattern_stacks = {'PATTERN1STACK', 'PATTERN2STACK', 'PATTERN3STACK'}
        present_patterns = pattern_stacks & set(resources.keys())
        if not present_patterns:
            issues.append("No pattern stacks found - at least one pattern should be present")
        
        if issues:
            self.logger.error("Basic template validation failed:")
            for issue in issues:
                self.logger.error(f"  - {issue}")
            return False
        
        self.logger.info("✅ Basic template validation passed")
        return True

    def generate_govcloud_template(self, input_file: str, output_file: str) -> bool:
        """Main method to generate GovCloud template"""
        try:
            self.logger.info("🏛️  Starting GovCloud template generation")
            
            # Load template
            template = self.load_template(input_file)
            
            # Apply transformations
            template = self.remove_resources(template)
            template = self.remove_parameters(template)
            template = self.remove_outputs(template)
            template = self.remove_conditions(template)
            template = self.remove_rules(template)
            template = self.clean_template_for_headless_deployment(template)
            template = self.clean_parameter_groups(template)
            template = self.update_arn_partitions(template)
            template = self.update_description(template)
            
            # Save template and perform basic validation
            self.save_template(template, output_file)
            
            # Perform basic validation
            if not self.validate_template_basic(template):
                return False
            
            self.logger.info("🎉 GovCloud template generation completed successfully!")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to generate GovCloud template: {e}")
            if self.verbose:
                import traceback
                self.logger.debug(traceback.format_exc())
            return False

    def print_deployment_summary(self, bucket_name: str, prefix: str, region: str, govcloud_url: str = ""):
        """Print deployment outputs in the same format as the original publish script"""
        from urllib.parse import quote
        
        # Display deployment information first (matching original format)
        print(f"\nDeployment Information:")
        print(f"  • Region: {region}")
        print(f"  • Bucket: {bucket_name}")
        print(f"  • Template Path: {prefix}/idp-main.yaml")
        print(f"  • GovCloud Template Path: {prefix}/idp-govcloud.yaml")
        
        print(f"\nDeployment Outputs")
                     
        # GovCloud template outputs (if available)
        if govcloud_url:
            print(f"\n🏛️  GovCloud Template:")
            
            # 1-Click Launch for GovCloud template
            encoded_govcloud_url = quote(govcloud_url, safe=":/?#[]@!$&'()*+,;=")
            if "us-gov" in region:
                domain="aws.amazonaws-us-gov.com"
            else:
                domain="aws.amazon.com"
            govcloud_launch_url = f"https://{region}.console.{domain}/cloudformation/home?region={region}#/stacks/create/review?templateURL={encoded_govcloud_url}&stackName=IDP-GovCloud"
            print(f"1-Click Launch (creates new stack):")
            print(f"  {govcloud_launch_url}")
            print(f"Template URL (for updating existing stack):")
            print(f"  {govcloud_url}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Complete GovCloud template generation and publication script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script orchestrates the complete GovCloud-compatible build process:

1. Builds all Lambda functions and uploads to S3 (calls publish.py)
2. Generates GovCloud-compatible template 
3. Uploads GovCloud template to S3
4. Provides deployment URLs and instructions

Examples:
    # Standard deployment
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1

    # GovCloud deployment  
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-gov-west-1

    # With verbose output and concurrency control
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1 --verbose --max-workers 4

    # With clean build (forces full rebuild)
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1 --clean-build

    # With clean build (forces full rebuild)
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1 --clean-build

    # Public artifacts
    python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1 public
        """
    )
    
    # Accept all the same arguments as publish.py
    parser.add_argument('cfn_bucket_basename', help='Base name for the CloudFormation artifacts bucket')
    parser.add_argument('cfn_prefix', help='S3 prefix for artifacts')
    parser.add_argument('region', help='AWS region for deployment')
    parser.add_argument('public', nargs='?', help='Make artifacts publicly readable')
    parser.add_argument('--max-workers', type=int, help='Maximum number of concurrent workers')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--skip-build', action='store_true', help='Skip the build step and only generate/upload GovCloud template')
    parser.add_argument('--clean-build', action='store_true', help='Delete all .checksum files to force full rebuild')
    
    # Parse known args to handle the flexible argument structure
    args, unknown = parser.parse_known_args()
    
    # Reconstruct arguments for publish.py
    publish_args = [args.cfn_bucket_basename, args.cfn_prefix, args.region]
    
    if args.public:
        publish_args.append('public')
    
    if args.max_workers:
        publish_args.extend(['--max-workers', str(args.max_workers)])
    
    if args.verbose:
        publish_args.append('--verbose')
    
    if args.clean_build:
        publish_args.append('--clean-build')
    
    # Always skip validation in publish.py since we validate the GovCloud template separately
    publish_args.append('--no-validate')
    
    # Add any unknown arguments
    publish_args.extend(unknown)
    
    # Calculate bucket name
    bucket_name = f"{args.cfn_bucket_basename}-{args.region}"
    
    try:
        generator = GovCloudTemplateGenerator(verbose=args.verbose)
        
        print("🚀 Starting complete GovCloud publication process")
        print(f"Target region: {args.region}")
        
        # Step 1: Run standard publish script (unless skipped)
        if not args.skip_build:
            print("\n" + "=" * 60)
            print("STEP 1: Building and Publishing Artifacts")
            print("=" * 60)
            if not generator.run_publish_script(publish_args):
                sys.exit(1)
        else:
            print("\n⏩ Skipping build step (--skip-build specified)")
        
        # Step 2: Generate GovCloud template
        print("\n" + "=" * 60)
        print("STEP 2: Generating GovCloud Template")
        print("=" * 60)
        
        input_template = '.aws-sam/idp-main.yaml'
        output_template = '.aws-sam/idp-govcloud.yaml'
        
        if not generator.generate_govcloud_template(input_template, output_template):
            print("❌ GovCloud template generation failed")
            sys.exit(1)
        
        # Step 3: Upload GovCloud template to S3
        print("\n" + "=" * 60)  
        print("STEP 3: Uploading GovCloud Template to S3")
        print("=" * 60)
        
        govcloud_url = generator.upload_govcloud_template_to_s3(
            output_template, bucket_name, args.cfn_prefix, args.region
        )
        
        if not govcloud_url:
            print("⚠️  Failed to upload GovCloud template to S3")
        else:
            # Step 3.5: Validate uploaded GovCloud template using CloudFormation API
            print("🔍 Validating uploaded GovCloud template with CloudFormation API")
            if not generator.validate_template_via_s3(govcloud_url, args.region):
                print("❌ GovCloud template validation failed - template may have issues")
                # Don't exit - let user decide based on the error details shown
            else:
                print("✅ GovCloud template CloudFormation validation passed")
        
        # Step 4: Print deployment summary with URLs
        print("\n" + "=" * 60)
        print("STEP 4: Deployment Summary")
        print("=" * 60)
        
       
        generator.print_deployment_summary(bucket_name, args.cfn_prefix, args.region, govcloud_url)
        
        print("✅ Complete GovCloud publication process finished successfully!")
        print("   Both standard and GovCloud templates are ready for deployment.")
        
    except KeyboardInterrupt:
        print("\n❌ Publication process cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Publication process failed: {e}")
        if args.verbose:
            import traceback
            print(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
