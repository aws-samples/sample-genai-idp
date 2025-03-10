from idp_cli.util.cfn_util import CfnUtil
from idp_cli.util.path_util import PathUtil
from idp_cli.util.s3_util import S3Util
import time
import json
import os
from loguru import logger

class SmokeTestService():
    def __init__(self, 
                 stack_name: str, 
                 file_path: str, 
                 verify_string: str):
        
        self.stack_name = stack_name
        self.file_path = file_path
        self.verify_string = verify_string

        logger.debug(f"stack_name: {stack_name}\nfile_path: {file_path}\nverify_string: [{verify_string}]")

    def get_bucket_names(self):
        logger.debug(f"Getting bucket names for stack: {self.stack_name}")
        outputs = CfnUtil.get_stack_outputs(stack_name=self.stack_name)

        input_bucket_name = outputs["S3InputBucketName"]
        output_bucket_name = outputs["S3OutputBucketName"]
        logger.debug(f"Retrieved bucket names - Input: {input_bucket_name}, Output: {output_bucket_name}")
        return input_bucket_name, output_bucket_name

    def upload_testfile(self):
        # Extract just the filename from the provided file_path
        file_key = os.path.basename(self.file_path)
        logger.debug(f"Loading test file from: {self.file_path}")
        
        # Load bytes from the test file using the provided file_path
        with open(self.file_path, 'rb') as f:
            file_bytes = f.read()
        
        logger.debug(f"Loaded {len(file_bytes)} bytes from test file")
        
        # Get bucket names
        input_bucket_name, _ = self.get_bucket_names()
        
        # Upload file to s3 input_bucket
        logger.debug(f"Uploading test file to bucket: {input_bucket_name}, key: {file_key}")
        S3Util.put_bytes(
            bytes_data=file_bytes,  # Testfile bytes
            bucket_name=input_bucket_name,  # input_bucketname
            key=file_key 
        )
        logger.debug(f"Successfully uploaded test file")

        return file_key
        
    def wait_for_processing(self, file_key:str):
        _, output_bucket_name = self.get_bucket_names()
        
        max_attempts = 100
        wait_seconds = 10
        
        # Keep the full file key including extension for the output folder
        logger.debug(f"Waiting for processing, checking for folder: {file_key}/ in bucket: {output_bucket_name}")
        
        # Check for folder existence in a loop
        for attempt in range(max_attempts):
            try:
                logger.debug(f"Attempt {attempt+1}/{max_attempts} to check for folder")
                
                # Use S3Util.list_objects to check for the folder
                response = S3Util.list_objects(
                    bucket_name=output_bucket_name,
                    prefix=f"{file_key}/",
                    max_keys=1
                )

                logger.debug(response)
                
                # If the folder exists, there will be contents in the response
                if response.get('Contents'):
                    logger.debug(f"Successfully found folder: {file_key}/")
                    return file_key
                    
            except Exception as e:
                logger.debug(f"Waiting for processing... Attempt {attempt+1}/{max_attempts}. Error: {str(e)}")
            
            logger.debug(f"Sleeping for {wait_seconds} seconds before next attempt")
            time.sleep(wait_seconds)
        
        logger.error(f"Processing timed out after {max_attempts * wait_seconds} seconds")
        raise TimeoutError(f"Processing timed out after {max_attempts * wait_seconds} seconds")

    def verify_result(self, folder_key):
        logger.debug("Waiting in case the file needs time to write...")
        time.sleep(20)
        logger.debug("Verifying processing result")
        
        
        # Get the output bucket name
        _, output_bucket_name = self.get_bucket_names()
        
        # Define the path to the expected result.json file
        object_path = f"{folder_key}/pages/1/result.json"
        logger.debug(f"Looking for result file at: s3://{output_bucket_name}/{object_path}")
        
        try:
            # Get the JSON from S3
            result_json = S3Util.get_json(bucket_name=output_bucket_name, object_name=object_path)
            
            # Check if result exists
            if not result_json:
                logger.error(f"Result file not found at: s3://{output_bucket_name}/{object_path}")
                raise ValueError(f"Result file not found")
            
            # Check for text property
            if "text" not in result_json:
                logger.error("Missing 'text' property in result JSON")
                raise ValueError("Missing 'text' property in result JSON")
            
            # Check if the text content contains the expected verification string
            if self.verify_string not in result_json["text"]:
                logger.error(f"Text content does not contain expected string: '{self.verify_string}'")
                logger.debug(f"Actual text starts with: '{result_json['text'][:100]}...'")
                raise ValueError(f"Text content does not contain expected verification string")
            
            logger.debug("Smoke test verification passed!")
            return True
            
        except Exception as e:
            logger.error(f"Verification failed: {str(e)}")
            raise

    def do_smoketest(self):
        logger.debug("Starting smoke test")
        
        # Get bucket names
        input_bucket_name, output_bucket_name = self.get_bucket_names()
        logger.debug(f"Using input bucket: {input_bucket_name}")
        logger.debug(f"Using output bucket: {output_bucket_name}")
        
        # Upload test file
        file_key = self.upload_testfile()
        logger.debug(f"Uploaded test file: {file_key}")
        
        # Wait for processing
        logger.debug("Waiting for processing to complete...")
        folder_key = self.wait_for_processing(file_key=file_key)
        logger.debug("Processing completed!")
        
        # Verify result
        self.verify_result(folder_key=folder_key)
        logger.debug("Smoke test completed successfully!")
        
        return True