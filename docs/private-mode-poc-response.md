Subject: GenAI IDP Accelerator – Private Mode POC: VPC Sizing, Endpoints, Permissions & Network Requirements

---

Hi [Customer Name],

Thank you for your interest in running a POC of the GenAI IDP Accelerator in Private Mode. Below are the details addressing each of your questions.

---

## 1. VPC/Network Sizing – CIDR & ENI Requirements

In Private Mode, the solution deploys Lambda functions inside VPC subnets (each concurrent invocation consumes one ENI) and creates VPC Interface Endpoints (each consumes one ENI per Availability Zone).

### ENI Consumption Estimate (POC)

| Component | ENIs per AZ | Total (2 AZs) |
|-----------|-------------|----------------|
| VPC Interface Endpoints (17 services) | 17 | 34 |
| S3 Interface VPCE (created by ALB stack) | 1 | 2 |
| Application Load Balancer | 1+ | 2–4 |
| Lambda concurrent executions (POC load) | 5–15 | 10–30 |
| CodeBuild (during UI builds) | 1 | 2 |
| **TOTAL (POC)** | | **~50–72 ENIs** |

> **Note:** At higher concurrency (production), Lambda can scale to 1,000 concurrent executions (default quota), each consuming 1 ENI. Plan for peak accordingly.

### Recommended Subnet CIDR

| Use Case | CIDR per Subnet | Usable IPs | Guidance |
|----------|----------------|-------------|----------|
| **POC / Light load** | /25 (128 IPs) | ~123 | Sufficient for ~50 ENIs per AZ |
| **Production / Moderate** | /24 (256 IPs) | ~251 | Recommended minimum for production |
| **Production / High throughput** | /23 (512 IPs) | ~507 | For 200+ concurrent document processing |

**Minimum VPC requirements:**
- At least **2 private subnets in 2 different Availability Zones** (required by ALB)
- `enableDnsSupport=true` and `enableDnsHostnames=true` on the VPC
- Recommended overall VPC CIDR: /22 or /21 to allow headroom

---

## 2. AWS VPC Endpoint Services Required

### Interface Endpoints (PrivateLink – billed per hour + per GB processed)

| # | Service Name | Purpose |
|---|-------------|---------|
| 1 | `com.amazonaws.<region>.s3` (Interface) | ALB → S3 static content; Lambda → S3 I/O |
| 2 | `com.amazonaws.<region>.appsync-api` | GraphQL API & WebSocket (real-time status) |
| 3 | `com.amazonaws.<region>.appsync` | AppSync control plane |
| 4 | `com.amazonaws.<region>.sqs` | Document queue processing |
| 5 | `com.amazonaws.<region>.states` | Step Functions workflow orchestration |
| 6 | `com.amazonaws.<region>.kms` | KMS encryption operations |
| 7 | `com.amazonaws.<region>.logs` | CloudWatch Logs |
| 8 | `com.amazonaws.<region>.monitoring` | CloudWatch Metrics |
| 9 | `com.amazonaws.<region>.bedrock-runtime` | Bedrock model inference (AI extraction) |
| 10 | `com.amazonaws.<region>.textract` | OCR / document text extraction |
| 11 | `com.amazonaws.<region>.ssm` | Systems Manager Parameter Store |
| 12 | `com.amazonaws.<region>.secretsmanager` | Secrets management |
| 13 | `com.amazonaws.<region>.lambda` | Lambda-to-Lambda invocations |
| 14 | `com.amazonaws.<region>.events` | EventBridge event routing |
| 15 | `com.amazonaws.<region>.athena` | Evaluation/reporting queries |
| 16 | `com.amazonaws.<region>.sts` | STS AssumeRole (required for BDA mode) |
| 17 | `com.amazonaws.<region>.ssmmessages` | SSM Session Manager (testing/bastion only) |
| 18 | `com.amazonaws.<region>.ec2messages` | SSM agent communication (testing/bastion only) |

### Gateway Endpoints (free – no hourly or data charges)

| # | Service Name | Purpose |
|---|-------------|---------|
| 1 | `com.amazonaws.<region>.s3` (Gateway) | Bulk S3 data transfer from Lambda subnets |
| 2 | `com.amazonaws.<region>.dynamodb` | DynamoDB read/write (tracking, config, concurrency) |

### Not Required as VPC Endpoints

- **Cognito** (`cognito-idp`, `cognito-identity`) – AWS does not support PrivateLink for Cognito when the User Pool has a domain. Authentication traffic flows via user browsers over their normal internet path, or through a NAT Gateway for testing from within the VPC.

---

## 3. AWS Services Used (for IAM Role/Permission Derivation)

Below is the complete list of AWS services the solution uses. Your team can map these to appropriate IAM roles and Active Directory groups.

### Runtime Services (Document Processing)

| Service | Usage |
|---------|-------|
| Amazon S3 | Input/output/config document storage |
| Amazon DynamoDB | Workflow tracking, configuration, concurrency control |
| AWS Lambda | All processing functions |
| AWS Step Functions | Document processing workflow orchestration |
| Amazon SQS | Document queuing and flow control |
| Amazon EventBridge | Trigger workflows on S3 uploads |
| AWS KMS | Encryption (buckets, tables, logs) |
| Amazon Bedrock | LLM inference for classification & extraction |
| Amazon Bedrock Guardrails | Content safety and policy enforcement |
| Amazon Textract | OCR text extraction |
| Amazon Bedrock Data Automation (BDA) | End-to-end doc processing (optional mode) |
| Amazon CloudWatch | Monitoring, dashboards, alarms, logs |
| Amazon SNS | Operational alerts |
| Amazon Athena | Evaluation/reporting queries |
| AWS Systems Manager (SSM) | Parameter Store configuration |
| AWS Secrets Manager | Credential storage |
| AWS STS | Temporary credential issuance |

### Web UI & API Services

| Service | Usage |
|---------|-------|
| Elastic Load Balancing (ALB) | Internal web UI hosting |
| AWS AppSync | GraphQL API (private visibility mode) |
| Amazon Cognito | User authentication & authorization |

### Deployment-Time Services

| Service | Usage |
|---------|-------|
| AWS CloudFormation | Infrastructure provisioning |
| AWS SAM | Serverless application packaging |
| AWS IAM | Role and policy creation |
| AWS ACM (Certificate Manager) | TLS certificate for ALB |
| AWS CodeBuild | Build and package web UI assets |
| Amazon ECR | Container image storage (if custom models) |

### Suggested AD Group → Role Mapping

| AD Group (suggested) | AWS Access Level | Scope |
|---------------------|-----------------|-------|
| IDP-Admins | Full CloudFormation deploy + IAM | Deployment & stack management |
| IDP-Operators | CloudWatch, Step Functions console, S3 read | Monitoring & troubleshooting |
| IDP-Users | Web UI access (Cognito) | Upload documents, view results |
| IDP-Developers | Lambda, S3, DynamoDB, Bedrock read/invoke | Configuration & testing |

---

## 4. Ports & Protocols Required Through the IPsec Tunnel

For Private Mode, all Lambda-to-service communication stays **within the VPC** via VPC Endpoints. The IPsec tunnel is only needed for **user/browser access** and **DNS resolution**.

### Required Through the Tunnel

| Direction | Source | Destination | Protocol/Port | Purpose |
|-----------|--------|-------------|---------------|---------|
| On-prem → VPC | User browsers | Internal ALB (private IP) | **TCP 443 (HTTPS)** | Web UI access |
| On-prem → VPC | Corporate DNS | Route 53 Resolver Inbound Endpoint | **TCP/UDP 53 (DNS)** | Resolve AppSync private API hostnames |
| VPC → On-prem | Route 53 Resolver | Corporate DNS | **TCP/UDP 53 (DNS)** | DNS response path |

### NOT Required Through the Tunnel

| Traffic | Why |
|---------|-----|
| Lambda → AWS services | Stays in VPC via Interface/Gateway Endpoints |
| Cognito authentication | Browser uses its own internet path (corporate proxy/firewall); does NOT traverse the tunnel |
| S3 data transfer | Lambda uses S3 Gateway + Interface endpoints inside VPC |

### Summary: Only Two Ports Needed

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| **443** | TCP | Inbound to VPC | User browser → ALB |
| **53** | TCP/UDP | Bidirectional | DNS forwarding for private AppSync resolution |

---

## Additional POC Prerequisites

1. **NAT Gateway** – Required for Cognito auth (browser testing from within VPC) and CodeBuild dependency resolution (npm/pip). Can be avoided with an internal artifact repository.
2. **ACM Certificate** – Required for ALB HTTPS listener. Self-signed is acceptable for POC; corporate CA-signed for production.
3. **Bedrock Model Access** – Must [request access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) to Amazon Nova models and/or Anthropic Claude models in the target region.
4. **VPC DNS Settings** – `enableDnsSupport=true` and `enableDnsHostnames=true` must be enabled on the VPC.

---

Please let us know if you have any follow-up questions or if we can assist with the VPC design or deployment planning.

Best regards,
[Your Name]
[Your Title]
AWS Professional Services
