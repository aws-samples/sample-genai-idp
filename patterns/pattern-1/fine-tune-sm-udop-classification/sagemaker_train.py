#!/usr/bin/env python3
import argparse
import json
import boto3
import sagemaker
from sagemaker.pytorch import PyTorch
from sagemaker.debugger import TensorBoardOutputConfig
from botocore.exceptions import ClientError

def create_sagemaker_role(role_name, bucket, data_bucket):
    """
    Create a least privilege IAM role for SageMaker training
    """
    iam = boto3.client('iam')
    
    # Define the role trust policy for SageMaker
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
        # Create the IAM role
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        
        # Attach AmazonSageMakerFullAccess managed policy
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn='arn:aws:iam::aws:policy/AmazonSageMakerFullAccess'
        )
        
        # Create custom policy for S3 access
        bucket_list = [bucket]
        if data_bucket and data_bucket != bucket:
            bucket_list.append(data_bucket)
            
        s3_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket"
                ],
                "Resource": sum([[f"arn:aws:s3:::{b}", f"arn:aws:s3:::{b}/*"] for b in bucket_list], [])
            }]
        }
        
        # Create and attach the custom policy
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
        
        # Wait for role to be ready
        waiter = iam.get_waiter('role_exists')
        waiter.wait(RoleName=role_name)
        
        # Wait for policy attachments to propagate
        import time
        time.sleep(10)   # semgrep-ignore: arbitrary-sleep - Intentional delay. Duration is hardcoded and not user-controlled.
        
        return response['Role']['Arn']
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            # If role exists, get its ARN
            response = iam.get_role(RoleName=role_name)
            return response['Role']['Arn']
        raise e

def create_training_job(role, bucket, job_name, max_epochs, base_model, 
                       bucket_prefix="", data_bucket="", data_bucket_prefix=""):
    """
    Create and run a SageMaker training job
    """
    if not data_bucket:
        data_bucket = bucket
    if not data_bucket_prefix:
        data_bucket_prefix = bucket_prefix
        
    # If no role ARN provided, create one
    if not role:
        role_name = f"sagemaker-training-{job_name}"
        role = create_sagemaker_role(role_name, bucket, data_bucket)
        print(f"Created IAM role: {role}")
        
    # Helper function to construct S3 paths
    def get_s3_path(bucket_name, prefix, path):
        if prefix:
            return f"s3://{bucket_name}/{prefix.rstrip('/')}/{path}"
        return f"s3://{bucket_name}/{path}"
    
    sagemaker_session = sagemaker.Session()
    output_dir = '/opt/ml/output'
    
    # Update all S3 paths to include prefixes
    tensorboard_output_config = TensorBoardOutputConfig(
        s3_output_path=get_s3_path(bucket, bucket_prefix, "tensorboard"),
        container_local_output_path=output_dir + '/tensorboard'
    )
    
    estimator = PyTorch(
        entry_point="train.py",
        source_dir="./code",
        role=role,
        framework_version="2.4.0",
        py_version="py311",
        instance_type="ml.g5.12xlarge",
        instance_count=1,
        output_path=get_s3_path(bucket, bucket_prefix, "models/"),
        hyperparameters={
            "max_epochs": max_epochs,
            "base_model": base_model,
            "output_dir": output_dir
        },
        code_location=get_s3_path(bucket, bucket_prefix, "scripts/training/"),
        sagemaker_session=sagemaker_session,
        tensorboard_output_config=tensorboard_output_config,
        environment={"FI_EFA_FORK_SAFE": "1"}
    )
    
    # Update data channels with prefixed paths
    estimator.fit({
        "training": get_s3_path(data_bucket, data_bucket_prefix, "training"),
        "validation": get_s3_path(data_bucket, data_bucket_prefix, "validation")
    }, job_name=job_name)

    print(f"Model path: {get_s3_path(bucket, bucket_prefix, f'models/{job_name}/output/model.tar.gz')}")
    
    return sagemaker_session


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role", type=str, required=False, default="",
        help="Role ARN for creating the job. If not provided, a least privilege role will be created."
    )
    parser.add_argument(
        "--bucket", type=str, required=True,
        help="S3 bucket name to save the training results"
    )
    parser.add_argument(
        "--bucket-prefix", type=str, default="",
        help="Prefix for paths in the output S3 bucket"
    )
    parser.add_argument(
        "--job-name", type=str, required=True,
        help="Training job name"
    )
    parser.add_argument(
        "--max-epochs", type=int, default=3,
        help="Max epoch for training"
    )
    parser.add_argument(
        "--base-model", type=str, default="microsoft/udop-large",
        help="Base model name"
    )
    parser.add_argument(
        "--data-bucket", type=str, default="",
        help="Name of the S3 bucket, which has the training data. Default to the value of `bucket` arg"
    )
    parser.add_argument(
        "--data-bucket-prefix", type=str, default="",
        help="Prefix for paths in the data S3 bucket. Defaults to the value of bucket-prefix"
    )
    args = parser.parse_args()
    create_training_job(
        args.role, args.bucket, args.job_name,
        args.max_epochs, args.base_model, args.bucket_prefix,
        args.data_bucket, args.data_bucket_prefix
    )