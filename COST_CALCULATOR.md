# GenAI IDP Accelerator Cost Calculator

> **DRAFT DOCUMENT**  
> This cost calculator is a draft and is subject to review and modification.  
> Pricing information may not be current and should be verified against official AWS pricing.

This document provides a framework for estimating the costs of running the GenAI Intelligent Document Processing (GenAIIDP) Accelerator solution. The calculator breaks down costs by AWS service and processing volume to help with budgeting and cost optimization.

## Cost Estimation Framework

### Input Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `documents_per_month` | Number of documents processed monthly | 1,000 |
| `avg_pages_per_document` | Average number of pages per document | 5 |
| `avg_images_per_page` | Average number of images per page | 1 |
| `avg_kb_queries_per_document` | Average number of knowledge base queries per document (if using KB feature) | 0 |
| `selected_pattern` | Processing pattern (1, 2, or 3) | 2 |
| `region` | AWS Region | us-east-1 |
| `storage_retention_months` | How long to retain processed documents | 3 |

### Monthly Cost Breakdown

#### 1. Storage Costs

```
total_pages = documents_per_month × avg_pages_per_document
storage_size_gb = total_pages × (5 MB per page) / 1024
s3_monthly_cost = storage_size_gb × $0.023 × storage_retention_months
dynamodb_monthly_cost = documents_per_month × 2 KB × $0.25 / 1024 / 1024
```

#### 2. Processing Costs

##### Lambda Execution

```
total_lambda_executions = documents_per_month × (3 + avg_pages_per_document)
avg_lambda_duration_ms = 3000
total_lambda_gb_seconds = total_lambda_executions × avg_lambda_duration_ms / 1000 × 1 GB
lambda_monthly_cost = total_lambda_gb_seconds × $0.0000166667
```

##### Step Functions

```
total_state_transitions = documents_per_month × 15
step_functions_monthly_cost = total_state_transitions × $0.000025
```

##### SQS

```
total_sqs_requests = documents_per_month × 10
sqs_monthly_cost = total_sqs_requests × $0.0000004
```

#### 3. AI/ML Service Costs

##### Amazon Textract

```
total_pages = documents_per_month × avg_pages_per_document
textract_monthly_cost = total_pages × $0.015
```

##### Amazon Bedrock (varies by model)

###### Claude Instant

```
avg_input_tokens_per_page = 4000
avg_output_tokens_per_page = 1000
total_input_tokens = total_pages × avg_input_tokens_per_page
total_output_tokens = total_pages × avg_output_tokens_per_page
bedrock_claude_instant_cost = (total_input_tokens × $0.0000008) + (total_output_tokens × $0.0000024)
```

###### Claude 3 Haiku

```
avg_input_tokens_per_page = 4000
avg_output_tokens_per_page = 1000
total_input_tokens = total_pages × avg_input_tokens_per_page
total_output_tokens = total_pages × avg_output_tokens_per_page
bedrock_claude_haiku_cost = (total_input_tokens × $0.00000125) + (total_output_tokens × $0.00000375)
```

###### Claude 3 Sonnet

```
avg_input_tokens_per_page = 4000
avg_output_tokens_per_page = 1000
total_input_tokens = total_pages × avg_input_tokens_per_page
total_output_tokens = total_pages × avg_output_tokens_per_page
bedrock_claude_sonnet_cost = (total_input_tokens × $0.00000375) + (total_output_tokens × $0.00001125)
```

##### SageMaker (Pattern 3 only)

```
sagemaker_instance_type = "ml.g5.xlarge"
sagemaker_hourly_rate = $1.12
sagemaker_monthly_cost = sagemaker_hourly_rate × 24 × 30
```

##### Bedrock Knowledge Base (if used)

```
total_kb_queries = documents_per_month × avg_kb_queries_per_document
kb_query_cost = total_kb_queries × $0.08
kb_storage_cost = storage_size_gb × $0.20
```

#### 4. Data Transfer Costs

```
avg_data_transfer_gb = total_pages × 5 MB / 1024
data_transfer_cost = avg_data_transfer_gb × $0.09
```

#### 5. Additional Services

```
cloudwatch_logs_cost = total_pages × 2 KB × $0.50 / 1024 / 1024
cloudwatch_metrics_cost = 10 metrics × $0.30
cognito_cost = $0.0055 × active_users
appsync_cost = documents_per_month × 5 queries × $4.00 / 1,000,000
```

### Pattern-Specific Cost Considerations

#### Pattern 1: Bedrock Data Automation (BDA)

```
bda_processing_cost = documents_per_month × $0.025
```

#### Pattern 2: Textract and Bedrock

```
# Costs calculated in the Textract and Bedrock sections above
```

#### Pattern 3: Textract, SageMaker (UDOP), and Bedrock

```
# Additional SageMaker costs calculated above
```

## Cost Calculation Examples

### Example 1: Small Volume (1,000 documents/month)

| Service | Cost Calculation | Estimated Cost |
|---------|------------------|----------------|
| S3 Storage | 1,000 docs × 5 pages × 5 MB × $0.023 × 3 months / 1024 | $1.69 |
| DynamoDB | 1,000 docs × 2 KB × $0.25 / 1024 / 1024 | $0.00 |
| Lambda | 1,000 × (3 + 5) × 3s × $0.0000166667 | $0.40 |
| Step Functions | 1,000 × 15 × $0.000025 | $0.38 |
| SQS | 1,000 × 10 × $0.0000004 | $0.00 |
| Textract | 1,000 × 5 × $0.015 | $75.00 |
| Bedrock (Claude Instant) | (1,000 × 5 × 4,000 × $0.0000008) + (1,000 × 5 × 1,000 × $0.0000024) | $28.00 |
| CloudWatch | Various metrics and logs | $5.00 |
| **Total (Pattern 2)** | | **$110.47** |

### Example 2: Medium Volume (10,000 documents/month)

| Service | Cost Calculation | Estimated Cost |
|---------|------------------|----------------|
| S3 Storage | 10,000 docs × 5 pages × 5 MB × $0.023 × 3 months / 1024 | $16.89 |
| DynamoDB | 10,000 docs × 2 KB × $0.25 / 1024 / 1024 | $0.00 |
| Lambda | 10,000 × (3 + 5) × 3s × $0.0000166667 | $4.00 |
| Step Functions | 10,000 × 15 × $0.000025 | $3.75 |
| SQS | 10,000 × 10 × $0.0000004 | $0.04 |
| Textract | 10,000 × 5 × $0.015 | $750.00 |
| Bedrock (Claude Instant) | (10,000 × 5 × 4,000 × $0.0000008) + (10,000 × 5 × 1,000 × $0.0000024) | $280.00 |
| CloudWatch | Various metrics and logs | $10.00 |
| **Total (Pattern 2)** | | **$1,064.68** |

### Example 3: High Volume (100,000 documents/month)

| Service | Cost Calculation | Estimated Cost |
|---------|------------------|----------------|
| S3 Storage | 100,000 docs × 5 pages × 5 MB × $0.023 × 3 months / 1024 | $168.95 |
| DynamoDB | 100,000 docs × 2 KB × $0.25 / 1024 / 1024 | $0.05 |
| Lambda | 100,000 × (3 + 5) × 3s × $0.0000166667 | $40.00 |
| Step Functions | 100,000 × 15 × $0.000025 | $37.50 |
| SQS | 100,000 × 10 × $0.0000004 | $0.40 |
| Textract | 100,000 × 5 × $0.015 | $7,500.00 |
| Bedrock (Claude Instant) | (100,000 × 5 × 4,000 × $0.0000008) + (100,000 × 5 × 1,000 × $0.0000024) | $2,800.00 |
| CloudWatch | Various metrics and logs | $25.00 |
| **Total (Pattern 2)** | | **$10,571.90** |

## Cost Optimization Recommendations

1. **Right-size your model selection**:
   - Use Claude Instant for routine document processing
   - Reserve Claude 3 Sonnet for complex documents requiring higher accuracy

2. **Optimize document preprocessing**:
   - Compress images before processing to reduce Textract costs
   - Convert multi-page documents to optimized formats

3. **Implement tiered storage**:
   - Move older processed documents to S3 Infrequent Access or Glacier
   - Implement lifecycle policies based on document age

4. **Adjust concurrency settings**:
   - Fine-tune Lambda concurrency to prevent throttling while minimizing costs
   - Batch small documents together when possible

5. **Monitor and alert on costs**:
   - Set up AWS Budgets to track spending
   - Create alerts for unusual processing volumes

6. **Optimize knowledge base usage**:
   - Limit knowledge base queries to essential use cases
   - Implement caching for common queries

## Interactive Cost Calculator

For a more precise cost estimate, use the AWS Pricing Calculator at https://calculator.aws and input your specific usage patterns. The calculator allows you to model different scenarios and get region-specific pricing.

## Disclaimer

The pricing information provided is for estimation purposes only and is based on AWS pricing as of April 2025. Actual costs may vary based on your specific usage patterns, AWS region, and any special pricing agreements you may have with AWS. Always refer to the official AWS pricing pages for the most up-to-date information.

## References

- [AWS Lambda Pricing](https://aws.amazon.com/lambda/pricing/)
- [Amazon S3 Pricing](https://aws.amazon.com/s3/pricing/)
- [Amazon Textract Pricing](https://aws.amazon.com/textract/pricing/)
- [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [AWS Step Functions Pricing](https://aws.amazon.com/step-functions/pricing/)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)
- [Amazon DynamoDB Pricing](https://aws.amazon.com/dynamodb/pricing/)
- [Amazon CloudWatch Pricing](https://aws.amazon.com/cloudwatch/pricing/)