# Lambda Hooks — Threat Analysis

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Feature** | Lambda Hooks (Inference & Post-Processing) |
| **Classification** | Internal |

## 1. Feature Overview

Lambda Hooks provide extensibility points for customer-managed code execution within the processing pipeline:

### 1.1 Inference Hook
- Invoked during extraction step as an alternative or supplement to Bedrock inference
- Receives document data and context, returns structured extraction results
- Enables integration with custom models, external ML services, or specialized processing logic

### 1.2 Post-Processing Hook
- Invoked after document processing completes
- Receives full processing results (decompressed) including all extracted data
- Enables integration with downstream systems (databases, CRMs, ERPs, notifications)
- Results are decompressed by a platform-managed Decompressor Lambda before hook invocation

## 2. Architecture

```mermaid
flowchart TD
    subgraph Platform Managed
        SFN[Step Functions]
        Decomp[Decompressor Lambda]
    end

    subgraph Customer Managed - TB6
        InfHook[Inference Hook Lambda]
        PostHook[Post-Processing Hook Lambda]
    end

    subgraph External
        ExtModel[External ML Model]
        ExtAPI[External API / System]
        CRM[CRM / ERP]
        DB[External Database]
    end

    SFN -->|Invoke with doc data| InfHook
    InfHook --> ExtModel
    InfHook -->|Return results| SFN

    SFN -->|Invoke| Decomp
    Decomp -->|Decompressed results| PostHook
    PostHook --> ExtAPI
    PostHook --> CRM
    PostHook --> DB
```

## 3. Threat Analysis

### HOOK.T01: Malicious Customer Code Execution

| Attribute | Value |
|-----------|-------|
| **Threat ID** | HOOK.T01 |
| **Category** | STRIDE: Tampering, Elevation of Privilege |
| **Description** | Customer-managed Lambda hooks execute arbitrary code within the customer's AWS account. Malicious or compromised hook code could abuse its position in the processing pipeline |
| **Attack Vector** | Deploy malicious Lambda function as inference or post-processing hook that exploits its access to document data and AWS resources |
| **Impact** | Data exfiltration, modification of processing results, abuse of IAM permissions, lateral movement within AWS account |
| **Likelihood** | Low |
| **Severity** | Critical |
| **Affected Components** | Customer Lambda hooks, IAM roles |
| **Mitigations** | Customer responsibility for hook security, documentation of security best practices, hook Lambda runs with customer-managed IAM role (separate from platform roles), platform only has invoke permission on hook |

### HOOK.T02: Data Exfiltration via Post-Processing Hook

| Attribute | Value |
|-----------|-------|
| **Threat ID** | HOOK.T02 |
| **Category** | STRIDE: Information Disclosure |
| **Description** | Post-processing hooks receive complete decompressed processing results including all extracted data, PII, and document content. This data could be sent to unauthorized external destinations |
| **Attack Vector** | Post-processing hook sends full document results to unauthorized endpoint |
| **Impact** | Complete exfiltration of all processed document data |
| **Likelihood** | Medium |
| **Severity** | Critical |
| **Affected Components** | Post-Processing Hook Lambda, Decompressor Lambda |
| **Mitigations** | Customer-managed VPC with egress controls on hook Lambda, security review of hook code, network-level monitoring, data loss prevention policies |

### HOOK.T03: Inference Hook Result Tampering

| Attribute | Value |
|-----------|-------|
| **Threat ID** | HOOK.T03 |
| **Category** | STRIDE: Tampering |
| **Description** | Inference hooks return results that feed into the downstream pipeline. A compromised hook could return manipulated extraction results |
| **Attack Vector** | Inference hook returns carefully crafted false extraction data that passes validation but contains incorrect or malicious content |
| **Impact** | Corrupted processing results, incorrect business decisions based on tampered data |
| **Likelihood** | Low |
| **Severity** | High |
| **Affected Components** | Inference Hook Lambda, downstream pipeline steps |
| **Mitigations** | Output schema validation in platform code, assessment step as verification layer, evaluation framework to detect accuracy degradation, human review for critical documents |

### HOOK.T04: Hook Lambda Timeout/Failure Cascade

| Attribute | Value |
|-----------|-------|
| **Threat ID** | HOOK.T04 |
| **Category** | STRIDE: Denial of Service |
| **Description** | Customer hook Lambdas that timeout, fail, or hang can block the processing pipeline, especially if retry policies are aggressive |
| **Attack Vector** | Hook Lambda with infinite loop, external dependency timeout, or resource exhaustion |
| **Impact** | Pipeline processing blocked for affected documents, Step Functions execution stuck |
| **Likelihood** | Medium |
| **Severity** | Medium |
| **Affected Components** | Step Functions, Hook Lambdas |
| **Mitigations** | Step Functions timeout configuration on hook invocation states, error handling with fallback states, CloudWatch alarms on hook failures, DLQ for failed processing |

### HOOK.T05: Privilege Escalation via Hook IAM Role

| Attribute | Value |
|-----------|-------|
| **Threat ID** | HOOK.T05 |
| **Category** | STRIDE: Elevation of Privilege |
| **Description** | If the hook Lambda's IAM role has excessive permissions, compromised hook code could access platform resources beyond its intended scope |
| **Attack Vector** | Hook Lambda with over-permissioned IAM role accesses platform S3 buckets, DynamoDB tables, or other resources |
| **Impact** | Unauthorized access to platform data and resources |
| **Likelihood** | Low |
| **Severity** | High |
| **Affected Components** | Hook Lambda IAM role, platform resources |
| **Mitigations** | Documentation emphasizing least-privilege IAM for hooks, platform resources use resource-based policies that don't grant hook roles access, clear boundary between platform and customer IAM roles |

## 4. Security Controls Summary

| Control | Implementation | Threats Mitigated |
|---------|---------------|-------------------|
| **Invocation-only access** | Platform only has lambda:InvokeFunction on hooks | HOOK.T01 |
| **Separate IAM roles** | Hook Lambdas use customer-managed IAM roles | HOOK.T01, HOOK.T05 |
| **Output validation** | Schema validation of hook return values | HOOK.T03 |
| **Timeout handling** | Step Functions timeout on hook states | HOOK.T04 |
| **Error handling** | Fallback states and DLQ | HOOK.T04 |
| **Security documentation** | Best practices guide for hook development | HOOK.T01, HOOK.T02, HOOK.T05 |
| **Network controls** | Customer-managed VPC for hook Lambdas | HOOK.T02 |
