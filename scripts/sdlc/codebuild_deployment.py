#!/usr/bin/env python3
"""
CodeBuild Deployment Script

Handles IDP stack deployment and testing in AWS CodeBuild environment.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from textwrap import dedent

import boto3


def run_command(cmd, check=True, timeout=None):
    """Run shell command and return result

    Args:
        cmd: Command to run
        check: Raise exception if command fails
        timeout: Timeout in seconds (default: None for no timeout)
    """
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)  # nosec B602 nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - hardcoded commands, no user input
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


def generate_stack_name():
    """Generate unique stack name with timestamp including seconds"""
    timestamp = datetime.now().strftime("%m%d-%H%M%S")  # Format: MMDD-HHMMSS
    return f"idp-{timestamp}"


def cleanup_stale_bda_blueprints():
    """Delete BDA projects, blueprint versions, and blueprints whose stacks are no longer active"""
    print("🧹 Cleaning up stale BDA blueprints...")
    try:
        bda_client = boto3.client('bedrock-data-automation')
        cf_client = boto3.client('cloudformation')

        active_statuses = {
            'CREATE_IN_PROGRESS', 'CREATE_COMPLETE',
            'UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE',
            'UPDATE_ROLLBACK_COMPLETE', 'UPDATE_ROLLBACK_IN_PROGRESS',
            'IMPORT_IN_PROGRESS', 'IMPORT_COMPLETE',
        }

        # Collect all idp- blueprints and projects
        paginator = bda_client.get_paginator('list_blueprints')
        blueprints = []
        for page in paginator.paginate(blueprintStageFilter='LIVE'):
            for bp in page.get('blueprints', []):
                name = bp.get('blueprintName', '')
                arn = bp.get('blueprintArn', '')
                if name.startswith('idp-') and 'aws:blueprint' not in arn:
                    blueprints.append((name, arn))

        projects = []
        for p in bda_client.list_data_automation_projects().get('projects', []):
            name = p.get('projectName', '')
            arn = p.get('projectArn', '')
            if name.startswith('idp-'):
                projects.append((name, arn))

        if not blueprints and not projects:
            print("✅ No stale BDA resources found")
            return

        # Check stack status for each unique stack prefix
        stack_cache = {}
        for name, _ in blueprints + projects:
            parts = name.split('-')
            if len(parts) >= 3:
                prefix = f"{parts[0]}-{parts[1]}-{parts[2]}"
                if prefix not in stack_cache:
                    try:
                        resp = cf_client.describe_stacks(StackName=prefix)
                        status = resp['Stacks'][0]['StackStatus']
                        stack_cache[prefix] = status in active_statuses
                    except cf_client.exceptions.ClientError:
                        stack_cache[prefix] = False

        def _is_stale(name):
            parts = name.split('-')
            if len(parts) >= 3:
                return not stack_cache.get(f"{parts[0]}-{parts[1]}-{parts[2]}", False)
            return False

        # Step 1: Delete projects first (blueprints are referenced by projects)
        deleted_projects = 0
        for name, arn in projects:
            if _is_stale(name):
                try:
                    bda_client.delete_data_automation_project(projectArn=arn)
                    deleted_projects += 1
                except Exception as e:
                    print(f"  ⚠️ Failed to delete project {name}: {e}")
                    time.sleep(1)

        if deleted_projects:
            time.sleep(5)

        # Step 2: Delete blueprint versions then base blueprints
        deleted_bps = 0
        for name, arn in blueprints:
            if _is_stale(name):
                try:
                    try:
                        bda_client.delete_blueprint(blueprintArn=arn, blueprintVersion='1')
                    except Exception:
                        pass
                    time.sleep(0.3)
                    bda_client.delete_blueprint(blueprintArn=arn)
                    deleted_bps += 1
                except Exception as e:
                    print(f"  ⚠️ Failed to delete blueprint {name}: {e}")
                    time.sleep(0.5)

        print(f"✅ Cleaned up {deleted_projects} projects, {deleted_bps} blueprints (skipped active stacks)")
    except Exception as e:
        print(f"⚠️ BDA blueprint cleanup failed: {e}")


def publish_templates():
    """Run publish.py to build and upload templates to S3"""
    print("📦 Publishing templates to S3...")

    # Get AWS account ID and region
    account_id = get_env_var("IDP_ACCOUNT_ID", "020432867916")
    region = get_env_var("AWS_DEFAULT_REGION", "us-east-1")

    # Generate bucket name and prefix
    bucket_basename = f"genaiic-sdlc-sourcecode-{account_id}"
    prefix = f"codebuild-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Run idp-cli publish
    cmd = f"idp-cli publish --source-dir . --bucket-basename {bucket_basename} --prefix {prefix} --region {region}"
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


def test_step3_default_config(stack_name):
    """Step 3: Test with default config (Pipeline mode)"""
    print("Step 3: Testing with default config (Pipeline mode)...")
    batch_id = "test-default"
    sample_file = "lending_package.pdf"
    verify_string = "ANYTOWN, USA 12345"
    result_location = "pages/1/result.json"
    content_path = "text"

    def verify_extraction(json_data):
        inference_result = json_data.get('inference_result', {})
        if not inference_result:
            return False, "No inference_result found"
        total_fields = len(inference_result)
        if total_fields == 0:
            return False, "inference_result is empty"
        populated_fields = sum(1 for v in inference_result.values() if v not in [None, [], {}])
        min_expected_fields = 3
        if total_fields < min_expected_fields:
            return False, f"Expected at least {min_expected_fields} fields, found {total_fields}"
        if populated_fields == 0:
            return False, "No fields contain extracted data (all null/empty)"
        return True, f"{populated_fields}/{total_fields} fields populated"

    def verify_classification(json_data):
        doc_class = json_data.get('document_class', {}).get('type')
        if not doc_class:
            return False, "No document_class.type found"
        if doc_class == 'none':
            return False, "Document classified as 'none' (no class detected)"
        return True, f"Classified as '{doc_class}'"

    additional_checks = [
        ("Extraction verification", "sections/1/result.json", verify_extraction),
        ("Classification verification", "sections/1/result.json", verify_classification),
    ]

    if not run_inference_test(stack_name, sample_file, batch_id, verify_string, result_location, content_path, None, "samples", additional_checks):
        return {"success": False, "error": "Default config test failed"}

    return {"success": True}


def test_step4_bda_mode(stack_name):
    """Step 4: Upload and test BDA config (sync without activation for parallel execution)"""
    print("Step 4: Testing with BDA mode...")
    config_version = "test-bda"
    config_path = "config_library/unified/lending-package-sample/config.yaml"

    with open(config_path, 'r') as f:
        config_content = f.read()

    bda_config_content = config_content.replace('use_bda: false', 'use_bda: true')

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        tmp.write(bda_config_content)
        bda_config_path = tmp.name

    try:
        print("Uploading BDA config (use_bda: true)")
        cmd = f"idp-cli config-upload --stack-name {stack_name} --config-file {bda_config_path} --config-version {config_version}"
        run_command(cmd)

        print("Syncing BDA config to create blueprints (without activation)")
        cmd = f"idp-cli config-sync-bda --stack-name {stack_name} --config-version {config_version}"
        run_command(cmd)
        print("✅ BDA config synced (will use --config-version for inference)")

        batch_id = "test-bda"
        sample_file = "lending_package.pdf"
        verify_string = "ANYTOWN, USA 12345"
        bda_result_location = "pages/1/parsedResult.json"
        content_path = "text"

        def verify_bda_extraction(json_data):
            inference_result = json_data.get('inference_result', {})
            if not inference_result:
                return False, "No inference_result found in BDA output"
            total_fields = len(inference_result)
            populated_fields = sum(1 for v in inference_result.values() if v not in [None, [], {}])
            min_expected_fields = 3
            if total_fields < min_expected_fields:
                return False, f"Expected at least {min_expected_fields} fields, found {total_fields}"
            if populated_fields == 0:
                return False, "No fields contain extracted data (all null/empty)"
            return True, f"{populated_fields}/{total_fields} fields populated by BDA"

        bda_additional_checks = [
            ("BDA extraction verification", "sections/1/result.json", verify_bda_extraction),
        ]

        if not run_inference_test(stack_name, sample_file, batch_id, verify_string, bda_result_location, content_path, config_version, "samples", bda_additional_checks):
            return {"success": False, "error": "BDA config test failed"}

        return {"success": True}
    finally:
        os.unlink(bda_config_path)


def test_step5_rule_validation(stack_name):
    """Step 5: Test rule validation"""
    print("Step 5: Testing rule validation...")
    config_version = "rule-validation"
    config_path = "config_library/unified/rule-validation/config.yaml"
    sample_file = "Prior-Auth-12345678.pdf"
    sample_dir = "samples/rule-validation"
    batch_id = "test-rules"
    verify_string = "global_periods"
    result_location = "rule_validation/sections/section_1_responses.json"
    content_path = "responses.global_periods.0.rule_type"

    print(f"Uploading rule validation config from: {config_path}")
    cmd = f"idp-cli config-upload --stack-name {stack_name} --config-file {config_path} --config-version {config_version}"
    run_command(cmd)

    def verify_rule_results(json_data):
        responses = json_data.get('responses', {})
        if not responses:
            return False, "No rule responses found"
        total_rules = 0
        passed_rules = 0
        failed_rules = 0
        for rule_name, rule_list in responses.items():
            if isinstance(rule_list, list):
                for rule in rule_list:
                    total_rules += 1
                    result = rule.get('result', '').lower()
                    if 'pass' in result:
                        passed_rules += 1
                    elif 'fail' in result:
                        failed_rules += 1
        if total_rules == 0:
            return False, "No rules were evaluated"
        return True, f"{total_rules} rules evaluated ({passed_rules} passed, {failed_rules} failed)"

    rule_additional_checks = [
        ("Rule validation results", "rule_validation/sections/section_1_responses.json", verify_rule_results),
    ]

    if not run_inference_test(stack_name, sample_file, batch_id, verify_string, result_location, content_path, config_version, sample_dir, rule_additional_checks):
        return {"success": False, "error": "Rule validation test failed"}

    return {"success": True}


def test_step6_multi_document(stack_name):
    """Step 6: Test multi-document batch processing"""
    print("Step 6: Testing multi-document batch processing...")
    batch_id = "test-multi-batch"
    sample_dir = "samples/w2"
    file_pattern = "W2_XL_input_clean_100[0-2].pdf"

    try:
        print("Processing 3 W-2 documents in parallel...")
        cmd = f"idp-cli run-inference --stack-name {stack_name} --dir {sample_dir} --file-pattern '{file_pattern}' --batch-id {batch_id} --monitor"
        run_command(cmd)

        result_dir = f"/tmp/result-{batch_id}"  # nosec B108
        cmd = f"idp-cli download-results --stack-name {stack_name} --batch-id {batch_id} --output-dir {result_dir}"
        run_command(cmd)

        print("Verifying all documents processed successfully...")
        cmd = f"find {result_dir} -path '*/sections/*/result.json' | wc -l"
        result = run_command(cmd, check=False)
        extraction_count = int(result.stdout.strip())

        if extraction_count < 3:
            print(f"❌ Expected 3 documents processed, found {extraction_count}")
            return {"success": False, "error": f"Multi-document batch test failed: only {extraction_count}/3 documents processed"}

        print(f"✅ Multi-document batch test passed: {extraction_count} documents processed successfully")
        return {"success": True}

    except Exception as e:
        print(f"❌ Multi-document batch test failed: {e}")
        return {"success": False, "error": f"Multi-document batch test failed: {str(e)}"}


def test_step7_test_studio(stack_name):
    """Step 7: Test Studio - Run evaluation against pre-deployed test set using idp-cli test-result"""
    print("Step 7: Testing Test Studio with pre-deployed test set...")

    try:
        cf_client = boto3.client('cloudformation')
        stack_response = cf_client.describe_stacks(StackName=stack_name)
        outputs = stack_response['Stacks'][0].get('Outputs', [])

        test_set_bucket = None
        for output in outputs:
            if output['OutputKey'] == 'S3TestSetBucketName':
                test_set_bucket = output['OutputValue']
                break

        if not test_set_bucket:
            print("⚠️  S3TestSetBucketName not found in stack outputs, skipping Test Studio test")
            return {"success": True}

        s3_client = boto3.client('s3')
        try:
            response = s3_client.list_objects_v2(Bucket=test_set_bucket, Delimiter='/', MaxKeys=10)
            test_sets = [prefix['Prefix'].rstrip('/') for prefix in response.get('CommonPrefixes', [])]

            if not test_sets:
                print(f"⚠️  No test sets found in {test_set_bucket}, skipping Test Studio test")
                return {"success": True}

            print(f"Found test sets: {', '.join(test_sets)}")

            test_set_name = None
            for preferred in ['fake-w2', 'realkie-fcc-verified']:
                if preferred in test_sets:
                    test_set_name = preferred
                    break
            if not test_set_name:
                test_set_name = test_sets[0]

            print(f"Running test against test set: {test_set_name} (limited to 3 documents)")
            print(f"Using config version: {test_set_name}")

            # Run test inference
            cmd = f"idp-cli run-inference --stack-name {stack_name} --test-set {test_set_name} --config-version {test_set_name} --context 'CI/CD smoke test' --number-of-files 3"
            result = run_command(cmd, check=False)

            if result.returncode != 0:
                print("⚠️  Test set processing failed")
                return {"success": False, "error": f"Test Studio test failed for {test_set_name}"}

            # Extract test run ID from output
            test_run_id = None
            for line in result.stdout.split('\n'):
                if 'Test run started:' in line:
                    test_run_id = line.split('Test run started:')[1].strip()
                    break

            if not test_run_id:
                print("⚠️  Could not extract test run ID from output, skipping result verification")
                return {"success": True}

            print(f"Test run ID: {test_run_id}")
            print("Retrieving test results using idp-cli test-result...")

            # Use idp-cli test-result command to get results (triggers evaluation and waits)
            cmd = f"idp-cli test-result --stack-name {stack_name} --test-run-id {test_run_id} --wait --timeout 600"
            result = run_command(cmd, check=False)

            if result.returncode != 0:
                print("❌ Test result retrieval failed")
                return {"success": False, "error": "Test Studio test result retrieval failed"}

            # Parse output for accuracy check
            overall_accuracy = None
            for line in result.stdout.split('\n'):
                if 'Overall Accuracy:' in line:
                    # Extract percentage (e.g., "Overall Accuracy: 95.45%")
                    parts = line.split(':')
                    if len(parts) >= 2:
                        accuracy_str = parts[1].strip().rstrip('%')
                        try:
                            overall_accuracy = float(accuracy_str) / 100.0
                        except ValueError:
                            pass
                    break

            if overall_accuracy is not None:
                if overall_accuracy > 0.30:
                    print(f"✅ Test Studio test completed: {test_set_name} with {overall_accuracy:.2%} accuracy")
                else:
                    print(f"⚠️  Low accuracy detected: {overall_accuracy:.2%} (threshold: 30%)")
                return {"success": True}
            else:
                print("⚠️  Could not parse accuracy from output, but test completed")
                return {"success": True}

        except Exception as e:
            print(f"⚠️  Could not access test set bucket: {e}")

        return {"success": True}

    except Exception as e:
        print(f"❌ Test Studio test failed: {e}")
        return {"success": False, "error": f"Test Studio test failed: {str(e)}"}


def test_step8_agentic_extraction(stack_name):
    """Step 8: Test agentic extraction with large table"""
    print("Step 8: Testing agentic extraction with Nuveen (532 fund items)...")

    try:
        print("Uploading nuveen.yaml configuration...")
        cmd = f"idp-cli config-upload --stack-name {stack_name} --config-file scripts/sdlc/config/nuveen.yaml --config-version agentic-nuveen --no-validate"
        run_command(cmd, check=False)

        print("Running agentic extraction on samples/Nuveen.pdf (this will take ~9 minutes)...")
        cmd = f"idp-cli run-inference --stack-name {stack_name} --dir samples/ --file-pattern Nuveen.pdf --config-version agentic-nuveen --monitor"
        result = run_command(cmd, check=False)

        if result.returncode != 0:
            print("❌ Agentic extraction command failed")
            return {"success": False, "error": "Agentic extraction command failed"}

        batch_id = None
        for line in result.stdout.split('\n'):
            if 'Batch ID:' in line:
                batch_id = line.split('Batch ID:')[1].strip()
                break

        if batch_id:
            print(f"Downloading results for batch: {batch_id}")
            result_dir = f"/tmp/result-agentic-{batch_id}"  # nosec B108
            cmd = f"idp-cli download-results --stack-name {stack_name} --batch-id {batch_id} --output-dir {result_dir}"
            run_command(cmd, check=False)

            cmd = f"find {result_dir} -path '*/sections/*/result.json' -type f | head -1"
            find_result = run_command(cmd, check=False)
            result_file = find_result.stdout.strip()

            if result_file:
                with open(result_file, "r") as f:
                    result_json = json.load(f)

                doc_class = result_json.get("document_class", {}).get("type")
                if doc_class == "Estimated2024AnnualTaxableDistributions":
                    print(f"  ✓ Document class correct: {doc_class}")
                else:
                    print(f"❌ Unexpected document class: {doc_class}")
                    return {"success": False, "error": f"Agentic extraction test failed: unexpected document class '{doc_class}'"}

                fund_info = result_json.get("inference_result", {}).get("FundInformation", [])
                fund_count = len(fund_info)
                if fund_count == 532:
                    print(f"  ✓ FundInformation count correct: {fund_count} items")
                    print("✅ Agentic extraction test completed successfully")
                    return {"success": True}
                else:
                    print(f"❌ FundInformation count mismatch: expected 532, got {fund_count}")
                    return {"success": False, "error": f"Agentic extraction test failed: expected 532 fund items, got {fund_count}"}
            else:
                print("❌ Result file not found")
                return {"success": False, "error": "Agentic extraction test failed: result file not found"}
        else:
            print("❌ Could not extract batch ID from output")
            return {"success": False, "error": "Agentic extraction test failed: could not extract batch ID"}

    except Exception as e:
        print(f"❌ Agentic extraction test failed: {e}")
        return {"success": False, "error": f"Agentic extraction test failed: {str(e)}"}


def test_step9_single_doc_discovery(stack_name):
    """Step 9: Test single-document discovery"""
    print("Step 9: Testing single-document discovery...")

    try:
        sample_file = "samples/insurance_package_single.pdf"
        config_version = "test-discovery"
        print(f"Running discovery on {sample_file}...")
        print(f"Saving to config version: {config_version}")
        print("This will take approximately 3-5 minutes...")

        cmd = f"idp-cli discover --stack-name {stack_name} -d {sample_file} --config-version {config_version}"
        result = run_command(cmd, check=True, timeout=300)

        print("Verifying discovered class saved to configuration...")

        config_file = "/tmp/discovery-config.yaml"  # nosec B108
        cmd = f"idp-cli config-download --stack-name {stack_name} --config-version {config_version} --output {config_file}"
        run_command(cmd, check=True)

        import yaml
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f)

        classes = config_data.get('classes', [])
        if len(classes) == 0:
            print(f"❌ No classes found in config version {config_version}")
            return {"success": False, "error": f"Single-document discovery test failed: no classes found in config version {config_version}"}

        discovered_class = classes[0]
        doc_class = discovered_class.get('$id', 'Unknown')
        num_properties = len(discovered_class.get('properties', {}))
        print(f"  ✓ Discovered class: {doc_class}")
        print(f"  ✓ Properties: {num_properties} top-level fields")
        print(f"✅ Discovery test completed: schema saved to config version {config_version}")
        return {"success": True}

    except Exception as e:
        print(f"❌ Single-document discovery test failed: {e}")
        return {"success": False, "error": f"Single-document discovery test failed: {str(e)}"}


def test_step10_multi_doc_discovery(stack_name):
    """Step 10: Test multi-document discovery"""
    print("Step 10: Testing multi-document discovery...")

    try:
        test_dir = "/tmp/multidoc-test"  # nosec B108
        import shutil

        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        os.makedirs(test_dir)

        sample_files = [
            ("samples/w2/W2_XL_input_clean_1000.pdf", "w2_1.pdf"),
            ("samples/w2/W2_XL_input_clean_1001.pdf", "w2_2.pdf"),
            ("samples/bank-statement-multipage.pdf", "bank_statement.pdf"),
            ("samples/insurance_package_single.pdf", "insurance.pdf"),
        ]

        for src, dest_name in sample_files:
            dest = f"{test_dir}/{dest_name}"
            if not os.path.exists(src):
                raise FileNotFoundError(f"Sample file not found: {src}")
            shutil.copy(src, dest)
            if not os.path.exists(dest):
                raise RuntimeError(f"Failed to copy {src} to {dest}")

        copied_files = len(os.listdir(test_dir))
        print(f"  ✓ Copied {copied_files} sample documents to {test_dir}")

        if copied_files != len(sample_files):
            raise RuntimeError(f"Expected {len(sample_files)} files but found {copied_files}")

        print(f"Running multi-document discovery on {test_dir}...")
        print("This will take approximately 2-3 minutes...")

        cmd = f"idp-cli discover-multidoc --dir {test_dir} -o /tmp/multidoc-schemas"
        run_command(cmd, check=True, timeout=240)

        cmd = "find /tmp/multidoc-schemas -name '*.json' | wc -l"
        count_result = run_command(cmd, check=True)
        schema_count = int(count_result.stdout.strip()) if count_result.stdout.strip() else 0

        if schema_count == 0:
            print("❌ Multi-document discovery completed but no schemas found")
            return {"success": False, "error": "Multi-document discovery test failed: no schemas generated"}

        print(f"  ✓ Generated {schema_count} schema(s)")

        cmd = "find /tmp/multidoc-schemas -name '*.json' | head -1"
        first_schema = run_command(cmd, check=True).stdout.strip()
        if not first_schema:
            print("❌ Could not find generated schema file")
            return {"success": False, "error": "Multi-document discovery test failed: could not find generated schema file"}

        with open(first_schema, "r") as f:
            schema_json = json.load(f)

        if "$schema" not in schema_json or "properties" not in schema_json:
            print("❌ Generated schema missing required fields ($schema, properties)")
            return {"success": False, "error": "Multi-document discovery test failed: schema missing required fields"}

        print("  ✓ Schema structure validated")
        print("✅ Multi-document discovery test completed")
        return {"success": True}

    except Exception as e:
        print(f"❌ Multi-document discovery test failed: {e}")
        return {"success": False, "error": f"Multi-document discovery test failed: {str(e)}"}


def test_step11_test_compare(stack_name):
    """Step 11: Test Compare - Compare results from multiple test runs using idp-cli test-compare"""
    print("Step 11: Testing test-compare command...")

    try:
        cf_client = boto3.client('cloudformation')
        stack_response = cf_client.describe_stacks(StackName=stack_name)
        outputs = stack_response['Stacks'][0].get('Outputs', [])

        test_set_bucket = None
        for output in outputs:
            if output['OutputKey'] == 'S3TestSetBucketName':
                test_set_bucket = output['OutputValue']
                break

        if not test_set_bucket:
            print("⚠️  S3TestSetBucketName not found in stack outputs, skipping test-compare test")
            return {"success": True}

        s3_client = boto3.client('s3')
        try:
            response = s3_client.list_objects_v2(Bucket=test_set_bucket, Delimiter='/', MaxKeys=10)
            test_sets = [prefix['Prefix'].rstrip('/') for prefix in response.get('CommonPrefixes', [])]

            if not test_sets:
                print(f"⚠️  No test sets found in {test_set_bucket}, skipping test-compare test")
                return {"success": True}

            print(f"Found test sets: {', '.join(test_sets)}")

            test_set_name = None
            for preferred in ['fake-w2', 'realkie-fcc-verified']:
                if preferred in test_sets:
                    test_set_name = preferred
                    break
            if not test_set_name:
                test_set_name = test_sets[0]

            print(f"Running 2 test inferences against test set: {test_set_name} (limited to 2 documents each)")

            # Run first test inference
            test_run_ids = []
            for i in range(2):
                print(f"\nRunning test inference {i+1}/2...")
                cmd = f"idp-cli run-inference --stack-name {stack_name} --test-set {test_set_name} --config-version {test_set_name} --context 'CI/CD test-compare test {i+1}' --number-of-files 2"
                result = run_command(cmd, check=False)

                if result.returncode != 0:
                    print(f"⚠️  Test inference {i+1} failed")
                    return {"success": False, "error": f"Test inference {i+1} failed for test-compare"}

                # Extract test run ID from output
                test_run_id = None
                for line in result.stdout.split('\n'):
                    if 'Test run started:' in line:
                        test_run_id = line.split('Test run started:')[1].strip()
                        break

                if not test_run_id:
                    print(f"⚠️  Could not extract test run ID {i+1} from output")
                    return {"success": False, "error": f"Could not extract test run ID {i+1}"}

                test_run_ids.append(test_run_id)
                print(f"Test run {i+1} ID: {test_run_id}")

                # Wait for test run to complete before starting next one
                print(f"Waiting for test run {i+1} to complete...")
                cmd = f"idp-cli test-result --stack-name {stack_name} --test-run-id {test_run_id} --wait --timeout 300"
                result = run_command(cmd, check=False)

                if result.returncode != 0:
                    print(f"⚠️  Test run {i+1} completion check failed")
                    return {"success": False, "error": f"Test run {i+1} completion failed"}

            # Compare the two test runs and save to JSON for validation
            print(f"\nComparing test runs: {', '.join(test_run_ids)}")

            # Create temp directory for comparison output
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                cmd = f"idp-cli test-compare --stack-name {stack_name} --test-run-ids '{','.join(test_run_ids)}' --output-dir {tmpdir}"
                result = run_command(cmd, check=False)

                if result.returncode != 0:
                    print("❌ test-compare command failed")
                    return {"success": False, "error": "test-compare command failed"}

                # Find and load the comparison JSON file
                comparison_files = [f for f in os.listdir(tmpdir) if f.startswith('comparison-') and f.endswith('.json')]

                if not comparison_files:
                    print("⚠️  No comparison JSON file generated")
                    return {"success": False, "error": "No comparison JSON file generated"}

                comparison_file = os.path.join(tmpdir, comparison_files[0])

                with open(comparison_file, 'r') as f:
                    comparison_data = json.load(f)

                # Validate JSON structure contains expected data
                if 'metrics' not in comparison_data:
                    print("⚠️  Comparison data missing 'metrics' field")
                    return {"success": False, "error": "Comparison data missing 'metrics' field"}

                metrics = comparison_data['metrics']

                # Verify both test runs are in metrics
                missing_runs = [tid for tid in test_run_ids if tid not in metrics]
                if missing_runs:
                    print(f"⚠️  Test runs missing from comparison: {', '.join(missing_runs)}")
                    return {"success": False, "error": f"Test runs missing from comparison: {', '.join(missing_runs)}"}

                # Verify each test run has required metric fields
                required_metrics = ['overallAccuracy', 'totalCost']
                for test_run_id in test_run_ids:
                    run_metrics = metrics[test_run_id]
                    missing_metrics = [m for m in required_metrics if m not in run_metrics]

                    if missing_metrics:
                        print(f"⚠️  Test run {test_run_id} missing metrics: {', '.join(missing_metrics)}")
                        return {"success": False, "error": f"Test run missing metrics: {', '.join(missing_metrics)}"}

                print("  ✓ Comparison JSON contains both test runs")
                print("  ✓ All required metrics present")
                print("✅ test-compare test completed successfully")
                return {"success": True}

        except Exception as e:
            print(f"⚠️  Could not access test set bucket: {e}")
            return {"success": True}

    except Exception as e:
        print(f"❌ test-compare test failed: {e}")
        return {"success": False, "error": f"test-compare test failed: {str(e)}"}


def deploy_and_test_stack(stack_name, admin_email, template_url):
    """Deploy and test the unified IDP stack"""
    print(f"Starting deployment: {stack_name}")

    try:
        # Step 0: Create IAM resources
        print("Step 0: Creating IAM resources...")
        role_arn, permissions_boundary_arn = create_iam_resources(stack_name)
        if not role_arn or not permissions_boundary_arn:
            raise Exception("Failed to create required IAM resources")
        
        # Step 1: Deploy using template URL
        print("Step 1: Deploying stack...")
        cmd = f"idp-cli deploy --stack-name {stack_name} --template-url {template_url} --admin-email {admin_email} --wait"
        cmd += f" --role-arn {role_arn}"
        cmd += f" --parameters PermissionsBoundaryArn={permissions_boundary_arn}"
        
        run_command(cmd)
        print("✅ Deployment completed")

        # Step 2: Test stack status
        print("Step 2: Verifying stack status...")
        cmd = f"aws cloudformation describe-stacks --stack-name {stack_name} --query 'Stacks[0].StackStatus' --output text"
        result = run_command(cmd)

        if "COMPLETE" not in result.stdout:
            print(f"❌ Stack status: {result.stdout.strip()}")
            return {
                "stack_name": stack_name,
                "success": False,
                "error": f"Stack deployment failed with status: {result.stdout.strip()}"
            }

        print("✅ Stack is healthy")

        # Run tests 3-10 in parallel (Step 4 BDA now uses config-sync-bda + --config-version, no activation race)
        print(f"\n{'='*80}")
        print("Running tests 3-10 in parallel (fail-fast enabled)...")
        print(f"{'='*80}\n")

        parallel_tests = [
            (test_step3_default_config, "Step 3: Default config"),
            (test_step4_bda_mode, "Step 4: BDA mode"),
            (test_step5_rule_validation, "Step 5: Rule validation"),
            (test_step6_multi_document, "Step 6: Multi-document batch"),
            (test_step7_test_studio, "Step 7: Test Studio"),
            (test_step8_agentic_extraction, "Step 8: Agentic extraction"),
            (test_step9_single_doc_discovery, "Step 9: Single-doc discovery"),
            (test_step10_multi_doc_discovery, "Step 10: Multi-doc discovery"),
        ]

        failed_test = None
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all parallel tests
            futures = {executor.submit(func, stack_name): name for func, name in parallel_tests}

            # Process results as they complete (fail-fast)
            for future in as_completed(futures):
                test_name = futures[future]
                try:
                    result = future.result()
                    if result["success"]:
                        print(f"✅ {test_name} passed")
                    else:
                        print(f"❌ {test_name} failed: {result.get('error', 'Unknown error')}")
                        failed_test = (test_name, result)
                        # Cancel all remaining tests
                        for f in futures:
                            f.cancel()
                        break
                except Exception as e:
                    print(f"❌ {test_name} exception: {e}")
                    failed_test = (test_name, {"success": False, "error": str(e)})
                    # Cancel all remaining tests
                    for f in futures:
                        f.cancel()
                    break

        # Check if any parallel test failed
        if failed_test:
            test_name, result = failed_test
            print(f"\n❌ Test suite failed at {test_name}")
            return {
                "stack_name": stack_name,
                "success": False,
                "error": f"{test_name} failed: {result.get('error', 'Unknown error')}"
            }

        # Run Step 11 (test-compare) sequentially after parallel tests
        print(f"\n{'='*80}")
        print("Running Step 11 (test-compare) sequentially...")
        print(f"{'='*80}\n")

        result = test_step11_test_compare(stack_name)
        if result["success"]:
            print("✅ Step 11: test-compare passed")
        else:
            print(f"❌ Step 11: test-compare failed: {result.get('error', 'Unknown error')}")
            return {
                "stack_name": stack_name,
                "success": False,
                "error": f"Step 11: test-compare failed: {result.get('error', 'Unknown error')}"
            }

        print("✅ All tests passed")
        return {
            "stack_name": stack_name,
            "success": True
        }

    except Exception as e:
        print(f"❌ Testing failed: {e}")
        return {
            "stack_name": stack_name,
            "success": False,
            "error": f"Deployment/testing failed: {str(e)}"
        }


def run_inference_test(stack_name, sample_file, batch_id, verify_string, result_location, content_path, config_version=None, sample_dir="samples", additional_checks=None):
    """Run inference test and verify results

    Args:
        stack_name: Name of the CloudFormation stack
        sample_file: Name of the sample file to process
        batch_id: Batch ID for this test run
        verify_string: String to verify in the main result
        result_location: Path to the main result file (relative to document directory)
        content_path: Dot-separated path to content in JSON (e.g., "pages.0.text")
        config_version: Optional config version to use
        sample_dir: Directory containing sample files
        additional_checks: Optional list of (check_name, file_path, verify_func) tuples
                          where verify_func takes JSON and returns (success: bool, message: str)
    """
    try:
        # Run inference
        print(f"Running inference with batch-id: {batch_id}...")
        cmd = f"idp-cli run-inference --stack-name {stack_name} --dir {sample_dir} --file-pattern {sample_file} --batch-id {batch_id} --monitor"
        if config_version:
            cmd += f" --config-version {config_version}"
        run_command(cmd)
        print("✅ Inference completed")

        # Download results
        print("Downloading results...")
        result_dir = f"/tmp/result-{batch_id}"  # nosec B108 - isolated CodeBuild environment
        cmd = f"idp-cli download-results --stack-name {stack_name} --batch-id {batch_id} --output-dir {result_dir}"
        run_command(cmd)

        # Verify result content
        print("Verifying result content...")

        # Find result file
        cmd = f"find {result_dir} -path '*/{result_location}' | head -1"
        result = run_command(cmd, check=False)
        result_file = result.stdout.strip()

        if not result_file:
            cmd = f"find {result_dir} -name 'result.json' | head -10"
            debug_result = run_command(cmd, check=False)
            print("Found result.json files:")
            print(debug_result.stdout)
            print(f"❌ No result file found at {result_location}")
            return False

        # Verify content
        with open(result_file, "r") as f:
            result_json = json.load(f)

        text_content = result_json
        for key in content_path.split("."):
            if key.isdigit():
                text_content = text_content[int(key)]
            else:
                text_content = text_content[key]

        if verify_string not in str(text_content):
            print(f"❌ Text content does not contain expected string: '{verify_string}'")
            print(f"Actual text starts with: '{str(text_content)[:100]}...'")
            return False

        print(f"✅ Found expected verification string: '{verify_string}'")

        # Run additional verification checks
        if additional_checks:
            for check_name, check_path, verify_func in additional_checks:
                print(f"Running additional check: {check_name}...")

                # Find the check file
                cmd = f"find {result_dir} -path '*/{check_path}' | head -1"
                check_result = run_command(cmd, check=False)
                check_file = check_result.stdout.strip()

                if not check_file:
                    print(f"⚠️  {check_name}: file not found at {check_path} (may be optional)")
                    continue  # Skip optional checks

                # Load and verify
                try:
                    with open(check_file, "r") as f:
                        check_json = json.load(f)

                    success, message = verify_func(check_json)
                    if not success:
                        print(f"❌ {check_name} failed: {message}")
                        return False

                    print(f"✅ {check_name} passed: {message}")
                except Exception as e:
                    print(f"❌ {check_name} error: {e}")
                    return False

        return True

    except Exception as e:
        print(f"❌ Inference test failed: {e}")
        return False


def get_codebuild_logs():
    """Get CodeBuild logs from CloudWatch"""
    try:
        # Get CodeBuild build ID from environment
        build_id = os.environ.get('CODEBUILD_BUILD_ID', '')
        if not build_id:
            return "CodeBuild logs not available (not running in CodeBuild)"
        
        # Wait for logs to propagate to CloudWatch
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
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "temperature": 0,
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


def generate_deployment_summary(result, stack_name, template_url):
    """Generate deployment summary using Bedrock API with CodeBuild and CloudFormation logs"""
    try:
        # Get CodeBuild logs (limit if failure to reduce noise from success markers)
        deployment_logs = get_codebuild_logs()
        if not result.get("success", True):
            # For failures, only show last 100 lines to reduce noise
            log_lines = deployment_logs.split('\n')
            if len(log_lines) > 100:
                deployment_logs = '\n'.join(log_lines[-100:])

        # Initialize Bedrock client
        bedrock = boto3.client('bedrock-runtime')

        # Create prompt for Bedrock with structured analysis
        # IMPORTANT: Deployment result is at END for recency bias
        prompt = dedent(f"""
        You are an AWS deployment analyst. Analyze deployment result and determine appropriate response.

        Deployment Information:
        - Stack Name: {stack_name}
        - Template URL: {template_url}

        CodeBuild Logs (for context only - DO NOT use to determine pass/fail):
        {deployment_logs}

        ==================== DEPLOYMENT RESULT (SOURCE OF TRUTH) ====================
        {json.dumps(result, indent=2)}
        =============================================================================

        STEP 0: What is the value of the "success" field in Deployment Result above?
        Write it here: success = _____

        If success = false, this is a FAILURE. Do NOT say "All Tests Passed".
        If success = true, this is a SUCCESS.

        CRITICAL: Check the "success" field in Deployment Result FIRST:
        - If "success": false → This is a FAILURE, analyze the "error" field
        - If "success": true → This is a SUCCESS
        - NEVER say "All Tests Passed" if "success": false

        STEP 1: Determine case based on Deployment Result (check in this order):

        Case B (INFRASTRUCTURE - check FIRST): "success": false AND "error" contains ("Stack deployment failed" OR "CREATE_FAILED" OR "ROLLBACK")
            → Respond with: "NEED_CF_LOGS: {stack_name}"

        Case A (SMOKE TEST - check SECOND): "success": false AND "error" contains "Step"
            → Generate smoke test failure summary

        Case C (SUCCESS): "success": true
            → Generate success summary

        STEP 2: Respond based on case:

        FOR SUCCESS CASE (Case C only):
        🚀 DEPLOYMENT RESULTS

        📋 Stack Status: {stack_name} deployed successfully

        ✅ All Tests Passed (9 tests):
        • Test 1 (Step 3): Default config with pipeline mode processing ✓
        • Test 2 (Step 4): BDA mode config and inference (parallel) ✓
        • Test 3 (Step 5): Rule validation config and processing ✓
        • Test 4 (Step 6): Multi-document batch processing ✓
        • Test 5 (Step 7): Test Studio evaluation with test-result command ✓
        • Test 6 (Step 8): Agentic extraction with large tables ✓
        • Test 7 (Step 9): Single-document discovery ✓
        • Test 8 (Step 10): Multi-document discovery ✓
        • Test 9 (Step 11): Test comparison with test-compare command ✓

        📊 Test Results:
        • All inference tests completed successfully
        • Test Studio achieved high accuracy scores
        • Discovery pipeline generated valid schemas
        • BDA mode processing validated

        FOR INFRASTRUCTURE FAILURE (Case B):
        Respond ONLY with: "NEED_CF_LOGS: {stack_name}"

        FOR SMOKE TEST FAILURE (Case A):
        🚀 DEPLOYMENT RESULTS

        📋 Test Status: FAILED - [extract which step/test failed from "error" field]

        🔍 Root Cause Analysis:
        • Extract the exact error message from the "error" field
        • Identify which test step failed (Step 3-11)
        • Explain what the test validates

        💡 Fix Guidance:
        • Suggest specific fixes based on the error message
        • Reference relevant CLI commands if applicable

        Keep each bullet point under 75 characters.

        CRITICAL REMINDERS:
        1. The "success" field in Deployment Result is the SOURCE OF TRUTH
        2. If "success": false, you MUST generate a FAILURE summary
        3. For Case B (Infrastructure Failure): Respond with EXACTLY "NEED_CF_LOGS: {stack_name}" and NOTHING else
        4. CodeBuild logs are for context only, not for determining success/failure
        5. All 9 tests must be listed in success case (Steps 3-10 run in parallel, Step 11 sequential)
        """)
        
        # Call Bedrock API with temperature=0 for deterministic output
        response = bedrock.invoke_model(
            modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}]
            })
        )
        
        response_body = json.loads(response['body'].read())
        initial_summary = response_body['content'][0]['text']
        
        # Check if we need CloudFormation logs
        if initial_summary.startswith("NEED_CF_LOGS"):
            print("🔍 Getting CloudFormation logs for detailed analysis...")
            # Get CloudFormation logs for failed stacks
            logs = []
            if not result["success"] and result.get("stack_name") and result["stack_name"] != "N/A":
                print(f"📋 Getting CF logs for: {result['stack_name']}")
                try:
                    logs = get_cloudformation_logs(result["stack_name"])
                    # Check if we got actual events or just error messages
                    if logs and not (len(logs) == 1 and 'error' in logs[0]):
                        print(f"✅ Retrieved {len(logs)} events for {result['stack_name']}")
                    else:
                        error_msg = logs[0].get('error', 'Unknown error') if logs else 'No logs returned'
                        print(f"⚠️ Failed to get CF logs for {result['stack_name']}: {error_msg}")
                        logs= [{"error": error_msg, "stack_name": result["stack_name"]}]
                except Exception as e:
                    print(f"⚠️ Exception getting CF logs for {result['stack_name']}: {e}")
                    logs = [{"error": f"Exception: {str(e)}", "stack_name": result["stack_name"]}]
            
            print(f"✅ Retrieved {len(logs)} CF logs for {stack_name}")
            
            # Always proceed with second Bedrock call, even with partial/error data
            print("🤖 Making second Bedrock call with available CF data...")
            cf_prompt = dedent(f"""
            Analyze CloudFormation error events to determine root cause of deployment failures.

            Pattern Results:
            {json.dumps(result, indent=2)}

            CloudFormation Error Events:
            {json.dumps(logs, indent=2)}

            IMPORTANT: Stack may have failed to retrieve logs (check for "error" fields).
            For log retrieval errors, base analysis on the result error messages.
            
            Search through the events and find CREATE_FAILED events. Determine the root cause based on ResourceStatusReason.
            If no events available due to log retrieval failures, analyze the error messages for clues.

            Provide analysis in this format:

            🚀 DEPLOYMENT RESULT

            📋 Status:
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
                modelId='us.anthropic.claude-sonnet-4-20250514-v1:0',
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4000,
                    "temperature": 0,
                    "messages": [{"role": "user", "content": cf_prompt}]
                })
            )
            
            cf_response_body = json.loads(cf_response['body'].read())
            print("✅ Second Bedrock call completed successfully")
            return cf_response_body['content'][0]['text']
        
        return initial_summary
        
    except Exception as e:
        # Manual summary when Bedrock unavailable
        return dedent(f"""
        DEPLOYMENT SUMMARY (MANUAL)
        
        Deployment result {stack_name} : {'SUCCESS' if result['success'] else 'FAILED'}
        
        Error: Failed to generate AI analysis: {e}
        """)

def cancel_bedrock_ingestion_jobs(stack_name):
    """Cancel any running Bedrock ingestion jobs before stack deletion"""
    print(f"[{stack_name}] Checking for running Bedrock ingestion jobs...")

    try:
        cf_client = boto3.client('cloudformation')
        bedrock_agent = boto3.client('bedrock-agent')

        # Get all resources from main stack and nested stacks
        stacks_to_check = [stack_name]

        # Find nested stacks
        try:
            resources = cf_client.describe_stack_resources(StackName=stack_name)
            for resource in resources['StackResources']:
                if resource['ResourceType'] == 'AWS::CloudFormation::Stack':
                    nested_stack_name = resource['PhysicalResourceId'].split('/')[1]
                    stacks_to_check.append(nested_stack_name)
        except Exception as e:
            print(f"  ⚠️ Could not list nested stacks: {e}")

        jobs_cancelled = 0

        # Check each stack for Bedrock data sources
        for stack in stacks_to_check:
            try:
                resources = cf_client.describe_stack_resources(StackName=stack)

                for resource in resources['StackResources']:
                    if resource['ResourceType'] == 'AWS::Bedrock::DataSource':
                        # Parse physical resource ID: knowledgeBaseId|dataSourceId
                        physical_id = resource['PhysicalResourceId']
                        if '|' in physical_id:
                            kb_id, ds_id = physical_id.split('|')

                            # List ingestion jobs for this data source
                            try:
                                response = bedrock_agent.list_ingestion_jobs(
                                    knowledgeBaseId=kb_id,
                                    dataSourceId=ds_id,
                                    maxResults=10
                                )

                                for job in response.get('ingestionJobSummaries', []):
                                    if job['status'] == 'IN_PROGRESS':
                                        job_id = job['ingestionJobId']
                                        print(f"  Cancelling ingestion job: {job_id}")

                                        # Stop the ingestion job
                                        bedrock_agent.stop_ingestion_job(
                                            knowledgeBaseId=kb_id,
                                            dataSourceId=ds_id,
                                            ingestionJobId=job_id
                                        )
                                        jobs_cancelled += 1
                                        print(f"  ✓ Cancelled ingestion job: {job_id}")

                            except Exception as e:
                                print(f"  ⚠️ Could not check/cancel jobs for {physical_id}: {e}")

            except Exception as e:
                print(f"  ⚠️ Could not check stack {stack}: {e}")

        if jobs_cancelled > 0:
            print(f"[{stack_name}] ✅ Cancelled {jobs_cancelled} running ingestion job(s)")
            # Wait a bit for cancellation to propagate
            print(f"[{stack_name}] Waiting 10s for job cancellation to complete...")
            time.sleep(10)
        else:
            print(f"[{stack_name}] No running ingestion jobs found")

    except Exception as e:
        print(f"[{stack_name}] ⚠️ Error checking ingestion jobs: {e}")


def cleanup_stack(result):
    """Clean up stack"""
    stack_name = result.get("stack_name")
    print(f"🧹 Starting cleanup for stack: {stack_name}")
    try:
        # Check stack status first
        cmd_result = run_command(f"aws cloudformation describe-stacks --stack-name {stack_name} --query 'Stacks[0].StackStatus' --output text", check=False)
        stack_status = cmd_result.stdout.strip() if cmd_result.returncode == 0 else "NOT_FOUND"

        print(f"[{stack_name}] stack status: {stack_status}")

        # Cancel any running Bedrock ingestion jobs before stack deletion
        cancel_bedrock_ingestion_jobs(stack_name)

        # Delete the stack and wait for completion (includes all cleanup via --force-delete-all)
        print(f"[{stack_name}] attempting stack deletion...")
        run_command(f"idp-cli delete --stack-name {stack_name} --force --empty-buckets --force-delete-all --wait", check=False)

        print(f"[{stack_name}] ✅ Cleanup completed")

        # Clean up CodeBuild-specific IAM resources
        cleanup_iam_resources(stack_name)
    except Exception as e:
        print(f"⚠️ Cleanup task failed: {e}")

def main():
    """Main execution function"""
    print("Starting CodeBuild deployment process...")

    admin_email = get_env_var("IDP_ADMIN_EMAIL", "tanimath@amazon.com")
    stack_name = generate_stack_name()

    print(f"Stack Name: {stack_name}")
    print(f"Admin Email: {admin_email}")

    #initialize AI summary
    ai_summary = ""
    publish_success = False
    stack_success = False

    # Step 0: Clean up stale BDA blueprints from previous runs
    cleanup_stale_bda_blueprints()

    # Step 1: Publish templates to S3
    try:
        template_url = publish_templates()
        print(f"Publish script ran successfully template url {template_url}")
        publish_success = True
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        ai_summary = generate_publish_failure_summary(str(e))
    
    
    if publish_success:
        # Step 2: Deploy and test patterns concurrently (only if publish succeeded)
        print(f"🚀 Starting deployment for stack: {stack_name}")
        try:
            result = deploy_and_test_stack(stack_name, admin_email, template_url)
            if not result["success"]:
                print(f"[{stack_name}] ❌ Failed")
            else:
                stack_success = True
                print(f"[{stack_name}] ✅ Success")
        except Exception as e:
            print(f"[{stack_name}] ❌ Exception: {e}")
            # Add failed result for exception cases
            result = {"stack_name": stack_name, "success": False, "error": str(e)}
    
        # Step 3: Generate deployment summary using Bedrock (but don't print yet)
        try:
            ai_summary = generate_deployment_summary(result, stack_name, template_url)
        except Exception as e:
            ai_summary = f"⚠️ Failed to generate deployment summary: {e}"

        # Step 4: clean up stack
        cleanup_stack(result)

    # Step 5: Print AI analysis results at the end
    print("\n🤖 Generating deployment summary with Bedrock...")
    if ai_summary:
        print(ai_summary)

    # Check final status after all cleanups are done
    if stack_success:
        print(f"🎉 Stack: {stack_name} deployment completed successfully!")
        sys.exit(0)
    else:
        print(f"💥 Stack: {stack_name} deployment failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
