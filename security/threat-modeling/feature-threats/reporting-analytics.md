# Reporting & Analytics — Threat Analysis

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Feature** | Reporting Database, Analytics, Evaluation |
| **Classification** | Internal |

## 1. Feature Overview

The reporting and analytics subsystem provides:
- **Reporting Database**: Document processing results written as Parquet files to S3, cataloged by AWS Glue, and queryable via Amazon Athena
- **Evaluation Framework**: Automated accuracy comparison against ground truth documents, with enhanced reporting and metrics
- **Cost Calculator**: Token-based cost estimation for processing operations
- **Dashboard Metrics**: Processing volume, success rates, costs, and performance metrics displayed in the Web UI
- **Test Studio**: Interactive document testing with real-time feedback
- **Discovery**: AI-assisted configuration generation from sample document analysis

## 2. Architecture

```mermaid
flowchart TD
    subgraph Data Collection
        ReportLambda[Reporting Lambda] -->|Parquet| S3Report[S3 Reporting Bucket]
        EvalLambda[Evaluation Lambda] -->|Results| S3Report
        MeterLambda[Metering Lambda] -->|Usage Data| S3Report
    end

    subgraph Data Catalog
        Glue[AWS Glue Crawler] -->|Catalog| S3Report
        Glue --> GlueCatalog[Glue Data Catalog]
    end

    subgraph Query Layer
        Athena[Amazon Athena] --> GlueCatalog
        Athena --> S3Report
        Agent[Analytics Agent] --> Athena
    end

    subgraph UI
        Dashboard[Dashboard] -->|AppSync| Lambda[Status/Metrics Lambda]
        Lambda --> DDB[DynamoDB]
        TestStudio[Test Studio] -->|AppSync| TestLambda[Test Lambda]
        Discovery[Discovery] -->|AppSync| DiscLambda[Discovery Lambda]
        DiscLambda --> Bedrock[Amazon Bedrock]
    end
```

## 3. Threat Analysis

### RPT.T01: Reporting Data Tampering

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T01 |
| **Category** | STRIDE: Tampering, Repudiation |
| **Description** | Parquet files in the reporting S3 bucket could be modified or deleted, altering historical processing records and analytics |
| **Attack Vector** | Direct S3 access with compromised credentials, or Lambda bug that overwrites existing reporting data |
| **Impact** | Corrupted analytics, unreliable evaluation metrics, loss of audit trail |
| **Likelihood** | Low |
| **Severity** | Medium |
| **Affected Components** | S3 Reporting Bucket, Parquet files |
| **Mitigations** | S3 versioning, write-only IAM policies for reporting Lambdas (no delete/overwrite), S3 Object Lock for critical records, CloudTrail logging of S3 operations |

### RPT.T02: Athena Query Data Exposure

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T02 |
| **Category** | STRIDE: Information Disclosure |
| **Description** | Athena queries over reporting data expose all processed document information. Query results stored in Athena output location could be accessed by unauthorized users |
| **Attack Vector** | Access Athena query results S3 bucket, or submit queries that extract sensitive fields from processed documents |
| **Impact** | Exposure of all processed document data including extracted PII and business-sensitive information |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | Amazon Athena, S3 query results, Glue Data Catalog |
| **Mitigations** | Athena workgroup with restricted query result location, S3 lifecycle policies on query results (auto-delete), IAM restrictions on Athena access (Admin/Author only), Athena query logging |

### RPT.T03: Glue Catalog Manipulation

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T03 |
| **Category** | STRIDE: Tampering |
| **Description** | The Glue Data Catalog defines table schemas and S3 data locations. If modified, Athena queries could read wrong data, miss data, or expose additional S3 paths |
| **Attack Vector** | Modify Glue table definitions to point to different S3 locations, or alter column definitions to expose additional data |
| **Impact** | Athena queries return wrong data, or expose data from other S3 paths |
| **Likelihood** | Low |
| **Severity** | Medium |
| **Affected Components** | AWS Glue Data Catalog, Glue Crawler |
| **Mitigations** | IAM restrictions on Glue API operations, Glue Catalog resource policies, CloudTrail logging of Glue operations, periodic catalog validation |

### RPT.T04: Evaluation Data Manipulation

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T04 |
| **Category** | STRIDE: Tampering |
| **Description** | Ground truth data and evaluation results could be tampered with to hide accuracy degradation or mask the impact of attacks on processing quality |
| **Attack Vector** | Modify ground truth files in S3 to match incorrect extraction results, or tamper with evaluation metrics |
| **Impact** | False confidence in processing accuracy, masked detection of prompt injection or processing attacks |
| **Likelihood** | Low |
| **Severity** | High |
| **Affected Components** | S3 (ground truth and evaluation data), Evaluation Lambda |
| **Mitigations** | RBAC (Admin-only ground truth management), S3 versioning on ground truth data, evaluation result integrity checks, separate evaluation metrics storage |

### RPT.T05: Discovery Feature — Prompt Injection via Sample Documents

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T05 |
| **Category** | STRIDE: Tampering, Elevation of Privilege |
| **Description** | The Discovery feature analyzes sample documents to auto-generate processing configurations. Adversarial sample documents could manipulate the AI into generating malicious configurations |
| **Attack Vector** | Upload crafted sample documents that contain prompt injection causing Discovery to generate configurations with malicious prompts, extraction schemas, or class definitions |
| **Impact** | Auto-generated configurations that systematically misprocess or exfiltrate data when used for production processing |
| **Likelihood** | Medium |
| **Severity** | High |
| **Affected Components** | Discovery Lambda, Amazon Bedrock, Configuration S3 |
| **Mitigations** | Discovery generates draft configs that require human review before activation, configuration schema validation, RBAC (Admin/Author required), evaluation testing before production use |

### RPT.T06: Test Studio — Uncontrolled Processing Costs

| Attribute | Value |
|-----------|-------|
| **Threat ID** | RPT.T06 |
| **Category** | STRIDE: Denial of Service |
| **Description** | Test Studio allows interactive document testing that invokes the full processing pipeline. Excessive testing could consume Bedrock tokens, Textract calls, and Lambda execution time |
| **Attack Vector** | Repeatedly submit documents through Test Studio to generate excessive processing costs |
| **Impact** | Cost escalation, processing resource exhaustion affecting production workloads |
| **Likelihood** | Medium |
| **Severity** | Medium |
| **Affected Components** | Test Studio, processing pipeline, Bedrock, Textract |
| **Mitigations** | RBAC (Admin/Author required for Test Studio), rate limiting on test submissions, separate test processing tracking, CloudWatch alarms on processing costs |

## 4. Security Controls Summary

| Control | Implementation | Threats Mitigated |
|---------|---------------|-------------------|
| **S3 versioning** | Versioning on reporting and ground truth buckets | RPT.T01, RPT.T04 |
| **Write-only IAM** | Reporting Lambda can write but not delete Parquet files | RPT.T01 |
| **Athena workgroup** | Restricted query result location, IAM scoping | RPT.T02 |
| **IAM restrictions** | Glue API access restricted to platform roles | RPT.T03 |
| **RBAC** | Role-based access to evaluation, discovery, test studio | RPT.T04, RPT.T05, RPT.T06 |
| **Config validation** | Schema validation of discovery-generated configs | RPT.T05 |
| **Rate limiting** | Test Studio submission limits | RPT.T06 |
| **Audit logging** | CloudTrail for S3, Glue, Athena operations | All |
