# Terraform Outputs

# ============================================================================
# S3 Buckets
# ============================================================================

output "input_bucket_name" {
  description = "Name of the input S3 bucket"
  value       = module.input_bucket.bucket_id
}

output "input_bucket_arn" {
  description = "ARN of the input S3 bucket"
  value       = module.input_bucket.bucket_arn
}

output "discovery_bucket_name" {
  description = "Name of the discovery S3 bucket"
  value       = module.discovery_bucket.bucket_id
}

output "discovery_bucket_arn" {
  description = "ARN of the discovery S3 bucket"
  value       = module.discovery_bucket.bucket_arn
}

output "working_bucket_name" {
  description = "Name of the working S3 bucket"
  value       = module.working_bucket.bucket_id
}

output "working_bucket_arn" {
  description = "ARN of the working S3 bucket"
  value       = module.working_bucket.bucket_arn
}

output "output_bucket_name" {
  description = "Name of the output S3 bucket"
  value       = module.output_bucket.bucket_id
}

output "output_bucket_arn" {
  description = "ARN of the output S3 bucket"
  value       = module.output_bucket.bucket_arn
}

# ============================================================================
# DynamoDB
# ============================================================================

output "bda_metadata_table_name" {
  description = "Name of the BDA metadata DynamoDB table"
  value       = module.bda_metadata_table.table_name
}

output "bda_metadata_table_arn" {
  description = "ARN of the BDA metadata DynamoDB table"
  value       = module.bda_metadata_table.table_arn
}

output "configuration_table_name" {
  description = "Name of the Configuration DynamoDB table"
  value       = module.configuration_table.table_name
}

output "configuration_table_arn" {
  description = "ARN of the Configuration DynamoDB table"
  value       = module.configuration_table.table_arn
}

output "discovery_tracking_table_name" {
  description = "Name of the Discovery Tracking DynamoDB table"
  value       = module.discovery_tracking_table.table_name
}

output "discovery_tracking_table_arn" {
  description = "ARN of the Discovery Tracking DynamoDB table"
  value       = module.discovery_tracking_table.table_arn
}

output "tracking_table_name" {
  description = "Name of the Tracking DynamoDB table"
  value       = module.tracking_table.table_name
}

output "tracking_table_arn" {
  description = "ARN of the Tracking DynamoDB table"
  value       = module.tracking_table.table_arn
}

# ============================================================================
# Lambda Functions
# ============================================================================

# InvokeBDA Function
output "invoke_bda_function_name" {
  description = "Name of the InvokeBDA Lambda function"
  value       = module.invoke_bda_function.function_name
}

output "invoke_bda_function_arn" {
  description = "ARN of the InvokeBDA Lambda function"
  value       = module.invoke_bda_function.function_arn
}

output "invoke_bda_function_role_arn" {
  description = "ARN of the InvokeBDA Lambda function's IAM role"
  value       = module.invoke_bda_function.role_arn
}

output "invoke_bda_log_group_name" {
  description = "Name of the InvokeBDA Lambda function's CloudWatch Log Group"
  value       = module.invoke_bda_function.log_group_name
}

# ProcessResults Function
output "process_results_function_name" {
  description = "Name of the ProcessResults Lambda function"
  value       = module.process_results_function.function_name
}

output "process_results_function_arn" {
  description = "ARN of the ProcessResults Lambda function"
  value       = module.process_results_function.function_arn
}

output "process_results_function_role_arn" {
  description = "ARN of the ProcessResults Lambda function's IAM role"
  value       = module.process_results_function.role_arn
}

# HITLWait Function
output "hitl_wait_function_name" {
  description = "Name of the HITLWait Lambda function"
  value       = module.hitl_wait_function.function_name
}

output "hitl_wait_function_arn" {
  description = "ARN of the HITLWait Lambda function"
  value       = module.hitl_wait_function.function_arn
}

output "hitl_wait_function_role_arn" {
  description = "ARN of the HITLWait Lambda function's IAM role"
  value       = module.hitl_wait_function.role_arn
}

# HITLStatusUpdate Function
output "hitl_status_update_function_name" {
  description = "Name of the HITLStatusUpdate Lambda function"
  value       = module.hitl_status_update_function.function_name
}

output "hitl_status_update_function_arn" {
  description = "ARN of the HITLStatusUpdate Lambda function"
  value       = module.hitl_status_update_function.function_arn
}

output "hitl_status_update_function_role_arn" {
  description = "ARN of the HITLStatusUpdate Lambda function's IAM role"
  value       = module.hitl_status_update_function.role_arn
}

# Summarization Function
output "summarization_function_name" {
  description = "Name of the Summarization Lambda function"
  value       = module.summarization_function.function_name
}

output "summarization_function_arn" {
  description = "ARN of the Summarization Lambda function"
  value       = module.summarization_function.function_arn
}

output "summarization_function_role_arn" {
  description = "ARN of the Summarization Lambda function's IAM role"
  value       = module.summarization_function.role_arn
}

# HITLProcess Function
output "hitl_process_function_name" {
  description = "Name of the HITLProcess Lambda function"
  value       = module.hitl_process_function.function_name
}

output "hitl_process_function_arn" {
  description = "ARN of the HITLProcess Lambda function"
  value       = module.hitl_process_function.function_arn
}

output "hitl_process_function_role_arn" {
  description = "ARN of the HITLProcess Lambda function's IAM role"
  value       = module.hitl_process_function.role_arn
}

# BDACompletion Function
output "bda_completion_function_name" {
  description = "Name of the BDACompletion Lambda function"
  value       = module.bda_completion_function.function_name
}

output "bda_completion_function_arn" {
  description = "ARN of the BDACompletion Lambda function"
  value       = module.bda_completion_function.function_arn
}

output "bda_completion_function_role_arn" {
  description = "ARN of the BDACompletion Lambda function's IAM role"
  value       = module.bda_completion_function.role_arn
}

output "bda_completion_dlq_arn" {
  description = "ARN of the BDACompletion function's dead letter queue"
  value       = aws_sqs_queue.bda_completion_dlq.arn
}

# BDADiscovery Function
output "bda_discovery_function_name" {
  description = "Name of the BDADiscovery Lambda function"
  value       = module.bda_discovery_function.function_name
}

output "bda_discovery_function_arn" {
  description = "ARN of the BDADiscovery Lambda function"
  value       = module.bda_discovery_function.function_arn
}

output "bda_discovery_function_role_arn" {
  description = "ARN of the BDADiscovery Lambda function's IAM role"
  value       = module.bda_discovery_function.role_arn
}

# ============================================================================
# SQS Queues
# ============================================================================

output "configuration_queue_arn" {
  description = "ARN of the configuration SQS queue"
  value       = aws_sqs_queue.configuration_queue.arn
}

output "configuration_queue_url" {
  description = "URL of the configuration SQS queue"
  value       = aws_sqs_queue.configuration_queue.url
}

output "configuration_queue_dlq_arn" {
  description = "ARN of the configuration queue DLQ"
  value       = aws_sqs_queue.configuration_queue_dlq.arn
}

# ============================================================================
# Step Functions State Machine
# ============================================================================

output "state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = module.document_processing_state_machine.state_machine_name
}

output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = module.document_processing_state_machine.state_machine_arn
}

output "state_machine_role_arn" {
  description = "ARN of the Step Functions state machine IAM role"
  value       = module.document_processing_state_machine.state_machine_role_arn
}

output "state_machine_log_group_name" {
  description = "Name of the Step Functions state machine CloudWatch Log Group"
  value       = module.document_processing_state_machine.log_group_name
}

output "state_machine_console_url" {
  description = "AWS Console URL for the Step Functions state machine"
  value       = module.document_processing_state_machine.console_url
}

# ============================================================================
# EventBridge Rules
# ============================================================================

output "bda_event_rule_arn" {
  description = "ARN of the BDA EventBridge rule"
  value       = aws_cloudwatch_event_rule.bda_event_rule.arn
}

output "hitl_event_rule_arn" {
  description = "ARN of the HITL EventBridge rule"
  value       = aws_cloudwatch_event_rule.hitl_event_rule.arn
}

# ============================================================================
# General Information
# ============================================================================

output "aws_region" {
  description = "AWS region where resources are deployed"
  value       = var.aws_region
}

output "stack_name" {
  description = "Name of the stack"
  value       = var.stack_name
}

output "environment" {
  description = "Environment name"
  value       = var.environment
}

# ============================================================================
# Next Steps
# ============================================================================

output "next_steps" {
  description = "Instructions for next steps"
  value       = <<-EOT

  ✅ Terraform deployment complete!

  Resources Created:
  - S3 Buckets: ${module.working_bucket.bucket_id}, ${module.output_bucket.bucket_id}
  - DynamoDB Table: ${module.bda_metadata_table.table_name}
  - Lambda Function: ${module.invoke_bda_function.function_name}
  - Step Functions State Machine: ${module.document_processing_state_machine.state_machine_name}

  Next Steps:
  1. View Step Functions state machine in console:
     ${module.document_processing_state_machine.console_url}

  2. Start a Step Functions execution:
     aws stepfunctions start-execution \
       --state-machine-arn ${module.document_processing_state_machine.state_machine_arn} \
       --input '{"document": {"bucket": "${module.working_bucket.bucket_id}", "key": "test-doc.pdf"}}'

  3. View Step Functions logs:
     aws logs tail ${module.document_processing_state_machine.log_group_name} --follow

  4. Test Lambda function directly (optional):
     aws lambda invoke --function-name ${module.invoke_bda_function.function_name} \
       --payload '{"test": "event"}' response.json

  5. View Lambda logs:
     aws logs tail ${module.invoke_bda_function.log_group_name} --follow

  6. Check DynamoDB table:
     aws dynamodb scan --table-name ${module.bda_metadata_table.table_name} --max-items 10

  7. List S3 buckets:
     aws s3 ls s3://${module.working_bucket.bucket_id}/
     aws s3 ls s3://${module.output_bucket.bucket_id}/

  8. View CloudWatch dashboard (if created):
     https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards

  NOTE: All Lambda functions referenced in the state machine workflow have been
        provisioned by this stack and are ready for use.

  For enhanced monitoring and automation, consider adding:
  - CloudWatch dashboards for workflow visualization
  - Additional EventBridge rules for custom triggers

  EOT
}
