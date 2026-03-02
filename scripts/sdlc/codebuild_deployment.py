#!/usr/bin/env python3
"""
CodeBuild Deployment Script

Handles IDP stack deployment and testing in AWS CodeBuild environment.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from textwrap import dedent

import boto3

# Configuration for patterns to deploy
DEPLOY_PATTERNS = [
    {
        "name": "Pattern 1 - BDA",
        "id": "pattern-1",
        "suffix": "p1",
        "sample_file": "lending_package.pdf",
        "verify_string": "ANYTOWN, USA 12345",
        "result_location": "pages/0/result.json",
        "content_path": "pages.0.representation.markdown",
    },
    {
        "name": "Pattern 2 - OCR + Bedrock",
        "id": "pattern-2",
        "suffix": "p2",
        "sample_file": "lending_package.pdf",
        "verify_string": "ANYTOWN, USA 12345",
        "result_location": "pages/1/result.json",
        "content_path": "text",
    },
    # {"name": "Pattern 3 - UDOP + Bedrock", "id": "pattern-3", "suffix": "p3", "sample_file": "rvl_cdip_package.pdf", "verify_string": "WESTERN DARK FIRED TOBACCO GROWERS", "result_location": "pages/1/result.json", "content_path": "text"},
]


def run_command(cmd, check=True):
    """Run shell command and return result"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True) # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - Reviewed: command input is controlled and sanitized
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if check and result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}")
        raise Exception(f"Command failed: {cmd}")
    return result


def get_env_var(name, default=None):
    """Get environment variable with optional default"""
    value = os.environ.get(name, default)
    if value is None:
        raise Exception(f"Environment variable {name} is required")
    return value


def generate_stack_prefix():
    """Generate unique stack prefix with timestamp including seconds"""
    timestamp = datetime.now().strftime("%m%d-%H%M%S")  # Format: MMDD-HHMMSS
    return f"idp-{timestamp}"


def publish_templates():
    """Run publish.py to build and upload templates to S3"""
    print("📦 Publishing templates to S3...")

    # Get AWS account ID and region
    account_id = get_env_var("IDP_ACCOUNT_ID", "020432867916")
    region = get_env_var("AWS_DEFAULT_REGION", "us-east-1")

    # Generate bucket name and prefix
    bucket_basename = f"genaiic-sdlc-sourcecode-{account_id}"
    prefix = f"codebuild-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Run publish.sh
    cmd = f"./publish.sh {bucket_basename} {prefix} {region}"
    result = run_command(cmd)

    # Extract template URL from output - match S3 URLs only
    template_url_pattern = r"https://s3\..*?idp-main\.yaml"
    
    # Remove line breaks that might split the URL in terminal output
    clean_stdout = result.stdout.replace('\n', '').replace('\r', '')
    template_url_match = re.search(template_url_pattern, clean_stdout)

    if template_url_match:
        template_url = template_url_match.group(0)
        print(f"✅ Template published: {template_url}")
        return template_url
    else:
        print("❌ Failed to extract template URL from publish output")
        raise Exception("Failed to extract template URL from publish output")


def create_iam_resources(stack_name):
    """Create IAM role and permission boundary using CloudFormation template"""
    print(f"[{stack_name}] Creating IAM resources...")
    
    try:
        cf_client = boto3.client('cloudformation')
        iam_stack_name = f"{stack_name}-iam"
        
        # Deploy IAM CloudFormation stack
        with open('iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml', 'r') as f:
            template_body = f.read()
        
        try:
            cf_client.create_stack(
                StackName=iam_stack_name,
                TemplateBody=template_body,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            
            # Wait for stack creation to complete
            waiter = cf_client.get_waiter('stack_create_complete')
            waiter.wait(StackName=iam_stack_name, WaiterConfig={'MaxAttempts': 30, 'Delay': 10})
            
            print(f"[{stack_name}] ✅ Created IAM stack: {iam_stack_name}")
            
        except cf_client.exceptions.AlreadyExistsException:
            print(f"[{stack_name}] ℹ️ IAM stack already exists: {iam_stack_name}")
        
        # Get outputs from the stack
        response = cf_client.describe_stacks(StackName=iam_stack_name)
        outputs = response['Stacks'][0].get('Outputs', [])
        
        role_arn = None
        for output in outputs:
            if output['OutputKey'] == 'ServiceRoleArn':
                role_arn = output['OutputValue']
                break
        
        if not role_arn:
            raise Exception("Could not find ServiceRoleArn in stack outputs")
        
        # Create permission boundary policy
        iam_client = boto3.client('iam')
        boundary_name = f"{stack_name}-PermissionsBoundary"
        boundary_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "*",
                    "Resource": "*"
                }
            ]
        }
        
        try:
            iam_client.create_policy(
                PolicyName=boundary_name,
                PolicyDocument=json.dumps(boundary_policy),
                Description=f"Permissions boundary for {stack_name} IDP deployment"
            )
            print(f"[{stack_name}] ✅ Created permissions boundary: {boundary_name}")
        except iam_client.exceptions.EntityAlreadyExistsException:
            print(f"[{stack_name}] ℹ️ Permissions boundary already exists: {boundary_name}")
        
        # Get account ID for boundary ARN
        sts_client = boto3.client('sts')
        account_id = sts_client.get_caller_identity()['Account']
        boundary_arn = f"arn:aws:iam::{account_id}:policy/{boundary_name}"
        
        return role_arn, boundary_arn
        
    except Exception as e:
        print(f"[{stack_name}] ❌ Failed to create IAM resources: {e}")
        return None, None


def cleanup_iam_resources(stack_name):
    """Clean up IAM CloudFormation stack"""
    print(f"[{stack_name}] Cleaning up IAM stack...")
    
    try:
        # Clean up IAM CloudFormation stack
        cf_client = boto3.client('cloudformation')
        iam_stack_name = f"{stack_name}-iam"
        try:
            cf_client.delete_stack(StackName=iam_stack_name)
            
            # Wait for stack deletion to complete
            waiter = cf_client.get_waiter('stack_delete_complete')
            waiter.wait(StackName=iam_stack_name, WaiterConfig={'MaxAttempts': 30, 'Delay': 10})
            
            print(f"[{stack_name}] ✅ Deleted IAM stack: {iam_stack_name}")
        except cf_client.exceptions.ClientError as e:
            if 'does not exist' in str(e):
                print(f"[{stack_name}] ℹ️ IAM stack not found: {iam_stack_name}")
            else:
                print(f"[{stack_name}] ⚠️ Failed to delete IAM stack: {e}")
            
    except Exception as e:
        print(f"[{stack_name}] ❌ Failed to cleanup IAM stack: {e}")


def deploy_and_test_pattern(stack_prefix, pattern_config, admin_email, template_url, role_arn=None, permissions_boundary_arn=None):
    """Deploy and test a specific IDP pattern"""
    pattern_name = pattern_config["name"]
    pattern_id = pattern_config["id"]
    pattern_suffix = pattern_config["suffix"]
    sample_file = pattern_config["sample_file"]
    verify_string = pattern_config["verify_string"]
    result_location = pattern_config["result_location"]
    content_path = pattern_config["content_path"]

    stack_name = f"{stack_prefix}-{pattern_suffix}"
    batch_id = f"test-{pattern_suffix}"

    print(f"[{pattern_name}] Starting deployment: {stack_name}")

    try:
        # Step 0: Create IAM resources
        print(f"[{pattern_name}] Step 0: Creating IAM resources...")
        role_arn, permissions_boundary_arn = create_iam_resources(stack_name)
        
        if not role_arn or not permissions_boundary_arn:
            raise Exception("Failed to create required IAM resources")
        
        # Step 1: Deploy using template URL
        print(f"[{pattern_name}] Step 1: Deploying stack...")
        cmd = f"idp-cli deploy --stack-name {stack_name} --template-url {template_url} --pattern {pattern_id} --admin-email {admin_email} --wait"
        
        # Add role-arn and permissions boundary
        cmd += f" --role-arn {role_arn}"
        cmd += f" --parameters PermissionsBoundaryArn={permissions_boundary_arn}"
        
        # Add role-arn if provided
        if role_arn:
            cmd += f" --role-arn {role_arn}"
        
        # Add permissions boundary if provided
        if permissions_boundary_arn:
            cmd += f" --parameters PermissionsBoundaryArn={permissions_boundary_arn}"
        
        run_command(cmd)
        print(f"[{pattern_name}] ✅ Deployment completed")

        # Step 2: Test stack status
        print(f"[{pattern_name}] Step 2: Verifying stack status...")
        cmd = f"aws cloudformation describe-stacks --stack-name {stack_name} --query 'Stacks[0].StackStatus' --output text"
        result = run_command(cmd)

        if "COMPLETE" not in result.stdout:
            print(f"[{pattern_name}] ❌ Stack status: {result.stdout.strip()}")
            return {
                "stack_name": stack_name,
                "pattern_name": pattern_name,
                "success": False,
                "error": f"Stack deployment failed with status: {result.stdout.strip()}"
            }

        print(f"[{pattern_name}] ✅ Stack is healthy")

        # Step 3: Run inference test
        print(f"[{pattern_name}] Step 3: Running inference test with {sample_file}...")
        cmd = f"idp-cli run-inference --stack-name {stack_name} --dir samples --file-pattern {sample_file} --batch-id {batch_id} --monitor"
        run_command(cmd)
        print(f"[{pattern_name}] ✅ Inference completed")

        # Wait for results to propagate to S3
        print(f"[{pattern_name}] Waiting 20 seconds for results to propagate...")
        import time
        time.sleep(20)

        # Step 4: Download and verify results
        print(f"[{pattern_name}] Step 4: Downloading results...")
        results_dir = f"/tmp/results-{pattern_suffix}"

        cmd = f"idp-cli download-results --stack-name {stack_name} --batch-id {batch_id} --output-dir {results_dir}"
        run_command(cmd)

        # Step 5: Verify result content
        print(f"[{pattern_name}] Step 5: Verifying result content...")
        
        # Wait for results to be fully written
        print(f"[{pattern_name}] Waiting 10 seconds for results to be fully written...")
        import time
        time.sleep(10)

        # Find the result file at the specified location
        cmd = f"find {results_dir} -path '*/pages/1/result.json' -o -path '*/pages/0/result.json' | head -1"
        result = run_command(cmd, check=False)
        result_file = result.stdout.strip()

        if not result_file:
            # Debug: List what files were actually downloaded
            cmd = f"find {results_dir} -name 'result.json' | head -10"
            debug_result = run_command(cmd, check=False)
            print(f"[{pattern_name}] Found result.json files:")
            print(debug_result.stdout)
            
            print(f"[{pattern_name}] ❌ No result file found at pages/0 or pages/1")
            return {
                "stack_name": stack_name,
                "pattern_name": pattern_name,
                "success": False,
                "error": f"No result file found at expected location: {result_location}"
            }

        # Verify the result file contains expected content
        try:
            import json

            with open(result_file, "r") as f:
                result_json = json.load(f)

            # Extract text content using the specified path
            text_content = result_json
            for key in content_path.split("."):
                if key.isdigit():
                    text_content = text_content[int(key)]
                else:
                    text_content = text_content[key]

            # Verify expected string in content
            if verify_string not in text_content:
                print(
                    f"[{pattern_name}] ❌ Text content does not contain expected string: '{verify_string}'"
                )
                print(
                    f"[{pattern_name}] Actual text starts with: '{text_content[:100]}...'"
                )
                return {
                    "stack_name": stack_name,
                    "pattern_name": pattern_name,
                    "success": False,
                    "error": f"Verification failed: Expected string '{verify_string}' not found in result"
                }

            print(
                f"[{pattern_name}] ✅ Found expected verification string: '{verify_string}'"
            )
            
            success_result = {
                "stack_name": stack_name,
                "pattern_name": pattern_name,
                "success": True,
                "verification_string": verify_string
            }

        except Exception as e:
            print(f"[{pattern_name}] ❌ Failed to validate result content: {e}")
            success_result = {
                "stack_name": stack_name,
                "pattern_name": pattern_name,
                "success": False,
                "error": f"Result validation failed: {str(e)}"
            }

    except Exception as e:
        print(f"[{pattern_name}] ❌ Testing failed: {e}")
        success_result = {
            "stack_name": stack_name,
            "pattern_name": pattern_name,
            "success": False,
            "error": f"Deployment/testing failed: {str(e)}"
        }

    return success_result


def get_codebuild_logs():
    """Get CodeBuild logs from CloudWatch"""
    try:
        # Get CodeBuild build ID from environment
        build_id = os.environ.get('CODEBUILD_BUILD_ID', '')
        if not build_id:
            return "CodeBuild logs not available (not running in CodeBuild)"
        
        # Wait for logs to propagate to CloudWatch
        import time
        time.sleep(10)
        
        # Extract log group and stream from build ID
        log_group = f"/aws/codebuild/{build_id.split(':')[0]}"
        log_stream = build_id.split(':')[-1]
        
        # Get logs from CloudWatch
        logs_client = boto3.client('logs')
        response = logs_client.get_log_events(
            logGroupName=log_group,
            logStreamName=log_stream,
            startFromHead=True
        )
        
        # Extract log messages
        log_messages = []
        for event in response.get('events', []):
            log_messages.append(event['message'])
        
        return '\n'.join(log_messages)
        
    except Exception as e:
        return f"Failed to retrieve CodeBuild logs: {str(e)}"


def generate_publish_failure_summary(publish_error):
    """Generate summary for publish/build failures"""
    try:
        bedrock = boto3.client('bedrock-runtime')
        
        prompt = dedent(f"""
        You are a build system analyst. Analyze this publish/build failure and provide specific technical guidance.

        Publish Error: {publish_error}
        
        Build Logs:
        {get_codebuild_logs()}

        ANALYZE THE LOGS FOR ALL ERROR TYPES:
        - Python linting/formatting errors (ruff check failed, code formatting check failed)
        - Python syntax errors (py_compile failures, SyntaxError, IndentationError)
        - UI build failures (npm ci errors, package-lock.json sync issues, missing @esbuild packages)
        - AWS/Infrastructure errors (S3 access denied, CloudFormation validation failed, SAM build/package failures)
        - Missing prerequisites (aws/sam not found, version requirements not met)
        - File system errors (missing files, permission denied, disk space issues)
        - Dependency issues (pip install failures, missing Python packages, Docker build errors)
        - Lambda validation failures (missing idp_common in builds, import test failures)

        Create a summary focused on BUILD/PUBLISH issues with bullet points:

        🔧 BUILD FAILURE ANALYSIS

        📋 Component Status:
        • UI Build: FAILED - npm dependency issues
        • Lambda Build: SUCCESS - All patterns built correctly
        • Template Publish: FAILED - S3 access denied

        🔍 Technical Root Cause:
        • Extract exact error messages from logs (ruff, npm, pip, aws, sam errors)
        • Identify specific missing packages, version conflicts, or permission issues
        • Focus on build-time errors, not deployment errors
        • Check AWS credentials, S3 bucket permissions, and file access issues

        💡 Fix Commands:
        • Provide specific commands based on actual error found
        • For linting: run ruff format . && ruff check --fix .
        • For npm: cd src/ui && rm package-lock.json && npm install
        • For AWS S3: aws s3 ls s3://bucket-name to test access
        • For permissions: chmod +x script.sh or check IAM policies

        Keep each bullet point under 75 characters. Use sub-bullets for details.
        
        IMPORTANT: Respond ONLY with the bullet format above. Do not include any text before or after.
        """)
        
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-5-sonnet-20240620-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        response_body = json.loads(response['body'].read())
        summary = response_body['content'][0]['text']
        
        return summary
        
    except Exception as e:
        return f"⚠️ Failed to generate build failure summary: {e}"


def get_cloudformation_logs(stack_name):
    """Get CloudFormation stack events for error analysis"""
    try:
        cf_client = boto3.client('cloudformation')
        all_failed_events = []
        
        # Get events from main stack
        all_events = []
        next_token = None
        
        while True:
            if next_token:
                response = cf_client.describe_stack_events(
                    StackName=stack_name,
                    NextToken=next_token
                )
            else:
                response = cf_client.describe_stack_events(StackName=stack_name)
            
            events = response.get('StackEvents', [])
            all_events.extend(events)
            
            next_token = response.get('NextToken')
            if not next_token:
                break
        
        # Filter for failed events and extract nested stack ARNs
        nested_stack_arns = []
        for event in all_events:
            status = event.get('ResourceStatus', '')
            if 'FAILED' in status or 'ROLLBACK' in status:
                all_failed_events.append({
                    'stack_name': stack_name,
                    'timestamp': event.get('Timestamp', '').isoformat() if event.get('Timestamp') else '',
                    'resource_type': event.get('ResourceType', ''),
                    'logical_id': event.get('LogicalResourceId', ''),
                    'status': status,
                    'reason': event.get('ResourceStatusReason', 'No reason provided')
                })
                
                # Extract nested stack ARN from CREATE_FAILED events
                if (status == 'CREATE_FAILED' and 
                    event.get('ResourceType') == 'AWS::CloudFormation::Stack' and
                    'Embedded stack arn:aws:cloudformation:' in event.get('ResourceStatusReason', '')):
                    reason = event.get('ResourceStatusReason', '')
                    start = reason.find('arn:aws:cloudformation:')
                    end = reason.find(' was not successfully created')
                    if start != -1 and end != -1:
                        nested_arn = reason[start:end]
                        nested_stack_arns.append(nested_arn)
        
        # Get events from nested stacks
        for nested_arn in nested_stack_arns:
            try:
                nested_events = []
                next_token = None
                
                while True:
                    if next_token:
                        response = cf_client.describe_stack_events(
                            StackName=nested_arn,
                            NextToken=next_token
                        )
                    else:
                        response = cf_client.describe_stack_events(StackName=nested_arn)
                    
                    events = response.get('StackEvents', [])
                    nested_events.extend(events)
                    
                    next_token = response.get('NextToken')
                    if not next_token:
                        break
                
                # Add failed events from nested stack
                for event in nested_events:
                    status = event.get('ResourceStatus', '')
                    if 'FAILED' in status or 'ROLLBACK' in status:
                        all_failed_events.append({
                            'stack_name': nested_arn.split('/')[-2],  # Extract stack name from ARN
                            'timestamp': event.get('Timestamp', '').isoformat() if event.get('Timestamp') else '',
                            'resource_type': event.get('ResourceType', ''),
                            'logical_id': event.get('LogicalResourceId', ''),
                            'status': status,
                            'reason': event.get('ResourceStatusReason', 'No reason provided')
                        })
                        
            except Exception:
                # Skip nested stacks we can't access
                continue
        
        return all_failed_events
        
    except Exception as e:
        return [{'error': f"Failed to retrieve CloudFormation logs: {str(e)}"}]


def generate_deployment_summary(deployment_results, stack_prefix, template_url):
    """Generate deployment summary using Bedrock API with CodeBuild and CloudFormation logs"""
    try:
        # Get CodeBuild logs
        deployment_logs = get_codebuild_logs()
        
        # Initialize Bedrock client
        bedrock = boto3.client('bedrock-runtime')
        
        # Create prompt for Bedrock with structured analysis
        prompt = dedent(f"""
        You are an AWS deployment analyst. Analyze deployment results and determine appropriate response.

        Deployment Information:
        - Stack Prefix: {stack_prefix}
        - Template URL: {template_url}
        - Total Patterns: {len(deployment_results)}

        Pattern Results (ANALYZE THIS FIRST):
        {json.dumps(deployment_results, indent=2)}

        CodeBuild Logs (may be interleaved due to parallel execution):
        {deployment_logs}

        STEP 1: Check Pattern Results for failure classification:
        - If ALL patterns have "success": true → SUCCESS CASE
        - If error contains "No result file found" or "verification failed" → SMOKE TEST FAILURE
        - If error contains "deployment failed" or "CREATE_FAILED" or "timeout" → INFRASTRUCTURE FAILURE

        STEP 2: Respond based on classification:

        FOR SUCCESS CASE (all patterns successful):
        🚀 DEPLOYMENT RESULTS

        📋 Pattern Status:
        • Pattern 1 - BDA: SUCCESS - Stack deployed and tested successfully
        • Pattern 2 - OCR: SUCCESS - Stack deployed and tested successfully

        FOR INFRASTRUCTURE FAILURE:
        Respond ONLY with: "NEED_CF_LOGS: stack1,stack2" (list failed stack names)

        FOR SMOKE TEST FAILURE:
        🚀 DEPLOYMENT RESULTS

        📋 Pattern Status:
        • [Pattern Name]: FAILED - [specific failure reason from Pattern Results]
        • [Pattern Name]: SUCCESS - Stack deployed and tested successfully

        🔍 Root Cause Analysis:
        • Extract specific error from Pattern Results
        • Focus on post-deployment verification issues
        • Identify timing, file path, or result validation problems

        💡 Fix Commands:
        • Provide specific commands to resolve verification issues

        Keep each bullet point under 75 characters.
        
        IMPORTANT: Only use NEED_CF_LOGS for actual infrastructure/deployment failures, NOT for smoke test failures.
        """)
        
        # Call Bedrock API
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-5-sonnet-20240620-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        response_body = json.loads(response['body'].read())
        initial_summary = response_body['content'][0]['text']
        
        # Check if we need CloudFormation logs
        if initial_summary.startswith("NEED_CF_LOGS"):
            print("🔍 Getting CloudFormation logs for detailed analysis...")
            # Get CloudFormation logs for failed stacks
            cf_logs = {}
            logs_retrieved = 0
            
            for result in deployment_results:
                if not result["success"] and result.get("stack_name") and result["stack_name"] != "N/A":
                    print(f"📋 Getting CF logs for: {result['stack_name']}")
                    try:
                        logs = get_cloudformation_logs(result["stack_name"])
                        # Check if we got actual events or just error messages
                        if logs and not (len(logs) == 1 and 'error' in logs[0]):
                            cf_logs[result["stack_name"]] = logs
                            logs_retrieved += 1
                            print(f"✅ Retrieved {len(logs)} events for {result['stack_name']}")
                        else:
                            error_msg = logs[0].get('error', 'Unknown error') if logs else 'No logs returned'
                            print(f"⚠️ Failed to get CF logs for {result['stack_name']}: {error_msg}")
                            cf_logs[result["stack_name"]] = [{"error": error_msg, "stack_name": result["stack_name"]}]
                    except Exception as e:
                        print(f"⚠️ Exception getting CF logs for {result['stack_name']}: {e}")
                        cf_logs[result["stack_name"]] = [{"error": f"Exception: {str(e)}", "stack_name": result["stack_name"]}]
            
            print(f"✅ Retrieved CF logs for {logs_retrieved}/{len(cf_logs)} stacks")
            
            # Always proceed with second Bedrock call, even with partial/error data
            print("🤖 Making second Bedrock call with available CF data...")
            cf_prompt = dedent(f"""
            Analyze CloudFormation error events to determine root cause of deployment failures.

            Pattern Results:
            {json.dumps(deployment_results, indent=2)}

            CloudFormation Error Events:
            {json.dumps(cf_logs, indent=2)}

            IMPORTANT: Some stacks may have failed to retrieve logs (check for "error" fields).
            For stacks with log retrieval errors, base analysis on the pattern results error messages.
            
            Search through the events and find CREATE_FAILED events. Determine the root cause based on ResourceStatusReason.
            If no events available due to log retrieval failures, analyze the pattern error messages for clues.

            Provide analysis in this format:

            🚀 DEPLOYMENT RESULTS

            📋 Pattern Status:
            [Determine actual status from the data provided]

            🔍 CloudFormation Root Cause:
            • Find CREATE_FAILED events and extract ResourceStatusReason
            • Identify which specific resources failed to create
            • Analyze error messages for technical root cause

            💡 Fix Commands:
            • Provide specific AWS CLI commands based on actual failures found
            • Focus on the resources that actually failed

            Keep each bullet point under 75 characters.
            """)
            
            cf_response = bedrock.invoke_model(
                modelId='anthropic.claude-3-5-sonnet-20240620-v1:0',
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4000,
                    "messages": [{"role": "user", "content": cf_prompt}]
                })
            )
            
            cf_response_body = json.loads(cf_response['body'].read())
            print("✅ Second Bedrock call completed successfully")
            return cf_response_body['content'][0]['text']
        
        return initial_summary
        
    except Exception as e:
        # Manual summary when Bedrock unavailable
        successful = sum(1 for r in deployment_results if r["success"])
        total = len(deployment_results)
        
        return dedent(f"""
        DEPLOYMENT SUMMARY (MANUAL)
        
        Successful Patterns: {successful}/{total}
        
        Pattern Results:
        {chr(10).join(f"- {r['pattern_name']}: {'SUCCESS' if r['success'] else 'FAILED'}" for r in deployment_results)}
        
        Error: Failed to generate AI analysis: {e}
        """)

def cleanup_single_stack(stack_name, pattern_name):
    """Clean up a single stack"""
    print(f"[{pattern_name}] Cleaning up: {stack_name}")
    try:
        # Check stack status first
        result = run_command(f"aws cloudformation describe-stacks --stack-name {stack_name} --query 'Stacks[0].StackStatus' --output text", check=False)
        stack_status = result.stdout.strip() if result.returncode == 0 else "NOT_FOUND"
        
        print(f"[{pattern_name}] Stack status: {stack_status}")
        
        # Delete the stack and wait for completion (includes all cleanup via --force-delete-all)
        print(f"[{pattern_name}] Attempting stack deletion...")
        run_command(f"idp-cli delete --stack-name {stack_name} --force --empty-buckets --force-delete-all --wait", check=False)
        
        print(f"[{pattern_name}] ✅ Cleanup completed")
        
        # Clean up CodeBuild-specific IAM resources
        cleanup_iam_resources(stack_name)
        
    except Exception as e:
        print(f"[{pattern_name}] ⚠️ Cleanup failed: {e}")


def cleanup_stacks(deployment_results):
    """Clean up multiple stacks in parallel"""
    stacks_to_cleanup = [
        (result["stack_name"], result["pattern_name"])
        for result in deployment_results
        if result.get("stack_name") and result["stack_name"] != "N/A"
    ]
    
    if not stacks_to_cleanup:
        print("No stacks to cleanup")
        return
    
    print(f"🧹 Starting parallel cleanup of {len(stacks_to_cleanup)} stacks...")
    
    with ThreadPoolExecutor(max_workers=len(stacks_to_cleanup)) as executor:
        futures = [
            executor.submit(cleanup_single_stack, stack_name, pattern_name)
            for stack_name, pattern_name in stacks_to_cleanup
        ]
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"⚠️ Cleanup task failed: {e}")

def main():
    """Main execution function"""
    print("Starting CodeBuild deployment process...")

    admin_email = get_env_var("IDP_ADMIN_EMAIL", "tanimath@amazon.com")
    stack_prefix = generate_stack_prefix()

    print(f"Stack Prefix: {stack_prefix}")
    print(f"Admin Email: {admin_email}")
    print(f"Patterns to deploy: {[p['name'] for p in DEPLOY_PATTERNS]}")

    # Step 1: Publish templates to S3
    try:
        template_url = publish_templates()
        publish_success = True
        publish_error = None
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        template_url = "N/A - Publish failed"
        publish_success = False
        publish_error = str(e)

    all_success = publish_success
    deployment_results = []

    # Step 2: Deploy and test patterns concurrently (only if publish succeeded)
    if publish_success:
        print("🚀 Starting concurrent deployment of all patterns...")
        with ThreadPoolExecutor(max_workers=len(DEPLOY_PATTERNS)) as executor:
            # Submit all deployment tasks (without cleanup)
            future_to_pattern = {
                executor.submit(
                    deploy_and_test_pattern,
                    stack_prefix,
                    pattern_config,
                    admin_email,
                    template_url,
                ): pattern_config
                for pattern_config in DEPLOY_PATTERNS
            }

            # Collect results as they complete
            for future in as_completed(future_to_pattern):
                pattern_config = future_to_pattern[future]
                try:
                    result = future.result()
                    deployment_results.append(result)
                    if not result["success"]:
                        all_success = False
                        print(f"[{pattern_config['name']}] ❌ Failed")
                    else:
                        print(f"[{pattern_config['name']}] ✅ Success")
                        
                except Exception as e:
                    print(f"[{pattern_config['name']}] ❌ Exception: {e}")
                    # Add failed result for exception cases
                    deployment_results.append({
                        "stack_name": f"{stack_prefix}-{pattern_config['suffix']}",
                        "pattern_name": pattern_config['name'],
                        "success": False,
                        "error": str(e)
                    })
                    all_success = False
    else:
        # Add publish failure to results for AI analysis
        deployment_results.append({
            "stack_name": "N/A",
            "pattern_name": "Template Publishing",
            "success": False,
            "error": "Failed to publish templates to S3"
        })

    # Step 3: Generate deployment summary using Bedrock (but don't print yet)
    ai_summary = None
    try:
        if not publish_success:
            ai_summary = generate_publish_failure_summary(publish_error)
        else:
            ai_summary = generate_deployment_summary(deployment_results, stack_prefix, template_url)
    except Exception as e:
        ai_summary = f"⚠️ Failed to generate deployment summary: {e}"

    # Step 4: Cleanup stacks after analysis
    cleanup_stacks(deployment_results)

    # Step 5: Print AI analysis results at the end
    print("\n🤖 Generating deployment summary with Bedrock...")
    if ai_summary:
        print(ai_summary)

    # Check final status after all cleanups are done
    if all_success:
        print("🎉 All pattern deployments completed successfully!")
        sys.exit(0)
    else:
        print("💥 Some deployments failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
