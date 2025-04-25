# AWS Services and IAM Role Requirements for GenAI IDP Accelerator

This document outlines the AWS services used by the GenAI Intelligent Document Processing (IDP) Accelerator solution, along with the IAM role scopes needed for deployment and operation.

## AWS Services Used

### Core Infrastructure Services

| Service | Usage | Deployment | Runtime |
|---------|-------|------------|---------|
| **Amazon S3** | Stores input documents, processed outputs, and web UI assets | ✓ | ✓ |
| **Amazon DynamoDB** | Tracks document processing, manages configurations and concurrency | ✓ | ✓ |
| **AWS Lambda** | Executes document processing functions and business logic | ✓ | ✓ |
| **AWS Step Functions** | Orchestrates document processing workflows | ✓ | ✓ |
| **Amazon SQS** | Queues documents for processing and handles throttling | ✓ | ✓ |
| **Amazon EventBridge** | Triggers document processing workflows when files are uploaded | ✓ | ✓ |
| **Amazon CloudFront** | Delivers the web UI with global distribution | ✓ | ✓ |
| **AWS CloudFormation** | Deploys and manages the solution infrastructure | ✓ | |
| **AWS SAM** | Simplifies serverless application deployment | ✓ | |

### AI/ML Services

| Service | Usage | Deployment | Runtime |
|---------|-------|------------|---------|
| **Amazon Bedrock** | Provides foundation models for document understanding | ✓ | ✓ |
| **Amazon Bedrock Guardrails** | Enforces content safety, information security, and model usage policies | ✓ | ✓ |
| **Amazon Textract** | Extracts text and data from documents (OCR) | | ✓ |
| **Amazon SageMaker** | Hosts custom ML models for document classification (UDOP) | ✓ | ✓ |
| **Amazon Bedrock Knowledge Base** | Enables semantic document querying (optional) | ✓ | ✓ |
| **Bedrock Data Automation (BDA)** | Automates document processing workflows (Pattern 1) | | ✓ |

### Auth & API Services

| Service | Usage | Deployment | Runtime |
|---------|-------|------------|---------|
| **Amazon Cognito** | Manages user authentication and authorization | ✓ | ✓ |
| **AWS AppSync** | Provides GraphQL API for the web UI | ✓ | ✓ |
| **AWS WAF** | Protects web applications from web exploits (optional) | ✓ | ✓ |
| **Amazon OpenSearch Service** | Powers document indexing and search (for KB feature) | ✓ | ✓ |

### Monitoring & Operations

| Service | Usage | Deployment | Runtime |
|---------|-------|------------|---------|
| **Amazon CloudWatch** | Provides monitoring, logging, and alerting | ✓ | ✓ |
| **AWS SNS** | Delivers operational alerts and notifications | ✓ | ✓ |
| **AWS KMS** | Manages encryption keys for secure data storage | ✓ | ✓ |

## IAM Role Requirements

### Deployment Roles

Deploying this solution requires an IAM role/user with the following permissions:

#### Essential Permissions
* `cloudformation:*` - Create and manage CloudFormation stacks
* `iam:*` - Create and manage IAM roles and policies
* `lambda:*` - Create and configure Lambda functions
* `states:*` - Create and manage Step Functions state machines
* `s3:*` - Create buckets and manage S3 resources
* `dynamodb:*` - Create and configure DynamoDB tables
* `sqs:*` - Create and configure SQS queues
* `events:*` - Create and configure EventBridge rules
* `cloudfront:*` - Create and configure CloudFront distributions
* `cognito-idp:*` - Create and configure Cognito user pools
* `appsync:*` - Create and configure AppSync APIs
* `logs:*` - Create and configure CloudWatch log groups
* `cloudwatch:*` - Create and configure CloudWatch dashboards and alarms
* `sns:*` - Create and configure SNS topics

#### Pattern-Specific Permissions
* `bedrock:*` - Create Bedrock resources (all patterns)
* `sagemaker:*` - Create SageMaker endpoints (Pattern 3)
* `opensearch:*` - Create OpenSearch domains (Knowledge Base feature)
* `kms:*` - Create KMS keys for encryption
* `wafv2:*` - Configure WAF rules (optional)

### Runtime Roles

The solution creates various IAM roles to run different components of the system. Key role scopes include:

#### Document Processing Roles
* **Queue Processing Role**:
  * `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`
  * `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`
  * `states:StartExecution`
  * `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

* **Step Functions Execution Role**:
  * `lambda:InvokeFunction`
  * `states:*`
  * `events:PutEvents`

* **OCR Processing Role**:
  * `textract:AnalyzeDocument`, `textract:DetectDocumentText`
  * `s3:GetObject`, `s3:PutObject`
  * `logs:*`

* **Classification Role**:
  * `sagemaker:InvokeEndpoint` (Pattern 3)
  * `bedrock:InvokeModel` (Patterns 2 & 3)
  * `bedrock:ApplyGuardrail` (when Guardrails configured)
  * `s3:GetObject`, `s3:PutObject`
  * `logs:*`

* **Extraction Role**:
  * `bedrock:InvokeModel`
  * `bedrock:ApplyGuardrail` (when Guardrails configured)
  * `s3:GetObject`, `s3:PutObject`
  * `logs:*`

* **BDA Integration Role** (Pattern 1):
  * `bedrock-agent:StartIngestionJob`
  * `bedrock-agent:GetIngestionJob`
  * `s3:GetObject`, `s3:PutObject`
  * `logs:*`

#### Web UI & API Roles
* **AppSync Service Role**:
  * `dynamodb:GetItem`, `dynamodb:Query`, `dynamodb:Scan`
  * `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`
  * `lambda:InvokeFunction`

* **Cognito Authentication Role**:
  * `appsync:GraphQL`
  * `s3:GetObject` (for UI assets)
  * `mobileanalytics:PutEvents`, `cognito-sync:*`

* **Knowledge Base Query Role**:
  * `bedrock:InvokeModel`
  * `bedrock:ApplyGuardrail` (when Guardrails configured)
  * `opensearch:ESHttpGet`, `opensearch:ESHttpPost`
  * `logs:*`

#### Monitoring & Operations Roles
* **CloudWatch Dashboard Role**:
  * `cloudwatch:GetDashboard`, `cloudwatch:PutDashboard`
  * `logs:DescribeLogGroups`

* **Workflow Tracking Role**:
  * `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`
  * `cloudwatch:PutMetricData`
  * `logs:*`

## Service Quotas Considerations

For high-volume document processing, consider requesting quota increases for:

| Service | Quota to Increase | Typical Default |
|---------|-------------------|----------------|
| Amazon Bedrock | On-demand InvokeModel tokens per minute | Varies by model |
| Amazon Bedrock | On-demand InvokeModel requests per minute | Varies by model |
| Amazon Bedrock | ApplyGuardrail requests per minute | Varies by region |
| Amazon Textract | DetectDocumentText transactions per second | 3-5 TPS |
| Amazon SageMaker | Number of endpoints per region | 2-10 endpoints |
| AWS Lambda | Concurrent executions | 1,000 executions |
| AWS Step Functions | State transitions per second | 2,000 transitions |
| Amazon SQS | API requests per queue | Very high by default |
| Amazon CloudWatch | PutMetricData API requests per second | 150 requests/second |
| Bedrock Data Automation | Concurrent jobs (Pattern 3) | Varies by region |

## Security Recommendations

When deploying this solution, consider the following security best practices:

1. **Encryption**:
   * Enable SSE-KMS encryption for all S3 buckets
   * Use customer-managed CMKs for sensitive data
   * Enable encryption for DynamoDB tables

2. **Network Security**:
   * Use CloudFront security features (geo-restrictions, HTTPS, etc.)
   * Configure AWS WAF to protect web interfaces

3. **Authentication**:
   * Enforce MFA for admin users in Cognito
   * Set strong password policies
   * Limit admin access to necessary personnel

4. **IAM Best Practices**:
   * Use least privilege principles for all roles
   * Regularly audit and rotate credentials
   * Enable CloudTrail logging for all API actions

5. **Content Safety & Control**:
   * Configure Bedrock Guardrails with appropriate topic filters
   * Set up content blocking for sensitive information
   * Implement trace logging for guardrail activations
   * Use different guardrail configurations for different environments (dev/test/prod)

6. **Data Protection**:
   * Implement lifecycle policies for S3 objects
   * Configure appropriate retention policies for logs and data
   * Consider data residency requirements when selecting regions