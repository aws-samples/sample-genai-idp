import boto3
import time
from loguru import logger

class CodePipelineUtil:
    @staticmethod
    def wait_for_pipeline_execution(pipeline_name, initial_wait_seconds=10, poll_interval_seconds=30, max_wait_minutes=60):
        """
        Monitors a CodePipeline execution until completion.
        
        Args:
            pipeline_name (str): The name of the CodePipeline to monitor
            initial_wait_seconds (int): Time to wait initially for the pipeline to start
            poll_interval_seconds (int): Time between status checks
            max_wait_minutes (int): Maximum time to wait for pipeline completion
            
        Returns:
            None
            
        Raises:
            Exception: If the pipeline execution fails or times out
        """
        client = boto3.client('codepipeline')
        
        # Wait initially to ensure the pipeline has started
        logger.info(f"Waiting {initial_wait_seconds} seconds for pipeline '{pipeline_name}' to start...")
        time.sleep(initial_wait_seconds)
        
        start_time = time.time()
        max_wait_seconds = max_wait_minutes * 60
        
        while True:
            # Check if we've exceeded the maximum wait time
            elapsed_time = time.time() - start_time
            if elapsed_time > max_wait_seconds:
                raise Exception(f"Pipeline '{pipeline_name}' execution timed out after {max_wait_minutes} minutes")
            
            # Get the latest execution
            try:
                response = client.get_pipeline_state(name=pipeline_name)
                stage_states = response.get('stageStates', [])
                
                # Check if pipeline is still running
                pipeline_running = False
                failed_stages = []
                
                for stage in stage_states:
                    stage_name = stage.get('stageName', 'Unknown')
                    latest_execution = stage.get('latestExecution', {})
                    status = latest_execution.get('status', 'Unknown')
                    
                    if status == 'InProgress':
                        pipeline_running = True
                        logger.info(f"Pipeline '{pipeline_name}' is running. Current stage: {stage_name}")
                        break
                    elif status == 'Failed':
                        failed_stages.append(f"{stage_name} ({latest_execution.get('message', 'No message')})")
                
                # If any stages failed, raise an exception
                if failed_stages:
                    message = f"Pipeline '{pipeline_name}' execution failed in stages: {', '.join(failed_stages)}"
                    logger.error(message)
                    raise Exception(message)
                
                # If pipeline is not running and no stages failed, it must have succeeded
                if not pipeline_running:
                    logger.success(f"Pipeline '{pipeline_name}' execution completed successfully!")
                    return
                
                # Wait before checking again
                logger.info(f"Waiting {poll_interval_seconds} seconds before checking pipeline status again...")
                time.sleep(poll_interval_seconds)
                
            except Exception as e:
                if "not found" in str(e).lower():
                    raise Exception(f"Pipeline '{pipeline_name}' not found")
                else:
                    raise e