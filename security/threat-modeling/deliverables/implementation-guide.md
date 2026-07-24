# Security Controls Implementation Guide

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Classification** | Internal |

## 1. Overview

This guide details the security controls implemented in the GenAI IDP Accelerator to mitigate the 62 identified threats. Controls are organized by security domain and mapped to the specific threats they address.

## 2. Authentication & Identity (AUTH)

### 2.1 Amazon Cognito User Pool

**Threats mitigated**: AUTH.T01, AUTH.T02, AUTH.T04, AUTH.T05

| Control | Implementation | Configuration |
|---------|---------------|---------------|
| Self-signup disabled | `AllowAdminCreateUserOnly: true` | CloudFormation |
| Strong password policy | Minimum 8 chars, mixed case, numbers, symbols | Cognito config |
| Token lifetimes | Access: 1 hour, Refresh: configurable | Cognito config |
| Advanced security | Compromised credential detection, adaptive auth | Optional |
| Admin-only group management | IAM policies on `cognito-idp:Admin*` operations | IAM policies |

### 2.2 RBAC (4-Tier Role System)

**Threats mitigated**: AUTH.T01, AUTH.T03, PM.T06, PM.T07, KB.T01, RPT.T05

| Role | Group Name | Allowed Operations |
|------|-----------|-------------------|
| **Admin** | `{StackName}-Admin` | All operations including user management, KB management, BDA project config |
| **Author** | `{StackName}-Author` | Config CRUD, document upload, processing, agent access, test studio |
| **Reviewer** | `{StackName}-Reviewer` | Document review, HITL tasks, view results |
| **Viewer** | `{StackName}-Viewer` | Read-only access to results and dashboards |

**Enforcement layers**:
1. **AppSync resolver authorization**: VTL/JS resolvers check `$ctx.identity.claims['cognito:groups']`
2. **Lambda authorization**: Business logic verifies role from JWT claims
3. **UI authorization**: React components conditionally rendered based on role

### 2.3 JWT Validation

**Threats mitigated**: AUTH.T02, AUTH.T03

- AppSync validates JWT signature against Cognito JWKS
- Token expiration enforced by AppSync
- Group claims extracted for authorization decisions
- HTTPS-only communication (TLS 1.2+)

## 3. API Security (UI, SDK)

### 3.1 AppSync GraphQL API

**Threats mitigated**: UI.T03, AUTH.T03, CHAT.T02, CHAT.T03

| Control | Implementation |
|---------|---------------|
| **Authentication** | Cognito User Pool authorization mode |
| **Field-level auth** | Resolver-level group membership checks on all mutations |
| **Subscription auth** | User-scoped subscription filters |
| **Rate limiting** | AppSync default throttling + CloudWatch alarms |
| **Query limits** | AppSync max query depth and complexity |

### 3.2 CloudFront Distribution

**Threats mitigated**: UI.T01, UI.T04

| Control | Implementation |
|---------|---------------|
| **Origin Access Control** | OAC for S3 origin (replaces OAI) |
| **HTTPS enforcement** | Redirect HTTP to HTTPS, TLS 1.2 minimum |
| **Response headers** | CSP, X-Frame-Options, X-Content-Type-Options |
| **S3 bucket policy** | Only CloudFront OAC can read UI bucket |

### 3.3 Presigned URLs

**Threats mitigated**: UI.T02

| Control | Implementation |
|---------|---------------|
| **Short expiration** | 15-minute expiration on upload URLs |
| **Conditions** | Content-type restrictions, file size limits |
| **Scope** | Presigned to specific S3 prefix per upload |

## 4. Data Protection

### 4.1 Encryption at Rest

**Threats mitigated**: CHAT.T04, KB.T03, RPT.T01

| Resource | Encryption |
|----------|-----------|
| S3 buckets (all) | SSE-S3 (default), SSE-KMS (optional) |
| DynamoDB tables (all) | AWS-managed encryption |
| OpenSearch Serverless | Encryption at rest (AWS-managed) |
| CloudWatch Logs | CloudWatch default encryption |

### 4.2 Encryption in Transit

| Resource | Protocol |
|----------|----------|
| All API calls | HTTPS / TLS 1.2+ |
| AppSync subscriptions | WSS (WebSocket Secure) |
| AWS service calls | TLS via AWS SDK |
| CloudFront | HTTPS only |

### 4.3 Data Isolation

**Threats mitigated**: AGT.T05, CHAT.T02, AUTH.T06

| Mechanism | Implementation |
|-----------|---------------|
| **Single-tenant** | One CloudFormation stack per environment |
| **User-scoped queries** | DynamoDB partition keys include user ID |
| **Session isolation** | UUID-based conversation session IDs |
| **Stack isolation** | Separate Cognito pools, S3 buckets, DynamoDB tables per stack |

## 5. AI/ML Security

### 5.1 Prompt Injection Defense

**Threats mitigated**: PM.T01, CHAT.T01, KB.T02, RPT.T05

| Layer | Control |
|-------|---------|
| **Prompt engineering** | System prompts with clear role boundaries, input/output tags separating user content from instructions |
| **Bedrock Guardrails** | Optional content filtering, topic denial policies, PII detection |
| **Output validation** | JSON Schema validation of all model outputs |
| **Context isolation** | RAG/KB context marked as reference data, not instructions |
| **Assessment step** | Verification layer checking extraction quality |

### 5.2 Model Output Validation

**Threats mitigated**: PM.T03, BDA.T02, HOOK.T03

| Validation | Implementation |
|-----------|---------------|
| **Schema validation** | JSON Schema enforcement on extraction outputs |
| **Confidence thresholds** | Configurable minimum confidence for classification |
| **Type checking** | Field type validation (dates, numbers, strings) |
| **Evaluation framework** | Ground truth comparison for accuracy monitoring |

### 5.3 Agent Security

**Threats mitigated**: AGT.T01, AGT.T02, AGT.T03

| Control | Implementation |
|---------|---------------|
| **Athena read-only** | IAM role with SELECT-only permissions on Glue catalog |
| **AgentCore sandbox** | AWS-managed isolation (no network, no credentials, no persistent storage) |
| **Tool-level auth** | Each agent tool validates caller permissions |
| **Audit logging** | All tool invocations logged with parameters and results |

## 6. Extensibility Security

### 6.1 Lambda Hooks

**Threats mitigated**: HOOK.T01, HOOK.T02, HOOK.T03, HOOK.T04, HOOK.T05

| Control | Implementation |
|---------|---------------|
| **Invocation-only** | Platform IAM role has only `lambda:InvokeFunction` on hook ARN |
| **Separate IAM** | Hook Lambdas use customer-managed IAM roles (not platform roles) |
| **Output validation** | Platform validates hook return value schema |
| **Timeout handling** | Step Functions state timeout on hook invocation |
| **Error handling** | Catch states with DLQ for hook failures |

**Customer recommendations**:
- Use VPC with restrictive egress for post-processing hooks
- Apply least-privilege IAM to hook execution roles
- Implement input validation in hook code
- Enable CloudWatch logging on hook Lambdas

### 6.2 MCP Integration

**Threats mitigated**: MCP.T01, MCP.T02, MCP.T03, MCP.T04, MCP.T05, MCP.T06

| Control | Implementation |
|---------|---------------|
| **IaC-managed tools** | MCP tool definitions in CloudFormation (not runtime-configurable) |
| **Separate IAM roles** | Each MCP Lambda has dedicated execution role |
| **Response sanitization** | Tool output validated and size-limited |
| **Parameter validation** | Input schemas enforced per tool |
| **Authentication** | Cognito auth required for external MCP clients |
| **Gateway monitoring** | CloudWatch alarms on AgentCore Gateway status |

## 7. Infrastructure Security

### 7.1 IAM Least Privilege

**Threats mitigated**: Multiple (all components)

| Principle | Implementation |
|-----------|---------------|
| **Per-function roles** | Each Lambda function has its own execution role |
| **Resource-scoped policies** | IAM policies reference specific resource ARNs |
| **No wildcards** | Avoid `*` in resource specifications where possible |
| **Service-linked roles** | Use AWS-managed roles for Bedrock, Textract, BDA access |

### 7.2 S3 Bucket Security

**Threats mitigated**: PM.T04, BDA.T05, RPT.T01, RPT.T04

| Control | Implementation |
|---------|---------------|
| **Block public access** | `BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets` all enabled |
| **Bucket policies** | Restrict access to specific IAM roles and CloudFront OAC |
| **Versioning** | Enabled on reporting and configuration buckets |
| **Lifecycle policies** | Automatic cleanup of temporary files and query results |
| **Server-side encryption** | SSE-S3 default, SSE-KMS optional |

### 7.3 DynamoDB Security

**Threats mitigated**: CHAT.T04, AGT.T04

| Control | Implementation |
|---------|---------------|
| **Encryption** | AWS-managed encryption at rest |
| **Per-table IAM** | Lambda roles scoped to specific tables |
| **Point-in-time recovery** | Optional PITR for critical tables |
| **TTL** | Conversation records with configurable TTL |

### 7.4 Monitoring & Alerting

**Threats mitigated**: Multiple (detection and response)

| Control | Implementation |
|---------|---------------|
| **CloudWatch Alarms** | 60+ alarms on Lambda errors, SQS depth, Step Functions failures |
| **CloudWatch Logs** | All Lambda functions log to CloudWatch |
| **CloudTrail** | API-level audit trail for AWS service calls |
| **Custom metrics** | Processing success rates, latency, costs |
| **Dashboard** | CloudWatch dashboard with operational metrics |

## 8. Network Security

### 8.1 Default Configuration

| Control | Status |
|---------|--------|
| **No public Lambda URLs** | Lambda functions only invoked via AppSync, SQS, EventBridge, Step Functions |
| **HTTPS everywhere** | All communication over TLS 1.2+ |
| **CloudFront as WAF endpoint** | Optional WAF integration for additional protection |

### 8.2 Optional VPC Configuration

For deployments requiring network-level isolation:

| Control | Implementation |
|---------|---------------|
| **VPC Lambda** | Lambda functions deployed in customer VPC |
| **Private subnets** | Processing Lambdas in private subnets |
| **VPC endpoints** | PrivateLink endpoints for AWS service access |
| **NAT gateway** | Controlled internet egress through NAT |
| **Security groups** | Fine-grained network access control |

## 9. Compliance Mapping

### AWS Well-Architected Security Pillar

| Principle | Controls |
|-----------|----------|
| **Identity and access management** | Cognito, RBAC, IAM least-privilege |
| **Detection** | CloudWatch alarms, CloudTrail, custom metrics |
| **Infrastructure protection** | VPC (optional), security groups, TLS |
| **Data protection** | Encryption at rest/in transit, S3 bucket policies |
| **Incident response** | CloudWatch alarms, DLQ monitoring, operational dashboards |

## 10. Implementation Checklist

### Pre-Deployment

- [ ] Review and customize RBAC role permissions for your organization
- [ ] Configure Cognito password policy and advanced security settings
- [ ] Plan S3 encryption strategy (SSE-S3 vs SSE-KMS)
- [ ] Review Lambda hook security requirements
- [ ] Plan VPC configuration if network isolation is required

### Post-Deployment

- [ ] Create Cognito users with appropriate group assignments
- [ ] Verify AppSync resolver authorization rules
- [ ] Test RBAC permissions across all four roles
- [ ] Configure CloudWatch alarm notifications
- [ ] Review CloudTrail logging coverage
- [ ] Document Lambda hook deployment procedures
- [ ] Establish evaluation baseline for accuracy monitoring

### Ongoing Operations

- [ ] Periodic AppSync authorization audit
- [ ] Review CloudWatch alarm history for security events
- [ ] Monitor Athena query patterns for anomalies
- [ ] Review and rotate SDK/CLI credentials
- [ ] Update Bedrock Guardrails policies as needed
- [ ] Maintain evaluation ground truth data integrity
