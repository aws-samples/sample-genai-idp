# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Step Functions State Machine Module
# Converts CloudFormation AWS::Serverless::StateMachine to Terraform

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

# ============================================================================
# CloudWatch Log Group for State Machine
# ============================================================================

resource "aws_cloudwatch_log_group" "state_machine" {
  name              = "/aws/vendedlogs/states/${var.state_machine_name}/workflow"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = var.tags
}

# ============================================================================
# IAM Role for State Machine
# ============================================================================

# Trust policy - allows Step Functions to assume this role
data "aws_iam_policy_document" "state_machine_assume_role" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

# IAM Role
resource "aws_iam_role" "state_machine" {
  name                 = "${var.state_machine_name}-StateMachineRole"
  assume_role_policy   = data.aws_iam_policy_document.state_machine_assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = var.tags
}

# Policy for invoking Lambda functions
data "aws_iam_policy_document" "lambda_invoke" {
  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = var.lambda_function_arns
  }
}

resource "aws_iam_policy" "lambda_invoke" {
  name        = "${var.state_machine_name}-LambdaInvokePolicy"
  description = "Allow Step Functions to invoke Lambda functions"
  policy      = data.aws_iam_policy_document.lambda_invoke.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_invoke" {
  role       = aws_iam_role.state_machine.name
  policy_arn = aws_iam_policy.lambda_invoke.arn
}

# Policy for CloudWatch Logs
data "aws_iam_policy_document" "cloudwatch_logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups"
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "${aws_cloudwatch_log_group.state_machine.arn}:*"
    ]
  }
}

resource "aws_iam_policy" "cloudwatch_logs" {
  name        = "${var.state_machine_name}-CloudWatchLogsPolicy"
  description = "Allow Step Functions to write to CloudWatch Logs"
  policy      = data.aws_iam_policy_document.cloudwatch_logs.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cloudwatch_logs" {
  role       = aws_iam_role.state_machine.name
  policy_arn = aws_iam_policy.cloudwatch_logs.arn
}

# ============================================================================
# State Machine Definition
# ============================================================================

# Load the state machine definition from file
locals {
  # Substitute variables in the definition
  definition = templatefile("${path.module}/workflow.asl.json", {
    InvokeBDALambdaArn          = var.invoke_bda_lambda_arn
    ProcessResultsLambdaArn     = var.process_results_lambda_arn
    HITLWaitFunctionArn         = var.hitl_wait_function_arn
    HITLStatusUpdateFunctionArn = var.hitl_status_update_function_arn
    SummarizationLambdaArn      = var.summarization_lambda_arn
    EnableHITL                  = var.enable_hitl
    OutputBucket                = var.output_bucket
    WorkingBucket               = var.working_bucket
    BDAProjectArn               = var.bda_project_arn
  })
}

# ============================================================================
# Step Functions State Machine
# ============================================================================

resource "aws_sfn_state_machine" "this" {
  name     = var.state_machine_name
  role_arn = aws_iam_role.state_machine.arn

  definition = local.definition

  type = "STANDARD" # or "EXPRESS" for high-volume, short-duration workflows

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    include_execution_data = true
    level                  = "ALL" # ALL, ERROR, FATAL, OFF
  }

  tracing_configuration {
    enabled = var.enable_xray_tracing
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.lambda_invoke,
    aws_iam_role_policy_attachment.cloudwatch_logs,
    aws_cloudwatch_log_group.state_machine
  ]
}

# ============================================================================
# CloudWatch Alarms (Optional)
# ============================================================================

resource "aws_cloudwatch_metric_alarm" "execution_failed" {
  count = var.create_alarms ? 1 : 0

  alarm_name          = "${var.state_machine_name}-ExecutionsFailed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = var.execution_failed_threshold
  alarm_description   = "Alert when Step Functions executions fail"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.this.arn
  }

  alarm_actions = var.alarm_sns_topic_arns

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "execution_duration" {
  count = var.create_alarms ? 1 : 0

  alarm_name          = "${var.state_machine_name}-ExecutionDuration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionTime"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Average"
  threshold           = var.execution_time_threshold_ms
  alarm_description   = "Alert when Step Functions execution duration exceeds threshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.this.arn
  }

  alarm_actions = var.alarm_sns_topic_arns

  tags = var.tags
}
