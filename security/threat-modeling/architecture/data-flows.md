# Data Flows

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Classification** | Internal |

## 1. Overview

This document describes the primary data flows through the GenAI IDP Accelerator, identifying where data crosses trust boundaries, undergoes transformation, and is persisted. Each flow is analyzed for security-relevant characteristics.

## 2. Document Processing Flow (Core Pipeline)

### 2.1 Document Ingestion

```mermaid
sequenceDiagram
    participant User as User / System
    participant S3 as S3 Input Bucket
    participant EB as EventBridge
    participant QS as Queue Sender Lambda
    participant SQS as SQS Queue
    participant QP as Queue Processor Lambda
    participant DDB as DynamoDB
    participant SFN as Step Functions

    User->>S3: Upload document (S3 PutObject / presigned URL)
    S3->>EB: Object created event
    EB->>QS: Trigger Lambda
    QS->>SQS: Enqueue document reference
    SQS->>QP: Dequeue message
    QP->>DDB: Check/update concurrency counter
    QP->>DDB: Create document tracking record
    QP->>SFN: Start execution (document reference, config)
```

**Data in transit**: Document bytes (S3 upload), S3 object key references (SQS messages), configuration JSON (Step Functions input).

**Trust boundary crossings**:
- TB1→TB2: User uploads document over HTTPS
- TB3 internal: S3 → EventBridge → Lambda → SQS → Lambda → Step Functions

**Security controls**:
- S3 bucket policy restricts upload access
- SQS encryption at rest (SSE-SQS)
- Step Functions input validated by Queue Processor Lambda
- DynamoDB concurrency counter prevents runaway processing

### 2.2 Pipeline Mode Processing

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant OCR as OCR Lambda
    participant Textract as Amazon Textract
    participant Class as Classification Lambda
    participant Extract as Extraction Lambda
    participant Assess as Assessment Lambda
    participant Bedrock as Amazon Bedrock
    participant S3 as S3 Output Bucket

    SFN->>OCR: Invoke with document reference
    OCR->>Textract: DetectDocumentText / AnalyzeDocument
    Textract-->>OCR: OCR results (text, layout, tables)
    OCR->>S3: Store OCR output

    SFN->>Class: Invoke with OCR text
    Class->>Bedrock: Prompt with document text + class definitions
    Bedrock-->>Class: Classification result
    Class->>S3: Store classification output

    SFN->>Extract: Invoke with OCR text + classification
    Extract->>Bedrock: Prompt with extraction schema
    Bedrock-->>Extract: Structured extracted data (JSON)
    Extract->>S3: Store extraction output

    SFN->>Assess: Invoke with extracted data
    Assess->>Bedrock: Prompt with assessment criteria
    Bedrock-->>Assess: Assessment scores/results
    Assess->>S3: Store assessment output
```

**Data transformation**: Raw document → OCR text/layout → classified document type → structured JSON extraction → quality assessment scores.

**Sensitive data exposure**: Full document text is sent to Bedrock and Textract API endpoints. Extracted PII/sensitive data flows through Lambda memory and is written to S3.

**Trust boundary crossings**:
- TB3→TB4: Lambda sends document text to Textract and Bedrock APIs

### 2.3 BDA Mode Processing

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant BDALambda as BDA Lambda
    participant BDA as Bedrock Data Automation
    participant S3 as S3 Output Bucket

    SFN->>BDALambda: Invoke with document reference
    BDALambda->>BDA: Submit document for processing (S3 URI)
    BDA-->>BDALambda: Processing results (classification + extraction)
    BDALambda->>BDALambda: Map BDA output → standard format
    BDALambda->>S3: Store normalized output
```

**Data transformation**: Raw document → BDA-processed results → normalized to standard pipeline output format.

**Trust boundary crossings**:
- TB3→TB4: Lambda provides S3 URI to BDA service; BDA reads document directly from S3

### 2.4 Shared Processing Tail

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant HITL as HITL Check Lambda
    participant A2I as Amazon A2I
    participant RV as Rule Validation Lambda
    participant Bedrock as Amazon Bedrock
    participant Sum as Summarization Lambda
    participant Eval as Evaluation Lambda
    participant S3 as S3 Output Bucket
    participant DDB as DynamoDB
    participant Report as Reporting Lambda

    SFN->>HITL: Check if human review needed
    alt HITL Enabled
        HITL->>A2I: Create human review task
        A2I-->>HITL: Review results (async)
    end

    SFN->>RV: Validate extracted data against rules
    RV->>Bedrock: Optional AI-assisted rule evaluation
    RV-->>SFN: Validation results

    SFN->>Sum: Generate document summary
    Sum->>Bedrock: Summarization prompt
    Sum-->>SFN: Summary text

    SFN->>Eval: Compare results to ground truth (if available)
    Eval->>S3: Store evaluation report

    SFN->>Report: Save metering/reporting data
    Report->>S3: Write Parquet file to reporting bucket
    Report->>DDB: Update document record with final status
```

## 3. Web UI Data Flows

### 3.1 Authentication Flow

```mermaid
sequenceDiagram
    participant Browser as Browser
    participant CF as CloudFront
    participant Cognito as Cognito
    participant AppSync as AppSync

    Browser->>CF: Load SPA (React app)
    CF-->>Browser: Static assets from S3
    Browser->>Cognito: Authenticate (username/password or SSO)
    Cognito-->>Browser: JWT tokens (ID, Access, Refresh)
    Browser->>AppSync: GraphQL request + JWT
    AppSync->>AppSync: Validate JWT, extract Cognito groups
    AppSync->>AppSync: Apply field-level authorization
```

**Trust boundary crossings**: TB1→TB2 (browser to CloudFront/Cognito), TB2→TB3 (Cognito JWT to AppSync).

### 3.2 Configuration Management Flow

```mermaid
sequenceDiagram
    participant Browser as Browser
    participant AppSync as AppSync
    participant Lambda as Config Lambda
    participant S3 as S3 Config Bucket
    participant DDB as DynamoDB Config Table

    Browser->>AppSync: Save configuration (GraphQL mutation)
    AppSync->>Lambda: Resolve mutation
    Lambda->>Lambda: Validate config schema (JSON Schema)
    Lambda->>S3: Write config YAML to S3
    Lambda->>DDB: Update config version record
    Lambda-->>AppSync: Success response
    AppSync-->>Browser: Confirmation
```

**Security note**: Configuration includes model IDs, prompts, extraction schemas, and processing parameters. Malicious configuration could influence all subsequent document processing.

### 3.3 Document Upload Flow (UI)

```mermaid
sequenceDiagram
    participant Browser as Browser
    participant AppSync as AppSync
    participant Lambda as Presigned URL Lambda
    participant S3 as S3 Input Bucket

    Browser->>AppSync: Request presigned upload URL
    AppSync->>Lambda: Generate presigned URL
    Lambda->>S3: CreatePresignedPost
    Lambda-->>AppSync: Presigned URL + fields
    AppSync-->>Browser: Presigned URL
    Browser->>S3: Direct upload via presigned URL (HTTPS)
```

## 4. Agent & Chat Data Flows

### 4.1 Companion Chat Flow

```mermaid
sequenceDiagram
    participant Browser as Browser
    participant AppSync as AppSync
    participant Lambda as Chat Processor Lambda
    participant DDB as DynamoDB Conversations Table
    participant Bedrock as Amazon Bedrock
    participant Tools as Agent Tools (Athena, MCP, etc.)

    Browser->>AppSync: Send chat message (mutation)
    AppSync->>Lambda: Invoke chat processor
    Lambda->>DDB: Load conversation history (last 20 turns)
    Lambda->>Bedrock: Invoke model with context + tools
    
    loop Tool Use
        Bedrock-->>Lambda: Tool call request
        Lambda->>Tools: Execute tool (Athena query, MCP call, etc.)
        Tools-->>Lambda: Tool result
        Lambda->>Bedrock: Continue with tool result
    end

    Bedrock-->>Lambda: Final response (streaming)
    Lambda->>AppSync: Publish response chunks (subscription)
    AppSync-->>Browser: Real-time response stream
    Lambda->>DDB: Save conversation turn
```

**Trust boundary crossings**:
- TB1→TB3: User message via AppSync
- TB3→TB4: Conversation context sent to Bedrock
- TB3→TB5: Analytics queries to Athena
- TB3→TB6: MCP tool calls to customer-managed agents

### 4.2 Agent Analysis Flow

```mermaid
sequenceDiagram
    participant Lambda as Agent Processor Lambda
    participant Bedrock as Orchestrator (Bedrock)
    participant Analytics as Analytics Agent
    participant Athena as Amazon Athena
    participant AgentCore as Bedrock AgentCore
    participant MCP as MCP Agents

    Lambda->>Bedrock: User query + tools
    Bedrock-->>Lambda: Route to analytics agent
    Lambda->>Analytics: Execute analytics query
    Analytics->>Athena: SQL query over processed data
    Athena-->>Analytics: Query results
    Analytics->>AgentCore: Execute Python visualization code
    AgentCore-->>Analytics: Generated chart/analysis
    Analytics-->>Lambda: Analysis result
```

**Security note**: Natural language → SQL translation creates SQL injection risk. AgentCore code execution is sandboxed but executes AI-generated code.

### 4.3 MCP Integration Flow

```mermaid
sequenceDiagram
    participant Agent as Agent Lambda
    participant Bedrock as Amazon Bedrock
    participant MCPLambda as MCP Gateway Lambda
    participant ExtService as External Service / API

    Agent->>Bedrock: Prompt with MCP tool definitions
    Bedrock-->>Agent: Tool call (MCP tool)
    Agent->>MCPLambda: Invoke MCP Lambda with tool parameters
    MCPLambda->>ExtService: Call external API / service
    ExtService-->>MCPLambda: Response
    MCPLambda-->>Agent: Tool result
```

**Trust boundary crossings**: TB3→TB6→External. MCP agents can call external services, introducing data exfiltration and injection risks.

## 5. SDK/CLI Data Flow

```mermaid
sequenceDiagram
    participant CLI as SDK/CLI Client
    participant Cognito as Cognito
    participant AppSync as AppSync
    participant S3 as S3 Buckets
    participant Lambda as Lambda Functions

    CLI->>Cognito: Authenticate (SRP / username+password)
    Cognito-->>CLI: JWT tokens
    CLI->>AppSync: GraphQL operations (config, status, etc.)
    CLI->>S3: Upload documents (presigned URLs)
    CLI->>AppSync: Monitor processing (subscriptions)
```

**Security note**: SDK/CLI stores credentials locally on developer machines. Tokens are short-lived but refresh tokens provide extended access.

## 6. Reporting & Analytics Data Flow

```mermaid
sequenceDiagram
    participant Lambda as Reporting Lambda
    participant S3 as S3 Reporting Bucket
    participant Glue as AWS Glue Crawler
    participant Athena as Amazon Athena
    participant Agent as Analytics Agent

    Lambda->>S3: Write Parquet files (metering, evaluation data)
    Glue->>S3: Crawl and catalog Parquet data
    Glue->>Glue: Update Glue Data Catalog
    Agent->>Athena: SQL query
    Athena->>S3: Read Parquet data
    Athena-->>Agent: Query results
```

## 7. Knowledge Base Data Flow

```mermaid
sequenceDiagram
    participant Lambda as KB Lambda
    participant S3 as S3 KB Source Bucket
    participant BedrockKB as Bedrock Knowledge Base
    participant OpenSearch as OpenSearch Serverless
    participant Pipeline as Processing Pipeline

    Lambda->>S3: Upload reference documents
    Lambda->>BedrockKB: Trigger data source sync
    BedrockKB->>S3: Read source documents
    BedrockKB->>BedrockKB: Chunk, embed documents
    BedrockKB->>OpenSearch: Store vector embeddings

    Pipeline->>BedrockKB: RAG query (retrieve relevant context)
    BedrockKB->>OpenSearch: Vector similarity search
    OpenSearch-->>BedrockKB: Matching chunks
    BedrockKB-->>Pipeline: Retrieved context for augmented prompts
```

## 8. Lambda Hook Data Flows

### 8.1 Inference Hook

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant Hook as Customer Lambda Hook
    participant ExtModel as External Model / API

    SFN->>Hook: Invoke with document data + context
    Hook->>ExtModel: Custom inference call
    ExtModel-->>Hook: Model results
    Hook-->>SFN: Results in expected format
```

### 8.2 Post-Processing Hook

```mermaid
sequenceDiagram
    participant SFN as Step Functions
    participant Decomp as Decompressor Lambda
    participant Hook as Customer Lambda Hook
    participant ExtSys as External System

    SFN->>Decomp: Invoke with compressed results
    Decomp->>Decomp: Decompress document data
    Decomp->>Hook: Invoke with full document results
    Hook->>ExtSys: Push results to external system
    Hook-->>Decomp: Acknowledgment
```

**Trust boundary crossings**: TB3→TB6. Customer-managed Lambda hooks receive full document processing results and can send data to arbitrary external systems.

## 9. Summary of Cross-Boundary Data Flows

| Flow | From | To | Data Sensitivity | Controls |
|------|------|----|-----------------|----------|
| Document upload | TB1 | TB3 | High (customer docs) | HTTPS, presigned URLs, auth |
| OCR processing | TB3 | TB4 | High (full document text) | TLS, IAM roles |
| LLM prompts | TB3 | TB4 | High (document text + PII) | TLS, IAM roles, no training opt-out |
| Chat messages | TB1 | TB3→TB4 | Medium-High (user queries + context) | Auth, TLS, conversation isolation |
| MCP tool calls | TB3 | TB6→External | Variable (depends on tool) | IAM, customer responsibility |
| Lambda hooks | TB3 | TB6 | High (full processing results) | IAM, invocation-only permissions |
| Analytics queries | TB3 | TB5 | High (aggregated processing data) | Athena workgroup, IAM |
| KB retrieval | TB3 | TB4→TB5 | Medium (reference doc chunks) | IAM, encryption |
| SDK/CLI auth | TB1 | TB2 | High (credentials) | SRP protocol, short-lived tokens |
| Configuration | TB1 | TB3 | Medium (prompts, schemas) | Auth, schema validation |
