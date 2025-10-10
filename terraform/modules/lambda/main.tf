# Lambda Function Module - InvokeBDAFunction equivalent

# CloudWatch Log Group (must be created before Lambda)
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

# IAM Role for Lambda execution
resource "aws_iam_role" "lambda" {
  name                 = "${var.function_name}-role"
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = var.tags
}

# Basic Lambda execution policy
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Custom IAM policy for Lambda
resource "aws_iam_role_policy" "lambda_custom" {
  name = "${var.function_name}-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      # S3 read permissions
      length(var.s3_read_buckets) > 0 ? [
        {
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:GetObjectVersion"
          ]
          Resource = [
            for bucket in var.s3_read_buckets : "arn:aws:s3:::${bucket}/*"
          ]
        }
      ] : [],
      # S3 write permissions
      length(var.s3_write_buckets) > 0 ? [
        {
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:GetObjectVersion",
            "s3:PutObject",
            "s3:DeleteObject",
            "s3:ListBucket"
          ]
          Resource = flatten([
            for bucket in var.s3_write_buckets : [
              "arn:aws:s3:::${bucket}",
              "arn:aws:s3:::${bucket}/*"
            ]
          ])
        }
      ] : [],
      # DynamoDB permissions
      length(var.dynamodb_tables) > 0 ? [
        {
          Effect = "Allow"
          Action = concat(
            [
              "dynamodb:GetItem",
              "dynamodb:Query",
              "dynamodb:Scan",
              "dynamodb:BatchGetItem"
            ],
            var.dynamodb_read_only ? [] : [
              "dynamodb:PutItem",
              "dynamodb:UpdateItem",
              "dynamodb:DeleteItem",
              "dynamodb:BatchWriteItem"
            ]
          )
          Resource = [
            for table in var.dynamodb_tables : "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${table}"
          ]
        }
      ] : [],
      # KMS permissions
      [
        {
          Effect = "Allow"
          Action = [
            "kms:Encrypt",
            "kms:Decrypt",
            "kms:ReEncrypt*",
            "kms:GenerateDataKey*",
            "kms:DescribeKey"
          ]
          Resource = var.kms_key_arn
        }
      ],
      # CloudWatch Metrics
      [
        {
          Effect   = "Allow"
          Action   = "cloudwatch:PutMetricData"
          Resource = "*"
        }
      ],
      # Bedrock permissions
      var.bda_project_arn != "" ? [
        {
          Effect = "Allow"
          Action = "bedrock:InvokeDataAutomationAsync"
          Resource = concat(
            [var.bda_project_arn],
            [
              for region in ["us-east-1", "us-east-2", "us-west-1", "us-west-2"] :
              "arn:aws:bedrock:${region}:${var.aws_account_id}:data-automation-profile/us.data-automation-v1"
            ]
          )
        }
      ] : [],
      # Additional custom policy statements
      var.additional_policy_statements
    )
  })
}

# Lambda function
resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn

  # Code configuration
  filename         = var.source_code_zip
  source_code_hash = var.source_code_hash
  handler          = var.handler
  runtime          = var.runtime

  # Resource configuration
  timeout     = var.timeout
  memory_size = var.memory_size

  # Environment variables
  dynamic "environment" {
    for_each = length(var.environment_variables) > 0 ? [1] : []
    content {
      variables = var.environment_variables
    }
  }

  # Logging configuration
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.lambda.name
  }

  # VPC configuration (if provided)
  dynamic "vpc_config" {
    for_each = var.vpc_config != null ? [var.vpc_config] : []
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  # Reserved concurrent executions (optional)
  reserved_concurrent_executions = var.reserved_concurrent_executions

  # Layers (optional)
  layers = var.lambda_layers

  # Tracing (optional)
  tracing_config {
    mode = var.enable_xray_tracing ? "Active" : "PassThrough"
  }

  # Dead letter queue (optional)
  dynamic "dead_letter_config" {
    for_each = var.dead_letter_queue_arn != null ? [1] : []
    content {
      target_arn = var.dead_letter_queue_arn
    }
  }

  # File system config (optional - for EFS)
  dynamic "file_system_config" {
    for_each = var.file_system_config != null ? [var.file_system_config] : []
    content {
      arn              = file_system_config.value.arn
      local_mount_path = file_system_config.value.local_mount_path
    }
  }

  tags = merge(
    var.tags,
    {
      Name = var.function_name
    }
  )

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_custom,
    aws_iam_role_policy_attachment.lambda_basic
  ]
}

# CloudWatch alarms for monitoring (optional)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  count               = var.create_alarms ? 1 : 0
  alarm_name          = "${var.function_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "Lambda function errors exceed threshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.this.function_name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  count               = var.create_alarms ? 1 : 0
  alarm_name          = "${var.function_name}-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Average"
  threshold           = var.timeout * 1000 * 0.9 # 90% of timeout in milliseconds
  alarm_description   = "Lambda function duration approaching timeout"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.this.function_name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  count               = var.create_alarms ? 1 : 0
  alarm_name          = "${var.function_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "Lambda function throttles detected"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.this.function_name
  }

  tags = var.tags
}
