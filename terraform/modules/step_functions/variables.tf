# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Step Functions Module Variables

variable "state_machine_name" {
  description = "Name of the Step Functions state machine"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9-_]+$", var.state_machine_name))
    error_message = "State machine name must contain only alphanumeric characters, hyphens, and underscores"
  }
}

# Lambda Function ARNs
variable "invoke_bda_lambda_arn" {
  description = "ARN of the InvokeBDA Lambda function"
  type        = string
}

variable "process_results_lambda_arn" {
  description = "ARN of the ProcessResults Lambda function"
  type        = string
}

variable "hitl_wait_function_arn" {
  description = "ARN of the HITL Wait Lambda function"
  type        = string
  default     = ""
}

variable "hitl_status_update_function_arn" {
  description = "ARN of the HITL Status Update Lambda function"
  type        = string
  default     = ""
}

variable "summarization_lambda_arn" {
  description = "ARN of the Summarization Lambda function"
  type        = string
  default     = ""
}

# All Lambda function ARNs for IAM policy
variable "lambda_function_arns" {
  description = "List of all Lambda function ARNs that the state machine needs to invoke"
  type        = list(string)
}

# S3 Buckets
variable "working_bucket" {
  description = "Name of the S3 working bucket"
  type        = string
}

variable "output_bucket" {
  description = "Name of the S3 output bucket"
  type        = string
}

# Bedrock Configuration
variable "bda_project_arn" {
  description = "ARN of the Bedrock Data Automation project"
  type        = string
  default     = ""
}

# Feature Flags
variable "enable_hitl" {
  description = "Enable Human In The Loop (HITL) functionality"
  type        = string
  default     = "true"

  validation {
    condition     = contains(["true", "false"], var.enable_hitl)
    error_message = "enable_hitl must be 'true' or 'false'"
  }
}

variable "enable_xray_tracing" {
  description = "Enable AWS X-Ray tracing for the state machine"
  type        = bool
  default     = true
}

# Logging Configuration
variable "log_retention_days" {
  description = "CloudWatch Logs retention period in days"
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

# Security
variable "kms_key_arn" {
  description = "ARN of the KMS key for encryption"
  type        = string

  validation {
    condition     = can(regex("^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]+$", var.kms_key_arn))
    error_message = "Must be a valid KMS key ARN"
  }
}

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

# Monitoring and Alarms
variable "create_alarms" {
  description = "Create CloudWatch alarms for the state machine"
  type        = bool
  default     = true
}

variable "alarm_sns_topic_arns" {
  description = "List of SNS topic ARNs to notify when alarms trigger"
  type        = list(string)
  default     = []
}

variable "execution_failed_threshold" {
  description = "Threshold for failed executions alarm"
  type        = number
  default     = 1

  validation {
    condition     = var.execution_failed_threshold >= 0
    error_message = "Threshold must be a non-negative number"
  }
}

variable "execution_time_threshold_ms" {
  description = "Threshold for execution duration alarm in milliseconds"
  type        = number
  default     = 30000

  validation {
    condition     = var.execution_time_threshold_ms > 0
    error_message = "Threshold must be a positive number"
  }
}

# Tags
variable "tags" {
  description = "Map of tags to apply to all resources"
  type        = map(string)
  default     = {}
}
