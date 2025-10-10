# Terraform Outputs

# ============================================================================
# S3 Buckets
# ============================================================================

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

# ============================================================================
# Lambda Function
# ============================================================================

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
  value = <<-EOT

  ✅ Terraform deployment complete!

  Resources Created:
  - S3 Buckets: ${module.working_bucket.bucket_id}, ${module.output_bucket.bucket_id}
  - DynamoDB Table: ${module.bda_metadata_table.table_name}
  - Lambda Function: ${module.invoke_bda_function.function_name}

  Next Steps:
  1. Test Lambda function:
     aws lambda invoke --function-name ${module.invoke_bda_function.function_name} \
       --payload '{"test": "event"}' response.json

  2. View Lambda logs:
     aws logs tail ${module.invoke_bda_function.log_group_name} --follow

  3. Check DynamoDB table:
     aws dynamodb scan --table-name ${module.bda_metadata_table.table_name} --max-items 10

  4. List S3 buckets:
     aws s3 ls s3://${module.working_bucket.bucket_id}/
     aws s3 ls s3://${module.output_bucket.bucket_id}/

  5. View CloudWatch dashboard (if created):
     https://console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards

  For full stack deployment, continue converting:
  - Step Functions state machine
  - EventBridge rules
  - Additional Lambda functions
  - CloudWatch dashboards

  EOT
}
