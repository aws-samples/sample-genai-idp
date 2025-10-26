# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import os
import json
import boto3
from botocore.exceptions import ClientError

# Initialize AWS clients
secrets_manager = boto3.client("secretsmanager")
dynamodb = boto3.client("dynamodb")
stepfunctions = boto3.client("stepfunctions")

# Environment variables
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")
SECRET_NAME = os.environ.get(
    "SECRET_NAME", f"fiscalshield-dc-{ENVIRONMENT}-CompaniesHouseAPI"
)


def lambda_handler(event, context):
    """
    Health check endpoint for Data Collection Stack
    Verifies availability of all required services
    """
    print("Health check requested")

    services = {
        "companies_house": check_companies_house_api(),
        "step_functions": check_step_functions(context),
        "dynamodb": check_dynamodb(),
    }

    # Determine overall status
    all_operational = all(
        status == "operational" or status == "available" for status in services.values()
    )
    status = "available" if all_operational else "degraded"

    print(f"Health check result: {status}, services: {services}")

    response_body = {
        "status": status,
        "version": "1.0.0",
        "services": services,
        "region": AWS_REGION,
        "environment": ENVIRONMENT,
    }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Cache-Control": "max-age=300",  # Cache for 5 minutes
        },
        "body": json.dumps(response_body),
    }


def check_companies_house_api():
    """
    Verify Companies House API credentials exist and are accessible
    """
    try:
        # Just check if secret exists, don't actually call the API
        secrets_manager.describe_secret(SecretId=SECRET_NAME)
        print("Companies House credentials: OK")
        return "operational"
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print(f"Companies House credentials check failed: {error_code}")
        return "unavailable"
    except Exception as e:
        print(f"Companies House credentials check error: {e}")
        return "unavailable"


def check_step_functions(context):
    """
    Verify Step Functions state machine exists
    """
    try:
        # Get account ID from context
        account_id = (
            context.invoked_function_arn.split(":")[4]
            if hasattr(context, "invoked_function_arn")
            else "864899848062"
        )

        state_machine_arn = f"arn:aws:states:{AWS_REGION}:{account_id}:stateMachine:fiscalshield-dc-{ENVIRONMENT}-CompanyResearch"

        stepfunctions.describe_state_machine(stateMachineArn=state_machine_arn)
        print("Step Functions: OK")
        return "available"
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "StateMachineDoesNotExist":
            print("Step Functions state machine not deployed yet")
        else:
            print(f"Step Functions check failed: {error_code}")
        return "unavailable"
    except Exception as e:
        print(f"Step Functions check error: {e}")
        return "unavailable"


def check_dynamodb():
    """
    Verify DynamoDB tables exist and are accessible
    """
    try:
        # Check both FilingEvents and CompanyEvents tables
        tables = [
            f"fiscalshield-dc-{ENVIRONMENT}-FilingEvents",
            f"fiscalshield-dc-{ENVIRONMENT}-CompanyEvents"
        ]
        
        all_active = True
        for table_name in tables:
            try:
                response = dynamodb.describe_table(TableName=table_name)
                status = response["Table"]["TableStatus"]
                
                if status == "ACTIVE":
                    print(f"DynamoDB table {table_name}: OK")
                else:
                    print(f"DynamoDB table {table_name} status: {status}")
                    all_active = False
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    print(f"DynamoDB table {table_name} not found")
                    all_active = False
                else:
                    raise
        
        return "operational" if all_active else "degraded"

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        print(f"DynamoDB check failed: {error_code}")
        return "unavailable"
    except Exception as e:
        print(f"DynamoDB check error: {e}")
        return "unavailable"
