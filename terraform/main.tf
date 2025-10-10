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

# Input Bucket - receives raw documents for processing
module "input_bucket" {
  source = "./modules/s3"

  bucket_name       = var.input_bucket_name
  kms_key_arn       = var.kms_key_id
  enable_versioning = var.enable_s3_versioning
  force_destroy     = false # Safety: prevent accidental deletion

  lifecycle_rules = [
    {
      id      = "transition-old-files"
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

# Discovery Bucket - stores documents for discovery processing
module "discovery_bucket" {
  source = "./modules/s3"

  bucket_name       = var.discovery_bucket_name
  kms_key_arn       = var.kms_key_id
  enable_versioning = var.enable_s3_versioning
  force_destroy     = false

  lifecycle_rules = [
    {
      id      = "archive-discovery-files"
      enabled = true
      transitions = [
        {
          days          = var.s3_lifecycle_days
          storage_class = "GLACIER_IR"
        }
      ]
      expiration_days                    = null
      noncurrent_version_expiration_days = 365
    }
  ]

  tags = local.common_tags
}

# Working Bucket - for intermediate processing files
module "working_bucket" {
  source = "./modules/s3"

  bucket_name       = var.working_bucket_name
  kms_key_arn       = var.kms_key_id
  enable_versioning = var.enable_s3_versioning
  force_destroy     = false # Safety: prevent accidental deletion

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

  bucket_name       = var.output_bucket_name
  kms_key_arn       = var.kms_key_id
  enable_versioning = var.enable_s3_versioning
  force_destroy     = false

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

# Configuration Table - stores configuration for document processing patterns
module "configuration_table" {
  source = "./modules/dynamodb"

  table_name   = "${var.stack_name}-ConfigurationTable"
  billing_mode = var.dynamodb_billing_mode

  # Primary key
  hash_key  = "id"
  range_key = null

  # Attribute definitions
  attributes = [
    {
      name = "id"
      type = "S" # String
    }
  ]

  # TTL configuration
  ttl_attribute = var.dynamodb_ttl_attribute

  # Backup and recovery
  enable_point_in_time_recovery = var.enable_point_in_time_recovery

  # Encryption
  kms_key_arn = var.kms_key_id

  # Monitoring
  create_alarms = true

  tags = local.common_tags
}

# Discovery Tracking Table - tracks discovery job status and metadata
module "discovery_tracking_table" {
  source = "./modules/dynamodb"

  table_name   = "${var.stack_name}-DiscoveryTrackingTable"
  billing_mode = var.dynamodb_billing_mode

  # Primary key
  hash_key  = "id"
  range_key = null

  # Attribute definitions
  attributes = [
    {
      name = "id"
      type = "S" # String
    }
  ]

  # TTL configuration
  ttl_attribute = var.dynamodb_ttl_attribute

  # Backup and recovery
  enable_point_in_time_recovery = var.enable_point_in_time_recovery

  # Encryption
  kms_key_arn = var.kms_key_id

  # Monitoring
  create_alarms = true

  tags = local.common_tags
}

# Tracking Table - tracks document processing execution state
module "tracking_table" {
  source = "./modules/dynamodb"

  table_name   = "${var.stack_name}-TrackingTable"
  billing_mode = var.dynamodb_billing_mode

  # Primary key (composite)
  hash_key  = "execution_id"
  range_key = "record_id"

  # Attribute definitions
  attributes = [
    {
      name = "execution_id"
      type = "S" # String
    },
    {
      name = "record_id"
      type = "S" # String
    }
  ]

  # TTL configuration
  ttl_attribute = var.dynamodb_ttl_attribute

  # Backup and recovery
  enable_point_in_time_recovery = var.enable_point_in_time_recovery

  # Encryption
  kms_key_arn = var.kms_key_id

  # Optional: DynamoDB Streams
  stream_enabled   = false
  stream_view_type = "NEW_AND_OLD_IMAGES"

  # Monitoring
  create_alarms = true

  tags = local.common_tags
}

# ============================================================================
# SQS Queues
# ============================================================================

# Dead Letter Queue for Configuration Queue
resource "aws_sqs_queue" "configuration_queue_dlq" {
  name                       = "${var.stack_name}-ConfigurationQueueDLQ"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 345600 # 4 days
  kms_master_key_id          = var.kms_key_id

  tags = local.common_tags
}

# Configuration Queue - Triggers BDADiscoveryFunction
resource "aws_sqs_queue" "configuration_queue" {
  name                       = "${var.stack_name}-ConfigurationQueue"
  visibility_timeout_seconds = 900     # Match Lambda timeout
  message_retention_seconds  = 1209600 # 14 days
  kms_master_key_id          = var.kms_key_id

  # Dead letter queue configuration
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.configuration_queue_dlq.arn
    maxReceiveCount     = 3
  })

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
    TRACKING_TABLE   = module.tracking_table.table_name
    METRIC_NAMESPACE = var.stack_name
    MAX_WORKERS      = tostring(var.max_workers)
    LOG_LEVEL        = var.log_level
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.input_bucket.bucket_id
  ]
  s3_write_buckets = [
    module.working_bucket.bucket_id,
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.tracking_table.table_name,
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
    module.input_bucket,
    module.working_bucket,
    module.output_bucket,
    module.tracking_table,
    module.bda_metadata_table
  ]
}

# ============================================================================
# Lambda Function Packages - All 7 Functions
# ============================================================================

# 1. ProcessResultsFunction package
data "archive_file" "process_results_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/processresults_function"
  output_path = "${path.module}/lambda_packages/process_results_function.zip"
}

# 2. HITLWaitFunction package
data "archive_file" "hitl_wait_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/hitl-wait-function"
  output_path = "${path.module}/lambda_packages/hitl_wait_function.zip"
}

# 3. HITLStatusUpdateFunction package
data "archive_file" "hitl_status_update_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/hitl-status-update-function"
  output_path = "${path.module}/lambda_packages/hitl_status_update_function.zip"
}

# 4. SummarizationFunction package
data "archive_file" "summarization_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/summarization_function"
  output_path = "${path.module}/lambda_packages/summarization_function.zip"
}

# 5. HITLProcessLambdaFunction package
data "archive_file" "hitl_process_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/hitl-process-function"
  output_path = "${path.module}/lambda_packages/hitl_process_function.zip"
}

# 6. BDACompletionFunction package
data "archive_file" "bda_completion_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/bda_completion_function"
  output_path = "${path.module}/lambda_packages/bda_completion_function.zip"
}

# 7. BDADiscoveryFunction package
data "archive_file" "bda_discovery_package" {
  type        = "zip"
  source_dir  = "${path.module}/../patterns/pattern-1/src/bda_discovery_function"
  output_path = "${path.module}/lambda_packages/bda_discovery_function.zip"
}

# ============================================================================
# Lambda Functions - All 7 Functions
# ============================================================================

# 1. ProcessResultsFunction - Process BDA results and trigger HITL if needed
module "process_results_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-ProcessResultsFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = 900
  memory_size   = var.lambda_memory_size

  # Code
  source_code_zip  = data.archive_file.process_results_package.output_path
  source_code_hash = data.archive_file.process_results_package.output_base64sha256

  # Environment variables matching CloudFormation
  environment_variables = merge(
    {
      METRIC_NAMESPACE                = var.stack_name
      LOG_LEVEL                       = var.log_level
      TRACKING_TABLE                  = module.tracking_table.table_name
      ENABLE_HITL                     = tostring(var.enable_hitl)
      DB_NAME                         = module.bda_metadata_table.table_name
      BDA_PROJECT_ARN                 = var.bda_project_arn
      WORKING_BUCKET                  = module.working_bucket.bucket_id
      SAGEMAKER_A2I_REVIEW_PORTAL_URL = var.sagemaker_a2i_review_portal_url
      CONFIGURATION_TABLE_NAME        = module.configuration_table.table_name
    },
    # Conditional variables
    var.appsync_api_url != "" ? {
      APPSYNC_API_URL        = var.appsync_api_url
      DOCUMENT_TRACKING_MODE = "appsync"
      } : {
      DOCUMENT_TRACKING_MODE = "dynamodb"
    }
  )

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.input_bucket.bucket_id
  ]
  s3_write_buckets = [
    module.working_bucket.bucket_id,
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.bda_metadata_table.table_name,
    module.configuration_table.table_name,
    module.tracking_table.table_name
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions
  additional_policy_statements = concat(
    # AppSync permissions (conditional)
    var.appsync_api_url != "" ? [
      {
        Effect   = "Allow"
        Action   = ["appsync:GraphQL"]
        Resource = ["${var.appsync_api_arn}/types/Mutation/*"]
      }
    ] : [],
    [
      # SageMaker A2I permissions
      {
        Effect   = "Allow"
        Action   = ["sagemaker:StartHumanLoop"]
        Resource = "arn:${local.partition}:sagemaker:*:*:flow-definition/*"
      },
      # SSM permissions
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter",
          "ssm:GetParametersByPath"
        ]
        Resource = "*"
      },
      # Bedrock permissions
      {
        Effect = "Allow"
        Action = [
          "bedrock:GetDataAutomationProject",
          "bedrock:ListDataAutomationProjects",
          "bedrock:GetBlueprint",
          "bedrock:GetBlueprintRecommendation"
        ]
        Resource = "*"
      }
    ]
  )

  tags = local.common_tags

  depends_on = [
    module.input_bucket,
    module.working_bucket,
    module.output_bucket,
    module.bda_metadata_table,
    module.configuration_table,
    module.tracking_table
  ]
}

# 2. HITLWaitFunction - Check HITL status
module "hitl_wait_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-HITLWaitFunction"
  handler       = "index.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 60
  memory_size   = 256

  # Code
  source_code_zip  = data.archive_file.hitl_wait_package.output_path
  source_code_hash = data.archive_file.hitl_wait_package.output_base64sha256

  # Environment variables
  environment_variables = {
    TRACKING_TABLE                  = module.tracking_table.table_name
    DYNAMODB_TABLE                  = module.bda_metadata_table.table_name
    LOG_LEVEL                       = var.log_level
    SAGEMAKER_A2I_REVIEW_PORTAL_URL = var.sagemaker_a2i_review_portal_url
    WORKING_BUCKET                  = module.working_bucket.bucket_id
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.working_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.tracking_table.table_name,
    module.bda_metadata_table.table_name
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions (KMS decrypt only)
  additional_policy_statements = [
    {
      Effect   = "Allow"
      Action   = ["kms:Decrypt"]
      Resource = var.kms_key_id
    }
  ]

  tags = local.common_tags

  depends_on = [
    module.working_bucket,
    module.bda_metadata_table
  ]
}

# 3. HITLStatusUpdateFunction - Update HITL status
module "hitl_status_update_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-HITLStatusUpdateFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = 300
  memory_size   = 512

  # Code
  source_code_zip  = data.archive_file.hitl_status_update_package.output_path
  source_code_hash = data.archive_file.hitl_status_update_package.output_base64sha256

  # Environment variables
  environment_variables = {
    LOG_LEVEL      = var.log_level
    WORKING_BUCKET = module.working_bucket.bucket_id
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_write_buckets = [
    module.working_bucket.bucket_id
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  tags = local.common_tags

  depends_on = [
    module.working_bucket
  ]
}

# 4. SummarizationFunction - Summarize documents using Bedrock
module "summarization_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-SummarizationFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = 900
  memory_size   = var.lambda_memory_size

  # Code
  source_code_zip  = data.archive_file.summarization_package.output_path
  source_code_hash = data.archive_file.summarization_package.output_base64sha256

  # Environment variables
  environment_variables = merge(
    {
      METRIC_NAMESPACE         = var.stack_name
      CONFIGURATION_TABLE_NAME = module.configuration_table.table_name
      LOG_LEVEL                = var.log_level
      TRACKING_TABLE           = module.tracking_table.table_name
      WORKING_BUCKET           = module.working_bucket.bucket_id
    },
    # Conditional variables
    var.bedrock_guardrail_id != "" && var.bedrock_guardrail_version != "" ? {
      GUARDRAIL_ID_AND_VERSION = "${var.bedrock_guardrail_id}:${var.bedrock_guardrail_version}"
    } : {},
    var.appsync_api_url != "" ? {
      APPSYNC_API_URL        = var.appsync_api_url
      DOCUMENT_TRACKING_MODE = "appsync"
      } : {
      DOCUMENT_TRACKING_MODE = "dynamodb"
    }
  )

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.input_bucket.bucket_id
  ]
  s3_write_buckets = [
    module.working_bucket.bucket_id,
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.configuration_table.table_name,
    module.tracking_table.table_name
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions
  additional_policy_statements = concat(
    # AppSync permissions (conditional)
    var.appsync_api_url != "" ? [
      {
        Effect   = "Allow"
        Action   = ["appsync:GraphQL"]
        Resource = ["${var.appsync_api_arn}/types/Mutation/*"]
      }
    ] : [],
    [
      # Bedrock InvokeModel permissions
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:${local.partition}:bedrock:*::foundation-model/*",
          "arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/*"
        ]
      }
    ],
    # Bedrock Guardrail permissions (conditional)
    var.bedrock_guardrail_id != "" && var.bedrock_guardrail_version != "" ? [
      {
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = "arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:guardrail/${var.bedrock_guardrail_id}"
      }
    ] : []
  )

  tags = local.common_tags

  depends_on = [
    module.input_bucket,
    module.working_bucket,
    module.output_bucket,
    module.configuration_table,
    module.tracking_table
  ]
}

# 5. HITLProcessLambdaFunction - Process HITL completion events
module "hitl_process_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-HITLProcessLambdaFunction"
  handler       = "index.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 300
  memory_size   = 128

  # Code
  source_code_zip  = data.archive_file.hitl_process_package.output_path
  source_code_hash = data.archive_file.hitl_process_package.output_base64sha256

  # Environment variables
  environment_variables = {
    DYNAMODB_TABLE = module.bda_metadata_table.table_name
    TRACKING_TABLE = module.tracking_table.table_name
    LOG_LEVEL      = var.log_level
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.input_bucket.bucket_id,
    module.working_bucket.bucket_id
  ]
  s3_write_buckets = [
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.bda_metadata_table.table_name,
    module.tracking_table.table_name
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions
  additional_policy_statements = [
    # Step Functions SendTask* actions require Resource = "*"
    # See: https://docs.aws.amazon.com/step-functions/latest/dg/callback-task-sample-sqs.html
    {
      Effect = "Allow"
      Action = [
        "states:SendTaskSuccess",
        "states:SendTaskFailure"
      ]
      Resource = "*"
    }
  ]

  tags = local.common_tags

  depends_on = [
    module.working_bucket,
    module.output_bucket,
    module.bda_metadata_table
  ]
}

# 6. BDACompletionFunction - Handle BDA job completion events
# DLQ for BDACompletionFunction
resource "aws_sqs_queue" "bda_completion_dlq" {
  name                       = "${var.stack_name}-BDACompletionFunctionDLQ"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 345600 # 4 days
  kms_master_key_id          = var.kms_key_id

  tags = local.common_tags
}

module "bda_completion_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-BDACompletionFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = 900
  memory_size   = var.lambda_memory_size

  # Code
  source_code_zip  = data.archive_file.bda_completion_package.output_path
  source_code_hash = data.archive_file.bda_completion_package.output_base64sha256

  # Environment variables
  environment_variables = {
    TRACKING_TABLE   = module.tracking_table.table_name
    METRIC_NAMESPACE = var.stack_name
    LOG_LEVEL        = var.log_level
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # DynamoDB Permissions (read-only)
  dynamodb_tables = [
    module.tracking_table.table_name
  ]
  dynamodb_read_only = true

  # Dead letter queue
  dead_letter_queue_arn = aws_sqs_queue.bda_completion_dlq.arn

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions
  additional_policy_statements = [
    # Step Functions SendTask* actions require Resource = "*"
    # See: https://docs.aws.amazon.com/step-functions/latest/dg/callback-task-sample-sqs.html
    {
      Effect = "Allow"
      Action = [
        "states:SendTaskSuccess",
        "states:SendTaskFailure"
      ]
      Resource = "*"
    },
    # SQS permissions for DLQ
    {
      Effect = "Allow"
      Action = [
        "sqs:SendMessage"
      ]
      Resource = aws_sqs_queue.bda_completion_dlq.arn
    }
  ]

  tags = local.common_tags

  depends_on = [
    aws_sqs_queue.bda_completion_dlq
  ]
}

# 7. BDADiscoveryFunction - Discover document classes using Bedrock
module "bda_discovery_function" {
  source = "./modules/lambda"

  function_name = "${var.stack_name}-BDADiscoveryFunction"
  handler       = "index.handler"
  runtime       = var.lambda_runtime
  timeout       = 900
  memory_size   = var.lambda_memory_size

  # Code
  source_code_zip  = data.archive_file.bda_discovery_package.output_path
  source_code_hash = data.archive_file.bda_discovery_package.output_base64sha256

  # Environment variables
  environment_variables = {
    METRIC_NAMESPACE         = var.stack_name
    STACK_NAME               = var.stack_name
    LOG_LEVEL                = var.log_level
    DISCOVERY_TRACKING_TABLE = module.discovery_tracking_table.table_name
    CONFIGURATION_TABLE_NAME = module.configuration_table.table_name
    BDA_PROJECT_ARN          = var.bda_project_arn
  }

  # AWS Configuration
  aws_region     = var.aws_region
  aws_account_id = local.account_id

  # S3 Permissions
  s3_read_buckets = [
    module.input_bucket.bucket_id,
    module.discovery_bucket.bucket_id
  ]
  s3_write_buckets = [
    module.working_bucket.bucket_id,
    module.output_bucket.bucket_id
  ]

  # DynamoDB Permissions
  dynamodb_tables = [
    module.discovery_tracking_table.table_name,
    module.configuration_table.table_name
  ]

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms = true

  # Additional IAM permissions
  additional_policy_statements = concat(
    # Bedrock permissions (conditional - only if bda_project_arn is provided)
    var.bda_project_arn != "" ? [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeDataAutomationAsync",
          "bedrock:CreateDataAutomationProject",
          "bedrock:UpdateDataAutomationProject",
          "bedrock:GetDataAutomationProject",
          "bedrock:GetDataAutomationStatus",
          "bedrock:GetBlueprint",
          "bedrock:UpdateBlueprint",
          "bedrock:CreateBlueprint",
          "bedrock:CreateBlueprintVersion",
          "bedrock:ListBlueprints",
          "bedrock:DeleteBlueprint"
        ]
        Resource = [
          var.bda_project_arn,
          "arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:blueprint/*",
          "arn:${local.partition}:bedrock:${var.aws_region}:aws:blueprint/*"
        ]
      }
    ] : [],
    # SQS permissions for event source mapping
    [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = ["arn:${local.partition}:sqs:${var.aws_region}:${local.account_id}:${var.stack_name}-ConfigurationQueue"]
      }
    ]
  )

  tags = local.common_tags

  depends_on = [
    module.input_bucket,
    module.discovery_bucket,
    module.working_bucket,
    module.output_bucket,
    module.discovery_tracking_table,
    module.configuration_table
  ]
}

# SQS Event Source Mapping for BDADiscoveryFunction
resource "aws_lambda_event_source_mapping" "bda_discovery_sqs" {
  event_source_arn = aws_sqs_queue.configuration_queue.arn
  function_name    = module.bda_discovery_function.function_arn
  batch_size       = 1

  function_response_types = ["ReportBatchItemFailures"]

  depends_on = [
    module.bda_discovery_function,
    aws_sqs_queue.configuration_queue
  ]
}

# ============================================================================
# Step Functions State Machine
# ============================================================================

# Document Processing Workflow State Machine
# This orchestrates the BDA document processing pipeline
module "document_processing_state_machine" {
  source = "./modules/step_functions"

  state_machine_name = "${var.stack_name}-DocumentProcessingWorkflow"

  # Lambda function ARNs - all converted from CloudFormation
  invoke_bda_lambda_arn           = module.invoke_bda_function.function_arn
  process_results_lambda_arn      = module.process_results_function.function_arn
  hitl_wait_function_arn          = module.hitl_wait_function.function_arn
  hitl_status_update_function_arn = module.hitl_status_update_function.function_arn
  summarization_lambda_arn        = module.summarization_function.function_arn

  # All Lambda function ARNs for IAM policy
  lambda_function_arns = [
    module.invoke_bda_function.function_arn,
    module.process_results_function.function_arn,
    module.hitl_wait_function.function_arn,
    module.hitl_status_update_function.function_arn,
    module.summarization_function.function_arn,
  ]

  # S3 buckets
  working_bucket = module.working_bucket.bucket_id
  output_bucket  = module.output_bucket.bucket_id

  # Bedrock configuration
  bda_project_arn = var.bda_project_arn

  # Feature flags
  enable_hitl         = var.enable_hitl
  enable_xray_tracing = var.enable_xray_tracing

  # Security
  kms_key_arn              = var.kms_key_id
  permissions_boundary_arn = var.permissions_boundary_arn

  # Logging
  log_retention_days = var.log_retention_days

  # Monitoring
  create_alarms               = var.create_step_functions_alarms
  alarm_sns_topic_arns        = var.alarm_sns_topic_arns
  execution_failed_threshold  = var.execution_failed_threshold
  execution_time_threshold_ms = var.execution_time_threshold_ms

  tags = local.common_tags

  depends_on = [
    module.invoke_bda_function,
    module.process_results_function,
    module.hitl_wait_function,
    module.hitl_status_update_function,
    module.summarization_function,
    module.input_bucket,
    module.working_bucket,
    module.output_bucket,
    module.tracking_table,
    module.configuration_table
  ]
}

# ============================================================================
# EventBridge Rules
# ============================================================================

# BDA Event Rule - Triggers BDACompletionFunction on Bedrock job completion
resource "aws_cloudwatch_event_rule" "bda_event_rule" {
  name        = "${var.stack_name}-BDAEventRule"
  description = "Trigger BDACompletionFunction on Bedrock Data Automation job completion"
  state       = "ENABLED"

  event_pattern = jsonencode({
    source = ["aws.bedrock"]
    detail-type = [
      "Bedrock Data Automation Job Succeeded",
      "Bedrock Data Automation Job Failed With Client Error",
      "Bedrock Data Automation Job Failed With Service Error"
    ]
  })

  tags = local.common_tags
}

# EventBridge Target - BDACompletionFunction
resource "aws_cloudwatch_event_target" "bda_completion_target" {
  rule      = aws_cloudwatch_event_rule.bda_event_rule.name
  target_id = "BDACompletionFunction"
  arn       = module.bda_completion_function.function_arn

  retry_policy {
    maximum_retry_attempts       = 3
    maximum_event_age_in_seconds = 3600 # 1 hour
  }
}

# Lambda Permission - Allow EventBridge to invoke BDACompletionFunction
resource "aws_lambda_permission" "bda_event_invoke" {
  statement_id  = "AllowExecutionFromBDAEventRule"
  action        = "lambda:InvokeFunction"
  function_name = module.bda_completion_function.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.bda_event_rule.arn
}

# HITL Event Rule - Triggers HITLProcessLambdaFunction on SageMaker A2I status change
resource "aws_cloudwatch_event_rule" "hitl_event_rule" {
  name        = "${var.stack_name}-HITLEventRule"
  description = "Trigger HITLProcessLambdaFunction on SageMaker A2I HumanLoop status change"
  state       = "ENABLED"

  event_pattern = jsonencode({
    source      = ["aws.sagemaker"]
    detail-type = ["SageMaker A2I HumanLoop Status Change"]
    detail = {
      humanLoopStatus = ["Completed", "Failed", "Stopped"]
    }
  })

  tags = local.common_tags
}

# EventBridge Target - HITLProcessLambdaFunction
resource "aws_cloudwatch_event_target" "hitl_process_target" {
  rule      = aws_cloudwatch_event_rule.hitl_event_rule.name
  target_id = "HITLProcessLambdaTarget"
  arn       = module.hitl_process_function.function_arn
}

# Lambda Permission - Allow EventBridge to invoke HITLProcessLambdaFunction
resource "aws_lambda_permission" "hitl_event_invoke" {
  statement_id  = "AllowExecutionFromHITLEventRule"
  action        = "lambda:InvokeFunction"
  function_name = module.hitl_process_function.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hitl_event_rule.arn
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
