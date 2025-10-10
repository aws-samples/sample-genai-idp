output "table_id" {
  description = "The ID of the table"
  value       = aws_dynamodb_table.this.id
}

output "table_arn" {
  description = "The ARN of the table"
  value       = aws_dynamodb_table.this.arn
}

output "table_name" {
  description = "The name of the table"
  value       = aws_dynamodb_table.this.name
}

output "stream_arn" {
  description = "The ARN of the Table Stream (if enabled)"
  value       = var.stream_enabled ? aws_dynamodb_table.this.stream_arn : null
}

output "stream_label" {
  description = "A timestamp of when the stream was enabled (if enabled)"
  value       = var.stream_enabled ? aws_dynamodb_table.this.stream_label : null
}
