#!/usr/bin/env python3
"""
Integration Test Deployment Script

Handles code packaging, S3 upload, and pipeline monitoring for integration tests.
"""

import os
import subprocess
import sys
import time

import boto3
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


def run_command(cmd, check=True):
    """Run shell command and return result"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # nosec B602 nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true - hardcoded commands, no user input
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result


def get_env_var(name, default=None):
    """Get environment variable with optional default"""
    value = os.environ.get(name, default)
    if value is None:
        print(f"Error: Environment variable {name} is required")
        sys.exit(1)
    return value


def create_deployment_package():
    """Create deployment zip package"""
    print("Creating deployment package...")

    # Create dist directory
    os.makedirs("./dist", exist_ok=True)

    # Remove existing zip
    if os.path.exists("./dist/code.zip"):
        os.remove("./dist/code.zip")

    # Create zip with exclusions
    excludes = [
        "*.git/*",
        "*.git/**",
        "*__pycache__/*",
        ".gitlab-ci.yml",
        "*.delete/*",
        "*.sav/*",
        "*.venv/*",
        "*.vscode/*",
        "*cdk.out/*",
        "*dist/*",
        "*.DS_Store",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.so",
        "**/.env",
        "*.docker/*",
        "*.aws-sam/*",
    ]

    exclude_args = " ".join([f'-x "{pattern}"' for pattern in excludes])
    cmd = f"zip -r ./dist/code.zip ./ {exclude_args}"

    run_command(cmd)
    print("✅ Deployment package created")


def upload_to_s3(bucket_name):
    """Upload code package to S3 and return version ID"""
    print(f"Uploading to S3 bucket: {bucket_name}")

    s3_client = boto3.client("s3")

    try:
        # Get GitLab user email to pass to CodeBuild
        gitlab_user_email = os.environ.get("GITLAB_USER_EMAIL", "")
        
        # Add metadata to pass email to CodeBuild
        metadata = {}
        if gitlab_user_email:
            metadata["gitlab-user-email"] = gitlab_user_email
            print(f"Adding GitLab user email to metadata: {gitlab_user_email}")

        response = s3_client.put_object(
            Bucket=bucket_name,
            Key="deploy/code.zip",
            Body=open("./dist/code.zip", "rb"),
            Metadata=metadata,
        )
        version_id = response.get("VersionId", "unknown")
        print(f"✅ Uploaded with version ID: {version_id}")
        return version_id
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)


def find_pipeline_execution_by_version(pipeline_name, version_id, max_wait=300):
    """Find pipeline execution that corresponds to specific S3 version ID"""
    console = Console()
    console.print(f"[cyan]Finding pipeline execution for version:[/cyan] {version_id}")
    
    codepipeline = boto3.client("codepipeline")
    start_time = time.time()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        
        task = progress.add_task("[yellow]Searching for pipeline execution...", total=None)
        
        while time.time() - start_time < max_wait:
            try:
                response = codepipeline.list_pipeline_executions(
                    pipelineName=pipeline_name, maxResults=10
                )
                
                for execution in response["pipelineExecutionSummaries"]:
                    execution_id = execution["pipelineExecutionId"]
                    
                    # Get execution details to check source version
                    details = codepipeline.get_pipeline_execution(
                        pipelineName=pipeline_name,
                        pipelineExecutionId=execution_id
                    )
                    
                    # Check if this execution matches our version ID
                    for artifact in details["pipelineExecution"].get("artifactRevisions", []):
                        if artifact.get("revisionId") == version_id:
                            progress.update(task, description="[green]✅ Found matching execution!")
                            console.print(f"[green]✅ Found matching execution:[/green] {execution_id}")
                            return execution_id
                
                elapsed = int(time.time() - start_time)
                progress.update(task, description=f"[yellow]Waiting for pipeline trigger ({elapsed}s)...")
                        
            except Exception as e:
                progress.update(task, description=f"[red]Error: {str(e)[:50]}...")
                console.print(f"[red]Error finding execution: {e}[/red]")
                
            time.sleep(10)
        
        progress.update(task, description="[red]❌ No matching execution found")
        console.print(f"[red]❌ Could not find pipeline execution for version {version_id}[/red]")
    return None


def monitor_pipeline_execution(pipeline_name, execution_id, max_wait=6000):
    """Monitor specific pipeline execution until completion with live progress

    max_wait defaults to 6000s (100 min), deliberately BELOW the GitLab job's
    2h ceiling: the script must own the deadline so it always returns and lets
    after_script capture codebuild_logs.txt + the S3 summary. When max_wait
    equalled the GitLab timeout (both 7200s), GitLab hard-killed the job before
    the monitor could report or after_script could run — a fast pipeline
    failure (e.g. ~64 min) still surfaced as an opaque "execution took longer
    than 2h" with no logs. The pipeline itself failing fast is the norm; this
    watcher just needs to notice and exit cleanly.
    """
    console = Console()
    console.print(f"[cyan]Monitoring pipeline execution:[/cyan] {execution_id}")

    codepipeline = boto3.client("codepipeline")
    poll_interval = 30
    # A persistent get_pipeline_execution failure (throttling, expired creds,
    # wrong id) must NOT masquerade as a 2h hang: the old handler logged each
    # error and kept polling to the deadline. Bail after this many consecutive
    # errors so the real problem is visible in minutes, not hours.
    max_consecutive_errors = 10
    consecutive_errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:

        task = progress.add_task("[yellow]Pipeline executing...", total=None)

        wait_time = 0
        while wait_time < max_wait:
            try:
                response = codepipeline.get_pipeline_execution(
                    pipelineName=pipeline_name,
                    pipelineExecutionId=execution_id
                )

                consecutive_errors = 0
                status = response["pipelineExecution"]["status"]
                elapsed_mins = wait_time // 60

                # Terminal states: return IMMEDIATELY and log explicitly so a
                # detection miss can never be confused with a timeout.
                if status == "Succeeded":
                    progress.update(task, description="[green]✅ Pipeline completed successfully!")
                    console.print(
                        f"[green]✅ Pipeline reached terminal state 'Succeeded' "
                        f"after {elapsed_mins}m — monitor exiting.[/green]"
                    )
                    return True
                elif status in ["Failed", "Cancelled", "Superseded", "Stopped"]:
                    progress.update(task, description=f"[red]❌ Pipeline failed: {status}")
                    console.print(
                        f"[red]❌ Pipeline reached terminal state '{status}' "
                        f"after {elapsed_mins}m — monitor exiting.[/red]"
                    )
                    return False
                elif status == "InProgress":
                    progress.update(task, description=f"[yellow]⏳ Pipeline running ({elapsed_mins}m elapsed)...")

            except Exception as e:
                consecutive_errors += 1
                progress.update(task, description=f"[red]Error: {str(e)[:50]}...")
                console.print(
                    f"[red]Error checking pipeline status "
                    f"({consecutive_errors}/{max_consecutive_errors}): {e}[/red]"
                )
                if consecutive_errors >= max_consecutive_errors:
                    console.print(
                        f"[red]❌ Aborting: {max_consecutive_errors} consecutive "
                        f"errors querying pipeline status (not a timeout).[/red]"
                    )
                    return False

            time.sleep(poll_interval)
            wait_time += poll_interval

        progress.update(task, description=f"[red]❌ Timeout after {max_wait//60} minutes")
        console.print(f"[red]❌ Pipeline monitoring timed out after {max_wait} seconds[/red]")
        return False


def monitor_pipeline(pipeline_name, version_id, max_wait=6000):
    """Monitor pipeline using version-based tracking"""
    # First find the execution that matches our version
    execution_id = find_pipeline_execution_by_version(pipeline_name, version_id)
    
    if not execution_id:
        return False
    
    # Write execution ID to file for GitLab CI to use
    with open("pipeline_execution_id.txt", "w") as f:
        f.write(execution_id)
    print(f"Pipeline execution ID written to file: {execution_id}")
        
    # Then monitor that specific execution
    return monitor_pipeline_execution(pipeline_name, execution_id, max_wait)


def main():
    """Main execution function"""
    print("Starting integration test deployment...")

    # Get configuration from environment
    account_id = get_env_var("IDP_ACCOUNT_ID", "020432867916")
    region = get_env_var("AWS_DEFAULT_REGION", "us-east-1")
    bucket_name = f"genaiic-sdlc-sourcecode-{account_id}-{region}"
    pipeline_name = get_env_var("IDP_PIPELINE_NAME", "genaiic-sdlc-deploy-pipeline")

    print(f"Account ID: {account_id}")
    print(f"Region: {region}")
    print(f"Bucket: {bucket_name}")
    print(f"Pipeline: {pipeline_name}")

    # Execute deployment steps
    create_deployment_package()
    version_id = upload_to_s3(bucket_name)

    success = monitor_pipeline(pipeline_name, version_id)

    if success:
        print("🎉 Integration test deployment completed successfully!")
        sys.exit(0)
    else:
        print("💥 Integration test deployment failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
