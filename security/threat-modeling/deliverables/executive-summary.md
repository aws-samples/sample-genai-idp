# Threat Model — Executive Summary

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Classification** | Internal |
| **System** | GenAI Intelligent Document Processing (IDP) Accelerator |

## 1. Purpose

This document provides an executive-level summary of the threat model for the GenAI IDP Accelerator, a serverless intelligent document processing solution deployed on AWS. The threat model identifies security risks across the system's architecture, features, and integrations, and documents the controls in place to mitigate them.

## 2. System Summary

The GenAI IDP Accelerator automates document processing using generative AI. It processes documents through a configurable pipeline (OCR → Classification → Extraction → Assessment → Validation → Evaluation) with two processing modes:

- **Pipeline Mode**: Amazon Textract + Amazon Bedrock foundation models
- **BDA Mode**: Amazon Bedrock Data Automation (integrated processing)

The system includes a web UI, multi-agent AI assistant, SDK/CLI for automation, human-in-the-loop review, extensibility via Lambda hooks and MCP integrations, and comprehensive analytics/reporting.

### Key Metrics

| Metric | Value |
|--------|-------|
| **AWS Services Used** | 15+ (Bedrock, Textract, Lambda, Step Functions, DynamoDB, S3, AppSync, Cognito, Athena, Glue, OpenSearch, CloudFront, SQS, EventBridge, CloudWatch) |
| **Lambda Functions** | 50+ |
| **DynamoDB Tables** | 6+ |
| **S3 Buckets** | 4+ |
| **CloudWatch Alarms** | 60+ |
| **Processing Modes** | 2 (Pipeline, BDA) |
| **RBAC Roles** | 4 (Admin, Author, Reviewer, Viewer) |

## 3. Threat Model Results

### 3.1 Threats Identified

| Category | Count |
|----------|-------|
| **Total threats identified** | **62** |
| Critical risk (score 8-12) | 5 |
| High risk (score 6-9) | 19 |
| Medium risk (score 3-4) | 28 |
| Low risk (score 1-2) | 10 |

### 3.2 STRIDE Distribution

| STRIDE Category | Count | Key Concern |
|----------------|-------|-------------|
| **Tampering** | 22 | Prompt injection, configuration manipulation, data poisoning |
| **Information Disclosure** | 16 | Data exfiltration via extensibility points, token/credential exposure |
| **Elevation of Privilege** | 12 | RBAC bypass, hook privilege escalation, agent routing manipulation |
| **Denial of Service** | 10 | Resource exhaustion, cost escalation, service dependency |
| **Spoofing** | 7 | Token theft, credential compromise, service impersonation |
| **Repudiation** | 5 | Insufficient audit trail, BDA opacity |

### 3.3 Mitigation Status

| Status | Count | Percentage |
|--------|-------|------------|
| **Mitigated** | 50 | 81% |
| **Partially Mitigated** | 7 | 11% |
| **Accepted** | 5 | 8% |

## 4. Key Risk Areas

### 4.1 Prompt Injection (Highest Impact)

Prompt injection remains the top threat vector across document processing (PM.T01), chat interactions (CHAT.T01), knowledge base retrieval (KB.T02), and discovery (RPT.T05). The system processes untrusted document content through LLM prompts, creating inherent injection risk.

**Mitigations**: Prompt engineering with guardrails, input/output tagging, Bedrock Guardrails, output schema validation, evaluation framework for accuracy monitoring, human review for critical documents.

### 4.2 Data Exfiltration via Extensibility Points

MCP integrations (MCP.T01) and post-processing Lambda hooks (HOOK.T02) can send processed document data to external systems. While this is by design for integration purposes, it creates data exfiltration channels.

**Mitigations**: IAM least-privilege, customer-managed VPC with egress controls, audit logging, security review documentation. Partially mitigated — additional VPC egress controls recommended.

### 4.3 Configuration as Attack Surface

The system's high configurability (prompts, schemas, model selection, agent tools) means configuration tampering (PM.T06) has critical impact. A compromised admin account could alter processing behavior for all documents.

**Mitigations**: 4-tier RBAC (Admin-only for critical config), configuration versioning, JSON Schema validation, audit logging.

### 4.4 Authentication & Authorization

RBAC is enforced at multiple layers (Cognito → AppSync → Lambda) but authorization gaps in any layer could enable privilege escalation (AUTH.T03). The system is single-tenant per deployment.

**Mitigations**: Comprehensive AppSync resolver authorization, defense-in-depth with Lambda-level role checks, Cognito advanced security features.

## 5. Recommendations

### Immediate (Partially Mitigated Critical/High Risks)

1. **Implement VPC egress controls** for MCP Lambda functions to prevent unauthorized data exfiltration
2. **Publish secure hook deployment guide** with reference VPC architecture and IAM templates
3. **Enhance SDK credential management** with credential helper integration
4. **Conduct AppSync authorization audit** to verify all resolvers enforce role-based access

### Ongoing

1. **Monitor evaluation metrics** for accuracy degradation indicating prompt injection attacks
2. **Periodic authorization review** of AppSync resolver rules
3. **Athena query pattern monitoring** for anomalous data access
4. **Agent usage analytics** to detect tool invocation anomalies

## 6. Compliance

The threat model has been developed using:
- **STRIDE methodology** for systematic threat identification
- **Risk scoring** (Likelihood × Severity) for prioritization
- **AWS Well-Architected Framework** security pillar alignment
- **AWS Threat Model Template** requirements

## 7. Document References

| Document | Description |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Unified architecture, components, trust boundaries |
| [Data Flows](../architecture/data-flows.md) | All data flow diagrams with security analysis |
| [STRIDE Analysis](../threat-analysis/stride-analysis.md) | Full STRIDE analysis across all components |
| [Risk Matrix](../risk-assessment/risk-matrix.md) | Complete risk register with scoring |
| [Implementation Guide](implementation-guide.md) | Security controls implementation details |
| [Threat ID Glossary](../threat-id-glossary.md) | All 62 threat IDs with cross-references |
