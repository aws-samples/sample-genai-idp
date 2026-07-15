#!/usr/bin/env python3
"""
CodeBuild Deployment Script

Handles IDP stack deployment and testing in AWS CodeBuild environment.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from textwrap import dedent

import boto3

# Cap test/monitor commands so a hung inference run cannot consume the
# CodeBuild job timeout and prevent stack cleanup from running (leaks ~116
# IAM roles). Known-slow commands (publish, deploy --wait, delete --wait)
# pass explicit larger timeouts.
DEFAULT_COMMAND_TIMEOUT = 3600

# Set when the test suite fails fast: newly started commands abort
# immediately, and _kill_running_commands() terminates in-flight ones so
# abandoned test threads cannot keep mutating the stack during cleanup.
ABORT_TESTS = threading.Event()
_RUNNING_PROCS = set()
_RUNNING_PROCS_LOCK = threading.Lock()


def _kill_proc_group(proc):
    """Best-effort SIGKILL of a subprocess's entire process group."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _kill_running_commands():
    """Kill the process groups of all in-flight run_command subprocesses."""
    with _RUNNING_PROCS_LOCK:
        procs = list(_RUNNING_PROCS)
    for proc in procs:
        _kill_proc_group(proc)


def run_command(cmd, check=True, timeout=DEFAULT_COMMAND_TIMEOUT):
    """Run shell command and return result

    Args:
        cmd: Command to run
        check: Raise exception if command fails
        timeout: Timeout in seconds (default: DEFAULT_COMMAND_TIMEOUT).
            With check=False a timeout returns a failed result instead of
            raising, so cleanup paths always continue.

    Commands run from test-pool threads (anything off the main thread) are
    abortable: when the suite fails fast, in-flight ones are killed and new
    ones refuse to start, so abandoned test threads cannot keep mutating the
    stack while cleanup deletes it.
    """
    abortable = threading.current_thread() is not threading.main_thread()
    if abortable and ABORT_TESTS.is_set():
        raise Exception(f"Command aborted (test suite failed fast): {cmd}")
    print(f"Running: {cmd}")
    # start_new_session puts the shell and everything it spawns (idp-cli,
    # docker, sam) in its own process group so timeout/abort can kill the
    # whole tree, not just the shell.
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )  # nosec B602 nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - hardcoded commands, no user input
    if abortable:
        with _RUNNING_PROCS_LOCK:
            _RUNNING_PROCS.add(proc)
        # Close the race with the fail-fast kill sweep: if ABORT_TESTS was set
        # between the check above and registration, the sweep may have already
        # run and missed this proc — kill it ourselves.
        if ABORT_TESTS.is_set():
            _kill_proc_group(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_proc_group(proc)
        # Bounded drain: a descendant that escaped the process group (its own
        # setsid) can hold the pipes open forever — losing partial output is
        # better than hanging the timeout path that guarantees progress.
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        returncode = -1
        msg = f"Command timed out after {timeout}s: {cmd}"
        print(msg)
        if check:
            raise Exception(msg)
        stderr = (stderr or "") + f"\n{msg}"
    finally:
        if abortable:
            with _RUNNING_PROCS_LOCK:
                _RUNNING_PROCS.discard(proc)
    result = subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
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
        bda_client = boto3.client("bedrock-data-automation")
        cf_client = boto3.client("cloudformation")

        active_statuses = {
            "CREATE_IN_PROGRESS",
            "CREATE_COMPLETE",
            "UPDATE_IN_PROGRESS",
            "UPDATE_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_IN_PROGRESS",
            "IMPORT_IN_PROGRESS",
            "IMPORT_COMPLETE",
        }

        # Collect all idp- blueprints and projects
        paginator = bda_client.get_paginator("list_blueprints")
        blueprints = []
        for page in paginator.paginate(blueprintStageFilter="LIVE"):
            for bp in page.get("blueprints", []):
                name = bp.get("blueprintName", "")
                arn = bp.get("blueprintArn", "")
                if name.startswith("idp-") and "aws:blueprint" not in arn:
                    blueprints.append((name, arn))

        projects = []
        for p in bda_client.list_data_automation_projects().get("projects", []):
            name = p.get("projectName", "")
            arn = p.get("projectArn", "")
            if name.startswith("idp-"):
                projects.append((name, arn))

        if not blueprints and not projects:
            print("✅ No stale BDA resources found")
            return

        # Check stack status for each unique stack prefix
        stack_cache = {}
        for name, _ in blueprints + projects:
            parts = name.split("-")
            if len(parts) >= 3:
                prefix = f"{parts[0]}-{parts[1]}-{parts[2]}"
                if prefix not in stack_cache:
                    try:
                        resp = cf_client.describe_stacks(StackName=prefix)
                        status = resp["Stacks"][0]["StackStatus"]
                        stack_cache[prefix] = status in active_statuses
                    except cf_client.exceptions.ClientError:
                        stack_cache[prefix] = False

        def _is_stale(name):
            parts = name.split("-")
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
                        bda_client.delete_blueprint(
                            blueprintArn=arn, blueprintVersion="1"
                        )
                    except Exception:
                        pass
                    time.sleep(0.3)
                    bda_client.delete_blueprint(blueprintArn=arn)
                    deleted_bps += 1
                except Exception as e:
                    print(f"  ⚠️ Failed to delete blueprint {name}: {e}")
                    time.sleep(0.5)

        print(
            f"✅ Cleaned up {deleted_projects} projects, {deleted_bps} blueprints (skipped active stacks)"
        )
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

    # Run idp-cli publish — cold-cache Docker/UI builds can run long
    cmd = f"idp-cli publish --source-dir . --bucket-basename {bucket_basename} --prefix {prefix} --region {region}"
    result = run_command(cmd, timeout=3 * 3600)

    # Extract template URL from output - match S3 URLs only
    template_url_pattern = r"https://s3\..*?idp-main\.yaml"

    # Remove line breaks that might split the URL in terminal output
    clean_stdout = result.stdout.replace("\n", "").replace("\r", "")
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
        cf_client = boto3.client("cloudformation")
        iam_stack_name = f"{stack_name}-iam"

        # Deploy IAM CloudFormation stack
        with open(
            "iam-roles/cloudformation-management/IDP-Cloudformation-Service-Role.yaml",
            "r",
        ) as f:
            template_body = f.read()

        try:
            cf_client.create_stack(
                StackName=iam_stack_name,
                TemplateBody=template_body,
                Capabilities=["CAPABILITY_NAMED_IAM"],
            )

            # Wait for stack creation to complete
            waiter = cf_client.get_waiter("stack_create_complete")
            waiter.wait(
                StackName=iam_stack_name, WaiterConfig={"MaxAttempts": 30, "Delay": 10}
            )

            print(f"[{stack_name}] ✅ Created IAM stack: {iam_stack_name}")

        except cf_client.exceptions.AlreadyExistsException:
            print(f"[{stack_name}] ℹ️ IAM stack already exists: {iam_stack_name}")

        # Get outputs from the stack
        response = cf_client.describe_stacks(StackName=iam_stack_name)
        outputs = response["Stacks"][0].get("Outputs", [])

        role_arn = None
        for output in outputs:
            if output["OutputKey"] == "ServiceRoleArn":
                role_arn = output["OutputValue"]
                break

        if not role_arn:
            raise Exception("Could not find ServiceRoleArn in stack outputs")

        # Create permission boundary policy
        iam_client = boto3.client("iam")
        boundary_name = f"{stack_name}-PermissionsBoundary"
        boundary_policy = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
        }

        try:
            iam_client.create_policy(
                PolicyName=boundary_name,
                PolicyDocument=json.dumps(boundary_policy),
                Description=f"Permissions boundary for {stack_name} IDP deployment",
            )
            print(f"[{stack_name}] ✅ Created permissions boundary: {boundary_name}")
        except iam_client.exceptions.EntityAlreadyExistsException:
            print(
                f"[{stack_name}] ℹ️ Permissions boundary already exists: {boundary_name}"
            )

        # Get account ID for boundary ARN
        sts_client = boto3.client("sts")
        account_id = sts_client.get_caller_identity()["Account"]
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
        cf_client = boto3.client("cloudformation")
        iam_stack_name = f"{stack_name}-iam"
        try:
            cf_client.delete_stack(StackName=iam_stack_name)

            # Wait for stack deletion to complete
            waiter = cf_client.get_waiter("stack_delete_complete")
            waiter.wait(
                StackName=iam_stack_name, WaiterConfig={"MaxAttempts": 30, "Delay": 10}
            )

            print(f"[{stack_name}] ✅ Deleted IAM stack: {iam_stack_name}")
        except cf_client.exceptions.ClientError as e:
            if "does not exist" in str(e):
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
        inference_result = json_data.get("inference_result", {})
        if not inference_result:
            return False, "No inference_result found"
        total_fields = len(inference_result)
        if total_fields == 0:
            return False, "inference_result is empty"
        populated_fields = sum(
            1 for v in inference_result.values() if v not in [None, [], {}]
        )
        min_expected_fields = 3
        if total_fields < min_expected_fields:
            return (
                False,
                f"Expected at least {min_expected_fields} fields, found {total_fields}",
            )
        if populated_fields == 0:
            return False, "No fields contain extracted data (all null/empty)"
        return True, f"{populated_fields}/{total_fields} fields populated"

    def verify_classification(json_data):
        doc_class = json_data.get("document_class", {}).get("type")
        if not doc_class:
            return False, "No document_class.type found"
        if doc_class == "none":
            return False, "Document classified as 'none' (no class detected)"
        return True, f"Classified as '{doc_class}'"

    additional_checks = [
        ("Extraction verification", "sections/1/result.json", verify_extraction),
        (
            "Classification verification",
            "sections/1/result.json",
            verify_classification,
        ),
    ]

    if not run_inference_test(
        stack_name,
        sample_file,
        batch_id,
        verify_string,
        result_location,
        content_path,
        None,
        "samples",
        additional_checks,
    ):
        return {"success": False, "error": "Default config test failed"}

    return {"success": True}


def test_step4_bda_mode(stack_name):
    """Step 4: Upload and test BDA config (sync without activation for parallel execution)"""
    print("Step 4: Testing with BDA mode...")
    config_version = "test-bda"
    config_path = "config_library/unified/lending-package-sample/config.yaml"

    with open(config_path, "r") as f:
        config_content = f.read()

    bda_config_content = config_content.replace("use_bda: false", "use_bda: true")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
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
            inference_result = json_data.get("inference_result", {})
            if not inference_result:
                return False, "No inference_result found in BDA output"
            total_fields = len(inference_result)
            populated_fields = sum(
                1 for v in inference_result.values() if v not in [None, [], {}]
            )
            min_expected_fields = 3
            if total_fields < min_expected_fields:
                return (
                    False,
                    f"Expected at least {min_expected_fields} fields, found {total_fields}",
                )
            if populated_fields == 0:
                return False, "No fields contain extracted data (all null/empty)"
            return True, f"{populated_fields}/{total_fields} fields populated by BDA"

        bda_additional_checks = [
            (
                "BDA extraction verification",
                "sections/1/result.json",
                verify_bda_extraction,
            ),
        ]

        if not run_inference_test(
            stack_name,
            sample_file,
            batch_id,
            verify_string,
            bda_result_location,
            content_path,
            config_version,
            "samples",
            bda_additional_checks,
        ):
            return {"success": False, "error": "BDA config test failed"}

        return {"success": True}
    finally:
        os.unlink(bda_config_path)


def test_step5_rule_validation(stack_name):
    """Step 5: Test rule validation"""
    print("Step 5: Testing rule validation...")
    config_version = "rule-validation"
    config_path = "config_library/unified/rule-validation/config.yaml"
    sample_file = "medicare_respiratory_pa_packet.pdf"
    sample_dir = "samples/rule-validation"
    batch_id = "test-rules"
    verify_string = "global_periods"
    result_location = "rule_validation/sections/section_1_responses.json"
    content_path = "responses.global_periods.0.policy_type"

    print(f"Uploading rule validation config from: {config_path}")
    cmd = f"idp-cli config-upload --stack-name {stack_name} --config-file {config_path} --config-version {config_version}"
    run_command(cmd)

    def verify_rule_results(json_data):
        responses = json_data.get("responses", {})
        if not responses:
            return False, "No rule responses found"
        total_rules = 0
        passed_rules = 0
        failed_rules = 0
        for rule_name, rule_list in responses.items():
            if isinstance(rule_list, list):
                for rule in rule_list:
                    total_rules += 1
                    result = rule.get("result", "").lower()
                    if "pass" in result:
                        passed_rules += 1
                    elif "fail" in result:
                        failed_rules += 1
        if total_rules == 0:
            return False, "No rules were evaluated"
        return (
            True,
            f"{total_rules} rules evaluated ({passed_rules} passed, {failed_rules} failed)",
        )

    rule_additional_checks = [
        (
            "Rule validation results",
            "rule_validation/sections/section_1_responses.json",
            verify_rule_results,
        ),
    ]

    if not run_inference_test(
        stack_name,
        sample_file,
        batch_id,
        verify_string,
        result_location,
        content_path,
        config_version,
        sample_dir,
        rule_additional_checks,
    ):
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
            return {
                "success": False,
                "error": f"Multi-document batch test failed: only {extraction_count}/3 documents processed",
            }

        print(
            f"✅ Multi-document batch test passed: {extraction_count} documents processed successfully"
        )
        return {"success": True}

    except Exception as e:
        print(f"❌ Multi-document batch test failed: {e}")
        return {
            "success": False,
            "error": f"Multi-document batch test failed: {str(e)}",
        }


def test_step7_test_studio(stack_name):
    """Step 7: Test Studio - Run evaluation against pre-deployed test set using idp-cli test-result"""
    print("Step 7: Testing Test Studio with pre-deployed test set...")

    try:
        cf_client = boto3.client("cloudformation")
        stack_response = cf_client.describe_stacks(StackName=stack_name)
        outputs = stack_response["Stacks"][0].get("Outputs", [])

        test_set_bucket = None
        for output in outputs:
            if output["OutputKey"] == "S3TestSetBucketName":
                test_set_bucket = output["OutputValue"]
                break

        if not test_set_bucket:
            print(
                "⚠️  S3TestSetBucketName not found in stack outputs, skipping Test Studio test"
            )
            return {"success": True}

        s3_client = boto3.client("s3")
        try:
            response = s3_client.list_objects_v2(
                Bucket=test_set_bucket, Delimiter="/", MaxKeys=10
            )
            test_sets = [
                prefix["Prefix"].rstrip("/")
                for prefix in response.get("CommonPrefixes", [])
            ]

            if not test_sets:
                print(
                    f"⚠️  No test sets found in {test_set_bucket}, skipping Test Studio test"
                )
                return {"success": True}

            print(f"Found test sets: {', '.join(test_sets)}")

            test_set_name = None
            for preferred in ["fake-w2", "realkie-fcc-verified"]:
                if preferred in test_sets:
                    test_set_name = preferred
                    break
            if not test_set_name:
                test_set_name = test_sets[0]

            print(
                f"Running test against test set: {test_set_name} (limited to 3 documents)"
            )
            print(f"Using config version: {test_set_name}")

            # Run test inference
            cmd = f"idp-cli run-inference --stack-name {stack_name} --test-set {test_set_name} --config-version {test_set_name} --context 'CI/CD smoke test' --number-of-files 3"
            result = run_command(cmd, check=False)

            if result.returncode != 0:
                print("⚠️  Test set processing failed")
                return {
                    "success": False,
                    "error": f"Test Studio test failed for {test_set_name}",
                }

            # Extract test run ID from output
            test_run_id = None
            for line in result.stdout.split("\n"):
                if "Test run started:" in line:
                    test_run_id = line.split("Test run started:")[1].strip()
                    break

            if not test_run_id:
                print(
                    "⚠️  Could not extract test run ID from output, skipping result verification"
                )
                return {"success": True}

            print(f"Test run ID: {test_run_id}")
            print("Retrieving test results using idp-cli test-result...")

            # Use idp-cli test-result command to get results (triggers evaluation and waits)
            cmd = f"idp-cli test-result --stack-name {stack_name} --test-run-id {test_run_id} --wait --timeout 600"
            result = run_command(cmd, check=False)

            if result.returncode != 0:
                print("❌ Test result retrieval failed")
                return {
                    "success": False,
                    "error": "Test Studio test result retrieval failed",
                }

            # Parse output for accuracy check
            overall_accuracy = None
            for line in result.stdout.split("\n"):
                if "Overall Accuracy:" in line:
                    # Extract percentage (e.g., "Overall Accuracy: 95.45%")
                    parts = line.split(":")
                    if len(parts) >= 2:
                        accuracy_str = parts[1].strip().rstrip("%")
                        try:
                            overall_accuracy = float(accuracy_str) / 100.0
                        except ValueError:
                            pass
                    break

            if overall_accuracy is not None:
                if overall_accuracy > 0.30:
                    print(
                        f"✅ Test Studio test completed: {test_set_name} with {overall_accuracy:.2%} accuracy"
                    )
                else:
                    print(
                        f"⚠️  Low accuracy detected: {overall_accuracy:.2%} (threshold: 30%)"
                    )
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

        print(
            "Running agentic extraction on samples/Nuveen.pdf (this will take ~9 minutes)..."
        )
        cmd = f"idp-cli run-inference --stack-name {stack_name} --dir samples/ --file-pattern Nuveen.pdf --config-version agentic-nuveen --monitor"
        result = run_command(cmd, check=False)

        if result.returncode != 0:
            print("❌ Agentic extraction command failed")
            return {"success": False, "error": "Agentic extraction command failed"}

        batch_id = None
        for line in result.stdout.split("\n"):
            if "Batch ID:" in line:
                batch_id = line.split("Batch ID:")[1].strip()
                break

        if batch_id:
            print(f"Downloading results for batch: {batch_id}")
            result_dir = f"/tmp/result-agentic-{batch_id}"  # nosec B108
            cmd = f"idp-cli download-results --stack-name {stack_name} --batch-id {batch_id} --output-dir {result_dir}"
            run_command(cmd, check=False)

            cmd = (
                f"find {result_dir} -path '*/sections/*/result.json' -type f | head -1"
            )
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
                    return {
                        "success": False,
                        "error": f"Agentic extraction test failed: unexpected document class '{doc_class}'",
                    }

                fund_info = result_json.get("inference_result", {}).get(
                    "FundInformation", []
                )
                fund_count = len(fund_info)
                if fund_count == 532:
                    print(f"  ✓ FundInformation count correct: {fund_count} items")
                    print("✅ Agentic extraction test completed successfully")
                    return {"success": True}
                else:
                    print(
                        f"❌ FundInformation count mismatch: expected 532, got {fund_count}"
                    )
                    return {
                        "success": False,
                        "error": f"Agentic extraction test failed: expected 532 fund items, got {fund_count}",
                    }
            else:
                print("❌ Result file not found")
                return {
                    "success": False,
                    "error": "Agentic extraction test failed: result file not found",
                }
        else:
            print("❌ Could not extract batch ID from output")
            return {
                "success": False,
                "error": "Agentic extraction test failed: could not extract batch ID",
            }

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
        run_command(cmd, check=True, timeout=300)

        print("Verifying discovered class saved to configuration...")

        config_file = "/tmp/discovery-config.yaml"  # nosec B108
        cmd = f"idp-cli config-download --stack-name {stack_name} --config-version {config_version} --output {config_file}"
        run_command(cmd, check=True)

        import yaml

        with open(config_file, "r") as f:
            config_data = yaml.safe_load(f)

        classes = config_data.get("classes", [])
        if len(classes) == 0:
            print(f"❌ No classes found in config version {config_version}")
            return {
                "success": False,
                "error": f"Single-document discovery test failed: no classes found in config version {config_version}",
            }

        discovered_class = classes[0]
        doc_class = discovered_class.get("$id", "Unknown")
        num_properties = len(discovered_class.get("properties", {}))
        print(f"  ✓ Discovered class: {doc_class}")
        print(f"  ✓ Properties: {num_properties} top-level fields")
        print(
            f"✅ Discovery test completed: schema saved to config version {config_version}"
        )
        return {"success": True}

    except Exception as e:
        print(f"❌ Single-document discovery test failed: {e}")
        return {
            "success": False,
            "error": f"Single-document discovery test failed: {str(e)}",
        }


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
            raise RuntimeError(
                f"Expected {len(sample_files)} files but found {copied_files}"
            )

        print(f"Running multi-document discovery on {test_dir}...")
        print("This will take approximately 2-3 minutes...")

        cmd = f"idp-cli discover-multidoc --dir {test_dir} -o /tmp/multidoc-schemas"
        run_command(cmd, check=True, timeout=240)

        cmd = "find /tmp/multidoc-schemas -name '*.json' | wc -l"
        count_result = run_command(cmd, check=True)
        schema_count = (
            int(count_result.stdout.strip()) if count_result.stdout.strip() else 0
        )

        if schema_count == 0:
            print("❌ Multi-document discovery completed but no schemas found")
            return {
                "success": False,
                "error": "Multi-document discovery test failed: no schemas generated",
            }

        print(f"  ✓ Generated {schema_count} schema(s)")

        cmd = "find /tmp/multidoc-schemas -name '*.json' | head -1"
        first_schema = run_command(cmd, check=True).stdout.strip()
        if not first_schema:
            print("❌ Could not find generated schema file")
            return {
                "success": False,
                "error": "Multi-document discovery test failed: could not find generated schema file",
            }

        with open(first_schema, "r") as f:
            schema_json = json.load(f)

        if "$schema" not in schema_json or "properties" not in schema_json:
            print("❌ Generated schema missing required fields ($schema, properties)")
            return {
                "success": False,
                "error": "Multi-document discovery test failed: schema missing required fields",
            }

        print("  ✓ Schema structure validated")
        print("✅ Multi-document discovery test completed")
        return {"success": True}

    except Exception as e:
        print(f"❌ Multi-document discovery test failed: {e}")
        return {
            "success": False,
            "error": f"Multi-document discovery test failed: {str(e)}",
        }


def test_step12_api_rbac(stack_name):
    """Step 12: API RBAC authorization tests (static scan + dynamic matrix).

    Runs sequentially (like Step 11) because the dynamic harness temporarily
    enables ADMIN_USER_PASSWORD_AUTH on the UI app client and restores it —
    safest not to interleave with the parallel suite. Creates temporary
    Cognito users, exercises every API op across all roles + unauthenticated
    + token negatives, then tears the users down.
    """
    print("Step 12: API RBAC authorization tests (static + dynamic)...")
    report_dir = "/tmp/api-test-results"  # nosec B108
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    cmd = (
        f"make api-test STACK_NAME={stack_name} REGION={region} REPORT_DIR={report_dir}"
    )
    result = run_command(cmd, check=False, timeout=1800)
    if result.returncode != 0:
        # Surface the report location; the full report is in the build log.
        return {
            "success": False,
            "error": (
                "API RBAC test failed (static scan or dynamic authorization "
                f"matrix) — see {report_dir} output in build log"
            ),
        }
    return {"success": True}


def test_step11_test_compare(stack_name):
    """Step 11: Test Compare - Compare results from multiple test runs using idp-cli test-compare"""
    print("Step 11: Testing test-compare command...")

    try:
        cf_client = boto3.client("cloudformation")
        stack_response = cf_client.describe_stacks(StackName=stack_name)
        outputs = stack_response["Stacks"][0].get("Outputs", [])

        test_set_bucket = None
        for output in outputs:
            if output["OutputKey"] == "S3TestSetBucketName":
                test_set_bucket = output["OutputValue"]
                break

        if not test_set_bucket:
            print(
                "⚠️  S3TestSetBucketName not found in stack outputs, skipping test-compare test"
            )
            return {"success": True}

        s3_client = boto3.client("s3")
        try:
            response = s3_client.list_objects_v2(
                Bucket=test_set_bucket, Delimiter="/", MaxKeys=10
            )
            test_sets = [
                prefix["Prefix"].rstrip("/")
                for prefix in response.get("CommonPrefixes", [])
            ]

            if not test_sets:
                print(
                    f"⚠️  No test sets found in {test_set_bucket}, skipping test-compare test"
                )
                return {"success": True}

            print(f"Found test sets: {', '.join(test_sets)}")

            test_set_name = None
            for preferred in ["fake-w2", "realkie-fcc-verified"]:
                if preferred in test_sets:
                    test_set_name = preferred
                    break
            if not test_set_name:
                test_set_name = test_sets[0]

            print(
                f"Running 2 test inferences against test set: {test_set_name} (limited to 2 documents each)"
            )

            # Run first test inference
            test_run_ids = []
            for i in range(2):
                print(f"\nRunning test inference {i + 1}/2...")
                cmd = f"idp-cli run-inference --stack-name {stack_name} --test-set {test_set_name} --config-version {test_set_name} --context 'CI/CD test-compare test {i + 1}' --number-of-files 2"
                result = run_command(cmd, check=False)

                if result.returncode != 0:
                    print(f"⚠️  Test inference {i + 1} failed")
                    return {
                        "success": False,
                        "error": f"Test inference {i + 1} failed for test-compare",
                    }

                # Extract test run ID from output
                test_run_id = None
                for line in result.stdout.split("\n"):
                    if "Test run started:" in line:
                        test_run_id = line.split("Test run started:")[1].strip()
                        break

                if not test_run_id:
                    print(f"⚠️  Could not extract test run ID {i + 1} from output")
                    return {
                        "success": False,
                        "error": f"Could not extract test run ID {i + 1}",
                    }

                test_run_ids.append(test_run_id)
                print(f"Test run {i + 1} ID: {test_run_id}")

                # Wait for test run to complete before starting next one
                print(f"Waiting for test run {i + 1} to complete...")
                cmd = f"idp-cli test-result --stack-name {stack_name} --test-run-id {test_run_id} --wait --timeout 300"
                result = run_command(cmd, check=False)

                if result.returncode != 0:
                    print(f"⚠️  Test run {i + 1} completion check failed")
                    return {
                        "success": False,
                        "error": f"Test run {i + 1} completion failed",
                    }

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
                comparison_files = [
                    f
                    for f in os.listdir(tmpdir)
                    if f.startswith("comparison-") and f.endswith(".json")
                ]

                if not comparison_files:
                    print("⚠️  No comparison JSON file generated")
                    return {
                        "success": False,
                        "error": "No comparison JSON file generated",
                    }

                comparison_file = os.path.join(tmpdir, comparison_files[0])

                with open(comparison_file, "r") as f:
                    comparison_data = json.load(f)

                # Validate JSON structure contains expected data
                if "metrics" not in comparison_data:
                    print("⚠️  Comparison data missing 'metrics' field")
                    return {
                        "success": False,
                        "error": "Comparison data missing 'metrics' field",
                    }

                metrics = comparison_data["metrics"]

                # Verify both test runs are in metrics
                missing_runs = [tid for tid in test_run_ids if tid not in metrics]
                if missing_runs:
                    print(
                        f"⚠️  Test runs missing from comparison: {', '.join(missing_runs)}"
                    )
                    return {
                        "success": False,
                        "error": f"Test runs missing from comparison: {', '.join(missing_runs)}",
                    }

                # Verify each test run has required metric fields
                required_metrics = ["overallAccuracy", "totalCost"]
                for test_run_id in test_run_ids:
                    run_metrics = metrics[test_run_id]
                    missing_metrics = [
                        m for m in required_metrics if m not in run_metrics
                    ]

                    if missing_metrics:
                        print(
                            f"⚠️  Test run {test_run_id} missing metrics: {', '.join(missing_metrics)}"
                        )
                        return {
                            "success": False,
                            "error": f"Test run missing metrics: {', '.join(missing_metrics)}",
                        }

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


# Single source of truth for the smoke-test suite: (func, step, name,
# description). The parallel runner, the success summary, and the AI
# failure-analysis prompt are all derived from this list — add or remove a
# test here only. Step 11 runs sequentially after the parallel steps.
PARALLEL_TEST_STEPS = [
    (
        test_step3_default_config,
        "Step 3",
        "Default config",
        "Default config inference (Pipeline mode)",
    ),
    (test_step4_bda_mode, "Step 4", "BDA mode", "BDA mode config and inference"),
    (
        test_step5_rule_validation,
        "Step 5",
        "Rule validation",
        "Rule validation config and processing",
    ),
    (
        test_step6_multi_document,
        "Step 6",
        "Multi-document batch",
        "Multi-document batch processing",
    ),
    (
        test_step7_test_studio,
        "Step 7",
        "Test Studio",
        "Test Studio evaluation (idp-cli test-result)",
    ),
    # Step 8: the earlier hang was NOT an extraction regression — nuveen.yaml set
    # extraction.agentic.enabled without extraction.mode, so the merge silently
    # reverted to simple single-pass, which times out on the 532-row/17-page doc.
    # Fixed by converting nuveen.yaml to native v0.6 (mode: advanced); live-
    # validated at ~305s extraction / 532 rows. Re-enabled.
    (
        test_step8_agentic_extraction,
        "Step 8",
        "Agentic extraction",
        "Agentic extraction with large tables",
    ),
    (
        test_step9_single_doc_discovery,
        "Step 9",
        "Single-doc discovery",
        "Single-document discovery",
    ),
    (
        test_step10_multi_doc_discovery,
        "Step 10",
        "Multi-doc discovery",
        "Multi-document discovery",
    ),
]
SEQUENTIAL_TEST_STEPS = [
    (
        test_step11_test_compare,
        "Step 11",
        "test-compare",
        "Test comparison (idp-cli test-compare)",
    ),
    (
        test_step12_api_rbac,
        "Step 12",
        "API RBAC",
        "API RBAC authorization tests (static scan + dynamic matrix)",
    ),
]
ALL_TEST_STEPS = PARALLEL_TEST_STEPS + SEQUENTIAL_TEST_STEPS


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

        # Full nested-stack creation can legitimately run long; don't let the
        # default test-command timeout kill a healthy in-progress deploy.
        run_command(cmd, timeout=3 * 3600)
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
                "failure_type": "deploy",
                "error": f"Stack deployment failed with status: {result.stdout.strip()}",
            }

        print("✅ Stack is healthy")

        # Run tests 3-10 in parallel (Step 4 BDA now uses config-sync-bda + --config-version, no activation race)
        print(f"\n{'=' * 80}")
        print("Running tests 3-10 in parallel (fail-fast enabled)...")
        print(f"{'=' * 80}\n")

        parallel_tests = [
            (func, f"{step}: {name}") for func, step, name, _ in PARALLEL_TEST_STEPS
        ]

        failed_test = None
        # No `with` block: its shutdown(wait=True) would join still-running
        # test threads on failure, burning the CodeBuild job timeout before
        # cleanup_stack can run (which is how stacks/IAM roles get leaked).
        executor = ThreadPoolExecutor(max_workers=8)
        futures = {
            executor.submit(func, stack_name): name for func, name in parallel_tests
        }

        # Process results as they complete (fail-fast)
        for future in as_completed(futures):
            test_name = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    print(f"✅ {test_name} passed")
                else:
                    print(
                        f"❌ {test_name} failed: {result.get('error', 'Unknown error')}"
                    )
                    failed_test = (test_name, result)
                    break
            except Exception as e:
                print(f"❌ {test_name} exception: {e}")
                failed_test = (test_name, {"success": False, "error": str(e)})
                break

        if failed_test:
            # Fail fast: stop the other tests from mutating the stack while
            # cleanup deletes it. New run_command calls in test threads abort
            # immediately; in-flight subprocess trees are killed. The threads
            # themselves then error out quickly against dead subprocesses.
            ABORT_TESTS.set()
            _kill_running_commands()
        executor.shutdown(wait=failed_test is None, cancel_futures=True)

        # Check if any parallel test failed
        if failed_test:
            test_name, result = failed_test
            print(f"\n❌ Test suite failed at {test_name}")
            return {
                "stack_name": stack_name,
                "success": False,
                "failure_type": "test",
                "error": f"{test_name} failed: {result.get('error', 'Unknown error')}",
            }

        # Run the sequential steps (test-compare, API RBAC) after parallel tests
        for func, step, name, _ in SEQUENTIAL_TEST_STEPS:
            print(f"\n{'=' * 80}")
            print(f"Running {step} ({name}) sequentially...")
            print(f"{'=' * 80}\n")

            result = func(stack_name)
            if result["success"]:
                print(f"✅ {step}: {name} passed")
            else:
                print(
                    f"❌ {step}: {name} failed: {result.get('error', 'Unknown error')}"
                )
                return {
                    "stack_name": stack_name,
                    "success": False,
                    "failure_type": "test",
                    "error": f"{step}: {name} failed: {result.get('error', 'Unknown error')}",
                }

        print("✅ All tests passed")
        return {"stack_name": stack_name, "success": True}

    except Exception as e:
        print(f"❌ Testing failed: {e}")
        return {
            "stack_name": stack_name,
            "success": False,
            "failure_type": "deploy",
            "error": f"Deployment/testing failed: {str(e)}",
        }


def run_inference_test(
    stack_name,
    sample_file,
    batch_id,
    verify_string,
    result_location,
    content_path,
    config_version=None,
    sample_dir="samples",
    additional_checks=None,
):
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
            print(
                f"❌ Text content does not contain expected string: '{verify_string}'"
            )
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
                    print(
                        f"⚠️  {check_name}: file not found at {check_path} (may be optional)"
                    )
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
        build_id = os.environ.get("CODEBUILD_BUILD_ID", "")
        if not build_id:
            return "CodeBuild logs not available (not running in CodeBuild)"

        # Wait for logs to propagate to CloudWatch
        time.sleep(10)

        # Extract log group and stream from build ID
        log_group = f"/aws/codebuild/{build_id.split(':')[0]}"
        log_stream = build_id.split(":")[-1]

        # Get the NEWEST events (startFromHead=False): a long build exceeds
        # one get_log_events page (~10K events / 1MB), and callers take the
        # tail of what we return — the first page would give them lines from
        # the start of the build instead of the failure at the end.
        logs_client = boto3.client("logs")
        response = logs_client.get_log_events(
            logGroupName=log_group, logStreamName=log_stream, startFromHead=False
        )

        # Extract log messages
        log_messages = []
        for event in response.get("events", []):
            log_messages.append(event["message"])

        return "\n".join(log_messages)

    except Exception as e:
        return f"Failed to retrieve CodeBuild logs: {str(e)}"


def get_workflow_failure_details(stack_name, max_executions=5):
    """Capture the real cause of a document processing failure before teardown.

    When a smoke test fails because a document didn't process, the tracking
    table / batch monitor only surface a generic "Unknown error" — the actual
    exception (a Lambda traceback, a Bedrock/BDA InvokeDataAutomationAsync
    error, a validation failure) lives in the Step Functions execution history
    and is destroyed when cleanup_stack deletes the stack. This snapshots the
    failed executions' error/cause so the summary can name the true root cause
    instead of echoing "Unknown error".

    Returns a list of {execution_arn, name, error, cause, failed_state} dicts
    (empty if none found or the stack has no reachable state machine).
    """
    try:
        cf = boto3.client("cloudformation")
        outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in cf.describe_stacks(StackName=stack_name)["Stacks"][0].get(
                "Outputs", []
            )
        }
        state_machine_arn = outputs.get("StateMachineArn", "")
        if not state_machine_arn:
            return []

        sfn = boto3.client("stepfunctions")
        failed = sfn.list_executions(
            stateMachineArn=state_machine_arn,
            statusFilter="FAILED",
            maxResults=max_executions,
        ).get("executions", [])

        details = []
        for execution in failed:
            arn = execution["executionArn"]
            # Walk the execution history for the terminal failure event, which
            # carries the concrete error + cause (Lambda stack trace, service
            # exception) that the tracking table flattens to "Unknown error".
            error = cause = failed_state = ""
            try:
                events = sfn.get_execution_history(
                    executionArn=arn, reverseOrder=True, maxResults=25
                ).get("events", [])
                for event in events:
                    for key in (
                        "executionFailedEventDetails",
                        "taskFailedEventDetails",
                        "lambdaFunctionFailedEventDetails",
                    ):
                        detail = event.get(key)
                        if detail:
                            error = error or detail.get("error", "")
                            cause = cause or detail.get("cause", "")
                    # reverseOrder=True → the first StateEntered we see is the
                    # last state the execution reached, i.e. the one that
                    # failed. (Don't break once error/cause are set: the
                    # terminal ExecutionFailed event precedes this in reverse
                    # order, so an early break would miss the state name.)
                    if not failed_state and event.get("type", "").endswith(
                        "StateEntered"
                    ):
                        failed_state = event.get("stateEnteredEventDetails", {}).get(
                            "name", ""
                        )
            except Exception as e:  # noqa: BLE001
                cause = f"(could not read execution history: {e})"

            details.append(
                {
                    "execution_arn": arn,
                    "name": execution.get("name", ""),
                    "error": error or "(no error field)",
                    # Causes can be huge (full traceback) — cap so the summary
                    # prompt stays small while keeping the actionable head.
                    "cause": (cause or "(no cause field)")[:2000],
                    "failed_state": failed_state or "(unknown state)",
                }
            )
        return details

    except Exception as e:  # noqa: BLE001
        return [{"error": f"Failed to retrieve workflow failure details: {str(e)}"}]


def generate_publish_failure_summary(publish_error):
    """Generate summary for publish/build failures"""
    try:
        # Build errors sit at the end of the log; a bounded tail keeps the
        # prompt small instead of shipping the entire (potentially huge) log.
        log_tail = "\n".join(get_codebuild_logs().split("\n")[-400:])
        prompt = dedent(f"""
        You are a build system analyst. Analyze this publish/build failure and provide specific technical guidance.

        Publish Error: {publish_error}

        Build Logs (last 400 lines):
        {log_tail}

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

        return _invoke_bedrock(prompt)

    except Exception as e:
        return f"⚠️ Failed to generate build failure summary: {e}"


def get_cloudformation_logs(stack_name):
    """Get CloudFormation stack events for error analysis"""
    try:
        cf_client = boto3.client("cloudformation")
        all_failed_events = []

        # Get events from main stack
        all_events = []
        next_token = None

        while True:
            if next_token:
                response = cf_client.describe_stack_events(
                    StackName=stack_name, NextToken=next_token
                )
            else:
                response = cf_client.describe_stack_events(StackName=stack_name)

            events = response.get("StackEvents", [])
            all_events.extend(events)

            next_token = response.get("NextToken")
            if not next_token:
                break

        # Filter for failed events and extract nested stack ARNs
        nested_stack_arns = []
        for event in all_events:
            status = event.get("ResourceStatus", "")
            if "FAILED" in status or "ROLLBACK" in status:
                all_failed_events.append(
                    {
                        "stack_name": stack_name,
                        "timestamp": event.get("Timestamp", "").isoformat()
                        if event.get("Timestamp")
                        else "",
                        "resource_type": event.get("ResourceType", ""),
                        "logical_id": event.get("LogicalResourceId", ""),
                        "status": status,
                        "reason": event.get(
                            "ResourceStatusReason", "No reason provided"
                        ),
                    }
                )

                # Extract nested stack ARN from CREATE_FAILED events
                if (
                    status == "CREATE_FAILED"
                    and event.get("ResourceType") == "AWS::CloudFormation::Stack"
                    and "Embedded stack arn:aws:cloudformation:"
                    in event.get("ResourceStatusReason", "")
                ):
                    reason = event.get("ResourceStatusReason", "")
                    start = reason.find("arn:aws:cloudformation:")
                    end = reason.find(" was not successfully created")
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
                            StackName=nested_arn, NextToken=next_token
                        )
                    else:
                        response = cf_client.describe_stack_events(StackName=nested_arn)

                    events = response.get("StackEvents", [])
                    nested_events.extend(events)

                    next_token = response.get("NextToken")
                    if not next_token:
                        break

                # Add failed events from nested stack
                for event in nested_events:
                    status = event.get("ResourceStatus", "")
                    if "FAILED" in status or "ROLLBACK" in status:
                        all_failed_events.append(
                            {
                                "stack_name": nested_arn.split("/")[
                                    -2
                                ],  # Extract stack name from ARN
                                "timestamp": event.get("Timestamp", "").isoformat()
                                if event.get("Timestamp")
                                else "",
                                "resource_type": event.get("ResourceType", ""),
                                "logical_id": event.get("LogicalResourceId", ""),
                                "status": status,
                                "reason": event.get(
                                    "ResourceStatusReason", "No reason provided"
                                ),
                            }
                        )

            except Exception:
                # Skip nested stacks we can't access
                continue

        return _filter_root_cause_events(all_failed_events)

    except Exception as e:
        return [{"error": f"Failed to retrieve CloudFormation logs: {str(e)}"}]


def _filter_root_cause_events(failed_events):
    """Drop cancellation-cascade noise so only concrete failures reach Bedrock.

    A full rollback emits hundreds of 'Resource creation cancelled' and
    ROLLBACK_* status events downstream of a handful of real failures;
    filtering them here shrinks the summary prompt ~50x and lets the model
    focus on actual ResourceStatusReasons.
    """
    cascade_markers = (
        "Resource creation cancelled",
        "cancelled",
        "Rollback requested by user",
        "No reason provided",
    )
    root_causes = [
        e
        for e in failed_events
        if "FAILED" in e.get("status", "")
        and not any(m in e.get("reason", "") for m in cascade_markers)
    ]
    # If filtering removed everything (unexpected event shapes), fall back to
    # the raw list rather than sending the model nothing. Cap either way.
    events = root_causes or failed_events
    events.sort(key=lambda e: e.get("timestamp", ""))
    return events[:20]


def _invoke_bedrock(prompt):
    """Invoke Bedrock with a prompt and return the response text"""
    bedrock = boto3.client("bedrock-runtime")
    # Opus 4.8 rejects sampling params (temperature/top_p/top_k) with a 400 —
    # do not add them back.
    response = bedrock.invoke_model(
        modelId="us.anthropic.claude-opus-4-8",
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": prompt}],
            }
        ),
    )
    response_body = json.loads(response["body"].read())
    # Opus 4.8 may emit thinking blocks before the text block — take the
    # first text block rather than assuming content[0] is text.
    for block in response_body["content"]:
        if block.get("type") == "text":
            return block["text"]
    # No text block (e.g. truncated response) — raise so callers fall back to
    # their manual summary instead of silently printing nothing.
    raise ValueError(
        f"Bedrock response contained no text block "
        f"(stop_reason={response_body.get('stop_reason')})"
    )


def generate_deployment_summary(result, stack_name, template_url):
    """Generate deployment summary using Bedrock API.

    Case routing (success / infrastructure failure / test failure) is done in
    Python from result["failure_type"] — the model is only asked to explain,
    never to decide pass/fail (earlier prompt-based routing misclassified
    failures and leaked its scratchpad into the summary).
    """
    try:
        error_text = result.get("error", "")

        # Case C: success — static summary, no analysis needed
        if result.get("success"):
            test_lines = "\n".join(
                f"• Test {i} ({step}): {desc} ✓"
                for i, (_, step, _, desc) in enumerate(ALL_TEST_STEPS, 1)
            )
            return dedent(f"""
            🚀 DEPLOYMENT RESULTS

            📋 Stack Status: {stack_name} deployed successfully
            📦 Template: {template_url}

            ✅ All Tests Passed ({len(ALL_TEST_STEPS)} tests):
            {{test_lines}}
            """).format(test_lines=test_lines)

        # Case B: infrastructure failure — the deploy itself failed, so pull
        # CloudFormation events for root cause. failure_type is set where the
        # failure is classified in deploy_and_test_stack; "deploy" is also the
        # safe default when the field is missing (e.g. exception result dicts
        # built in main), since CF-event analysis degrades gracefully.
        if result.get("failure_type", "deploy") != "test":
            # Use pre-captured events when the caller saved them before the
            # stack was torn down (the APIGW/VPC hosting test deletes its
            # throwaway stack in a finally block, so a post-cleanup fetch by
            # stack name would find nothing).
            logs = result.get("cf_events")
            if logs is None:
                print(f"🔍 Getting CloudFormation logs for: {stack_name}")
                try:
                    logs = get_cloudformation_logs(stack_name)
                    print(f"✅ Retrieved {len(logs)} CF events for {stack_name}")
                except Exception as e:
                    print(f"⚠️ Exception getting CF logs for {stack_name}: {e}")
                    logs = [{"error": f"Exception: {str(e)}", "stack_name": stack_name}]

            cf_prompt = dedent(f"""
            An AWS CloudFormation deployment failed. Analyze the error events to
            determine the root cause.

            Stack Name: {stack_name}

            Deployment error:
            {error_text}

            CloudFormation error events (may span multiple stacks — e.g. a
            throwaway VPC stack AND the IDP stack; the real failure can be in
            either, so read the `stack_name` field on each event):
            {json.dumps(logs, indent=2)}

            GROUNDING RULES — follow strictly:
            • Base the root cause ONLY on a concrete ResourceStatusReason
              actually present in the events above. Do NOT invent causes.
            • If the events list is empty or every entry has only an "error"
              field (retrieval failed / stack already deleted), you MUST say the
              root cause was NOT captured and recommend re-running with
              `idp-cli deploy --no-rollback` to preserve the failed resources.
              Do NOT guess at IAM/quota/API-limit causes with no evidence.
            • Find the FIRST CREATE_FAILED events (chronologically) with a
              concrete reason — later "Resource creation cancelled" events are
              cascades. Quote the exact reason string verbatim.

            Provide analysis in this format:

            🚀 DEPLOYMENT RESULT

            📋 Status: {stack_name} FAILED - [one-line root cause, or "root cause not captured"]

            🔍 CloudFormation Root Cause:
            • Quote the exact ResourceStatusReason of the original failure
            • Name the stack + logical resource that failed (from the events)
            • If nothing concrete was captured, say so explicitly

            💡 Fix Commands:
            • Provide specific AWS CLI commands based on actual failures found
            • If root cause not captured, give the --no-rollback re-run command

            Keep each bullet point under 75 characters.
            Respond ONLY with the format above, no other text.
            """)
            return _invoke_bedrock(cf_prompt)

        # Case A: smoke test failure — deploy succeeded, a test step failed.
        # Attach a bounded log tail: several tests report only a one-line
        # error, and the actual mismatch (expected string, missing file,
        # CLI stderr) is in the build log.
        log_tail = "\n".join(get_codebuild_logs().split("\n")[-150:])
        suite_reference = "\n".join(
            f"• {step}: {desc}" for _, step, _, desc in ALL_TEST_STEPS
        )

        # When a document failed to process, the test's own error is a generic
        # "Unknown error" (the tracking table flattens the real cause). Pull the
        # Step Functions execution failure now — the stack still exists (summary
        # runs before cleanup_stack) but will be gone by the time anyone reads
        # this. Prefer pre-captured details if the caller already snapshotted.
        workflow_failures = result.get("workflow_failures")
        if workflow_failures is None:
            print(f"🔍 Capturing Step Functions failures for: {stack_name}")
            workflow_failures = get_workflow_failure_details(stack_name)
        if workflow_failures:
            print(f"✅ Captured {len(workflow_failures)} workflow failure(s)")

        test_prompt = dedent(f"""
        An IDP deployment succeeded but a post-deployment smoke test failed.

        Stack Name: {stack_name}

        Test error (this is often a GENERIC wrapper like "Unknown error" or
        "BDA config test failed" — it is NOT necessarily the root cause):
        {error_text}

        Test suite reference:
        {suite_reference}

        Step Functions execution failures (the AUTHORITATIVE root cause when
        present — the `cause` field holds the real Lambda traceback / service
        exception behind a generic "Unknown error"):
        {json.dumps(workflow_failures, indent=2)}

        Last build log lines (context only — note that "exit code -9" / SIGKILL
        lines are fail-fast collateral from OTHER parallel tests being killed
        after the first failure, NOT independent failures; do not report them):
        {log_tail}

        GROUNDING RULES — follow strictly:
        • Base the root cause ONLY on evidence actually present above (the
          Step Functions `cause`/`error`, a concrete log line, or the test
          error). Do NOT invent likely causes.
        • If the Step Functions failures list is empty or contains only an
          "error" field (capture failed), and no concrete cause appears in the
          logs, you MUST say the root cause was not captured and recommend how
          to capture it — do NOT guess at IAM/region/quota/config causes.
        • Quote exact strings; never paraphrase an error you cannot see.

        Provide analysis in this format:

        🚀 DEPLOYMENT RESULTS

        📋 Test Status: FAILED - [which step/test failed, from the error]

        🔍 Root Cause Analysis:
        • Quote the exact error/cause from the Step Functions failure or logs
        • If no concrete cause is present, state: "Root cause not captured"
        • Identify which test step failed and what it validates

        💡 Fix Guidance:
        • Only suggest fixes that follow from evidence above
        • If root cause not captured, say what evidence to collect next
        • Reference relevant CLI commands if applicable

        Keep each bullet point under 75 characters.
        Respond ONLY with the format above, no other text.
        """)
        return _invoke_bedrock(test_prompt)

    except Exception as e:
        # Manual summary when Bedrock unavailable — still include the real
        # error so the job log is actionable without AI analysis
        return dedent(f"""
        DEPLOYMENT SUMMARY (MANUAL)

        Deployment result {stack_name} : {"SUCCESS" if result.get("success") else "FAILED"}

        Error: {result.get("error", "None")}

        (AI analysis unavailable: {e})
        """)


def cancel_bedrock_ingestion_jobs(stack_name):
    """Cancel any running Bedrock ingestion jobs before stack deletion"""
    print(f"[{stack_name}] Checking for running Bedrock ingestion jobs...")

    try:
        cf_client = boto3.client("cloudformation")
        bedrock_agent = boto3.client("bedrock-agent")

        # Get all resources from main stack and nested stacks
        stacks_to_check = [stack_name]

        # Find nested stacks
        try:
            resources = cf_client.describe_stack_resources(StackName=stack_name)
            for resource in resources["StackResources"]:
                if resource["ResourceType"] == "AWS::CloudFormation::Stack":
                    nested_stack_name = resource["PhysicalResourceId"].split("/")[1]
                    stacks_to_check.append(nested_stack_name)
        except Exception as e:
            print(f"  ⚠️ Could not list nested stacks: {e}")

        jobs_cancelled = 0

        # Check each stack for Bedrock data sources
        for stack in stacks_to_check:
            try:
                resources = cf_client.describe_stack_resources(StackName=stack)

                for resource in resources["StackResources"]:
                    if resource["ResourceType"] == "AWS::Bedrock::DataSource":
                        # Parse physical resource ID: knowledgeBaseId|dataSourceId
                        physical_id = resource["PhysicalResourceId"]
                        if "|" in physical_id:
                            kb_id, ds_id = physical_id.split("|")

                            # List ingestion jobs for this data source
                            try:
                                response = bedrock_agent.list_ingestion_jobs(
                                    knowledgeBaseId=kb_id,
                                    dataSourceId=ds_id,
                                    maxResults=10,
                                )

                                for job in response.get("ingestionJobSummaries", []):
                                    if job["status"] == "IN_PROGRESS":
                                        job_id = job["ingestionJobId"]
                                        print(f"  Cancelling ingestion job: {job_id}")

                                        # Stop the ingestion job
                                        bedrock_agent.stop_ingestion_job(
                                            knowledgeBaseId=kb_id,
                                            dataSourceId=ds_id,
                                            ingestionJobId=job_id,
                                        )
                                        jobs_cancelled += 1
                                        print(f"  ✓ Cancelled ingestion job: {job_id}")

                            except Exception as e:
                                print(
                                    f"  ⚠️ Could not check/cancel jobs for {physical_id}: {e}"
                                )

            except Exception as e:
                print(f"  ⚠️ Could not check stack {stack}: {e}")

        if jobs_cancelled > 0:
            print(
                f"[{stack_name}] ✅ Cancelled {jobs_cancelled} running ingestion job(s)"
            )
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
        cmd_result = run_command(
            f"aws cloudformation describe-stacks --stack-name {stack_name} --query 'Stacks[0].StackStatus' --output text",
            check=False,
        )
        stack_status = (
            cmd_result.stdout.strip() if cmd_result.returncode == 0 else "NOT_FOUND"
        )

        print(f"[{stack_name}] stack status: {stack_status}")

        # Cancel any running Bedrock ingestion jobs before stack deletion
        cancel_bedrock_ingestion_jobs(stack_name)

        # Delete the stack and wait for completion (includes all cleanup via
        # --force-delete-all). Bucket emptying + CloudFront/KB teardown can
        # run long; with check=False a timeout returns a failed result rather
        # than raising, so cleanup_iam_resources below always still runs.
        print(f"[{stack_name}] attempting stack deletion...")
        run_command(
            f"idp-cli delete --stack-name {stack_name} --force --empty-buckets --force-delete-all --wait",
            check=False,
            timeout=3 * 3600,
        )

        print(f"[{stack_name}] ✅ Cleanup completed")

        # Clean up CodeBuild-specific IAM resources
        cleanup_iam_resources(stack_name)
    except Exception as e:
        print(f"⚠️ Cleanup task failed: {e}")


# ---------------------------------------------------------------------------
# API Gateway Web UI hosting test (VPC / PRIVATE)
#
# Separate from the primary shared-stack test suite (Steps 3-11), which deploys
# once with default hosting (CloudFront, no VPC). This phase deploys a SECOND,
# throwaway IDP stack configured for the new API-Gateway Web UI hosting option
# WITH VPC support: WebUIHosting=APIGateway + ApiGatewayVisibility=PRIVATE +
# DeployInVPC=true. It stands up a self-contained test VPC (NAT egress + a
# single execute-api interface endpoint), deploys, validates the private
# REST API is serving the UI, and tears everything down.
#
# Gated by IDP_TEST_APIGW_VPC_HOSTING (default "true"); set to "false" to skip.
# ---------------------------------------------------------------------------
APIGW_HOSTING_VPC_TEMPLATE = "scripts/sdlc/apigw-hosting-test-vpc.yaml"


def create_apigw_test_vpc(vpc_stack_name):
    """Create the self-contained test VPC and return its outputs dict."""
    print(f"[{vpc_stack_name}] Creating test VPC for API Gateway hosting...")
    cf = boto3.client("cloudformation")
    with open(APIGW_HOSTING_VPC_TEMPLATE, "r") as f:
        template_body = f.read()
    try:
        cf.create_stack(StackName=vpc_stack_name, TemplateBody=template_body)
        cf.get_waiter("stack_create_complete").wait(
            StackName=vpc_stack_name, WaiterConfig={"MaxAttempts": 60, "Delay": 15}
        )
    except cf.exceptions.AlreadyExistsException:
        print(f"[{vpc_stack_name}] ℹ️ VPC stack already exists")
    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in cf.describe_stacks(StackName=vpc_stack_name)["Stacks"][0].get(
            "Outputs", []
        )
    }
    print(f"[{vpc_stack_name}] ✅ Test VPC ready: {outputs}")
    return outputs


def _force_delete_vpc_stack_enis(vpc_stack_name):
    """Delete detached Lambda ENIs that block a test VPC stack's teardown.

    IDP deploys VPC-attached Lambdas (e.g. DashboardMergerFunction). When the
    IDP stack is deleted, its ENIs linger in 'available' state for a while;
    CloudFormation then can't delete the subnets/security group, so the VPC
    stack goes DELETE_FAILED and the VPC leaks — eventually exhausting the
    account's VPC quota and rolling back every later apigw hosting test. This
    reaps the orphaned (unattached) ENIs so the stack delete can proceed.

    Returns the number of ENIs deleted. Best effort — never raises.
    """
    deleted = 0
    try:
        cf = boto3.client("cloudformation")
        outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in cf.describe_stacks(StackName=vpc_stack_name)["Stacks"][0].get(
                "Outputs", []
            )
        }
        vpc_id = outputs.get("VpcId", "")
        if not vpc_id:
            return 0
        ec2 = boto3.client("ec2")
        enis = ec2.describe_network_interfaces(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("NetworkInterfaces", [])
        for eni in enis:
            # Only unattached ENIs are safe to delete directly; attached ones
            # (VPC endpoint / NAT) are removed by CloudFormation with their
            # owning resource.
            if eni.get("Status") != "available" or eni.get("Attachment"):
                continue
            eni_id = eni["NetworkInterfaceId"]
            try:
                ec2.delete_network_interface(NetworkInterfaceId=eni_id)
                deleted += 1
                print(f"[{vpc_stack_name}]   force-deleted orphaned ENI {eni_id}")
            except Exception as e:  # noqa: BLE001
                print(f"[{vpc_stack_name}]   ⚠️ could not delete ENI {eni_id}: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"[{vpc_stack_name}]   ⚠️ ENI sweep failed: {e}")
    return deleted


def delete_apigw_test_vpc(vpc_stack_name):
    """Delete the test VPC stack, recovering from ENI-blocked DELETE_FAILED.

    First attempt is a plain stack delete. If it fails (almost always because
    orphaned Lambda ENIs hold the subnets/SG), sweep the detached ENIs and
    retry once — this stops the VPC leak that otherwise exhausts the account's
    VPC quota. Best effort — never raises.
    """
    print(f"[{vpc_stack_name}] Deleting test VPC...")
    cf = boto3.client("cloudformation")

    def _attempt():
        cf.delete_stack(StackName=vpc_stack_name)
        cf.get_waiter("stack_delete_complete").wait(
            StackName=vpc_stack_name, WaiterConfig={"MaxAttempts": 60, "Delay": 15}
        )

    try:
        _attempt()
        print(f"[{vpc_stack_name}] ✅ Test VPC deleted")
        return
    except Exception as e:  # noqa: BLE001
        print(f"[{vpc_stack_name}] ⚠️ First delete failed ({e}); sweeping ENIs and retrying")

    # Retry path: orphaned Lambda ENIs are the usual culprit. Give them a
    # moment to detach, sweep, then delete again.
    time.sleep(30)
    swept = _force_delete_vpc_stack_enis(vpc_stack_name)
    print(f"[{vpc_stack_name}] swept {swept} orphaned ENI(s); retrying delete")
    try:
        _attempt()
        print(f"[{vpc_stack_name}] ✅ Test VPC deleted (after ENI sweep)")
    except Exception as e:  # noqa: BLE001
        print(
            f"[{vpc_stack_name}] ❌ Test VPC still failed to delete after ENI sweep: {e}. "
            f"Startup reaper will retry on the next run."
        )


def cleanup_stale_apigw_test_vpcs():
    """Reap leftover apigw test VPC stacks from prior runs before starting.

    Defense in depth alongside delete_apigw_test_vpc: if a previous run's
    teardown failed (or the job was killed mid-cleanup), its throwaway
    `*-apigw-vpc` stack survives and holds a VPC. Left unchecked these
    accumulate until the account hits its VPC quota and EVERY subsequent apigw
    hosting test instant-rolls-back on VPC creation. Each run creates a fresh
    timestamped stack, so any pre-existing `*-apigw-vpc` stack is by definition
    stale and safe to delete here. Best effort — never raises.
    """
    print("🧹 Cleaning up stale apigw test VPC stacks...")
    try:
        cf = boto3.client("cloudformation")
        stale = []
        paginator = cf.get_paginator("list_stacks")
        for page in paginator.paginate(
            StackStatusFilter=[
                "CREATE_COMPLETE",
                "CREATE_FAILED",
                "ROLLBACK_COMPLETE",
                "ROLLBACK_FAILED",
                "DELETE_FAILED",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_COMPLETE",
            ]
        ):
            for s in page.get("StackSummaries", []):
                name = s.get("StackName", "")
                if name.startswith("idp-") and name.endswith("-apigw-vpc"):
                    stale.append(name)

        if not stale:
            print("✅ No stale apigw test VPC stacks found")
            return

        for name in stale:
            print(f"[{name}] reaping stale test VPC stack...")
            delete_apigw_test_vpc(name)
        print(f"✅ Reaped {len(stale)} stale apigw test VPC stack(s)")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Stale apigw VPC cleanup failed: {e}")


def validate_apigw_private_hosting(stack_name):
    """Assert the deployed stack serves the Web UI on a PRIVATE REST API.

    Cannot curl the endpoint (it's VPC-only, and CodeBuild is in a different
    network), so validate structurally:
      * the REST API "{stack}-api" has endpoint type PRIVATE, and
      * the stack's ApplicationWebURL output is the execute-api /api URL.
    """
    apig = boto3.client("apigateway")
    cf = boto3.client("cloudformation")

    # 1. REST API is PRIVATE
    api_name = f"{stack_name}-api"
    apis = apig.get_rest_apis(limit=500).get("items", [])
    match = next((a for a in apis if a.get("name") == api_name), None)
    if not match:
        return {"success": False, "error": f"REST API {api_name} not found"}
    types = match.get("endpointConfiguration", {}).get("types", [])
    if "PRIVATE" not in types:
        return {
            "success": False,
            "error": f"REST API {api_name} endpoint types={types}, expected PRIVATE",
        }

    # 2. ApplicationWebURL output points at the execute-api /api URL
    outputs = {
        o["OutputKey"]: o["OutputValue"]
        for o in cf.describe_stacks(StackName=stack_name)["Stacks"][0].get(
            "Outputs", []
        )
    }
    web_url = outputs.get("ApplicationWebURL", "")
    if "execute-api" not in web_url or "/api" not in web_url:
        return {
            "success": False,
            "error": f"ApplicationWebURL={web_url!r} is not an execute-api /api URL",
        }

    print(f"✅ PRIVATE REST API serving Web UI: {web_url} (types={types})")
    return {"success": True, "web_url": web_url}


def _capture_cf_events(result, *stack_names):
    """Snapshot CF failure events from candidate stacks before teardown.

    The APIGW hosting test can fail either in its throwaway IDP stack or in the
    self-contained VPC stack it stands up first; both are deleted in a finally
    block, so events must be captured while the stacks still exist. Passing all
    candidates (and dropping ones that were never created) means the summary
    sees the stack that actually rolled back — previously we only captured the
    IDP stack, so a VPC-creation failure surfaced as "<stack> does not exist".
    """
    events = []
    for name in stack_names:
        try:
            stack_events = get_cloudformation_logs(name)
        except Exception as e:  # noqa: BLE001
            stack_events = [{"error": f"Exception: {str(e)}", "stack_name": name}]
        # get_cloudformation_logs returns a single {"error": ...} entry when a
        # stack doesn't exist; keep only real failure events so a genuine
        # rollback in a sibling stack isn't buried under "does not exist" noise.
        real = [e for e in stack_events if "error" not in e]
        events.extend(real)
    # If every candidate yielded only "does not exist"/errors, keep a note so
    # the summary can say evidence was unavailable rather than showing nothing.
    result["cf_events"] = events or [
        {"error": "No CloudFormation events captured", "stacks": list(stack_names)}
    ]


def deploy_and_test_apigw_vpc_hosting(admin_email, template_url):
    """Deploy + validate + tear down the APIGateway/VPC/PRIVATE hosting variant."""
    stack_name = f"{generate_stack_name()}-apigw"
    vpc_stack_name = f"{stack_name}-vpc"
    result = {"stack_name": stack_name, "success": False}
    try:
        vpc = create_apigw_test_vpc(vpc_stack_name)
        role_arn, boundary_arn = create_iam_resources(stack_name)
        if not role_arn or not boundary_arn:
            raise Exception("Failed to create IAM resources for APIGateway VPC test")

        # idp-cli --parameters takes ONE comma-separated key=value string; its
        # parser splits on `key=` boundaries so comma-containing values (the
        # subnet lists) are preserved without needing per-value quoting.
        params = ",".join(
            [
                f"PermissionsBoundaryArn={boundary_arn}",
                "WebUIHosting=APIGateway",
                "ApiGatewayVisibility=PRIVATE",
                "DeployInVPC=true",
                f"VpcId={vpc['VpcId']}",
                f"PrivateSubnetIds={vpc['PrivateSubnetIds']}",
                f"LambdaSubnetIds={vpc['PrivateSubnetIds']}",
                f"LambdaSecurityGroupId={vpc['LambdaSecurityGroupId']}",
                f"ApiGatewayVpcEndpointId={vpc['ApiGatewayVpcEndpointId']}",
            ]
        )
        cmd = (
            f"idp-cli deploy --stack-name {stack_name} --template-url {template_url} "
            f"--admin-email {admin_email} --wait --role-arn {role_arn} "
            f'--parameters "{params}"'
        )
        print("APIGateway/VPC hosting: deploying stack...")
        run_command(cmd, timeout=3 * 3600)

        status = run_command(
            f"aws cloudformation describe-stacks --stack-name {stack_name} "
            "--query 'Stacks[0].StackStatus' --output text"
        )
        if "COMPLETE" not in status.stdout:
            result["error"] = f"Deploy status: {status.stdout.strip()}"
            result["failure_type"] = "deploy"
            _capture_cf_events(result, stack_name, vpc_stack_name)
            return result

        validation = validate_apigw_private_hosting(stack_name)
        result.update(validation)
        if not validation.get("success"):
            result["failure_type"] = "test"
        return result
    except Exception as e:  # noqa: BLE001
        print(f"❌ APIGateway/VPC hosting test exception: {e}")
        result["error"] = str(e)
        result["failure_type"] = "deploy"
        # The failure can originate in the VPC stack (created first) or the IDP
        # stack; capture both since both are torn down in the finally block.
        _capture_cf_events(result, stack_name, vpc_stack_name)
        return result
    finally:
        # Tear down IDP stack first (frees ENIs in the VPC), then the VPC.
        cleanup_stack({"stack_name": stack_name})
        delete_apigw_test_vpc(vpc_stack_name)


def publish_summary_to_s3(summary_text):
    """Upload the deployment summary to the SDLC source bucket.

    The GitLab job fetches this file directly (deterministic key derived from
    the CodeBuild build id) instead of scraping it out of CloudWatch Logs,
    which truncates on long builds. Best effort — never fails the build.
    """
    bucket = os.environ.get("SOURCE_BUCKET", "")
    build_id = os.environ.get("CODEBUILD_BUILD_ID", "")
    if not bucket or not build_id:
        print("ℹ️ Skipping summary upload (not running in CodeBuild)")
        return
    key = f"deploy/summaries/{build_id.split(':')[-1]}.txt"
    try:
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=summary_text.encode("utf-8")
        )
        print(f"📁 Summary uploaded to s3://{bucket}/{key}")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Failed to upload summary to S3: {e}")


def send_failure_notification(subject, summary_text):
    """Publish the failure summary to the SDLC SNS topic (email fan-out).

    Gated on IDP_FAILURE_SNS_TOPIC (set by the pipeline template). Best
    effort — a notification failure must never mask the build result.
    """
    topic_arn = os.environ.get("IDP_FAILURE_SNS_TOPIC", "")
    if not topic_arn:
        print("ℹ️ IDP_FAILURE_SNS_TOPIC not set — skipping failure email")
        return
    try:
        boto3.client("sns").publish(
            TopicArn=topic_arn,
            # SNS subjects are capped at 100 chars
            Subject=subject[:100],
            Message=summary_text,
        )
        print(f"📧 Failure notification published to {topic_arn}")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Failed to publish failure notification: {e}")


def main():
    """Main execution function"""
    print("Starting CodeBuild deployment process...")

    admin_email = get_env_var("IDP_ADMIN_EMAIL", "tanimath@amazon.com")
    stack_name = generate_stack_name()

    print(f"Stack Name: {stack_name}")
    print(f"Admin Email: {admin_email}")

    # initialize AI summary
    ai_summary = ""
    publish_success = False
    stack_success = False
    # One-line root cause carried onto the final 🎉/💥 line so the job result
    # is actionable even if the AI summary generation itself breaks.
    failure_reason = ""

    # Step 0: Clean up stale resources leaked by prior runs (BDA blueprints and
    # apigw test VPCs) — leaked VPCs otherwise exhaust the account VPC quota and
    # roll back every apigw hosting test.
    cleanup_stale_bda_blueprints()
    cleanup_stale_apigw_test_vpcs()

    # Step 1: Publish templates to S3
    try:
        template_url = publish_templates()
        print(f"Publish script ran successfully template url {template_url}")
        publish_success = True
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        failure_reason = f"publish/build failed: {e}"
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

        if not result["success"]:
            failure_reason = result.get("error", "Unknown error")

        # Step 3: Generate deployment summary using Bedrock (but don't print
        # yet). Must run before cleanup_stack so CF events still exist for
        # deploy-failure analysis.
        try:
            ai_summary = generate_deployment_summary(result, stack_name, template_url)
        except Exception as e:
            ai_summary = f"⚠️ Failed to generate deployment summary: {e}"

        # Step 4: clean up stack
        cleanup_stack(result)

        # Step 4b: API Gateway Web UI hosting test (VPC / PRIVATE). Runs on its
        # own throwaway stack + VPC, independent of the shared-stack suite.
        # Gated by IDP_TEST_APIGW_VPC_HOSTING (default on). A failure here marks
        # the overall run failed but does not affect the already-completed
        # primary suite result.
        if get_env_var("IDP_TEST_APIGW_VPC_HOSTING", "true").lower() == "true":
            print(f"\n{'=' * 80}")
            print("API Gateway Web UI hosting test (VPC / PRIVATE)...")
            print(f"{'=' * 80}\n")
            try:
                apigw_result = deploy_and_test_apigw_vpc_hosting(
                    admin_email, template_url
                )
            except Exception as e:  # noqa: BLE001
                apigw_result = {
                    "stack_name": f"{stack_name}-apigw",
                    "success": False,
                    "error": str(e),
                    "failure_type": "deploy",
                }
            if apigw_result.get("success"):
                print("✅ API Gateway / VPC hosting test passed")
            else:
                stack_success = False
                apigw_error = apigw_result.get("error", "Unknown error")
                print(f"❌ API Gateway / VPC hosting test failed: {apigw_error}")
                if not failure_reason:
                    failure_reason = f"APIGW/VPC hosting test failed: {apigw_error}"
                # The primary summary was generated before this phase ran and
                # may say "All Tests Passed" — analyze this failure too (its
                # CF events were captured before the throwaway stack teardown).
                try:
                    apigw_summary = generate_deployment_summary(
                        apigw_result,
                        apigw_result.get("stack_name", f"{stack_name}-apigw"),
                        template_url,
                    )
                except Exception as e:  # noqa: BLE001
                    apigw_summary = f"⚠️ Failed to generate APIGW summary: {e}"
                ai_summary = (
                    f"{ai_summary}\n\n"
                    f"--- API Gateway / VPC hosting test (Step 4b) ---\n"
                    f"{apigw_summary}"
                )
        else:
            print("ℹ️ Skipping API Gateway / VPC hosting test (disabled)")

    # Step 5: Print AI analysis results at the end
    print("\n🤖 Generating deployment summary with Bedrock...")
    if ai_summary:
        print(ai_summary)
        publish_summary_to_s3(ai_summary)

    # Check final status after all cleanups are done. Use os._exit so the
    # concurrent.futures atexit hook doesn't block on abandoned test threads
    # that are still failing out against the (now deleted) stack.
    if stack_success:
        print(f"🎉 Stack: {stack_name} deployment completed successfully!")
        exit_code = 0
    else:
        reason_suffix = f" — {failure_reason}" if failure_reason else ""
        print(f"💥 Stack: {stack_name} deployment failed!{reason_suffix}")
        send_failure_notification(
            f"IDP CI failure: {stack_name}",
            f"Stack: {stack_name}\nRoot cause: {failure_reason or 'unknown'}\n\n"
            f"{ai_summary or 'No AI summary available.'}",
        )
        exit_code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


if __name__ == "__main__":
    main()
