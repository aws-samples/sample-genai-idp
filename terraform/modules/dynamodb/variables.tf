variable "table_name" {
  description = "Name of the DynamoDB table"
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.table_name))
    error_message = "Table name must be 3-255 characters and contain only alphanumeric characters, underscores, hyphens, and periods"
  }
}

variable "billing_mode" {
  description = "Controls billing mode (PROVISIONED or PAY_PER_REQUEST)"
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PROVISIONED", "PAY_PER_REQUEST"], var.billing_mode)
    error_message = "Billing mode must be PROVISIONED or PAY_PER_REQUEST"
  }
}

variable "hash_key" {
  description = "Partition key (hash key)"
  type        = string
}

variable "range_key" {
  description = "Sort key (range key) - optional"
  type        = string
  default     = null
}

variable "attributes" {
  description = "List of attribute definitions"
  type = list(object({
    name = string
    type = string # S (string), N (number), B (binary)
  }))

  validation {
    condition = alltrue([
      for attr in var.attributes : contains(["S", "N", "B"], attr.type)
    ])
    error_message = "Attribute type must be S, N, or B"
  }
}

variable "ttl_attribute" {
  description = "Attribute name for TTL (optional)"
  type        = string
  default     = null
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery"
  type        = bool
  default     = true
}

variable "kms_key_arn" {
  description = "ARN of the KMS key for encryption"
  type        = string

  validation {
    condition     = can(regex("^arn:aws:kms:[a-z0-9-]+:[0-9]{12}:key/[a-f0-9-]+$", var.kms_key_arn))
    error_message = "Must be a valid KMS key ARN"
  }
}

variable "stream_enabled" {
  description = "Enable DynamoDB streams"
  type        = bool
  default     = false
}

variable "stream_view_type" {
  description = "Stream view type (KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES)"
  type        = string
  default     = "NEW_AND_OLD_IMAGES"

  validation {
    condition = contains([
      "KEYS_ONLY",
      "NEW_IMAGE",
      "OLD_IMAGE",
      "NEW_AND_OLD_IMAGES"
    ], var.stream_view_type)
    error_message = "Invalid stream view type"
  }
}

variable "global_secondary_indexes" {
  description = "Global secondary indexes"
  type = list(object({
    name               = string
    hash_key           = string
    range_key          = optional(string)
    projection_type    = string # ALL, KEYS_ONLY, INCLUDE
    non_key_attributes = optional(list(string))
    read_capacity      = optional(number)
    write_capacity     = optional(number)
  }))
  default = []
}

variable "local_secondary_indexes" {
  description = "Local secondary indexes"
  type = list(object({
    name               = string
    range_key          = string
    projection_type    = string
    non_key_attributes = optional(list(string))
  }))
  default = []
}

variable "read_capacity" {
  description = "Read capacity units (for PROVISIONED mode)"
  type        = number
  default     = 5
}

variable "write_capacity" {
  description = "Write capacity units (for PROVISIONED mode)"
  type        = number
  default     = 5
}

variable "replica_regions" {
  description = "Regions for global table replication"
  type        = list(string)
  default     = []
}

variable "create_alarms" {
  description = "Create CloudWatch alarms for throttling"
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags to apply to the table"
  type        = map(string)
  default     = {}
}
