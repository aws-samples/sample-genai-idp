---
title: "AWS Well-Architected Framework Assessment"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# AWS Well-Architected Framework Assessment

This document assesses the GenAI Intelligent Document Processing (GenAIIDP) Accelerator against the six pillars of the AWS Well-Architected Framework.

## Executive Summary

The GenAI Intelligent Document Processing (GenAIIDP) Accelerator demonstrates strong alignment with AWS Well-Architected principles, particularly in operational excellence, security, and reliability. The solution leverages serverless architecture to provide a scalable, resilient document processing platform with built-in monitoring, error handling, and security controls. Areas for potential enhancement include cost optimization through more granular controls and sustainability considerations through resource efficiency improvements.

## 1. Operational Excellence

### Strengths

- **Infrastructure as Code**: The entire solution is deployed using AWS SAM and CloudFormation templates, enabling consistent, repeatable deployments.
- **Comprehensive Monitoring**: Integrated CloudWatch dashboards provide visibility into document processing workflows, latency metrics, throughput, and error rates.
- **Automated Workflows**: Step Functions state machines orchestrate document processing with built-in error handling and retry mechanisms.
- **Observability**: Detailed logging across all components with configurable retention periods.
- **Operational Tooling**: Includes scripts for workflow management, document status lookup, and load testing.

### Recommendations

- Consider implementing canary deployments for safer updates to production environments.
- Add automated integration tests to validate end-to-end workflows before deployment.
- Implement distributed tracing across components to better understand cross-service dependencies and latencies.

## 2. Security

### Strengths

- **Defense in Depth**: Multiple security layers including IAM roles with least privilege, encryption at rest, and secure API access.
- **Enterprise IAM Governance**: Comprehensive support for IAM permissions boundaries to comply with organizational Service Control Policies (SCPs) that mandate permissions boundaries on all IAM roles.
- **Content Safety**: Integration with Amazon Bedrock Guardrails to enforce content policies, block sensitive information, prevent model misuse, and enable [Automated Reasoning Checks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning.html) for formal verification of model outputs.
- **Authentication**: Cognito user pools with configurable password policies and MFA support.
- **Authorization**: Fine-grained access controls for different components and resources.
- **Data Protection**: S3 bucket encryption, DynamoDB encryption, and secure transmission of data.
- **Audit Capabilities**: CloudWatch logs capture detailed activity for auditing purposes.
- **WAF Integration**: Web Application Firewall protection for the AppSync GraphQL API.

### Recommendations

- **Production Logging Security**: 
  - **Set the `LogLevel` parameter to WARN or ERROR (not INFO) for production deployments** to prevent sensitive information from being logged
  - The `LogLevel` parameter in template.yaml automatically configures logging levels across all Lambda functions, AppSync APIs, and other components
  - INFO level logging can inadvertently capture sensitive document contents, PII data (SSN, addresses, names), and S3 presigned URLs
  - For production environments, use `LogLevel: WARN` or `LogLevel: ERROR` in your CloudFormation deployment parameters
  - Implement log filtering and masking for any essential INFO-level logs that must be retained
  - Regularly audit CloudWatch log groups to ensure no sensitive information is being captured
- **CloudFront Security Enhancement** (CloudFront hosting mode): 
  - Create a custom domain with a custom ACM certificate for the CloudFront distribution
  - Enforce TLS 1.2 or greater protocol in the CloudFront security policy
  - Configure secure response headers (X-Content-Type-Options, X-Frame-Options, Content-Security-Policy)
  - Restrict viewer access using signed URLs or cookies for sensitive content
- **API Gateway Hosting Security** (API Gateway hosting mode — see [API Gateway Hosting](./apigateway-hosting.md)):
  - Set `ApiGatewayVisibility=PRIVATE` (with `DeployInVPC=true`) to restrict access to VPC-connected users via an execute-api interface endpoint
  - Configure `WAFAllowedIPv4Ranges` to limit ingress to specific network ranges (stage-level WAFv2)
  - No ACM certificate is required — the execute-api endpoint uses AWS-managed TLS
  - Enable VPC Flow Logs to monitor traffic to the execute-api interface endpoint
- **Additional WAF Protection**: 
  - Deploy a WAF WebACL with GLOBAL scope in the us-east-1 region (CloudFront) or REGIONAL scope (API Gateway)
  - Associate this WAF with the CloudFront distribution or the API Gateway stage to protect the UI
  - Enable core rule sets (AWS Managed Rules) including protections against XSS and SQL injection
  - Create custom rules for specific application threats
- **Sensitive Data Discovery**: Consider enabling [Amazon Macie](https://docs.aws.amazon.com/macie/latest/user/what-is-macie.html) on document S3 buckets to automatically discover and classify sensitive data (PII, financial data, credentials) in processed documents. Macie operates as a decoupled service requiring no changes to the accelerator.
- Consider implementing VPC endpoints for enhanced network isolation of sensitive services.
- Add automated security scanning in the CI/CD pipeline.
- Implement more granular data access controls based on document classification.
- Consider adding CloudTrail integration for comprehensive API activity monitoring.

## 3. Reliability

### Strengths

- **Fault Isolation**: Modular architecture with clear separation of concerns limits blast radius of failures.
- **Automatic Recovery**: Comprehensive retry mechanisms in Step Functions workflows and Lambda functions.
- **Throttling Management**: Built-in handling of service throttling with exponential backoff.
- **Scalability**: Serverless architecture automatically scales with demand.
- **Distributed System Design**: SQS queues decouple components and provide buffering during peak loads.
- **Testing**: Includes load testing scripts and sample documents for validation.

### Recommendations

- Implement circuit breakers for external service dependencies.
- Add chaos engineering practices to test resilience under various failure scenarios.
- Implement more comprehensive health checks for all components.

### Disaster Recovery

The solution includes several built-in capabilities that form the foundation of a disaster recovery (DR) strategy:

- **Durable, versioned storage**: All S3 buckets (Input, Output, Working, Configuration, Evaluation Baseline, and supporting buckets) have versioning enabled, so objects are protected against accidental overwrite or deletion and prior versions can be recovered.
- **Point-in-Time Recovery (PITR)**: All DynamoDB tables (tracking, concurrency, configuration, and related tables) have PITR enabled, allowing restoration to any second within the retention window.
- **Infrastructure as Code**: Because the entire stack is defined in SAM/CloudFormation, the environment can be reliably re-provisioned in another account or region from source.
- **Stateless compute**: Lambda and Step Functions hold no durable state; recovery depends on restoring S3 and DynamoDB data plus re-deploying the templates.

**Choosing a DR strategy.** The appropriate approach depends on your Recovery Time Objective (RTO) and Recovery Point Objective (RPO):

- **Backup & Restore (lowest cost, higher RTO)**: Rely on S3 versioning and DynamoDB PITR within a region. For cross-region protection, enable [S3 Cross-Region Replication (CRR)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html) on document and configuration buckets, and use [DynamoDB scheduled/on-demand backups](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/BackupRestore.html) (optionally via [AWS Backup](https://docs.aws.amazon.com/aws-backup/latest/devguide/whatisbackup.html)) copied to a DR region. Re-deploy the CloudFormation stack in the DR region when needed.
- **Pilot Light / Warm Standby (lower RTO, higher cost)**: Pre-deploy the stack in a second region and continuously replicate data using S3 CRR and [DynamoDB global tables](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html). Fail over by redirecting document ingestion to the standby region's Input bucket.
- **Multi-region active/active**: Run independent stacks in multiple regions behind a routing layer. This offers the lowest RTO/RPO but adds the most operational and cost complexity, and requires that the chosen Bedrock models and any Bedrock Data Automation projects are available in all target regions.

**Recommendations**:

- Define explicit RTO and RPO targets for your workload, then select the DR strategy above that meets them at acceptable cost.
- Enable S3 Cross-Region Replication on the Input, Output, and Configuration buckets for cross-region durability.
- Use DynamoDB global tables (or AWS Backup with cross-region copy) to protect tracking and configuration state beyond single-region PITR.
- Verify regional availability of required Bedrock models, Textract, and Bedrock Data Automation in your DR region before committing to a strategy — see [EU Region Model Support](./eu-region-model-support.md) for an example of region-specific model considerations.
- Regularly test the recovery procedure (restore + redeploy) to validate that RTO/RPO targets are actually achievable and that runbooks stay current.

## 4. Performance Efficiency

### Strengths

- **Serverless Architecture**: Pay-per-use model with automatic scaling eliminates the need for capacity planning.
- **Concurrency Management**: Configurable concurrency limits prevent overwhelming downstream services.
- **Asynchronous Processing**: SQS queues and Step Functions enable efficient parallel processing.
- **Resource Optimization**: Lambda functions configured with appropriate memory settings.
- **Performance Monitoring**: Detailed metrics for latency, throughput, and resource utilization.

### Recommendations

- Implement adaptive concurrency based on service health and throttling metrics.
- Consider caching mechanisms for frequently accessed documents or extraction results.
- Optimize image preprocessing to reduce processing time and model token usage.
- Evaluate performance across different AWS regions to optimize for global deployments.

## 5. Cost Optimization

### Strengths

- **Serverless Pay-per-Use**: Only pay for actual document processing with no idle resources.
- **Cost Monitoring**: CloudWatch metrics can be used to track usage and costs.
- **Right-Sizing**: Configurable parameters allow tuning resource allocation.
- **Resource Lifecycle Management**: Configurable log retention periods.

### Recommendations

- Implement more granular cost allocation tags to track expenses by document type, workflow, or customer. Bedrock [Application Inference Profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-create.html) can be used to tag model invocations for cost attribution — see [Cost Attribution with Application Inference Profiles](./cost-calculator.md#cost-attribution-with-bedrock-application-inference-profiles).
- Add cost anomaly detection to identify unexpected usage patterns.
- Consider implementing tiered storage strategies for processed documents based on access patterns.
- Evaluate model selection based on cost-performance tradeoffs for different document types.
- Add budget alerts and cost controls to prevent unexpected costs during high-volume processing.
- Leverage Bedrock Guardrails to constrain model behavior and reduce the risk of costly token overuse.

## 6. Sustainability

### Strengths

- **Serverless Architecture**: Resources only consume energy when actively processing documents.
- **Regional Deployment**: Solution can be deployed in regions with lower carbon footprints.
- **Efficient Resource Utilization**: Parallel processing and concurrency management optimize resource usage.

### Recommendations

- Implement document archiving strategies to reduce storage footprint over time.
- Consider optimizing image preprocessing to reduce computational requirements.
- Add sustainability metrics to track carbon footprint of document processing workflows.
- Evaluate AWS Graviton-based Lambda functions for improved energy efficiency.
- Consider implementing regional routing to process documents in regions with lower carbon intensity.

## Processing-Mode-Specific Assessments

Since v0.5.0, the solution is deployed as a single **Unified Pattern** that combines both processing modes into one stack. The `use_bda` configuration flag (set via the UI) selects the processing path at runtime — there is no longer a pattern selector at deployment time. See the [Architecture Overview](./architecture.md) and [Upgrading to the Unified Pattern](./migration-v04-to-v05.md) for details.

### BDA Mode (`use_bda: true`) — Bedrock Data Automation

- **Strengths**: Leverages the managed Amazon Bedrock Data Automation service for end-to-end processing, reducing operational overhead.
- **Considerations**: Monitor BDA service quotas and implement appropriate throttling controls.

### Pipeline Mode (`use_bda: false`, default) — Textract and Bedrock

- **Strengths**: Well-structured workflow with clear separation between OCR (Amazon Textract) and AI processing (Amazon Bedrock).
- **Considerations**: Optimize token usage in Bedrock models to balance cost and performance.

> **Note**: The previously separate Pattern-3 (Textract + SageMaker UDOP + Bedrock) configuration was deprecated and removed in v0.5.0. Custom classification models such as UDOP can be integrated into the unified pattern via [Lambda Inference Hooks](./lambda-hook-inference.md).

## Conclusion

The GenAI Intelligent Document Processing Accelerator demonstrates strong alignment with AWS Well-Architected principles, providing a robust foundation for document processing workloads. The modular architecture, comprehensive monitoring, and built-in security controls create a solution that can be deployed with confidence in production environments.

Key strengths include the serverless architecture, which provides automatic scaling and resilience, and the comprehensive monitoring capabilities that enable operational visibility. The solution's modular design allows for customization and extension to meet specific business requirements.

Areas for potential enhancement include more granular cost controls, extending the built-in data-protection capabilities into a full cross-region disaster recovery strategy (see [Disaster Recovery](#disaster-recovery)), and sustainability optimizations. By addressing these recommendations, the solution can further improve its alignment with Well-Architected best practices.
