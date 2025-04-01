#!/usr/bin/env python3
import argparse
import json
import boto3
import sagemaker
from sagemaker.pytorch import PyTorchModel
from botocore.exceptions import ClientError
import time

def create_deployment_role(role_name, model_bucket):
    """
    Create a least privilege IAM role for SageMaker endpoint deployment
    """
    iam = boto3.client('iam')
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Service": "sagemaker.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        
        # Required policies for model deployment
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn='arn:aws:iam::aws:policy/AmazonSageMakerFullAccess'
        )
        
        # Custom S3 policy for model artifacts
        s3_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    f"arn:aws:s3:::{model_bucket}",
                    f"arn:aws:s3:::{model_bucket}/*"
                ]
            }]
        }
        
        policy_name = f"{role_name}-s3-access"
        iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(s3_policy)
        )
        
        account_id = boto3.client('sts').get_caller_identity()['Account']
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn=f'arn:aws:iam::{account_id}:policy/{policy_name}'
        )
        
        # Wait for role and policies to propagate
        waiter = iam.get_waiter('role_exists')
        waiter.wait(RoleName=role_name)
        time.sleep(10)
        
        return response['Role']['Arn']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            response = iam.get_role(RoleName=role_name)
            return response['Role']['Arn']
        raise e

def deploy_model(role, base_model, model_artifact, endpoint_name):
    """
    Deploy a PyTorch model to a SageMaker endpoint
    """
    # If no role provided, create one
    if not role:
        bucket = model_artifact.split('/')[2]  # Extract bucket from S3 URI
        role_name = f"sagemaker-endpoint-{endpoint_name}"
        role = create_deployment_role(role_name, bucket)
        print(f"Created IAM role: {role}")
    
    sagemaker_session = sagemaker.Session()
    pytorch_model = PyTorchModel(
        model_data=model_artifact,
        role=role,
        framework_version="2.4.0",
        py_version="py311",
        sagemaker_session=sagemaker_session,
        env={"BASE_MODEL": base_model}
    )
    
    predictor = pytorch_model.deploy(
        initial_instance_count=1,
        instance_type="ml.g4dn.2xlarge",
        endpoint_name=endpoint_name
    )
    return predictor


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role", type=str, required=False, default="",
        help="Role ARN for deployment. If not provided, a least privilege role will be created."
    )
    parser.add_argument(
        "--model-artifact", type=str, required=True,
        help="S3 uri for the model.tar.gz"
    )
    parser.add_argument(
        "--endpoint-name", type=str, required=True,
        help="Endpoint name"
    )
    parser.add_argument(
        "--base-model", type=str, 
        default="microsoft/udop-large"
    )
    args = parser.parse_args()
    deploy_model(
        args.role, args.base_model, 
        args.model_artifact, args.endpoint_name
    )