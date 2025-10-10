variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}

variable "kms_key_arn" {
  description = "ARN of the KMS key for S3 encryption"
  type        = string
}

variable "enable_versioning" {
  description = "Enable bucket versioning"
  type        = bool
  default     = true
}

variable "force_destroy" {
  description = "Allow destroying bucket even if not empty (use with caution)"
  type        = bool
  default     = false
}

variable "lifecycle_rules" {
  description = "Lifecycle rules for the bucket"
  type = list(object({
    id      = string
    enabled = bool
    transitions = list(object({
      days          = number
      storage_class = string
    }))
    expiration_days                        = optional(number)
    noncurrent_version_expiration_days     = optional(number)
    abort_incomplete_multipart_upload_days = optional(number)
  }))
  default = null
}

variable "logging_bucket" {
  description = "Target bucket for access logs (optional)"
  type        = string
  default     = null
}

variable "enable_intelligent_tiering" {
  description = "Enable S3 Intelligent-Tiering"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to the bucket"
  type        = map(string)
  default     = {}
}
