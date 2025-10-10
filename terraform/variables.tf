# Core Variables
variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-west-2"

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]{1}$", var.aws_region))
    error_message = "Must be a valid AWS region (e.g., us-west-2, us-east-1)"
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod"
  }
}

variable "stack_name" {
  description = "Name of the stack (used for resource naming)"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]*$", var.stack_name))
    error_message = "Stack name must start with a letter and contain only alphanumeric characters and hyphens"
  }
}

# KMS Configuration
variable "kms_key_id" {
  description = "ARN of the KMS key for encryption at rest"
  type        = string

  validation {
    condition     = can(regex("^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]+$", var.kms_key_id))
    error_message = "Must be a valid KMS key ARN"
  }
}

# S3 Configuration
variable "enable_s3_versioning" {
  description = "Enable versioning on S3 buckets"
  type        = bool
  default     = true
}

variable "s3_lifecycle_days" {
  description = "Days before transitioning objects to cheaper storage classes"
  type        = number
  default     = 90

  validation {
    condition     = var.s3_lifecycle_days >= 30
    error_message = "Lifecycle transition must be at least 30 days"
  }
}

# DynamoDB Configuration
variable "dynamodb_billing_mode" {
  description = "DynamoDB billing mode (PROVISIONED or PAY_PER_REQUEST)"
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PROVISIONED", "PAY_PER_REQUEST"], var.dynamodb_billing_mode)
    error_message = "Billing mode must be PROVISIONED or PAY_PER_REQUEST"
  }
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery for DynamoDB tables"
  type        = bool
  default     = true
}

variable "dynamodb_ttl_attribute" {
  description = "Attribute name for DynamoDB TTL"
  type        = string
  default     = "ExpiresAfter"
}

# Lambda Configuration
variable "lambda_runtime" {
  description = "Lambda function runtime"
  type        = string
  default     = "python3.12"
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 900

  validation {
    condition     = var.lambda_timeout >= 1 && var.lambda_timeout <= 900
    error_message = "Lambda timeout must be between 1 and 900 seconds"
  }
}

variable "lambda_memory_size" {
  description = "Lambda function memory size in MB"
  type        = number
  default     = 4096

  validation {
    condition     = var.lambda_memory_size >= 128 && var.lambda_memory_size <= 10240
    error_message = "Lambda memory must be between 128 and 10240 MB"
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days"
  type        = number
  default     = 7

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180,
      365, 400, 545, 731, 1827, 3653
    ], var.log_retention_days)
    error_message = "Must be a valid CloudWatch Logs retention period"
  }
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "WARN"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"], var.log_level)
    error_message = "Log level must be DEBUG, INFO, WARN, ERROR, or CRITICAL"
  }
}

# Lambda Environment Variables
variable "max_workers" {
  description = "Maximum number of concurrent workers for Lambda"
  type        = number
  default     = 20

  validation {
    condition     = var.max_workers >= 1 && var.max_workers <= 100
    error_message = "Max workers must be between 1 and 100"
  }
}

# Bedrock Configuration
variable "bda_project_arn" {
  description = "ARN of the Bedrock Data Automation (BDA) project"
  type        = string
  default     = ""
}

# IAM Configuration
variable "permissions_boundary_arn" {
  description = "(Optional) ARN of IAM permissions boundary policy"
  type        = string
  default     = ""

  validation {
    condition = var.permissions_boundary_arn == "" || can(regex(
      "^arn:aws:iam::[0-9]{12}:policy/.+$",
      var.permissions_boundary_arn
    ))
    error_message = "Must be empty or a valid IAM policy ARN"
  }
}

# S3 Bucket Names (will be created)
variable "input_bucket_name" {
  description = "Name of the input S3 bucket (will be created)"
  type        = string
}

variable "output_bucket_name" {
  description = "Name of the output S3 bucket (will be created)"
  type        = string
}

variable "working_bucket_name" {
  description = "Name of the working S3 bucket (will be created)"
  type        = string
}

# Step Functions Configuration
variable "enable_hitl" {
  description = "Enable Human In The Loop (HITL) functionality"
  type        = bool
  default     = true
}

variable "enable_xray_tracing" {
  description = "Enable AWS X-Ray tracing for Step Functions"
  type        = bool
  default     = true
}

variable "create_step_functions_alarms" {
  description = "Create CloudWatch alarms for Step Functions state machine"
  type        = bool
  default     = true
}

variable "execution_failed_threshold" {
  description = "Threshold for Step Functions failed executions alarm"
  type        = number
  default     = 1

  validation {
    condition     = var.execution_failed_threshold >= 0
    error_message = "Threshold must be a non-negative number"
  }
}

variable "execution_time_threshold_ms" {
  description = "Threshold for Step Functions execution duration alarm in milliseconds"
  type        = number
  default     = 30000

  validation {
    condition     = var.execution_time_threshold_ms > 0
    error_message = "Threshold must be a positive number"
  }
}

variable "alarm_sns_topic_arns" {
  description = "List of SNS topic ARNs to notify when alarms trigger"
  type        = list(string)
  default     = []
}

# AppSync Configuration (optional)
variable "appsync_api_url" {
  description = "URL of the AppSync GraphQL API for document status updates"
  type        = string
  default     = ""
}

variable "appsync_api_arn" {
  description = "ARN of the AppSync GraphQL API for document status updates"
  type        = string
  default     = ""
}

# Bedrock Guardrail Configuration (optional)
variable "bedrock_guardrail_id" {
  description = "ID (not name) of an existing Bedrock Guardrail"
  type        = string
  default     = ""
}

variable "bedrock_guardrail_version" {
  description = "Version of the Bedrock Guardrail"
  type        = string
  default     = ""
}

# SageMaker A2I Configuration
variable "sagemaker_a2i_review_portal_url" {
  description = "SageMaker A2I Review Portal URL for HITL tasks"
  type        = string
  default     = ""
}

# Discovery Configuration
variable "discovery_bucket_name" {
  description = "Name of the discovery S3 bucket (will be created)"
  type        = string
}

# Tags
variable "additional_tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
