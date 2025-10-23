# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDP CLI - Main Command Line Interface

Command-line tool for batch document processing with the IDP Accelerator.
"""

import logging
import sys
import time
from typing import Optional

import click
from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import display
from .batch_processor import BatchProcessor
from .deployer import StackDeployer, build_parameters
from .manifest_parser import validate_manifest
from .progress_monitor import ProgressMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

console = Console()

# Region-specific template URLs
TEMPLATE_URLS = {
    "us-west-2": "https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml",
    "us-east-1": "https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main.yaml",
}


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """
    IDP CLI - Batch document processing for IDP Accelerator

    This tool provides commands for:
    - Stack deployment
    - Batch document upload and processing
    - Progress monitoring with live updates
    - Status checking and reporting
    """
    pass


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option(
    "--pattern",
    type=click.Choice(["pattern-1", "pattern-2", "pattern-3"]),
    help="IDP pattern to deploy (required for new stacks)",
)
@click.option(
    "--admin-email", help="Admin user email address (required for new stacks)"
)
@click.option(
    "--template-url",
    help="URL to CloudFormation template in S3 (default: auto-selected based on region)",
)
@click.option(
    "--max-concurrent",
    default=100,
    type=int,
    help="Maximum concurrent workflows (default: 100)",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARN", "ERROR"]),
    help="Logging level (default: INFO)",
)
@click.option(
    "--enable-hitl",
    default="false",
    type=click.Choice(["true", "false"]),
    help="Enable Human-in-the-Loop (default: false)",
)
@click.option("--pattern-config", help="Pattern configuration preset")
@click.option(
    "--custom-config",
    help="Path to local config file or S3 URI (e.g., ./config.yaml or s3://bucket/config.yaml)",
)
@click.option("--parameters", help="Additional parameters as key=value,key2=value2")
@click.option("--wait", is_flag=True, help="Wait for stack creation to complete")
@click.option("--region", help="AWS region (optional)")
def deploy(
    stack_name: str,
    pattern: str,
    admin_email: str,
    template_url: str,
    max_concurrent: int,
    log_level: str,
    enable_hitl: str,
    pattern_config: Optional[str],
    custom_config: Optional[str],
    parameters: Optional[str],
    wait: bool,
    region: Optional[str],
):
    """
    Deploy or update IDP stack from command line
    
    For new stacks, --pattern and --admin-email are required.
    For existing stacks, only specify parameters you want to update.
    
    Examples:
    
      # Create new stack with Pattern 2
      idp-cli deploy --stack-name my-idp --pattern pattern-2 --admin-email user@example.com
      
      # Update existing stack with local config file (NEW!)
      idp-cli deploy --stack-name my-idp --custom-config ./my-config.yaml
      
      # Update existing stack with custom settings
      idp-cli deploy --stack-name my-idp --max-concurrent 200 --wait
      
      # Create with additional parameters
      idp-cli deploy --stack-name my-idp --pattern pattern-2 \\
          --admin-email user@example.com \\
          --parameters "DataRetentionInDays=90,ErrorThreshold=5"
    """
    try:
        # Auto-detect region if not provided
        if not region:
            import boto3

            session = boto3.session.Session()
            region = session.region_name
            if not region:
                raise ValueError(
                    "Region could not be determined. Please specify --region or configure AWS_DEFAULT_REGION"
                )

        # Determine template URL (user-provided takes precedence)
        if not template_url:
            if region in TEMPLATE_URLS:
                template_url = TEMPLATE_URLS[region]
                console.print(f"[bold]Using template for region: {region}[/bold]")
            else:
                supported_regions = ", ".join(TEMPLATE_URLS.keys())
                raise ValueError(
                    f"Region '{region}' is not supported. "
                    f"Supported regions: {supported_regions}. "
                    f"Please provide --template-url explicitly for other regions."
                )

        # Initialize deployer
        deployer = StackDeployer(region=region)

        # Check if stack exists
        stack_exists = deployer._stack_exists(stack_name)

        if stack_exists:
            # Stack exists - updating
            console.print(
                f"[bold blue]Updating existing IDP stack: {stack_name}[/bold blue]"
            )

            # Get existing stack parameters
            try:
                response = deployer.cfn.describe_stacks(StackName=stack_name)
                existing_stack = response["Stacks"][0]
                existing_params = {
                    p["ParameterKey"]: p["ParameterValue"]
                    for p in existing_stack.get("Parameters", [])
                }

                # Use existing values if not provided
                if not pattern and "IDPPattern" in existing_params:
                    # Extract pattern from existing value
                    pattern_value = existing_params["IDPPattern"]
                    if "Pattern1" in pattern_value:
                        pattern = "pattern-1"
                    elif "Pattern2" in pattern_value:
                        pattern = "pattern-2"
                    elif "Pattern3" in pattern_value:
                        pattern = "pattern-3"

                if not admin_email and "AdminEmail" in existing_params:
                    admin_email = existing_params["AdminEmail"]

            except Exception as e:
                logger.warning(f"Could not retrieve existing stack parameters: {e}")
        else:
            # New stack - require pattern and admin_email
            console.print(
                f"[bold blue]Creating new IDP stack: {stack_name}[/bold blue]"
            )

            if not pattern:
                console.print(
                    "[red]✗ Error: --pattern is required when creating a new stack[/red]"
                )
                sys.exit(1)

            if not admin_email:
                console.print(
                    "[red]✗ Error: --admin-email is required when creating a new stack[/red]"
                )
                sys.exit(1)

        console.print(f"Pattern: {pattern}")
        console.print(f"Admin Email: {admin_email}")
        console.print()

        # Parse additional parameters
        additional_params = {}
        if parameters:
            for param in parameters.split(","):
                if "=" in param:
                    key, value = param.split("=", 1)
                    additional_params[key.strip()] = value.strip()

        # Build parameters
        cfn_parameters = build_parameters(
            pattern=pattern,
            admin_email=admin_email,
            max_concurrent=max_concurrent,
            log_level=log_level,
            enable_hitl=enable_hitl,
            pattern_config=pattern_config,
            custom_config=custom_config,
            additional_params=additional_params,
            region=region,
            stack_name=stack_name,
        )

        # Debug: Show CustomConfigPath if present
        if "CustomConfigPath" in cfn_parameters:
            console.print(
                f"[yellow]DEBUG: CustomConfigPath = {cfn_parameters['CustomConfigPath']}[/yellow]"
            )

        # Deploy stack
        with console.status("[bold green]Deploying stack..."):
            result = deployer.deploy_stack(
                stack_name=stack_name,
                template_url=template_url,
                parameters=cfn_parameters,
                wait=wait,
            )

        # Show results
        # Success if operation completed successfully OR was successfully initiated
        is_success = result.get("success") or result.get("status") == "INITIATED"

        if is_success:
            if result.get("success"):
                # Completed (with --wait)
                console.print(
                    f"\n[green]✓ Stack {result['operation']} completed successfully![/green]\n"
                )

                # Show outputs
                outputs = result.get("outputs", {})
                if outputs:
                    console.print("[bold]Important Outputs:[/bold]")
                    console.print(
                        f"  Application URL: [cyan]{outputs.get('ApplicationWebURL', 'N/A')}[/cyan]"
                    )
                    console.print(
                        f"  Input Bucket: {outputs.get('S3InputBucketName', 'N/A')}"
                    )
                    console.print(
                        f"  Output Bucket: {outputs.get('S3OutputBucketName', 'N/A')}"
                    )
                    console.print()

                console.print("[bold]Next Steps:[/bold]")
                console.print("1. Check your email for temporary admin password")
                console.print("2. Enable Bedrock model access (see README)")
                console.print("3. Process documents:")
                console.print(
                    f"   [cyan]idp-cli run-inference --stack-name {stack_name} --manifest docs.csv[/cyan]"
                )
                console.print()
            else:
                # Initiated (without --wait)
                console.print(
                    f"\n[green]✓ Stack {result['operation']} initiated successfully![/green]\n"
                )
                console.print("[bold]Monitor progress:[/bold]")
                console.print(f"  AWS Console: CloudFormation → Stacks → {stack_name}")
                console.print()
                console.print("[bold]Or use --wait flag to monitor in CLI:[/bold]")
                console.print(
                    f"  [cyan]idp-cli deploy --stack-name {stack_name} --wait[/cyan]"
                )
                console.print()
        else:
            console.print(f"\n[red]✗ Stack {result['operation']} failed![/red]")
            console.print(f"Status: {result.get('status')}")
            console.print(f"Error: {result.get('error', 'Unknown')}")
            sys.exit(1)

    except FileNotFoundError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error deploying stack: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--empty-buckets",
    is_flag=True,
    help="Empty S3 buckets before deletion (required if buckets contain data)",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Wait for deletion to complete (default: wait)",
)
@click.option("--region", help="AWS region (optional)")
def delete(
    stack_name: str,
    force: bool,
    empty_buckets: bool,
    wait: bool,
    region: Optional[str],
):
    """
    Delete an IDP CloudFormation stack

    ⚠️  WARNING: This permanently deletes all stack resources.

    S3 buckets configured with RetainExceptOnCreate will be deleted if empty.
    Use --empty-buckets to automatically empty buckets before deletion.

    Examples:

      # Interactive deletion with confirmation
      idp-cli delete --stack-name test-stack

      # Automated deletion (skip confirmation)
      idp-cli delete --stack-name test-stack --force

      # Delete with automatic bucket emptying
      idp-cli delete --stack-name test-stack --empty-buckets --force

      # Delete without waiting for completion
      idp-cli delete --stack-name test-stack --force --no-wait
    """
    try:
        deployer = StackDeployer(region=region)

        # Check if stack exists
        if not deployer._stack_exists(stack_name):
            console.print(f"[red]✗ Stack '{stack_name}' does not exist[/red]")
            sys.exit(1)

        # Get bucket information
        console.print(f"[bold blue]Analyzing stack: {stack_name}[/bold blue]")
        bucket_info = deployer.get_bucket_info(stack_name)

        # Show warning with bucket details
        console.print()
        console.print("[bold red]⚠️  WARNING: Stack Deletion[/bold red]")
        console.print("━" * 60)
        console.print(f"Stack: [cyan]{stack_name}[/cyan]")
        console.print(f"Region: {region or 'default'}")

        if bucket_info:
            console.print()
            console.print("[bold]S3 Buckets:[/bold]")
            has_data = False
            for bucket in bucket_info:
                obj_count = bucket.get("object_count", 0)
                size = bucket.get("size_display", "Unknown")
                logical_id = bucket.get("logical_id", "Unknown")

                if obj_count > 0:
                    has_data = True
                    console.print(
                        f"  • {logical_id}: [yellow]{obj_count} objects ({size})[/yellow]"
                    )
                else:
                    console.print(f"  • {logical_id}: [green]empty[/green]")

            if has_data and not empty_buckets:
                console.print()
                console.print("[bold red]⚠️  Buckets contain data![/bold red]")
                console.print("Deletion will FAIL unless you:")
                console.print("  1. Use --empty-buckets flag to auto-delete data, OR")
                console.print("  2. Manually empty buckets first")

        console.print()
        console.print("[bold red]This action cannot be undone.[/bold red]")
        console.print("━" * 60)
        console.print()

        # Confirmation unless --force
        if not force:
            response = click.confirm(
                "Are you sure you want to delete this stack?", default=False
            )
            if not response:
                console.print("[yellow]Deletion cancelled[/yellow]")
                return

            # Double confirmation if --empty-buckets
            if empty_buckets:
                console.print()
                console.print(
                    "[bold red]⚠️  You are about to permanently delete all bucket data![/bold red]"
                )
                response = click.confirm(
                    "Are you ABSOLUTELY sure you want to empty buckets and delete the stack?",
                    default=False,
                )
                if not response:
                    console.print("[yellow]Deletion cancelled[/yellow]")
                    return

        # Perform deletion
        console.print()
        with console.status("[bold red]Deleting stack..."):
            result = deployer.delete_stack(
                stack_name=stack_name,
                empty_buckets=empty_buckets,
                wait=wait,
            )

        # Show results
        if result.get("success"):
            console.print("\n[green]✓ Stack deleted successfully![/green]")
            console.print(f"Stack: {stack_name}")
            console.print(f"Status: {result.get('status')}")

            # Note about LoggingBucket
            console.print()
            console.print(
                "[bold]Note:[/bold] LoggingBucket (if exists) is retained by design."
            )
            console.print("Delete it manually if no longer needed:")
            console.print("  [cyan]aws s3 rb s3://<logging-bucket-name> --force[/cyan]")
            console.print()
        else:
            console.print("\n[red]✗ Stack deletion failed![/red]")
            console.print(f"Status: {result.get('status')}")
            console.print(f"Error: {result.get('error', 'Unknown')}")

            if "bucket" in result.get("error", "").lower():
                console.print()
                console.print(
                    "[yellow]Tip: Try again with --empty-buckets flag[/yellow]"
                )

            sys.exit(1)

    except Exception as e:
        logger.error(f"Error deleting stack: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option(
    "--step",
    required=True,
    type=click.Choice(["classification", "extraction"]),
    help="Pipeline step to rerun from",
)
@click.option(
    "--document-ids",
    help="Comma-separated list of document IDs to reprocess",
)
@click.option(
    "--batch-id",
    help="Batch ID to get document IDs from (alternative to --document-ids)",
)
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.option("--monitor", is_flag=True, help="Monitor progress until completion")
@click.option(
    "--refresh-interval",
    default=5,
    type=int,
    help="Seconds between status checks (default: 5)",
)
@click.option("--region", help="AWS region (optional)")
def rerun_inference(
    stack_name: str,
    step: str,
    document_ids: Optional[str],
    batch_id: Optional[str],
    force: bool,
    monitor: bool,
    refresh_interval: int,
    region: Optional[str],
):
    """
    Rerun processing for existing documents from a specific step
    
    Reprocesses documents already in InputBucket, leveraging existing OCR data.
    
    Steps:
      - classification: Reruns classification and all subsequent steps
      - extraction: Reruns extraction and assessment (keeps classification)
    
    Document ID Format: Use the S3 key format (e.g., "batch-id/document.pdf")
    
    Examples:
    
      # Rerun classification for specific documents
      idp-cli rerun-inference \\
          --stack-name my-stack \\
          --step classification \\
          --document-ids "batch-123/doc1.pdf,batch-123/doc2.pdf" \\
          --monitor
      
      # Rerun extraction for all documents in a batch
      idp-cli rerun-inference \\
          --stack-name my-stack \\
          --step extraction \\
          --batch-id cli-batch-20251015-143000 \\
          --monitor
    """
    try:
        # Validate mutually exclusive options
        if not document_ids and not batch_id:
            console.print(
                "[red]✗ Error: Must specify either --document-ids or --batch-id[/red]"
            )
            sys.exit(1)

        if document_ids and batch_id:
            console.print(
                "[red]✗ Error: Cannot specify both --document-ids and --batch-id[/red]"
            )
            sys.exit(1)

        from .rerun_processor import RerunProcessor

        # Initialize processor
        console.print(
            f"[bold blue]Initializing rerun processor for stack: {stack_name}[/bold blue]"
        )
        processor = RerunProcessor(stack_name=stack_name, region=region)

        # Get document IDs
        if document_ids:
            doc_id_list = [doc_id.strip() for doc_id in document_ids.split(",")]
            console.print(f"Processing {len(doc_id_list)} specified documents")
        else:
            console.print(f"Getting document IDs from batch: {batch_id}")
            doc_id_list = processor.get_batch_document_ids(batch_id)
            console.print(f"Found {len(doc_id_list)} documents in batch")

        # Show what will be cleared based on step
        console.print()
        console.print(f"[bold yellow]⚠️  Rerun Step: {step}[/bold yellow]")
        console.print("━" * 60)

        if step == "classification":
            console.print("[bold]What will be cleared:[/bold]")
            console.print("  • All page classifications")
            console.print("  • All document sections")
            console.print("  • All extraction results")
            console.print()
            console.print("[bold]What will be kept:[/bold]")
            console.print("  • OCR data (pages, images, text)")
        else:  # extraction
            console.print("[bold]What will be cleared:[/bold]")
            console.print("  • Section extraction results")
            console.print("  • Section attributes")
            console.print()
            console.print("[bold]What will be kept:[/bold]")
            console.print("  • OCR data (pages, images, text)")
            console.print("  • Page classifications")
            console.print("  • Document sections structure")

        console.print("━" * 60)
        console.print()

        # Confirmation unless --force
        if not force:
            if not click.confirm(
                f"Reprocess {len(doc_id_list)} documents from {step} step?",
                default=True,
            ):
                console.print("[yellow]Rerun cancelled[/yellow]")
                return

        # Perform rerun
        console.print()
        with console.status(
            f"[bold green]Reprocessing {len(doc_id_list)} documents..."
        ):
            results = processor.rerun_documents(
                document_ids=doc_id_list, step=step, monitor=monitor
            )

        # Show results
        console.print()
        if results["documents_queued"] > 0:
            console.print(
                f"[green]✓ Queued {results['documents_queued']} documents for {step} reprocessing[/green]"
            )

        if results["documents_failed"] > 0:
            console.print(
                f"[red]✗ Failed to queue {results['documents_failed']} documents[/red]"
            )
            for failed in results["failed_documents"]:
                console.print(f"  • {failed['object_key']}: {failed['error']}")

        console.print()

        if monitor and results["documents_queued"] > 0:
            # Monitor progress using existing monitoring function
            _monitor_progress(
                stack_name=stack_name,
                batch_id=batch_id or "rerun",
                document_ids=doc_id_list,
                refresh_interval=refresh_interval,
                region=region,
                resources=processor.resources,
            )

    except Exception as e:
        logger.error(f"Error rerunning documents: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option(
    "--manifest",
    type=click.Path(exists=True),
    help="Path to manifest file (CSV or JSON)",
)
@click.option(
    "--dir",
    "directory",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Local directory containing documents to process",
)
@click.option("--s3-uri", help="S3 URI to process (e.g., s3://bucket/prefix/)")
@click.option("--batch-id", help="Custom batch ID (auto-generated if not provided)")
@click.option(
    "--file-pattern",
    default="*.pdf",
    help="File pattern for directory/S3 scanning (default: *.pdf)",
)
@click.option(
    "--recursive/--no-recursive",
    default=True,
    help="Include subdirectories when scanning (default: recursive)",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    help="Path to configuration YAML file (optional)",
)
@click.option(
    "--batch-prefix",
    default="cli-batch",
    help="Batch ID prefix (used only if --batch-id not provided, default: cli-batch)",
)
@click.option("--monitor", is_flag=True, help="Monitor progress until completion")
@click.option(
    "--refresh-interval",
    default=5,
    type=int,
    help="Seconds between status checks (default: 5)",
)
@click.option("--region", help="AWS region (optional)")
def run_inference(
    stack_name: str,
    manifest: Optional[str],
    directory: Optional[str],
    s3_uri: Optional[str],
    batch_id: Optional[str],
    file_pattern: str,
    recursive: bool,
    config: Optional[str],
    batch_prefix: str,
    monitor: bool,
    refresh_interval: int,
    region: Optional[str],
):
    """
    Run inference on a batch of documents

    Specify documents using ONE of:
      --manifest: Explicit manifest file (CSV or JSON)
      --dir: Local directory (auto-generates manifest)
      --s3-uri: S3 URI (auto-generates manifest, any bucket)

    Examples:

      # Process from manifest file
      idp-cli run-inference --stack-name my-stack --manifest docs.csv --monitor

      # Process all PDFs in local directory
      idp-cli run-inference --stack-name my-stack --dir ./documents/ --monitor

      # Process with custom batch ID
      idp-cli run-inference --stack-name my-stack --dir ./docs/ --batch-id my-experiment-v1 --monitor

      # Process S3 URI (any bucket)
      idp-cli run-inference --stack-name my-stack --s3-uri s3://data-lake/archive/2024/ --monitor

      # Process with file pattern
      idp-cli run-inference --stack-name my-stack --dir ./docs/ --file-pattern "invoice*.pdf"
    """
    try:
        # Validate mutually exclusive options
        sources = [manifest, directory, s3_uri]
        sources_provided = sum(1 for s in sources if s is not None)

        if sources_provided == 0:
            console.print(
                "[red]✗ Error: Must specify one of: --manifest, --dir, or --s3-uri[/red]"
            )
            sys.exit(1)
        elif sources_provided > 1:
            console.print(
                "[red]✗ Error: Cannot specify more than one of: --manifest, --dir, --s3-uri[/red]"
            )
            sys.exit(1)

        # Validate manifest if provided
        if manifest:
            console.print("[bold blue]Validating manifest...[/bold blue]")
            is_valid, error = validate_manifest(manifest)
            if not is_valid:
                console.print(f"[red]✗ Manifest validation failed: {error}[/red]")
                sys.exit(1)
            console.print("[green]✓ Manifest validated successfully[/green]")

        # Initialize processor
        console.print(
            f"[bold blue]Initializing batch processor for stack: {stack_name}[/bold blue]"
        )
        processor = BatchProcessor(
            stack_name=stack_name, config_path=config, region=region
        )

        # Process batch based on source type
        with console.status("[bold green]Processing batch..."):
            if manifest:
                batch_result = processor.process_batch(
                    manifest_path=manifest,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                )
            elif directory:
                batch_result = processor.process_batch_from_directory(
                    dir_path=directory,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                )
            else:  # s3_uri
                batch_result = processor.process_batch_from_s3_uri(
                    s3_uri=s3_uri,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                )

        # Show submission results
        display.show_batch_submission_summary(batch_result)

        if monitor:
            # Monitor until completion
            _monitor_progress(
                stack_name=stack_name,
                batch_id=batch_result["batch_id"],
                document_ids=batch_result["document_ids"],
                refresh_interval=refresh_interval,
                region=region,
                resources=processor.resources,
            )
        else:
            # Show how to monitor later
            display.show_monitoring_instructions(stack_name, batch_result["batch_id"])

    except Exception as e:
        logger.error(f"Error processing batch: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option("--batch-id", required=True, help="Batch identifier")
@click.option("--wait", is_flag=True, help="Wait for all documents to complete")
@click.option(
    "--refresh-interval",
    default=5,
    type=int,
    help="Seconds between status checks (default: 5)",
)
@click.option("--region", help="AWS region (optional)")
def status(
    stack_name: str,
    batch_id: str,
    wait: bool,
    refresh_interval: int,
    region: Optional[str],
):
    """
    Check status of a batch processing job

    Examples:

      # Check current status once
      idp-cli status --stack-name my-stack --batch-id cli-batch-20250110-153045-abc12345

      # Monitor until completion
      idp-cli status --stack-name my-stack --batch-id cli-batch-20250110-153045-abc12345 --wait
    """
    try:
        # Get batch info
        processor = BatchProcessor(stack_name=stack_name, region=region)
        batch_info = processor.get_batch_info(batch_id)

        if not batch_info:
            console.print(f"[red]✗ Batch not found: {batch_id}[/red]")
            sys.exit(1)

        document_ids = batch_info["document_ids"]

        if wait:
            # Monitor until completion
            _monitor_progress(
                stack_name=stack_name,
                batch_id=batch_id,
                document_ids=document_ids,
                refresh_interval=refresh_interval,
                region=region,
                resources=processor.resources,
            )
        else:
            # Show current status once
            monitor = ProgressMonitor(
                stack_name=stack_name, resources=processor.resources, region=region
            )
            status_data = monitor.get_batch_status(document_ids)
            stats = monitor.calculate_statistics(status_data)

            console.print()
            console.print(f"[bold blue]Batch: {batch_id}[/bold blue]")
            display.display_status_table(status_data)

            # Show statistics
            console.print(display.create_statistics_panel(stats))
            console.print()

    except Exception as e:
        logger.error(f"Error checking status: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option("--limit", default=10, type=int, help="Maximum number of batches to list")
@click.option("--region", help="AWS region (optional)")
def list_batches(stack_name: str, limit: int, region: Optional[str]):
    """
    List recent batch processing jobs

    Example:

      idp-cli list-batches --stack-name my-stack --limit 5
    """
    try:
        processor = BatchProcessor(stack_name=stack_name, region=region)
        batches = processor.list_batches(limit=limit)

        if not batches:
            console.print("[yellow]No batches found[/yellow]")
            return

        # Create table
        table = Table(title=f"Recent Batches (Last {limit})", show_header=True)
        table.add_column("Batch ID", style="cyan")
        table.add_column("Documents", justify="right")
        table.add_column("Queued", justify="right")
        table.add_column("Failed", justify="right")
        table.add_column("Timestamp")

        for batch in batches:
            table.add_row(
                batch["batch_id"],
                str(len(batch["document_ids"])),
                str(batch["queued"]),
                str(batch["failed"]),
                batch["timestamp"][:19],  # Trim timestamp
            )

        console.print()
        console.print(table)
        console.print()

    except Exception as e:
        logger.error(f"Error listing batches: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--stack-name", required=True, help="CloudFormation stack name")
@click.option("--batch-id", required=True, help="Batch identifier")
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(),
    help="Output directory for downloaded results",
)
@click.option(
    "--file-types",
    default="all",
    help="File types to download: pages, sections, summary, evaluation, or 'all' (default: all)",
)
@click.option("--region", help="AWS region (optional)")
def download_results(
    stack_name: str,
    batch_id: str,
    output_dir: str,
    file_types: str,
    region: Optional[str],
):
    """
    Download processing results from OutputBucket

    Examples:

      # Download all results
      idp-cli download-results --stack-name my-stack --batch-id cli-batch-20251015-143000 --output-dir ./results/

      # Download only extraction results (sections)
      idp-cli download-results --stack-name my-stack --batch-id <id> --output-dir ./results/ --file-types sections

      # Download evaluations only
      idp-cli download-results --stack-name my-stack --batch-id <id> --output-dir ./results/ --file-types evaluation
    """
    try:
        console.print(
            f"[bold blue]Downloading results for batch: {batch_id}[/bold blue]"
        )

        processor = BatchProcessor(stack_name=stack_name, region=region)

        # Parse file types
        if file_types == "all":
            types_list = ["pages", "sections", "summary", "evaluation"]
        else:
            types_list = [t.strip() for t in file_types.split(",")]

        # Download results
        result = processor.download_batch_results(
            batch_id=batch_id, output_dir=output_dir, file_types=types_list
        )

        console.print(
            f"\n[green]✓ Downloaded {result['files_downloaded']} files to {output_dir}[/green]"
        )
        console.print(f"  Documents: {result['documents_downloaded']}")
        console.print(f"  Output: {output_dir}/{batch_id}/")
        console.print()

    except Exception as e:
        logger.error(f"Error downloading results: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--dir",
    "directory",
    type=click.Path(exists=True, file_okay=False),
    help="Local directory to scan",
)
@click.option("--s3-uri", help="S3 URI to scan (e.g., s3://bucket/prefix/)")
@click.option(
    "--baseline-dir",
    type=click.Path(exists=True, file_okay=False),
    help="Baseline directory to auto-match (only with --dir)",
)
@click.option(
    "--output", required=True, type=click.Path(), help="Output manifest file path (CSV)"
)
@click.option("--file-pattern", default="*.pdf", help="File pattern (default: *.pdf)")
@click.option(
    "--recursive/--no-recursive",
    default=True,
    help="Include subdirectories (default: recursive)",
)
@click.option("--region", help="AWS region (optional)")
def generate_manifest(
    directory: Optional[str],
    s3_uri: Optional[str],
    baseline_dir: Optional[str],
    output: str,
    file_pattern: str,
    recursive: bool,
    region: Optional[str],
):
    """
    Generate a manifest file from directory or S3 URI

    The manifest can then be edited to add baseline_source or customize document_id values.
    Use --baseline-dir to automatically match baseline directories by document ID.

    Examples:

      # Generate from local directory
      idp-cli generate-manifest --dir ./documents/ --output manifest.csv

      # With automatic baseline matching
      idp-cli generate-manifest --dir ./documents/ --baseline-dir ./baselines/ --output manifest.csv

      # Generate from S3 URI
      idp-cli generate-manifest --s3-uri s3://bucket/prefix/ --output manifest.csv

      # With file pattern
      idp-cli generate-manifest --dir ./docs/ --output manifest.csv --file-pattern "W2*.pdf"
    """
    try:
        import csv
        import os

        # Validate mutually exclusive options
        if not directory and not s3_uri:
            console.print("[red]✗ Error: Must specify either --dir or --s3-uri[/red]")
            sys.exit(1)
        if directory and s3_uri:
            console.print("[red]✗ Error: Cannot specify both --dir and --s3-uri[/red]")
            sys.exit(1)

        # Import here to avoid circular dependency during scanning

        documents = []

        if directory:
            console.print(f"[bold blue]Scanning directory: {directory}[/bold blue]")

            # Import scan method directly
            import glob as glob_module

            dir_path = os.path.abspath(directory)
            if recursive:
                search_pattern = os.path.join(dir_path, "**", file_pattern)
            else:
                search_pattern = os.path.join(dir_path, file_pattern)

            for file_path in glob_module.glob(search_pattern, recursive=recursive):
                if os.path.isfile(file_path):
                    documents.append({"document_path": file_path})
        else:  # s3_uri
            console.print(f"[bold blue]Scanning S3 URI: {s3_uri}[/bold blue]")

            # Parse S3 URI
            if not s3_uri.startswith("s3://"):
                console.print("[red]✗ Error: Invalid S3 URI[/red]")
                sys.exit(1)

            uri_parts = s3_uri[5:].split("/", 1)
            bucket = uri_parts[0]
            prefix = uri_parts[1] if len(uri_parts) > 1 else ""

            # List S3 objects
            import fnmatch

            import boto3

            s3 = boto3.client("s3", region_name=region)
            paginator = s3.get_paginator("list_objects_v2")

            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"

            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    if key.endswith("/"):
                        continue

                    if not recursive:
                        rel_key = key[len(prefix) :]
                        if "/" in rel_key:
                            continue

                    filename = os.path.basename(key)
                    if not fnmatch.fnmatch(filename, file_pattern):
                        continue

                    full_uri = f"s3://{bucket}/{key}"

                    documents.append({"document_path": full_uri})

        if not documents:
            console.print("[yellow]No documents found[/yellow]")
            sys.exit(1)

        console.print(f"Found {len(documents)} documents")

        # Match baselines if baseline_dir provided
        baseline_map = {}
        if baseline_dir:
            if s3_uri:
                console.print(
                    "[yellow]Warning: --baseline-dir only works with --dir, ignoring[/yellow]"
                )
            else:
                console.print(
                    f"[bold blue]Matching baselines from: {baseline_dir}[/bold blue]"
                )

                import os

                baseline_path = os.path.abspath(baseline_dir)

                # Scan for baseline subdirectories
                for item in os.listdir(baseline_path):
                    item_path = os.path.join(baseline_path, item)
                    if os.path.isdir(item_path):
                        # Map both with and without extension
                        # e.g., "doc.pdf/" → matches doc_id "doc"
                        baseline_map[item] = item_path

                        # Also map without extension
                        if item.endswith(".pdf"):
                            item_without_ext = item[:-4]
                            baseline_map[item_without_ext] = item_path

                console.print(f"Found {len(baseline_map)} baseline directories")

                # Show matching statistics
                matched = 0
                for doc in documents:
                    filename = os.path.basename(doc["document_path"])
                    doc_id = os.path.splitext(filename)[0]
                    if doc_id in baseline_map:
                        matched += 1

                console.print(
                    f"Matched {matched}/{len(documents)} documents to baselines"
                )
                console.print()

        # Write manifest (2 columns only)
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["document_path", "baseline_source"])
            writer.writeheader()
            for doc in documents:
                # Get filename and derive ID for baseline matching
                filename = os.path.basename(doc["document_path"])
                doc_id = os.path.splitext(filename)[0]
                baseline_source = baseline_map.get(doc_id, "")

                writer.writerow(
                    {
                        "document_path": doc["document_path"],
                        "baseline_source": baseline_source,
                    }
                )

        console.print(f"[green]✓ Generated manifest: {output}[/green]")
        console.print()

        if baseline_map:
            console.print("[bold]Baseline matching complete[/bold]")
            console.print("Ready to process with evaluations!")
        else:
            console.print("[bold]Next steps:[/bold]")
            console.print(
                "1. Edit manifest to add baseline_source or customize document_id"
            )

        console.print(
            f"2. Process: [cyan]idp-cli run-inference --stack-name <stack> --manifest {output}[/cyan]"
        )
        console.print()

    except Exception as e:
        logger.error(f"Error generating manifest: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


@cli.command(name="validate-manifest")
@click.option(
    "--manifest",
    required=True,
    type=click.Path(exists=True),
    help="Path to manifest file to validate",
)
def validate_manifest_cmd(manifest: str):
    """
    Validate a manifest file without processing

    Example:

      idp-cli validate-manifest --manifest documents.csv
    """
    try:
        is_valid, error = validate_manifest(manifest)

        if is_valid:
            console.print(f"[green]✓ Manifest is valid: {manifest}[/green]")
        else:
            console.print("[red]✗ Manifest validation failed:[/red]")
            console.print(f"  {error}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Error validating manifest: {e}", exc_info=True)
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


def _monitor_progress(
    stack_name: str,
    batch_id: str,
    document_ids: list,
    refresh_interval: int,
    region: Optional[str],
    resources: dict,
):
    """
    Monitor batch progress with live updates

    Args:
        stack_name: CloudFormation stack name
        batch_id: Batch identifier
        document_ids: List of document IDs to monitor
        refresh_interval: Seconds between status checks
        region: AWS region
        resources: Stack resources dictionary
    """
    monitor = ProgressMonitor(stack_name=stack_name, resources=resources, region=region)

    display.show_monitoring_header(batch_id)

    start_time = time.time()

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                # Get current status
                status_data = monitor.get_batch_status(document_ids)
                stats = monitor.calculate_statistics(status_data)
                elapsed_time = time.time() - start_time

                # Update display
                layout = display.create_live_display(
                    batch_id=batch_id,
                    status_data=status_data,
                    stats=stats,
                    elapsed_time=elapsed_time,
                )
                live.update(layout)

                # Check if all complete
                if stats["all_complete"]:
                    break

                # Wait before next check
                time.sleep(refresh_interval)

    except KeyboardInterrupt:
        logger.info("Monitoring interrupted by user")
        console.print()
        console.print(
            "[yellow]Monitoring stopped. Processing continues in background.[/yellow]"
        )
        display.show_monitoring_instructions(stack_name, batch_id)
        return
    except Exception as e:
        logger.error(f"Monitoring error: {e}", exc_info=True)
        console.print()
        console.print(f"[red]Monitoring error: {e}[/red]")
        console.print("[yellow]You can check status later with:[/yellow]")
        display.show_monitoring_instructions(stack_name, batch_id)
        return

    # Show final summary
    logger.info("Showing final summary")
    elapsed_time = time.time() - start_time
    display.show_final_summary(status_data, stats, elapsed_time)


def main():
    """Main entry point for the CLI"""
    cli()


if __name__ == "__main__":
    main()
