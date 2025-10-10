# Step Functions State Machine Module

This Terraform module creates an AWS Step Functions state machine for orchestrating the GenAI IDP document processing workflow.

## Overview

The module converts the CloudFormation `AWS::Serverless::StateMachine` resource to Terraform, providing:

- Step Functions state machine with Amazon States Language (ASL) definition
- IAM role and policies for state machine execution
- CloudWatch Logs integration for execution logging
- X-Ray tracing support
- CloudWatch alarms for monitoring execution failures and duration
- Proper encryption using KMS

## Architecture

The state machine orchestrates the following workflow:

1. **InvokeDataAutomation** - Initiates Bedrock Data Automation (BDA) processing
2. **ProcessResultsStep** - Processes BDA results and prepares for HITL if needed
3. **CheckHITLRequired** - Decision point for Human In The Loop review
4. **HITLReview** (conditional) - Waits for human review via SageMaker A2I
5. **HITLStatusUpdate** (conditional) - Updates document with human review results
6. **SummarizationStep** - Generates document summary using Bedrock
7. **WorkflowComplete** - Terminal success state

## CloudFormation to Terraform Mapping

### CloudFormation Resource
```yaml
DocumentProcessingStateMachine:
  Type: AWS::Serverless::StateMachine
  Properties:
    Name: !Sub "${AWS::StackName}-DocumentProcessingWorkflow"
    DefinitionUri: statemachine/workflow.asl.json
    DefinitionSubstitutions:
      InvokeBDALambdaArn: !GetAtt InvokeBDAFunction.Arn
      # ... other substitutions
    Logging:
      Level: ALL
      IncludeExecutionData: true
    Policies:
      - LambdaInvokePolicy
      - CloudWatchLogsFullAccess
```

### Terraform Resource
```hcl
resource "aws_sfn_state_machine" "this" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.state_machine.arn
  definition = templatefile("${path.module}/workflow.asl.json", {
    InvokeBDALambdaArn = var.invoke_bda_lambda_arn
    # ... other variables
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
}
```

## Usage

```hcl
module "document_processing_state_machine" {
  source = "./modules/step_functions"

  state_machine_name = "my-stack-DocumentProcessingWorkflow"

  # Lambda function ARNs
  invoke_bda_lambda_arn          = module.invoke_bda.function_arn
  process_results_lambda_arn     = module.process_results.function_arn
  hitl_wait_function_arn         = module.hitl_wait.function_arn
  hitl_status_update_function_arn = module.hitl_status_update.function_arn
  summarization_lambda_arn       = module.summarization.function_arn

  lambda_function_arns = [
    module.invoke_bda.function_arn,
    module.process_results.function_arn,
    # ... other functions
  ]

  # S3 buckets
  working_bucket = "my-working-bucket"
  output_bucket  = "my-output-bucket"

  # Bedrock configuration
  bda_project_arn = "arn:aws:bedrock:us-east-1:123456789012:data-automation-project/..."

  # Feature flags
  enable_hitl        = "true"
  enable_xray_tracing = true

  # Security
  kms_key_arn              = "arn:aws:kms:us-east-1:123456789012:key/..."
  permissions_boundary_arn = ""

  # Logging
  log_retention_days = 7

  # Monitoring
  create_alarms               = true
  alarm_sns_topic_arns        = ["arn:aws:sns:..."]
  execution_failed_threshold  = 1
  execution_time_threshold_ms = 30000

  tags = {
    Project     = "GenAI-IDP"
    Environment = "dev"
  }
}
```

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| state_machine_name | Name of the Step Functions state machine | string | - | yes |
| invoke_bda_lambda_arn | ARN of the InvokeBDA Lambda function | string | - | yes |
| process_results_lambda_arn | ARN of the ProcessResults Lambda function | string | - | yes |
| hitl_wait_function_arn | ARN of the HITL Wait Lambda function | string | "" | no |
| hitl_status_update_function_arn | ARN of the HITL Status Update Lambda function | string | "" | no |
| summarization_lambda_arn | ARN of the Summarization Lambda function | string | "" | no |
| lambda_function_arns | List of all Lambda function ARNs that the state machine needs to invoke | list(string) | - | yes |
| working_bucket | Name of the S3 working bucket | string | - | yes |
| output_bucket | Name of the S3 output bucket | string | - | yes |
| bda_project_arn | ARN of the Bedrock Data Automation project | string | "" | no |
| enable_hitl | Enable Human In The Loop (HITL) functionality | string | "true" | no |
| enable_xray_tracing | Enable AWS X-Ray tracing for the state machine | bool | true | no |
| log_retention_days | CloudWatch Logs retention period in days | number | 7 | no |
| kms_key_arn | ARN of the KMS key for encryption | string | - | yes |
| permissions_boundary_arn | (Optional) ARN of IAM permissions boundary policy | string | "" | no |
| create_alarms | Create CloudWatch alarms for the state machine | bool | true | no |
| alarm_sns_topic_arns | List of SNS topic ARNs to notify when alarms trigger | list(string) | [] | no |
| execution_failed_threshold | Threshold for failed executions alarm | number | 1 | no |
| execution_time_threshold_ms | Threshold for execution duration alarm in milliseconds | number | 30000 | no |
| tags | Map of tags to apply to all resources | map(string) | {} | no |

## Outputs

| Name | Description |
|------|-------------|
| state_machine_arn | ARN of the Step Functions state machine |
| state_machine_name | Name of the Step Functions state machine |
| state_machine_role_arn | ARN of the IAM role used by the state machine |
| log_group_name | Name of the CloudWatch Log Group |
| console_url | AWS Console URL for the state machine |

## IAM Permissions

The module creates an IAM role with the following permissions:

1. **Lambda Invoke** - Allows invoking all specified Lambda functions
2. **CloudWatch Logs** - Allows writing execution logs
3. **Step Functions** - Basic execution permissions

## Monitoring

When `create_alarms = true`, the module creates:

1. **Execution Failed Alarm** - Triggers when executions fail
2. **Execution Duration Alarm** - Triggers when execution time exceeds threshold

## Cost Considerations

- Step Functions Standard Workflows: $0.025 per 1,000 state transitions
- CloudWatch Logs: Storage and ingestion costs apply
- X-Ray tracing: Additional charges for traces

## Security Best Practices

1. **Encryption at Rest** - All logs encrypted with KMS
2. **IAM Least Privilege** - State machine role has minimal required permissions
3. **Permissions Boundary** - Optional support for organization SCPs
4. **VPC Integration** - Lambda functions can be configured in VPC if needed

## Differences from CloudFormation

1. **Explicit IAM Role Creation** - CloudFormation SAM auto-generates roles, Terraform requires explicit definition
2. **Template Substitution** - Uses Terraform's `templatefile()` function instead of CloudFormation's `DefinitionSubstitutions`
3. **Policy Attachments** - Explicit policy creation and attachment vs. SAM's shorthand policy templates
4. **State Machine Type** - Must explicitly specify "STANDARD" vs. "EXPRESS"

## Future Enhancements

1. Add support for Express workflows (high-volume, short-duration)
2. Implement Step Functions integration with EventBridge
3. Add execution history retention configuration
4. Support for multiple ASL definition files based on pattern type

## Related Resources

- [AWS Step Functions Documentation](https://docs.aws.amazon.com/step-functions/)
- [Amazon States Language Specification](https://states-language.net/spec.html)
- [Terraform AWS Provider - Step Functions](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sfn_state_machine)

## License

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
