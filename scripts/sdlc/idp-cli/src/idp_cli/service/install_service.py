from typing import Optional
import os
import subprocess
import datetime
import time
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
        # ./publish.sh <cfn_bucket_basename> <cfn_prefix> <region e.g. us-east-1>

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
            logger.debug(f"Running publish command: ./publish.sh {self.cfn_bucket_basename} {self.cfn_prefix} {self.region}")
            
            # Set up environment variables for the subprocess
            env_vars = os.environ.copy()

            process = subprocess.run(
                ['./publish.sh', self.cfn_bucket_basename, self.cfn_prefix, self.region],
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
        

    def install(self, admin_email: str, idp_pattern: str):
        """
        Install the IDP stack using CloudFormation.
        
        Args:
            admin_email: Email address for the admin user
            idp_pattern: IDP pattern to deploy
            stack_name: Optional stack name (defaults to idp-Stack)
        """
        template_file = '.aws-sam/idp-main.yaml'
        
        s3_prefix = f"{self.cfn_prefix}/0.2.2"  # TODO: Make version configurable

        try:
            # Verify template file exists
            template_path = os.path.join(self.abs_cwd, template_file)
            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Template file not found: {template_path}")

            # Construct the CloudFormation deploy command
            cmd = [
                'aws', 'cloudformation', 'deploy',
                '--region', self.region,
                '--template-file', template_file,
                '--s3-bucket', self.s3_bucket,
                '--s3-prefix', s3_prefix,
                '--capabilities', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND',
                '--parameter-overrides',
                f"IDPPattern={idp_pattern}",
                f"AdminEmail={admin_email}",
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

            logger.info(f"Successfully deployed stack {stack_name} in {self.region}")
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