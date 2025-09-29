# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import subprocess
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from loguru import logger


class InstallService():
    def __init__(self, 
                 account_id: str, 
                 cfn_prefix: Optional[str] = "idp-dev", 
                 cwd: Optional[str] = None, 
                 debug: bool = False):
        """
        Initialize the InstallService.
        
        Args:
            account_id: AWS account ID
            unique_id: Optional unique identifier (defaults to git SHA)
            cwd: Optional working directory for all operations
            env: Environment to use (default: desktop-linux)
        """
        self.account_id = account_id
        self.cwd = cwd
        self.cfn_prefix = cfn_prefix 
        self.cfn_bucket_basename = f"{self.cfn_prefix}-{self.account_id}"
        self.region = os.environ.get('AWS_REGION', 'us-east-1')
        self.s3_bucket = f"{self.cfn_prefix}-{self.account_id}-{self.region}"
        self.stack_name = f"{self.cfn_prefix}"

        

        logger.debug(f"account_id: {account_id}\ncfn_prefix: {cfn_prefix}\ncwd: {cwd}\ndebug: {debug}\nregion:{self.region}")

        if debug:
            # Enable SAM debug mode
            os.environ["SAM_DEBUG"] = "1"
            os.environ["AWS_SAM_DEBUG"] = "1"
        
        # Log the absolute working directory
        if self.cwd:
            self.abs_cwd = os.path.abspath(self.cwd)
            logger.debug(f"Using working directory: {self.abs_cwd}")
        else:
            self.abs_cwd = os.path.abspath(os.getcwd())
            logger.debug(f"Using current directory: {self.abs_cwd}")

    def git_sha(self):
        # Return Git SHA 7 chars from command line
        try:
            result = subprocess.run(['git', 'rev-parse', 'HEAD'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE,
                                   text=True,
                                   check=True,
                                   cwd=self.cwd)  # Use the specified working directory
            return result.stdout.strip()[:7]
        except (subprocess.SubprocessError, FileNotFoundError):
            # If git command fails or git is not installed
            return "local" + str(int(time.time()))[-7:]  # Fallback to timestamp-based ID

    def check_docker_availability(self):
        """Check if Docker is available and running"""
        try:
            result = subprocess.run(
                ['docker', 'info'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("Docker is available and running")
                logger.debug(f"Docker info: {result.stdout}")
                return True
            else:
                logger.warning(f"Docker is not running properly. Error: {result.stderr}")
                return False
                
        except FileNotFoundError:
            logger.error("Docker command not found. Docker may not be installed")
            return False

    def publish(self):
        # Add logic to run this command:
        # bash ./publish.sh <cfn_bucket_basename> <cfn_prefix> <region e.g. us-east-1>

        # Check Docker availability
        docker_available = self.check_docker_availability()
        if not docker_available:
            logger.warning("Docker is not available. Using --use-container=false for SAM build.")
            # Set environment variable for publish.sh to use
            os.environ["SAM_BUILD_CONTAINER"] = "false"
        
        try:
            # Log the absolute working directory again for clarity
            working_dir = self.cwd if self.cwd else os.getcwd()
            abs_working_dir = os.path.abspath(working_dir)
            logger.debug(f"Publishing from directory: {abs_working_dir}")
            logger.debug(f"Running publish command: bash ./publish.sh {self.cfn_bucket_basename} {self.cfn_prefix} {self.region}")
            
            # Set up environment variables for the subprocess
            env_vars = os.environ.copy()

            process = subprocess.run(
                ['bash','./publish.sh', self.cfn_bucket_basename, self.cfn_prefix, self.region],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,  # Use the specified working directory
                env=env_vars   # Pass environment variables
            )
            
            # Log the command output
            logger.debug(f"Publish command stdout: {process.stdout}")
            if process.stderr:
                logger.debug(f"Publish command stderr: {process.stderr}")
                
            logger.info(f"Successfully published to {self.cfn_bucket_basename} in {self.region}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to publish: {e}")
            if e.stdout:
                logger.debug(f"Command stdout: {e.stdout}")
            if e.stderr:
                logger.debug(f"Command stderr: {e.stderr}")
            return False
        

    def deploy_service_role(self):
        """
        Deploy the CloudFormation service role stack.
        
        Returns:
            str: The ARN of the service role, or None if deployment failed
        """
        service_role_stack_name = f"{self.cfn_prefix}-cloudformation-service-role"
        service_role_template = 'iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml'
        
        try:
            # Verify template file exists
            template_path = os.path.join(self.abs_cwd, service_role_template)
            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Service role template not found: {template_path}")

            logger.info(f"Deploying CloudFormation service role stack: {service_role_stack_name}")

            # Deploy the service role stack
            cmd = [
                'aws', 'cloudformation', 'deploy',
                '--region', self.region,
                '--template-file', service_role_template,
                '--capabilities', 'CAPABILITY_NAMED_IAM',
                '--stack-name', service_role_stack_name
            ]

            logger.debug(f"Running service role deploy command: {' '.join(cmd)}")

            process = subprocess.run(
                cmd,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd
            )

            logger.debug(f"Service role deploy stdout: {process.stdout}")
            if process.stderr:
                logger.debug(f"Service role deploy stderr: {process.stderr}")

            # Get the service role ARN from the deployed stack
            service_role_arn = self._get_service_role_arn_from_stack(service_role_stack_name)
            if service_role_arn:
                logger.info(f"Successfully deployed service role: {service_role_arn}")
                return service_role_arn
            else:
                logger.error("Failed to retrieve service role ARN after deployment")
                return None

        except FileNotFoundError as e:
            logger.error(f"Service role template error: {e}")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to deploy service role: {e}")
            if e.stdout:
                logger.debug(f"Command stdout: {e.stdout}")
            if e.stderr:
                logger.debug(f"Command stderr: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during service role deployment: {e}")
            return None

    def _get_service_role_arn_from_stack(self, stack_name):
        """
        Get service role ARN from a specific stack.
        
        Returns:
            str: The ARN of the service role, or None if not found
        """
        try:
            describe_cmd = [
                'aws', 'cloudformation', 'describe-stacks',
                '--region', self.region,
                '--stack-name', stack_name,
                '--query', 'Stacks[0].Outputs[?OutputKey==`ServiceRoleArn`].OutputValue',
                '--output', 'text'
            ]
            
            process = subprocess.run(
                describe_cmd,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            service_role_arn = process.stdout.strip()
            if service_role_arn and service_role_arn != "None":
                return service_role_arn
            else:
                return None

        except subprocess.CalledProcessError:
            return None
        except Exception as e:
            logger.error(f"Error getting service role ARN from stack {stack_name}: {e}")
            return None

    def create_permission_boundary_policy(self):
        """Create an 'allow everything' permission boundary policy"""
        
        policy_name = f"{self.cfn_prefix}-IDPPermissionBoundary"
        iam = boto3.client('iam')
        
        try:
            policy_document = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "*",
                        "Resource": "*"
                    }
                ]
            }
            
            response = iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(policy_document),
                Description="Permission boundary for IDP deployment - allows all actions"
            )
            
            policy_arn = response['Policy']['Arn']
            logger.info(f"Created permission boundary policy: {policy_arn}")
            return policy_arn
            
        except ClientError as create_error:
            logger.error(f"Error creating permission boundary policy: {create_error}")
            return None

    def validate_permission_boundary(self, stack_name, boundary_arn):
        """Validate that all IAM roles in the stack and nested stacks have the permission boundary"""
        cfn = boto3.client('cloudformation')
        iam = boto3.client('iam')
        
        def get_all_stacks(stack_name):
            """Recursively get all nested stacks"""
            stacks = [stack_name]
            try:
                paginator = cfn.get_paginator('list_stack_resources')
                page_iterator = paginator.paginate(StackName=stack_name)
                
                for page in page_iterator:
                    for resource in page['StackResourceSummaries']:
                        if resource['ResourceType'] == 'AWS::CloudFormation::Stack':
                            nested_stack_name = resource['PhysicalResourceId']
                            stacks.extend(get_all_stacks(nested_stack_name))
            except ClientError:
                pass
            return stacks
        
        try:
            # Get all stacks (main + nested)
            all_stacks = get_all_stacks(stack_name)
            logger.info(f"Checking {len(all_stacks)} stacks for IAM roles")
            
            roles = []
            for stack in all_stacks:
                try:
                    paginator = cfn.get_paginator('list_stack_resources')
                    page_iterator = paginator.paginate(StackName=stack)
                    
                    for page in page_iterator:
                        for resource in page['StackResourceSummaries']:
                            if resource['ResourceType'] == 'AWS::IAM::Role':
                                role_name = resource['PhysicalResourceId']
                                roles.append(role_name)
                except ClientError:
                    continue
            
            if not roles:
                logger.info("No IAM roles found in any stack")
                return True
            
            logger.info(f"Found {len(roles)} IAM roles across all stacks")
            failed_roles = []
            
            # Check each role
            for role_name in roles:
                try:
                    response = iam.get_role(RoleName=role_name)
                    role = response['Role']
                    
                    if 'PermissionsBoundary' in role:
                        actual_boundary = role['PermissionsBoundary']['PermissionsBoundaryArn']
                        if actual_boundary == boundary_arn:
                            logger.debug(f"✅ {role_name}: Has correct permission boundary")
                        else:
                            logger.error(f"❌ {role_name}: Has wrong permission boundary: {actual_boundary}")
                            failed_roles.append(role_name)
                    else:
                        logger.error(f"❌ {role_name}: Missing permission boundary")
                        failed_roles.append(role_name)
                        
                except ClientError as e:
                    logger.error(f"Error checking role {role_name}: {e}")
                    failed_roles.append(role_name)
            
            if failed_roles:
                logger.error(f"FAILED: {len(failed_roles)} roles do not have the correct permission boundary")
                return False
            else:
                logger.info(f"SUCCESS: All {len(roles)} roles have the correct permission boundary")
                return True
                
        except ClientError as e:
            logger.error(f"Error validating permission boundary: {e}")
            return False

    def install(self, admin_email: str, idp_pattern: str):
        """
        Install the IDP stack using CloudFormation with service role and permission boundary.
        
        Args:
            admin_email: Email address for the admin user
            idp_pattern: IDP pattern to deploy
        """
        template_file = '.aws-sam/idp-main.yaml'
        s3_prefix = f"{self.cfn_prefix}/0.2.2"  # TODO: Make version configurable

        try:
            # Step 1: Create permission boundary policy
            logger.info("Step 1: Creating permission boundary policy...")
            permission_boundary_arn = self.create_permission_boundary_policy()
            if not permission_boundary_arn:
                logger.error("Failed to create permission boundary policy. Aborting deployment.")
                return False

            # Step 2: Deploy CloudFormation service role
            logger.info("Step 2: Deploying CloudFormation service role...")
            service_role_arn = self.deploy_service_role()
            if not service_role_arn:
                logger.error("Failed to deploy service role. Aborting IDP deployment.")
                return False

            # Step 3: Deploy IDP stack using the service role and permission boundary
            logger.info("Step 3: Deploying IDP stack using service role and permission boundary...")
            
            # Verify template file exists
            template_path = os.path.join(self.abs_cwd, template_file)
            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Template file not found: {template_path}")

            logger.info(f"Using permission boundary ARN: {permission_boundary_arn}")
            
            cmd = [
                'aws', 'cloudformation', 'deploy',
                '--region', self.region,
                '--template-file', template_file,
                '--s3-bucket', self.s3_bucket,
                '--s3-prefix', s3_prefix,
                '--capabilities', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND',
                '--role-arn', service_role_arn,  # Use the service role
                '--parameter-overrides',
                "DocumentKnowledgeBase=DISABLED",
                f"IDPPattern={idp_pattern}",
                f"AdminEmail={admin_email}",
                f"PermissionsBoundaryArn={permission_boundary_arn}",
                '--stack-name', self.stack_name
            ]

            logger.debug(f"Running CloudFormation deploy command: {' '.join(cmd)}")

            # Set up environment variables for the subprocess
            env_vars = os.environ.copy()

            # Run the deploy command
            process = subprocess.run(
                cmd,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=env_vars
            )

            # Log the command output
            logger.debug(f"CloudFormation deploy stdout: {process.stdout}")
            if process.stderr:
                logger.debug(f"CloudFormation deploy stderr: {process.stderr}")

            logger.info(f"Successfully deployed stack {self.stack_name} in {self.region}")
            
            # Step 4: Validate permission boundary on all roles
            logger.info("Step 4: Validating permission boundary on all IAM roles...")
            if not self.validate_permission_boundary(self.stack_name, permission_boundary_arn):
                logger.error("Permission boundary validation failed!")
                logger.error("Deployment failed due to security policy violations.")
                return False
            
            logger.info("Deployment and validation completed successfully!")
            return True

        except FileNotFoundError as e:
            logger.error(f"Template file error: {e}")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to deploy stack: {e}")
            if e.stdout:
                logger.debug(f"Command stdout: {e.stdout}")
            if e.stderr:
                logger.debug(f"Command stderr: {e.stderr}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during stack deployment: {e}")
            return False