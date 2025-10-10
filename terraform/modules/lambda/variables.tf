variable "function_name" {
  description = "Name of the Lambda function"
  type        = string
}

variable "handler" {
  description = "Lambda function handler"
  type        = string
  default     = "index.handler"
}

variable "runtime" {
  description = "Lambda runtime"
  type        = string
  default     = "python3.12"
}

variable "timeout" {
  description = "Function timeout in seconds"
  type        = number
  default     = 900

  validation {
    condition     = var.timeout >= 1 && var.timeout <= 900
    error_message = "Timeout must be between 1 and 900 seconds"
  }
}

variable "memory_size" {
  description = "Memory size in MB"
  type        = number
  default     = 4096

  validation {
    condition     = var.memory_size >= 128 && var.memory_size <= 10240
    error_message = "Memory must be between 128 and 10240 MB"
  }
}

variable "source_code_zip" {
  description = "Path to Lambda deployment package ZIP file"
  type        = string
}

variable "source_code_hash" {
  description = "Base64-encoded SHA256 hash of the deployment package"
  type        = string
  default     = null
}

variable "environment_variables" {
  description = "Environment variables for the Lambda function"
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "ARN of KMS key for encryption"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days"
  type        = number
  default     = 7
}

variable "permissions_boundary_arn" {
  description = "ARN of IAM permissions boundary (optional)"
  type        = string
  default     = ""
}

# AWS Configuration
variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "aws_account_id" {
  description = "AWS account ID"
  type        = string
}

# S3 Permissions
variable "s3_read_buckets" {
  description = "List of S3 bucket names for read-only access"
  type        = list(string)
  default     = []
}

variable "s3_write_buckets" {
  description = "List of S3 bucket names for read-write access"
  type        = list(string)
  default     = []
}

# DynamoDB Permissions
variable "dynamodb_tables" {
  description = "List of DynamoDB table names to access"
  type        = list(string)
  default     = []
}

# Bedrock Configuration
variable "bda_project_arn" {
  description = "ARN of Bedrock Data Automation project"
  type        = string
  default     = ""
}

# VPC Configuration (optional)
variable "vpc_config" {
  description = "VPC configuration for Lambda"
  type = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

# Additional Configuration
variable "reserved_concurrent_executions" {
  description = "Reserved concurrent executions (-1 for unreserved)"
  type        = number
  default     = -1
}

variable "lambda_layers" {
  description = "List of Lambda Layer ARNs"
  type        = list(string)
  default     = []
}

variable "enable_xray_tracing" {
  description = "Enable AWS X-Ray tracing"
  type        = bool
  default     = false
}

variable "dead_letter_queue_arn" {
  description = "ARN of DLQ for failed invocations"
  type        = string
  default     = null
}

variable "file_system_config" {
  description = "EFS file system configuration"
  type = object({
    arn              = string
    local_mount_path = string
  })
  default = null
}

variable "additional_policy_statements" {
  description = "Additional IAM policy statements"
  type = list(object({
    Effect   = string
    Action   = list(string)
    Resource = any
  }))
  default = []
}

variable "create_alarms" {
  description = "Create CloudWatch alarms"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
