# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# Step Functions Module Outputs

output "state_machine_arn" {
  description = "ARN of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_id" {
  description = "ID of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.id
}

output "state_machine_name" {
  description = "Name of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.name
}

output "state_machine_creation_date" {
  description = "Creation date of the Step Functions state machine"
  value       = aws_sfn_state_machine.this.creation_date
}

output "state_machine_role_arn" {
  description = "ARN of the IAM role used by the state machine"
  value       = aws_iam_role.state_machine.arn
}

output "state_machine_role_name" {
  description = "Name of the IAM role used by the state machine"
  value       = aws_iam_role.state_machine.name
}

output "log_group_name" {
  description = "Name of the CloudWatch Log Group for the state machine"
  value       = aws_cloudwatch_log_group.state_machine.name
}

output "log_group_arn" {
  description = "ARN of the CloudWatch Log Group for the state machine"
  value       = aws_cloudwatch_log_group.state_machine.arn
}

output "console_url" {
  description = "AWS Console URL for the state machine"
  value = format(
    "https://console.%s/states/home?region=%s#/statemachines/view/%s",
    split(":", aws_sfn_state_machine.this.arn)[1] == "aws-us-gov" ? "aws-us-gov.amazon.com" : (
      split(":", aws_sfn_state_machine.this.arn)[1] == "aws-cn" ? "amazonaws.cn" : "aws.amazon.com"
    ),
    split(":", aws_sfn_state_machine.this.arn)[3],
    aws_sfn_state_machine.this.arn
  )
}
