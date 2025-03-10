import boto3
from botocore.exceptions import ClientError

class CfnUtil:
    """
    Utility class for interacting with AWS CloudFormation stacks.
    """
    
    @staticmethod
    def get_stack_outputs(stack_name, region_name=None, profile_name=None):
        """
        Get the outputs from a CloudFormation stack.
        
        Args:
            stack_name (str): Name of the CloudFormation stack.
            region_name (str, optional): AWS region name. If None, uses default region.
            profile_name (str, optional): AWS profile name. If None, uses default profile.
            
        Returns:
            dict: Dictionary of stack outputs where keys are output keys and values are output values.
            
        Raises:
            ClientError: If the stack does not exist or another AWS error occurs.
        """
        # Create a session with the specified region and profile
        session = boto3.Session(region_name=region_name, profile_name=profile_name)
        cfn_client = session.client('cloudformation')
        
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            
            # Check if stack exists and has outputs
            if not response['Stacks'] or 'Outputs' not in response['Stacks'][0]:
                return {}
                
            # Convert the outputs list to a dictionary
            outputs = {}
            for output in response['Stacks'][0]['Outputs']:
                outputs[output['OutputKey']] = output['OutputValue']
                
            return outputs
            
        except ClientError as e:
            if "Stack with id {} does not exist".format(stack_name) in str(e):
                raise ValueError(f"Stack '{stack_name}' does not exist")
            else:
                raise e
            
    @staticmethod
    def delete_stack(stack_name, wait=False):
        """
        Delete a CloudFormation stack.
        
        Args:
            stack_name (str): Name of the CloudFormation stack to delete.
            wait (bool, optional): If True, waits for the stack deletion to complete. Defaults to False.
            
        Returns:
            dict: The response from the delete_stack API call.
            
        Raises:
            ClientError: If the stack does not exist or another AWS error occurs.
        """
        cfn_client = boto3.client('cloudformation')
        
        try:
            response = cfn_client.delete_stack(StackName=stack_name)
            
            if wait:
                waiter = cfn_client.get_waiter('stack_delete_complete')
                waiter.wait(StackName=stack_name)
                
            return response
            
        except ClientError as e:
            if "Stack with id {} does not exist".format(stack_name) in str(e):
                raise ValueError(f"Stack '{stack_name}' does not exist")
            else:
                raise e