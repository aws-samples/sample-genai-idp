# Main Terraform Configuration - GenAI IDP Test Conversion
# This configuration demonstrates conversion of 3 core services from CloudFormation to Terraform

# Data sources
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  common_tags = merge(
    {
      Project     = "GenAI-IDP"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Stack       = var.stack_name
    },
    var.additional_tags
  )
}

# ============================================================================
# S3 Buckets
# ============================================================================

# Working Bucket - for intermediate processing files
module "working_bucket" {
  source = "./modules/s3"

  bucket_name        = var.working_bucket_name
  kms_key_arn        = var.kms_key_id
  enable_versioning  = var.enable_s3_versioning
  force_destroy      = false # Safety: prevent accidental deletion

  lifecycle_rules = [
    {
      id      = "transition-old-versions"
      enabled = true
      transitions = [
        {
          days          = var.s3_lifecycle_days
          storage_class = "INTELLIGENT_TIERING"
        }
      ]
      expiration_days                    = null
      noncurrent_version_expiration_days = 365
    }
  ]

  enable_intelligent_tiering = true

  tags = local.common_tags
}

# Output Bucket - for final processed results
module "output_bucket" {
  source = "./modules/s3"

  bucket_name        = var.output_bucket_name
  kms_key_arn        = var.kms_key_id
  enable_versioning  = var.enable_s3_versioning
  force_destroy      = false

  lifecycle_rules = [
    {
      id      = "archive-old-results"
      enabled = true
      transitions = [
        {
          days          = var.s3_lifecycle_days
          storage_class = "GLACIER_IR"
        },
        {
          days          = var.s3_lifecycle_days * 2
          storage_class = "DEEP_ARCHIVE"
        }
      ]
      expiration_days                    = null
      noncurrent_version_expiration_days = 730
    }
  ]

  tags = local.common_tags
}

# ============================================================================
# DynamoDB Table
# ============================================================================

# BDA Metadata Table - stores processing state for Bedrock Data Automation jobs
module "bda_metadata_table" {
  source = "./modules/dynamodb"

  table_name   = "${var.stack_name}-BDAMetadataTable"
  billing_mode = var.dynamodb_billing_mode

  # Keys matching CloudFormation configuration
  hash_key  = "execution_id"
  range_key = "record_number"

  # Attribute definitions
  attributes = [
    {
      name = "execution_id"
      type = "S" # String
    },
    {
      name = "record_number"
      type = "N" # Number
    }
  ]

  # TTL configuration
  ttl_attribute = var.dynamodb_ttl_attribute

  # Backup and recovery
  enable_point_in_time_recovery = var.enable_point_in_time_recovery

  # Encryption
  kms_key_arn = var.kms_key_id

  # Optional: Enable DynamoDB Streams for downstream processing
  stream_enabled   = false
  stream_view_type = "NEW_AND_OLD_IMAGES"

  # Monitoring
  create_alarms = true

  tags = local.common_tags
}

# ============================================================================
# Lambda Function - InvokeBDAFunction
# ============================================================================

# Package the Lambda function code
# NOTE: In production, this should be handled by a CI/CD pipeline
data "archive_file" "lambda_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/bda_invoke_function"
  output_path = "${path.module}/lambda_packages/invoke_bda_function.zip"
}

# InvokeBDA Lambda Function - Core document processing function
module "invoke_bda_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-InvokeBDAFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_size

  # Code
  source_code_zip  = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256

  # Environment variables matching CloudFormation
  environment_variables = {
    TRACKING_TABLE   = var.tracking_table_name
    METRIC_NAMESPACE = var.stack_name
    MAX_WORKERS      = tostring(var.max_workers)
    LOG_LEVEL        = var.log_level
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    var.input_bucket_name
  ]
  s3_write_buckets = [
    module.working_bucket.bucket_id,
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    var.tracking_table_name,
    module.bda_metadata_table.table_name
  ]

  # Bedrock configuration
  bda_project_arn = var.bda_project_arn

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Optional: VPC configuration (uncomment if Lambda needs VPC access)
  # vpc_config = {
  #   subnet_ids         = var.lambda_subnet_ids
  #   security_group_ids = var.lambda_security_group_ids
  # }

  tags = local.common_tags

  depends_on = [
    module.working_bucket,
    module.output_bucket,
    module.bda_metadata_table
  ]
}

# ============================================================================
# Additional Resources (Optional)
# ============================================================================

# Lambda function needs to be invoked by something
# In the full stack, this would be triggered by Step Functions
# For testing, you can invoke manually via AWS CLI or Console

# Example: CloudWatch Event Rule to trigger Lambda on a schedule (disabled by default)
# resource "aws_cloudwatch_event_rule" "invoke_bda_schedule" {
#   name                = "${var.stack_name}-invoke-bda-schedule"
#   description         = "Trigger InvokeBDA function on schedule"
#   schedule_expression = "rate(5 minutes)"
#   is_enabled          = false
#
#   tags = local.common_tags
# }
#
# resource "aws_cloudwatch_event_target" "invoke_bda" {
#   rule      = aws_cloudwatch_event_rule.invoke_bda_schedule.name
#   target_id = "InvokeBDAFunction"
#   arn       = module.invoke_bda_function.function_arn
# }
#
# resource "aws_lambda_permission" "allow_eventbridge" {
#   statement_id  = "AllowExecutionFromEventBridge"
#   action        = "lambda:InvokeFunction"
#   function_name = module.invoke_bda_function.function_name
#   principal     = "events.amazonaws.com"
#   source_arn    = aws_cloudwatch_event_rule.invoke_bda_schedule.arn
# }
