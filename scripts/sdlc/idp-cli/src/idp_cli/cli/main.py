import os
import sys
from idp_cli.service.install_service import InstallService
from idp_cli.util.codepipeline_util import CodePipelineUtil
import typer
from idp_cli.service.uninstall_service import UninstallService
from idp_cli.service.smoketest_service import SmokeTestService
from dotenv import load_dotenv

from loguru import logger

load_dotenv()

app = typer.Typer()

@app.callback()
def callback():
    """
    Awesome Portal Gun
    """


@app.command()
def install(
    account_id: str = typer.Option(..., "--account-id", help="AWS Account ID"),
    cfn_prefix: str = typer.Option("idp-dev", "--cfn-prefix", help="An identifier to prefix the stack"),
    admin_email: str = typer.Option(..., "--admin-email", help="The admin email"),
    idp_pattern: str = typer.Option("Pattern2 - Packet processing with Textract and Bedrock", "--idp-pattern", help="The IDP Pattern to install"),
    cwd: str = typer.Option("./", "--cwd", help="Current working directory"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug mode"),
    publish: bool = typer.Option(True, "--publish", help="Control publishing"),
    deploy: bool = typer.Option(True, "--deploy", help="Control deployment")
):
    """
    Install IDP Accelerator
    """
    typer.echo(f"Installing with account_id: {account_id}, cwd: {cwd}, debug: {debug}")
    service = InstallService(account_id=account_id, cfn_prefix=cfn_prefix, cwd=cwd, debug=debug)
    if publish:
        service.publish()
    
    if deploy:
        service.install(admin_email=admin_email, idp_pattern=idp_pattern)
        typer.echo("Install Complete!")


@app.command()
def uninstall(
    stack_name: str = typer.Option(..., "--stack-name", help="Name of the stack to uninstall"),
    account_id: str = typer.Option(..., "--account-id", help="AWS Account ID"),
    cfn_prefix: str = typer.Option("idp-dev", "--cfn-prefix", help="An identifier to prefix the stack")
):
    """
    Uninstall IDP Accelerator
    """
    try:
        typer.echo(f"Uninstalling stack: {stack_name}")

        service = UninstallService(stack_name=stack_name, account_id=account_id, cfn_prefix=cfn_prefix)

        service.uninstall()

        typer.echo("Uninstall Complete!")
    except Exception as e:
        logger.exception(f"Error during uninstall process: {str(e)}")
        typer.echo(f"Uninstall failed: {str(e)}", err=True)
        sys.exit(1)


@app.command()
def smoketest(
    stack_name: str = typer.Option("idp-Stack", "--stack-name", help="Name of the deployed stack to test"),
    file_path: str = typer.Option("../../../samples/rvl_cdip_package.pdf", "--file-path", help="Path to the test file"),
    verify_string: str = typer.Option("WESTERN DARK FIRED TOBACCO GROWERS", "--verify-string", help="String to verify in the processed output")
):
    """
    Run a smoke test on the deployed IDP Accelerator
    """
    try:
        typer.echo(f"Running smoke test on stack: {stack_name}")
        
        service = SmokeTestService(
            stack_name=stack_name,
            file_path=file_path,
            verify_string=verify_string
        )
        
        result = service.do_smoketest()
        
        if result:
            typer.echo("Smoke test passed successfully!")
        else:
            typer.echo("Smoke test failed!", err=True)
            sys.exit(1)
    except Exception as e:
        logger.exception(f"Error during smoke test: {str(e)}")
        typer.echo(f"Smoke test failed: {str(e)}", err=True)
        sys.exit(1)

@app.command()
def monitor_pipeline(
    pipeline_name: str = typer.Option(..., "--pipeline-name", help="Name of the CodePipeline to monitor"),
    initial_wait: int = typer.Option(10, "--initial-wait", help="Initial wait time in seconds before monitoring"),
    poll_interval: int = typer.Option(30, "--poll-interval", help="Time in seconds between status checks"),
    max_wait: int = typer.Option(60, "--max-wait", help="Maximum wait time in minutes")
):
    """
    Monitor a CodePipeline execution until completion
    """
    try:
        typer.echo(f"Monitoring pipeline: {pipeline_name}")
        
        CodePipelineUtil.wait_for_pipeline_execution(
            pipeline_name=pipeline_name,
            initial_wait_seconds=initial_wait,
            poll_interval_seconds=poll_interval,
            max_wait_minutes=max_wait
        )
        
        typer.echo("Pipeline execution completed successfully!")
    except Exception as e:
        logger.exception(f"Error monitoring pipeline: {str(e)}")
        typer.echo(f"Pipeline monitoring failed: {str(e)}", err=True)
        sys.exit(1)