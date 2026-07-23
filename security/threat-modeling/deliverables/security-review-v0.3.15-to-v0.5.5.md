# Security Review: Changes from v0.3.15 to v0.5.5

**Prepared for:** Security Review / Penetration Test Team
**Date:** April 2026
**Scope:** All features, API changes, and infrastructure modifications from v0.3.16 through v0.5.5 (20 releases)
**Last Reviewed Release:** v0.3.15
**Current Release:** v0.5.5

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Security Impact Legend](#2-security-impact-legend)
- [3. High-Impact Features Requiring Priority Review](#3-high-impact-features-requiring-priority-review)
  - [3.1 Role-Based Access Control (RBAC) — v0.5.2](#31-role-based-access-control-rbac--v052)
  - [3.2 RBAC Security Hardening — v0.5.3](#32-rbac-security-hardening--v053)
  - [3.3 MCP Integration (External App Access via OAuth 2.0) — v0.4.6](#33-mcp-integration-external-app-access-via-oauth-20--v046)
  - [3.4 External MCP Agent Integration — v0.3.13 (pre-v0.3.16 but relevant)](#34-external-mcp-agent-integration--v0313)
  - [3.5 Agent Companion Chat with Multi-Agent System — v0.4.0](#35-agent-companion-chat-with-multi-agent-system--v040)
  - [3.6 Code Intelligence Agent (Third-Party Data Flow) — v0.4.0](#36-code-intelligence-agent-third-party-data-flow--v040)
  - [3.7 Lambda Hook Inference (Custom LLM Integration) — v0.4.15](#37-lambda-hook-inference-custom-llm-integration--v0415)
  - [3.8 Custom Model Fine-Tuning — v0.5.2](#38-custom-model-fine-tuning--v052)
  - [3.9 User Management — v0.4.11](#39-user-management--v0411)
  - [3.10 ALB + S3 VPC Hosting Mode — v0.5.3](#310-alb--s3-vpc-hosting-mode--v053)
- [4. Moderate-Impact Features](#4-moderate-impact-features)
  - [4.1 Configuration Versioning System — v0.4.15](#41-configuration-versioning-system--v0415)
  - [4.2 Built-in Human-in-the-Loop (HITL) Review System — v0.4.11](#42-built-in-human-in-the-loop-hitl-review-system--v0411)
  - [4.3 Test Studio — v0.4.6](#43-test-studio--v046)
  - [4.4 IDP SDK & CLI — v0.3.20, v0.4.12, v0.5.3](#44-idp-sdk--cli--v0320-v0412-v053)
  - [4.5 IDP MCP Connector — v0.5.3](#45-idp-mcp-connector--v053)
  - [4.6 Multi-Document Discovery — v0.5.5](#46-multi-document-discovery--v055)
  - [4.7 Discovery UX Enhancements (Multi-Section, Auto-Detect) — v0.5.3](#47-discovery-ux-enhancements-multi-section-auto-detect--v053)
  - [4.8 Rule Validation — v0.4.13](#48-rule-validation--v0413)
  - [4.9 MLflow Experiment Tracking Integration — v0.5.4](#49-mlflow-experiment-tracking-integration--v054)
  - [4.10 Abort Workflow — v0.4.9](#410-abort-workflow--v049)
  - [4.11 Scalable Document List (GSI-Based) — v0.5.1](#411-scalable-document-list-gsi-based--v051)
  - [4.12 Custom Date Range Query — v0.4.15](#412-custom-date-range-query--v0415)
  - [4.13 Managed Configuration Versions — v0.5.3](#413-managed-configuration-versions--v053)
  - [4.14 Prompt Preview — v0.5.5](#414-prompt-preview--v055)
  - [4.15 Agentic Extraction with S3 Checkpointing — v0.5.4, v0.5.5](#415-agentic-extraction-with-s3-checkpointing--v054-v055)
- [5. Lower-Impact Changes](#5-lower-impact-changes)
  - [5.1 Unified Pattern (BDA + Pipeline Merge) — v0.5.0](#51-unified-pattern-bda--pipeline-merge--v050)
  - [5.2 S3 Vectors for Knowledge Base — v0.3.16](#52-s3-vectors-for-knowledge-base--v0316)
  - [5.3 Post-Processing Lambda Hook Decompression — v0.4.7](#53-post-processing-lambda-hook-decompression--v047)
  - [5.4 Containerized Lambda Deployments — v0.3.20, v0.4.2](#54-containerized-lambda-deployments--v0320-v042)
  - [5.5 Error Analyzer Agent — v0.3.19](#55-error-analyzer-agent--v0319)
  - [5.6 Agent Analysis (Analytics Agent) — v0.3.10](#56-agent-analysis-analytics-agent--v0310)
  - [5.7 Chandra OCR Lambda Hook Sample — v0.5.5](#57-chandra-ocr-lambda-hook-sample--v055)
  - [5.8 Standard Class Catalog — v0.5.2](#58-standard-class-catalog--v052)
  - [5.9 Third-Party Model Support — v0.5.1](#59-third-party-model-support--v051)
  - [5.10 Bedrock Service Tiers — v0.4.9](#510-bedrock-service-tiers--v049)
  - [5.11 Python 3.12+ Requirement — v0.5.2](#511-python-312-requirement--v052)
  - [5.12 Visual Document Editor Enhancements — v0.4.13](#512-visual-document-editor-enhancements--v0413)
  - [5.13 Section-Level DynamoDB Updates — v0.4.13](#513-section-level-dynamodb-updates--v0413)
  - [5.14 BDA/IDP Sync — v0.4.10, v0.4.14](#514-bdaidp-sync--v0410-v0414)
  - [5.15 Pricing Configuration UI — v0.4.10](#515-pricing-configuration-ui--v0410)
  - [5.16 Stickler-Based Evaluation — v0.4.2](#516-stickler-based-evaluation--v042)
  - [5.17 JSON Schema Format for Class Definitions — v0.4.0](#517-json-schema-format-for-class-definitions--v040)
  - [5.18 DynamoDB Config Compression — v0.4.16](#518-dynamodb-config-compression--v0416)
- [6. Complete GraphQL API Changes Summary](#6-complete-graphql-api-changes-summary)
  - [6.1 New Mutations](#61-new-mutations)
  - [6.2 New Queries](#62-new-queries)
  - [6.3 New Subscriptions](#63-new-subscriptions)
  - [6.4 Auth Directive Coverage](#64-auth-directive-coverage)
- [7. Infrastructure Changes Summary](#7-infrastructure-changes-summary)
  - [7.1 New Lambda Functions](#71-new-lambda-functions)
  - [7.2 New DynamoDB Tables / GSIs](#72-new-dynamodb-tables--gsis)
  - [7.3 New IAM Roles](#73-new-iam-roles)
  - [7.4 New CloudFormation Parameters](#74-new-cloudformation-parameters)
  - [7.5 Nested Stack Architecture Changes](#75-nested-stack-architecture-changes)
- [8. Security Fixes Included in Scope](#8-security-fixes-included-in-scope)
- [9. Recommended Pen Test Focus Areas](#9-recommended-pen-test-focus-areas)

---

## 1. Executive Summary

Between v0.3.15 and v0.5.5, the GenAI IDP Accelerator underwent **20 releases** introducing new capabilities that change the security footprint:

**Major security-relevant additions:**
- **Role-Based Access Control (RBAC)** with 4-role model (Admin, Author, Reviewer, Viewer) and server-side AppSync auth directives
- **MCP Integration** providing external application access via OAuth 2.0 through AWS Bedrock AgentCore Gateway
- **Multi-agent chat system** with streaming GraphQL subscriptions, external MCP server connectivity (DeepWiki), and DynamoDB-backed conversation history
- **Lambda Hook Inference** allowing customer-provided Lambda functions to be invoked during the processing pipeline
- **Custom Model Fine-Tuning** with training data generation from processed documents
- **User Management** enabling Admin users to create and manage Cognito user accounts
- **ALB+S3 VPC Hosting** as an alternative to CloudFront for private network deployments
- **IDP SDK, CLI, and MCP Connector** providing new programmatic access paths beyond the Web UI
- **Unified Pattern** merging BDA and Pipeline into a single deployment with runtime toggle

**GraphQL API surface area growth:** Approximately **40+ new mutations, 20+ new queries, and 5 new subscriptions** have been added, all with RBAC auth directives.

**Infrastructure growth:** Approximately **30+ new Lambda functions**, new DynamoDB GSIs, new nested CloudFormation stacks (AppSync, ALB hosting), and new IAM roles.

---

## 2. Security Impact Legend

| Icon | Level | Meaning |
|------|-------|---------|
| 🔴 | **New Attack Surface** | Introduces new external-facing interfaces, authentication flows, or third-party integrations |
| ⚠️ | **Changed Footprint** | Modifies existing security boundaries, adds new API endpoints, or changes authorization model |
| ✅ | **Minimal Impact** | Internal improvements, bug fixes, or cosmetic changes with no meaningful security footprint change |

---

## 3. High-Impact Features Requiring Priority Review

### 3.1 Role-Based Access Control (RBAC) — v0.5.2

**Security Impact:** 🔴 New Attack Surface

**Description:** Introduced a 4-role model (Admin, Author, Reviewer, Viewer) with server-side AppSync `@aws_auth` directives, server-side Reviewer document filtering, and UI adaptation. Replaces the previous all-or-nothing authenticated access model.

**Security Footprint Changes:**
- **Cognito User Groups** — 4 new groups created: `Admin`, `Author`, `Reviewer`, `Viewer`
- **AppSync `@aws_auth` directives** — Server-side role enforcement on all GraphQL operations
- **Server-side document filtering** — Reviewer role sees only HITL-pending documents
- **Config version scoping** — Non-admin roles can be scoped to specific config versions via `allowedConfigVersions`
- **UI adaptation** — Edit controls, save buttons, and destructive operations hidden for insufficient roles (but server-side enforcement is the real boundary)

**GraphQL API Changes:**
- `@aws_auth(cognito_groups: ["Admin", "Author", "Reviewer", "Viewer"])` directives added to all queries/mutations
- Mutations restricted: `updateConfiguration` (save as version/default = Admin only), `deleteConfigVersion` (Admin only), user management (Admin only)
- Queries restricted: Configuration, discovery, test studio, pricing queries → Admin/Author/Viewer only (Reviewer excluded)
- Document queries: All authenticated users, but Reviewer gets filtered results server-side

**Key Review Areas:**
1. **Privilege escalation** — Can a Reviewer or Viewer bypass `@aws_auth` directives to access Admin-only mutations?
2. **Server-side filtering bypass** — Can a Reviewer query documents outside their HITL-pending scope by manipulating query parameters?
3. **`allowedConfigVersions` enforcement** — Is config version scoping enforced server-side or only in UI?
4. **Token manipulation** — Can Cognito group claims be modified to elevate privileges?
5. **Mixed `@aws_auth` + `@aws_iam`** — Some mutations have both directives (for internal Lambda-to-AppSync calls). Verify IAM-authenticated callers cannot bypass RBAC.

---

### 3.2 RBAC Security Hardening — v0.5.3

**Security Impact:** ⚠️ Changed Footprint (security improvement)

**Description:** Comprehensive audit and hardening of GraphQL API authorization. This release specifically addressed gaps found in the initial RBAC implementation.

**Security Footprint Changes:**
- **20+ queries** that were open to all authenticated users now have server-side role enforcement
- **`updateConfiguration` resolver** — Server-side check rejects non-Admin `saveAsVersion`/`saveAsDefault` (previously only UI-blocked)
- **`listDocumentsByDateRange`** — Added reviewer-only filtering and config-version scope filtering
- **New environment variables** — `USERS_TABLE_NAME` added to resolvers for role lookup
- **New DynamoDB permissions** — Resolvers now read from Users table for RBAC checks

**GraphQL API Changes:**
- Added `@aws_auth` directives to: `getConfiguration`, `getPricing`, `getCapacityPlan`, `listDiscoveryJobs`, `getDiscoveryJob`, `listTestRuns`, `getTestRun`, `listTestSets`, `getTestSet`, `getConfigLibrary`, `getConfigLibraryReadme`, `listAgentChatSessions`, `getAgentChatSession`, `getAgentQuerySystem`
- `listDocumentsByDateRange` now performs server-side RBAC filtering matching `listDocuments` pattern

**Key Review Areas:**
1. **Completeness audit** — Are there any remaining queries/mutations without appropriate `@aws_auth` directives?
2. **Resolver-level enforcement** — For mutations like `updateConfiguration`, verify the Lambda resolver actually checks the caller's Cognito group (not just the AppSync directive)
3. **Date range resolver filtering** — Verify `listDocumentsByDateRange` cannot be used to bypass the Reviewer document scope

---

### 3.3 MCP Integration (External App Access via OAuth 2.0) — v0.4.6

**Security Impact:** 🔴 New Attack Surface

**Description:** Added MCP (Model Context Protocol) integration enabling external applications (like Amazon QuickSuite) to access IDP analytics through AWS Bedrock AgentCore Gateway with secure OAuth 2.0 authentication.

**Security Footprint Changes:**
- **New Cognito App Client** (`ExternalAppClient`) — OAuth 2.0 client for external applications
- **AgentCore Gateway** — New AWS Bedrock AgentCore Gateway endpoint exposed for MCP protocol
- **AgentCore Gateway Execution Role** — New IAM role for the gateway
- **AgentCore MCP Handler Lambda** — Processes MCP protocol requests (renamed from `agentcore_analytics_processor` in v0.5.3)
- **Cross-region support** — MCP connectivity across us-east-1, us-west-2, eu-west-1, ap-southeast-2
- **`EnableMCP` parameter** — Controls whether MCP resources are deployed (default: true)

**GraphQL API Changes:**
- No direct GraphQL changes, but MCP tools (`process`, `reprocess`, `status`, `search`) added in v0.4.16 and v0.5.1 provide alternative access to document processing operations
- MCP tools eventually call the same backend APIs

**Infrastructure:**
- New Lambda: `AgentCoreMCPHandlerFunction` (was `AgentCoreAnalyticsLambdaFunction`)
- New Lambda: `AgentCoreGatewayManagerFunction`
- New IAM Role: `AgentCoreGatewayExecutionRole`
- New Cognito App Client: `ExternalAppClient`
- CloudFormation Outputs: `MCPServerEndpoint`, `MCPClientId`, `MCPClientSecret`, `MCPUserPool`, `MCPTokenURL`, `MCPAuthorizationURL`

**Key Review Areas:**
1. **OAuth 2.0 flow** — Verify token validation, scopes, and expiration on the AgentCore Gateway
2. **MCP tool authorization** — Do MCP tools respect RBAC roles, or do they bypass GraphQL auth?
3. **Gateway endpoint exposure** — Is the AgentCore Gateway publicly accessible? What network controls exist?
4. **Client secret management** — How is `MCPClientSecret` stored and rotated?
5. **Cross-region trust** — Verify cross-region MCP connectivity doesn't create unintended trust relationships

---

### 3.4 External MCP Agent Integration — v0.3.13

**Security Impact:** 🔴 New Attack Surface

**Description:** Enables integration with custom MCP servers hosted in separate AWS accounts or external infrastructure, with secure OAuth authentication using AWS Cognito.

**Security Footprint Changes:**
- **Cross-account MCP server connectivity** — Outbound connections to external MCP servers
- **AWS Secrets Manager configuration** — JSON array configuration supporting multiple MCP server connections
- **OAuth bearer token authentication** — Cognito-based token validation
- **Dynamic tool discovery** — Auto-discovers and integrates tools from external MCP servers

**Key Review Areas:**
1. **Outbound connection control** — What prevents connection to malicious MCP servers?
2. **Secrets Manager access** — Who can modify the MCP server configuration in Secrets Manager?
3. **Tool injection** — Can a malicious MCP server inject tools that access internal resources?
4. **Data exfiltration** — Can document data be sent to external MCP servers through tool calls?

---

### 3.5 Agent Companion Chat with Multi-Agent System — v0.4.0

**Security Impact:** 🔴 New Attack Surface

**Description:** Interactive AI assistant with session-based multi-turn conversations, persistent DynamoDB chat history, real-time streaming via AppSync GraphQL subscriptions, and multiple specialized sub-agents.

**Security Footprint Changes:**
- **DynamoDB Agent Table** — New table storing conversation history (last 20 turns per session)
- **GraphQL subscriptions** — `onAgentChatMessageUpdate` for real-time streaming
- **Multi-agent orchestration** — Analytics Agent, Error Analyzer Agent, Code Intelligence Agent
- **Session isolation** — Unique session IDs per conversation
- **Bedrock AgentCore sandboxes** — Python code execution in isolated environments

**GraphQL API Changes:**
- New mutation: `sendAgentChatMessage` (all authenticated users)
- New mutation: `deleteAgentChatSession` (all authenticated users)
- New query: `listAgentChatSessions` (Admin, Author, Viewer — restricted in v0.5.3)
- New query: `getAgentChatSession` (Admin, Author, Viewer — restricted in v0.5.3)
- New subscription: `onAgentChatMessageUpdate`

**Key Review Areas:**
1. **Prompt injection** — Can user input in chat messages manipulate agent behavior to access unauthorized data?
2. **Cross-session data leakage** — Can one user's session access another user's conversation history?
3. **Agent tool scope** — What resources can the Analytics Agent's SQL tool access? Can it query beyond the reporting database?
4. **Subscription isolation** — Can a user subscribe to another user's chat message updates?
5. **Chat history access control** — Is chat history scoped to the session owner?

---

### 3.6 Code Intelligence Agent (Third-Party Data Flow) — v0.4.0

**Security Impact:** 🔴 New Attack Surface

**Description:** Specialized agent within Agent Companion Chat that connects to DeepWiki MCP server for code-related assistance. Sends data to a third-party service.

**Security Footprint Changes:**
- **Outbound connection to DeepWiki** — External MCP server (third-party service by Devin/Cognition AI)
- **User opt-in toggle** — Enabled by default in v0.4.0, requires explicit consent
- **Security guardrails** — Intended to prevent sensitive data exposure
- **Transport migration** — Migrated from SSE to Streamable HTTP transport (`/mcp` endpoint) in v0.4.15

**Key Review Areas:**
1. **Data sent to DeepWiki** — What document data or PII could be transmitted to the third-party MCP server?
2. **Opt-in enforcement** — Is the consent toggle enforced server-side or only in UI?
3. **Guardrail effectiveness** — Test whether security guardrails can be bypassed via prompt injection
4. **Network egress** — What Lambda functions have internet access to reach DeepWiki?

---

### 3.7 Lambda Hook Inference (Custom LLM Integration) — v0.4.15

**Security Impact:** 🔴 New Attack Surface

**Description:** Allows customers to provide custom Lambda functions that are invoked during any pipeline step (OCR, Classification, Extraction, Assessment, Summarization). The Lambda receives Converse API-compatible payloads including document content.

**Security Footprint Changes:**
- **Customer Lambda invocation** — IDP system invokes customer-owned Lambda functions
- **`GENAIIDP-` naming convention** — IAM permissions scoped to functions with this prefix
- **S3 image references** — Inline image bytes uploaded to S3 and replaced with `s3Location` references (avoids 6MB Lambda payload limit)
- **Metering integration** — Token usage from Lambda responses tracked
- **Per-step granularity** — Configurable independently for each pipeline step

**Key Review Areas:**
1. **IAM scoping** — Verify the `GENAIIDP-` prefix scoping is enforced and cannot be bypassed
2. **Payload content** — Document text, images, and metadata are sent to customer Lambda — confirm no unintended data leakage
3. **Response injection** — Can a malicious Lambda response manipulate downstream processing?
4. **S3 presigned URLs** — Are S3 image references properly scoped and time-limited?
5. **Error handling** — What happens if a customer Lambda returns malformed data?

---

### 3.8 Custom Model Fine-Tuning — v0.5.2

**Security Impact:** 🔴 New Attack Surface

**Description:** Fine-tune Amazon Nova models using processed IDP documents directly from the Web UI. Creates training data in JSONL format, submits fine-tuning jobs to Bedrock, and deploys custom models.

**Security Footprint Changes:**
- **New Step Functions workflow** — Orchestrates fine-tuning job lifecycle
- **Training data generation** — Processed documents converted to JSONL training format
- **Bedrock fine-tuning API access** — New IAM permissions for `bedrock:CreateModelCustomizationJob`, etc.
- **Custom model deployment** — Fine-tuned models stored in Bedrock and usable in extraction workflows
- **New GraphQL APIs** — Full CRUD for fine-tuning jobs

**GraphQL API Changes:**
- New mutations: `createFinetuningJob`, `deleteFinetuningJob` (Admin, Author)
- New queries: `listFinetuningJobs`, `getFinetuningJob`, `listFinetuningModels` (Admin, Author)
- New enum: `FinetuningJobStatus`

**Key Review Areas:**
1. **Training data access** — Who can access the generated JSONL training data in S3?
2. **Fine-tuning job authorization** — Can non-Admin/Author roles trigger fine-tuning?
3. **Custom model access** — Are fine-tuned models accessible only within the stack?
4. **Data in training** — Could sensitive document data persist in fine-tuned model weights?

---

### 3.9 User Management — v0.4.11

**Security Impact:** 🔴 New Attack Surface

**Description:** Admin users can create, manage, and delete additional Admin and Reviewer accounts through a new User Management page.

**Security Footprint Changes:**
- **Cognito user lifecycle** — Admin-initiated user creation/deletion
- **Role assignment** — Users assigned to Cognito groups (Admin, Reviewer; later expanded to Author, Viewer)
- **Users Table** — DynamoDB table tracking user metadata
- **Self-service profile** — Users can view their own profile

**GraphQL API Changes:**
- New mutations: `createUser`, `updateUser`, `deleteUser` (Admin only)
- New queries: `listUsers` (Admin only), `getMyProfile` (all authenticated)
- New mutation: `updateMyProfile` (all authenticated)

**Key Review Areas:**
1. **Admin privilege escalation** — Can an Admin create another Admin account? (Expected: yes — verify this is intentional)
2. **Self-modification** — Can a user change their own role via `updateMyProfile`?
3. **Cognito group manipulation** — Verify user group assignment is server-side only
4. **User deletion cleanup** — Are all resources (sessions, documents) cleaned up on user deletion?

---

### 3.10 ALB + S3 VPC Hosting Mode — v0.5.3

**Security Impact:** 🔴 New Attack Surface

**Description:** Alternative web UI hosting using Application Load Balancer with S3 VPC Interface Endpoint for environments that require VPC-based hosting (private networks, regulated environments).

**Security Footprint Changes:**
- **New `WebUIHosting` parameter** — `CloudFront` (default) or `ALB`; mutually exclusive resource creation
- **ALB nested stack** (`nested/alb-hosting/template.yaml`) — ALB, S3 Interface VPC Endpoint, security groups, custom resource Lambdas
- **TLS 1.3 enforcement** — ALB listener requires TLS 1.3
- **Access logging** — ALB access logs enabled
- **Scoped VPC endpoint policy** — `s3:GetObject`/`s3:ListBucket` only
- **Multi-CIDR security group ingress** — Manages ingress from multiple VPC CIDRs
- **Self-signed certificate support** — `scripts/generate_self_signed_cert.sh` for demo/testing
- **Custom resource Lambdas** — VPC CIDR lookup and target registration

**Key Review Areas:**
1. **ALB exposure** — Is the ALB internal-only or internet-facing? Verify security group rules
2. **S3 VPC Endpoint policy** — Verify the endpoint policy doesn't allow access to other S3 buckets
3. **TLS configuration** — Verify TLS 1.3 enforcement and certificate management
4. **Self-signed cert usage** — Ensure self-signed certs are not used in production
5. **VPC CIDR ingress** — Verify security group rules are correctly scoped

---

## 4. Moderate-Impact Features

### 4.1 Configuration Versioning System — v0.4.15

**Security Impact:** ⚠️ Changed Footprint

**Description:** Manage multiple named configuration versions as complete, self-contained snapshots. One version is marked active for processing.

**GraphQL API Changes:**
- Modified mutations: `updateConfiguration` now supports `saveAsVersion` and `saveAsDefault` operations
- New mutations: `deleteConfigVersion`, `activateConfigVersion` (Admin only per v0.5.3 hardening)
- Version metadata: `config-version` S3 metadata on uploaded documents

**Key Review Areas:**
1. **Version deletion protection** — Verify active/default versions cannot be deleted
2. **Save as Version/Default** — Confirm server-side Admin-only enforcement (was UI-only before v0.5.3)
3. **Config version in S3 metadata** — Can this be manipulated during upload to process with a different config?

---

### 4.2 Built-in Human-in-the-Loop (HITL) Review System — v0.4.11

**Security Impact:** ⚠️ Changed Footprint

**Description:** Replaced Amazon SageMaker A2I with a built-in HITL review system. Introduced review ownership model with Start/Release/Skip/Complete review workflow.

**Security Footprint Changes:**
- **Removed** SageMaker A2I resources (Flow Definition, Human Task UI, Workteam)
- **Removed** A2I-related Lambda functions and CloudFormation parameters
- **Added** review ownership model with concurrent edit prevention
- **Added** `HITLPendingReview` DynamoDB attribute for server-side filtering

**GraphQL API Changes:**
- New/modified mutations: `startReview`, `releaseReview`, `completeReview`, `skipAllReviews` (Admin + Reviewer)
- Review status fields: `ReviewStatus`, `ReviewOwner`, `ReviewCompletedBy`
- `updateDocumentStatus` mutation for lightweight status-only updates

**Key Review Areas:**
1. **Review ownership bypass** — Can a user edit a document claimed by another reviewer?
2. **Skip All Reviews** — Is this properly restricted to Admin role?
3. **HITL status manipulation** — Can a user directly set review status via `updateDocumentStatus`?

---

### 4.3 Test Studio — v0.4.6

**Security Impact:** ⚠️ Changed Footprint

**Description:** Unified web interface for managing test sets, running tests, and analyzing results. Test sets can be created from zip uploads or file patterns.

**Security Footprint Changes:**
- **New Lambda functions** — TestRunnerResolver, TestResultsResolver, TestSetResolver, DeleteTestsResolver
- **SQS queue** — For test execution queuing
- **HuggingFace dataset downloads** — Auto-deployed test sets download from external sources during stack deployment
- **Zip upload** — Presigned URL-based zip upload with automatic extraction

**GraphQL API Changes:**
- New mutations: `createTestSet`, `deleteTestSet`, `runTest`, `deleteTestRun` (Admin, Author)
- New queries: `listTestSets`, `getTestSet`, `listTestRuns`, `getTestRun`, `getTestResults`, `getTestComparison` (Admin, Author)
- New query: `getDocumentCount` (all authenticated)

**Key Review Areas:**
1. **Zip upload** — Path traversal in zip extraction? File type validation?
2. **HuggingFace downloads** — Are downloads validated/pinned? Supply chain risk?
3. **Test data access** — Can test set data (which may include ground truth/PII) be accessed by unauthorized roles?

---

### 4.4 IDP SDK & CLI — v0.3.20, v0.4.12, v0.5.3

**Security Impact:** ⚠️ Changed Footprint

**Description:** Python SDK (`idp_sdk`) and CLI (`idp-cli`) providing programmatic access to all IDP operations. Major refactoring in v0.5.3 introduced `IDPClient` with typed namespace access.

**Security Footprint Changes:**
- **New access path** — SDK/CLI bypass the Web UI but use same backend APIs
- **AWS credentials** — SDK/CLI use AWS credentials directly (no Cognito)
- **CLI commands** — `process`, `reprocess`, `deploy`, `delete`, `config-*`, `discover`, `chat`, `load-test`, `stop-workflows`, `delete-documents`
- **`--profile` parameter** — AWS profile selection

**Key Review Areas:**
1. **Authentication path** — SDK/CLI use IAM credentials, not Cognito. How does RBAC apply?
2. **`delete-documents`** — Wildcard pattern support (`--pattern`) — verify scope is limited
3. **`stop-workflows`** — Batch workflow termination — verify authorization
4. **`load-test`** — Could be used to generate high volumes — DoS potential?

---

### 4.5 IDP MCP Connector — v0.5.3

**Security Impact:** ⚠️ Changed Footprint

**Description:** Local package bridging coding assistants (Cline, Kiro) to IDP MCP Server with automatic Cognito authentication and dynamic tool discovery.

**Key Review Areas:**
1. **Cognito credential caching** — How are tokens stored locally?
2. **Tool discovery** — What prevents unauthorized tool access through the connector?

---

### 4.6 Multi-Document Discovery — v0.5.5

**Security Impact:** ⚠️ Changed Footprint

**Description:** Automatically discover document classes from a collection of documents. Supports S3 path input and zip upload via presigned URLs.

**GraphQL API Changes:**
- New mutations: `startMultiDocDiscovery`, `deleteMultiDocDiscoveryJob` (Admin, Author)
- New queries: `listMultiDocDiscoveryJobs`, `getMultiDocDiscoveryJob` (Admin, Author)

**Key Review Areas:**
1. **S3 path input** — Can a user specify an S3 path outside the stack's buckets?
2. **Presigned URL upload** — Scope and expiration of presigned URLs?
3. **Discovered schemas saved to DynamoDB** — Input validation on schema content?

---

### 4.7 Discovery UX Enhancements (Multi-Section, Auto-Detect) — v0.5.3

**Security Impact:** ⚠️ Changed Footprint

**Description:** Added multi-section package discovery with AI auto-detect, page range selection, and class name hints.

**GraphQL API Changes:**
- New mutation: `autoDetectSections` (Admin, Author)
- Modified: `uploadDiscoveryDocument` now accepts `pageRanges`/`pageLabels`
- New mutation: `deleteDiscoveryJob` (Admin, Author)
- New fields on job types: `pageRange`, `discoveredClassName`, `statusMessage`

**Key Review Areas:**
1. **Auto-detect sections** — LLM-based analysis — prompt injection via document content?
2. **Page range validation** — Are page ranges validated server-side?

---

### 4.8 Rule Validation — v0.4.13

**Security Impact:** ⚠️ Changed Footprint

**Description:** Automated validation of extracted data against configurable business rules using LLM. Extended to BDA mode in v0.5.0.

**Security Footprint Changes:**
- **New Step Functions integration** — Parallel processing in workflow
- **LLM-based rule evaluation** — Document data sent to LLM with business rules

**Key Review Areas:**
1. **Rule injection** — Can business rules in configuration be crafted to extract/exfiltrate data?
2. **Concurrent processing** — Resource limits for parallel rule validation

---

### 4.9 MLflow Experiment Tracking Integration — v0.5.4

**Security Impact:** ⚠️ Changed Footprint

**Description:** Optional integration with Amazon SageMaker MLflow for automated test run logging. Fire-and-forget async invocation.

**Security Footprint Changes:**
- **`EnableMLflow` parameter** — Creates SageMaker MLflow tracking server when enabled
- **Async Lambda invocation** — Test results, configuration snapshots, and metrics sent to MLflow
- **Zero resources when disabled**

**Key Review Areas:**
1. **Data in MLflow** — Configuration snapshots and test metrics may contain sensitive schema information
2. **MLflow access control** — Who can access the MLflow tracking server?

---

### 4.10 Abort Workflow — v0.4.9

**Security Impact:** ⚠️ Changed Footprint

**GraphQL API Changes:**
- New mutation: `abortWorkflow` (Admin, Author)

**Key Review Areas:**
1. **Authorization** — Can a non-Admin/Author abort workflows?
2. **DoS potential** — Mass workflow abortion

---

### 4.11 Scalable Document List (GSI-Based) — v0.5.1

**Security Impact:** ⚠️ Changed Footprint

**Description:** New DynamoDB GSI (`TypeDateIndex`) for efficient document listing, replacing full table scans.

**GraphQL API Changes:**
- New query: `listDocuments` (paginated, GSI-based) — all authenticated
- New query: `getDocumentCount` — all authenticated
- GSI attribute backfill mechanism via Step Functions state machine

**Key Review Areas:**
1. **Server-side pagination** — Verify pagination tokens cannot be manipulated
2. **GSI projections** — Verify the 20 projected attributes don't include sensitive data not meant for list views

---

### 4.12 Custom Date Range Query — v0.4.15

**Security Impact:** ⚠️ Changed Footprint

**GraphQL API Changes:**
- New query: `listDocumentsByDateRange` — uses new Lambda resolver with server-side shard iteration
- 365-day maximum enforced in UI

**Key Review Areas:**
1. **Date range limits** — Is the 365-day max enforced server-side?
2. **RBAC filtering** — Added in v0.5.3 hardening; verify Reviewer filtering is applied

---

### 4.13 Managed Configuration Versions — v0.5.3

**Security Impact:** ✅ Minimal Impact (security improvement)

**Description:** Stack-managed config versions (`managed: true`) with save/delete disabled in UI and API.

**Key Review Areas:**
1. **Managed flag bypass** — Can `managed: true` configs be modified via direct API calls?

---

### 4.14 Prompt Preview — v0.5.5

**Security Impact:** ✅ Minimal Impact

**Description:** UI-only feature showing actual prompts sent to LLM for each processing step. Read-only.

**Key Review Areas:**
1. **Sensitive data in prompts** — Preview shows real schema values; verify this is role-restricted (Admin, Author)

---

### 4.15 Agentic Extraction with S3 Checkpointing — v0.5.4, v0.5.5

**Security Impact:** ⚠️ Changed Footprint

**Description:** Incremental S3 checkpointing for agentic extraction, enabling resume-from-checkpoint on Lambda timeout.

**Security Footprint Changes:**
- **S3 checkpoint files** — Extraction state saved to S3 after each tool call
- **Thread-safe state management** — `contextvars.ContextVar` for concurrent extraction

**Key Review Areas:**
1. **Checkpoint data** — Partial extraction results stored in S3 — access controls?
2. **Resume integrity** — Can checkpoint data be tampered with to alter extraction results?

---

## 5. Lower-Impact Changes

### 5.1 Unified Pattern (BDA + Pipeline Merge) — v0.5.0

**Security Impact:** ✅ Minimal Impact

**Description:** Merged Pattern-1 (BDA) and Pattern-2 (Pipeline) into single deployment. `use_bda` toggle switches modes at runtime.

**Changes:** Primarily architectural consolidation. No new external interfaces. Removed `Pattern1BDAProjectArn` CloudFormation parameter. Replaced PyMuPDF (AGPL) with pypdfium2 (Apache/BSD) for license compliance.

---

### 5.2 S3 Vectors for Knowledge Base — v0.3.16

**Security Impact:** ⚠️ Changed Footprint

**Description:** S3 Vectors as alternative vector store to OpenSearch Serverless. Custom resource Lambda for S3 vector bucket/index management.

**Changes:** New KMS key policy with S3 Vectors service principal (`indexing.s3vectors.${AWS::URLSuffix}`). Fixed GovCloud incompatibility where this service principal doesn't exist.

---

### 5.3 Post-Processing Lambda Hook Decompression — v0.4.7

**Security Impact:** ✅ Minimal Impact

**Description:** New `PostProcessingDecompressor` Lambda intercepts EventBridge events, decompresses documents before invoking custom post-processors.

---

### 5.4 Containerized Lambda Deployments — v0.3.20, v0.4.2

**Security Impact:** ✅ Minimal Impact

**Description:** Migrated Lambda functions from zip to Docker image deployments. Increases package size limit from 250MB to 10GB.

**Note:** Lambda images pushed to ECR with automated cleanup. Optional ECR enhanced scanning support added in v0.4.1.

---

### 5.5 Error Analyzer Agent — v0.3.19

**Security Impact:** ⚠️ Changed Footprint

**Description:** AI-powered troubleshooting agent using Claude Sonnet with 8 specialized tools for diagnosing failures.

**Changes:** New Lambda functions with access to CloudWatch Logs, DynamoDB tracking table, Step Functions. X-Ray integration added in v0.3.21.

**GraphQL API Changes:**
- New mutation: `createAgentJob` (all authenticated) — for troubleshoot action
- New query: `getAgentJob` (all authenticated)
- New subscription: `onAgentJobComplete`

---

### 5.6 Agent Analysis (Analytics Agent) — v0.3.10

**Security Impact:** ⚠️ Changed Footprint

**Description:** Natural language querying of processed document data via Athena SQL, with code execution in isolated Bedrock AgentCore sandboxes.

**Note:** Introduced before v0.3.15 as a feature, but expanded through v0.3.17 (schema optimization) and v0.4.4 (UX improvements). Analytics Agent has access to the Athena reporting database.

---

### 5.7 Chandra OCR Lambda Hook Sample — v0.5.5

**Security Impact:** ✅ Minimal Impact

**Description:** Sample Lambda hook integrating Chandra OCR. Uses external Datalab hosted API.

**Note:** Sample code only — not deployed with the stack. Users must deploy separately.

---

### 5.8 Standard Class Catalog — v0.5.2

**Security Impact:** ✅ Minimal Impact

**Description:** 35 pre-built document type templates derived from AWS BDA standard blueprints. Imported classes are fully editable.

---

### 5.9 Third-Party Model Support — v0.5.1

**Security Impact:** ✅ Minimal Impact

**Description:** Added Meta Llama 4, Google Gemma 3, NVIDIA Nemotron models. Document data sent to Bedrock-hosted versions of these models.

---

### 5.10 Bedrock Service Tiers — v0.4.9

**Security Impact:** ✅ Minimal Impact

**Description:** Priority/Standard/Flex service tiers via model ID suffixes.

---

### 5.11 Python 3.12+ Requirement — v0.5.2

**Security Impact:** ✅ Minimal Impact (security improvement)

**Description:** Updated minimum Python from 3.10 to 3.12 to address security vulnerabilities in transitive dependencies.

---

### 5.12 Visual Document Editor Enhancements — v0.4.13

**Security Impact:** ✅ Minimal Impact

**Description:** Inline field editing with S3 save, evaluation baseline editing, save & reprocess workflow.

**Note:** Edit operations save directly to S3 and trigger reprocessing — verify authorization on these save operations.

---

### 5.13 Section-Level DynamoDB Updates — v0.4.13

**Security Impact:** ⚠️ Changed Footprint

**GraphQL API Changes:**
- New mutation: `updateDocumentStatus` — lightweight status-only (~500 bytes vs ~100KB)
- New mutation: `updateDocumentSection` — atomic section update using `SET Sections[index]`
- Both trigger `onUpdateDocument` subscription

**Key Review Areas:**
1. **Direct status manipulation** — Can these mutations be called by unauthorized users to change document status?

---

### 5.14 BDA/IDP Sync — v0.4.10, v0.4.14

**Security Impact:** ✅ Minimal Impact

**Description:** Bidirectional synchronization between BDA blueprints and IDP classes. Replace/Merge modes.

---

### 5.15 Pricing Configuration UI — v0.4.10

**Security Impact:** ⚠️ Changed Footprint

**GraphQL API Changes:**
- New mutations: `updatePricing`, `importPricing` (Admin only)
- New query: `getPricing` (Admin, Author, Viewer)

---

### 5.16 Stickler-Based Evaluation — v0.4.2

**Security Impact:** ✅ Minimal Impact

**Description:** Migrated evaluation to AWS Labs Stickler library. Internal processing change.

---

### 5.17 JSON Schema Format for Class Definitions — v0.4.0

**Security Impact:** ✅ Minimal Impact

**Description:** Configuration format migrated to JSON Schema Draft 2020-12. Auto-migration from legacy format.

---

### 5.18 DynamoDB Config Compression — v0.4.16

**Security Impact:** ✅ Minimal Impact

**Description:** Config data gzip-compressed before DynamoDB storage. Supports 3,000+ document classes. Backward compatible.

---

## 6. Complete GraphQL API Changes Summary

### 6.1 New Mutations

| Mutation | Version | Auth (cognito_groups) | Purpose |
|----------|---------|----------------------|---------|
| `sendAgentChatMessage` | v0.4.0 | Admin, Author, Reviewer, Viewer | Send message in agent chat |
| `deleteAgentChatSession` | v0.4.0 | Admin, Author, Reviewer, Viewer | Delete chat session |
| `createAgentJob` | v0.3.19 | Admin, Author, Reviewer, Viewer | Trigger error analysis / troubleshoot |
| `abortWorkflow` | v0.4.9 | Admin, Author | Stop in-progress document workflow |
| `updateDocumentStatus` | v0.4.13 | `@aws_iam` (internal only) | Lightweight status update |
| `updateDocumentSection` | v0.4.13 | `@aws_iam` (internal only) | Atomic section update |
| `startReview` | v0.4.11 | Admin, Reviewer | Claim document for review |
| `releaseReview` | v0.4.11 | Admin, Reviewer | Release review claim |
| `completeReview` | v0.4.11 | Admin, Reviewer | Complete section review |
| `skipAllReviews` | v0.4.11 | Admin, Reviewer | Skip all pending reviews |
| `createUser` | v0.4.11 | Admin | Create Cognito user |
| `updateUser` | v0.4.11 | Admin | Update user profile/role |
| `deleteUser` | v0.4.11 | Admin | Delete Cognito user |
| `updateMyProfile` | v0.4.11 | Admin, Author, Reviewer, Viewer | Update own profile |
| `createTestSet` | v0.4.6 | Admin, Author | Create test set |
| `deleteTestSet` | v0.4.6 | Admin, Author | Delete test set |
| `runTest` | v0.4.6 | Admin, Author | Execute test run |
| `deleteTestRun` | v0.4.6 | Admin, Author | Delete test results |
| `updatePricing` | v0.4.10 | Admin | Update pricing config |
| `importPricing` | v0.4.10 | Admin | Import pricing config |
| `deleteConfigVersion` | v0.4.15 | Admin | Delete config version |
| `activateConfigVersion` | v0.4.15 | Admin | Set active config version |
| `uploadDiscoveryDocument` | v0.3.15+ | Admin, Author | Upload document for discovery (enhanced with pageRanges in v0.5.3) |
| `autoDetectSections` | v0.5.3 | Admin, Author | AI auto-detect document sections |
| `deleteDiscoveryJob` | v0.5.3 | Admin, Author | Delete discovery job |
| `createFinetuningJob` | v0.5.2 | Admin, Author | Start model fine-tuning |
| `deleteFinetuningJob` | v0.5.2 | Admin, Author | Delete fine-tuning job |
| `startMultiDocDiscovery` | v0.5.5 | Admin, Author | Start multi-document discovery |
| `deleteMultiDocDiscoveryJob` | v0.5.5 | Admin, Author | Delete multi-doc discovery job |
| `processChanges` | v0.4.14 | Admin, Reviewer | Save edits and reprocess |
| `syncBda` | v0.4.10 | Admin, Author | Sync BDA blueprints |

### 6.2 New Queries

| Query | Version | Auth (cognito_groups) | Purpose |
|-------|---------|----------------------|---------|
| `listAgentChatSessions` | v0.4.0 | Admin, Author, Viewer | List chat sessions |
| `getAgentChatSession` | v0.4.0 | Admin, Author, Viewer | Get chat session details |
| `getAgentJob` | v0.3.19 | Admin, Author, Reviewer, Viewer | Get error analysis job |
| `getAgentQuerySystem` | v0.4.0 | Admin, Author, Viewer | Get agent config |
| `listDocuments` | v0.5.1 | Admin, Author, Reviewer, Viewer | GSI-based document list |
| `listDocumentsByDateRange` | v0.4.15 | Admin, Author, Reviewer, Viewer | Date range document query |
| `getDocumentCount` | v0.5.1 | Admin, Author, Reviewer, Viewer | Document count |
| `listUsers` | v0.4.11 | Admin | List Cognito users |
| `getMyProfile` | v0.4.11 | Admin, Author, Reviewer, Viewer | Get own profile |
| `listTestSets` | v0.4.6 | Admin, Author | List test sets |
| `getTestSet` | v0.4.6 | Admin, Author | Get test set details |
| `listTestRuns` | v0.4.6 | Admin, Author | List test runs |
| `getTestRun` | v0.4.6 | Admin, Author | Get test run details |
| `getTestResults` | v0.4.6 | Admin, Author | Get test results |
| `getTestComparison` | v0.4.6 | Admin, Author | Compare test runs |
| `getPricing` | v0.4.10 | Admin, Author, Viewer | Get pricing config |
| `getCapacityPlan` | v0.4.16 | Admin, Author | Get capacity plan |
| `getConfigLibrary` | v0.4.8 | Admin, Author, Viewer | List config library |
| `getConfigLibraryReadme` | v0.4.8 | Admin, Author, Viewer | Get config library README |
| `listDiscoveryJobs` | v0.3.15+ | Admin, Author | List discovery jobs |
| `getDiscoveryJob` | v0.3.15+ | Admin, Author | Get discovery job |
| `listFinetuningJobs` | v0.5.2 | Admin, Author | List fine-tuning jobs |
| `getFinetuningJob` | v0.5.2 | Admin, Author | Get fine-tuning job |
| `listFinetuningModels` | v0.5.2 | Admin, Author | List fine-tuned models |
| `listMultiDocDiscoveryJobs` | v0.5.5 | Admin, Author | List multi-doc discovery jobs |
| `getMultiDocDiscoveryJob` | v0.5.5 | Admin, Author | Get multi-doc discovery job |

### 6.3 New Subscriptions

| Subscription | Version | Auth | Purpose |
|--------------|---------|------|---------|
| `onAgentChatMessageUpdate` | v0.4.0 | All authenticated | Real-time chat streaming |
| `onAgentJobComplete` | v0.3.19 | All authenticated | Error analysis completion |
| `onDiscoveryJobStatusChange` | v0.3.15+ | All authenticated | Discovery job progress |

**Note:** Pre-existing subscriptions `onCreateDocument` and `onUpdateDocument` were not changed but now carry additional fields (review status, config version, etc.).

### 6.4 Auth Directive Coverage

The GraphQL schema uses two auth mechanisms:
- **`@aws_auth(cognito_groups: [...])`** — For browser-based users authenticated via Cognito
- **`@aws_iam`** — For internal Lambda-to-AppSync calls (e.g., workflow status updates)

**Dual-directive operations** (both `@aws_auth` and `@aws_iam`):
- `createDocument`, `updateDocument`, `deleteDocument` — Internal Lambda functions create/update documents
- `updateDocumentStatus`, `updateDocumentSection` — Workflow Lambda functions update status

**⚠️ Key concern:** Operations with both `@aws_auth` and `@aws_iam` can be called either by authenticated users (with role restrictions) or by IAM-authenticated callers (Lambda functions). Verify that IAM-authenticated callers are properly scoped and cannot be abused.

---

## 7. Infrastructure Changes Summary

### 7.1 New Lambda Functions

| Function | Version | Purpose | Notable Permissions |
|----------|---------|---------|-------------------|
| `AgentCoreMCPHandlerFunction` | v0.4.6 | MCP protocol handler | Athena, DynamoDB, Bedrock |
| `AgentCoreGatewayManagerFunction` | v0.4.6 | Gateway lifecycle management | AgentCore, IAM |
| `AgentCompanionChatFunction` | v0.4.0 | Multi-agent chat orchestrator | Bedrock, DynamoDB, Lambda |
| `ErrorAnalyzerFunction` | v0.3.19 | AI troubleshooting agent | CloudWatch Logs, X-Ray, DynamoDB, Step Functions |
| `TestRunnerResolverFunction` | v0.4.6 | Test execution | S3, DynamoDB, SQS |
| `TestResultsResolverFunction` | v0.4.6 | Test results | S3, DynamoDB, Athena |
| `TestSetResolverFunction` | v0.4.6 | Test set management | S3, DynamoDB |
| `DeleteTestsResolverFunction` | v0.4.6 | Test deletion | S3, DynamoDB |
| `UserManagementFunction` | v0.4.11 | Cognito user CRUD | Cognito |
| `PostProcessingDecompressor` | v0.4.7 | Document decompression | S3, Lambda |
| `FinetuningResolverFunction` | v0.5.2 | Fine-tuning job management | Bedrock, S3 |
| `BlueprintOptimizationFunction` | v0.5.4 | BDA blueprint optimization | Bedrock, S3 |
| `MultiDocDiscoveryFunction` | v0.5.5 | Multi-doc discovery | S3, DynamoDB, Bedrock |
| `DiscoveryProcessorFunction` | v0.3.15+ | Discovery processing | S3, Bedrock |
| `RuleValidationFunction` | v0.4.13 | Business rule validation | Bedrock |
| `MLflowLoggerFunction` | v0.5.4 | MLflow experiment logging | SageMaker MLflow |
| `GSIBackfillStateMachine` | v0.5.1 | DynamoDB GSI backfill | DynamoDB |
| Various test set deployers | v0.4.6+ | Deploy benchmark datasets | S3, DynamoDB |
| ALB hosting Lambdas | v0.5.3 | VPC CIDR lookup, target registration | EC2, ELB |

### 7.2 New DynamoDB Tables / GSIs

| Resource | Version | Purpose |
|----------|---------|---------|
| `TypeDateIndex` GSI | v0.5.1 | Efficient document/test listing by type and date |
| Agent Table (DynamoDB) | v0.4.0 | Conversation history for agent chat |
| Users Table entries | v0.4.11 | User metadata for RBAC |
| `HITLPendingReview` attribute | v0.4.11 | Server-side filtering for Reviewer role |
| `ItemType` attribute | v0.5.1 | GSI partition key (document, testrun, testset) |
| `managed` flag on config versions | v0.5.3 | Stack-managed config protection |

### 7.3 New IAM Roles

| Role | Version | Purpose |
|------|---------|---------|
| `AgentCoreGatewayExecutionRole` | v0.4.6 | AgentCore Gateway execution |
| Various resolver function roles | v0.4.6+ | Per-function IAM roles for new Lambda functions |
| `CloudFormation Service Role` (sample) | v0.3.16 | Delegated deployment access |

### 7.4 New CloudFormation Parameters

| Parameter | Version | Default | Purpose |
|-----------|---------|---------|---------|
| `EnableMCP` | v0.4.6 | `true` | Enable/disable MCP integration |
| `WebUIHosting` | v0.5.3 | `CloudFront` | `CloudFront` or `ALB` hosting mode |
| `EnableMLflow` | v0.5.4 | `false` | Enable MLflow experiment tracking |
| `KnowledgeBaseVectorStore` | v0.3.16 | `S3_VECTORS` (changed in v0.4.6) | Vector store backend |
| `DocumentSectionsCrawlerFrequency` | v0.3.7+ | `daily` | Glue crawler schedule |

**Removed parameters:**
- `EnableHITL` (v0.4.11 — replaced by config-driven setting)
- `PrivateWorkteamArn` (v0.4.11 — A2I removed)
- `Pattern1BDAProjectArn` (v0.5.0 — now managed post-deployment)
- `IsSummarizationEnabled` (v0.3.12 — replaced by config-driven setting)
- `IsAssessmentEnabled` (v0.3.12 — replaced by config-driven setting)

### 7.5 Nested Stack Architecture Changes

| Nested Stack | Version | Purpose |
|-------------|---------|---------|
| `nested/appsync/template.yaml` | v0.4.11 | 130 AppSync resources extracted from main template |
| `nested/alb-hosting/template.yaml` | v0.5.3 | ALB + S3 VPC Endpoint hosting |
| `nested/bedrockkb/` | moved in v0.4.11 | Knowledge Base resources |
| `nested/multi-doc-discovery/` | v0.5.5 | Multi-document discovery resources |

---

## 8. Security Fixes Included in Scope

These security-relevant fixes were made between v0.3.16 and v0.5.5:

| Fix | Version | Description |
|-----|---------|-------------|
| **XSS vulnerability** | v0.3.12 | Fixed `innerHTML` usage with user-controlled data in `FileViewer` component |
| **Log level security** | v0.3.16 | Recommendation to set LogLevel to WARN/ERROR in production to prevent PII logging |
| **Permissions boundary** | v0.3.12, v0.4.1 | Added permissions boundary support for all roles; fixed regressions |
| **S3 presigned URL encoding** | v0.5.3 | Fixed S3-safe URI encoding for document IDs with special characters |
| **RBAC gap fixes** | v0.5.3 | 20+ queries missing `@aws_auth` directives; server-side role enforcement for `updateConfiguration` |
| **HITL overwrite fix** | v0.5.4 | Start Review no longer overwrites document sections |
| **Config compression** | v0.4.16 | Fixed 400KB DynamoDB limit that could be used to DoS config storage |
| **GovCloud resource removal** | v0.4.7, v0.5.3 | Fixed unresolved references and dependency errors in GovCloud templates |
| **HuggingFace download pinning** | v0.3.12 | Added revision pinning to prevent supply chain attacks |
| **ECR scanning** | v0.4.1 | Optional ECR enhanced scanning for Lambda container images |

---

## 9. Recommended Pen Test Focus Areas

Based on the analysis above, we recommend the pen test team prioritize the following areas:

### Priority 1: Authentication & Authorization
1. **RBAC enforcement completeness** — Systematically test every GraphQL mutation and query with each role (Admin, Author, Reviewer, Viewer) to verify `@aws_auth` directives are correctly enforced
2. **Privilege escalation** — Attempt to modify Cognito group claims, manipulate JWT tokens, or use `@aws_iam` paths to bypass RBAC
3. **Server-side filtering** — Verify Reviewer role cannot access documents outside HITL scope through `listDocuments`, `listDocumentsByDateRange`, or direct `getDocument` queries
4. **User Management** — Test `createUser`/`updateUser` for role escalation (e.g., creating Admin from Author context)
5. **Config version scoping** — Verify `allowedConfigVersions` is enforced server-side

### Priority 2: External Integrations
6. **MCP/AgentCore Gateway** — Test OAuth 2.0 flow, token validation, endpoint exposure, and tool authorization
7. **External MCP Agent** — Test for SSRF, data exfiltration, and tool injection through external MCP servers
8. **Code Intelligence (DeepWiki)** — Verify data sent to third-party service, test guardrail bypass
9. **Lambda Hook Inference** — Test `GENAIIDP-` naming enforcement, response injection, S3 reference scoping

### Priority 3: Data Access & Input Validation
10. **Agent Chat prompt injection** — Test for unauthorized data access through conversational AI (SQL injection via analytics agent, cross-session data access)
11. **GraphQL subscription isolation** — Verify users cannot subscribe to other users' chat messages or document updates
12. **Discovery/Multi-Doc upload** — Test presigned URL scope, zip path traversal, S3 path input validation
13. **Test Studio zip upload** — Test for path traversal, malicious file types, oversized uploads
14. **Fine-tuning data access** — Verify training data (JSONL) access controls

### Priority 4: Infrastructure
15. **ALB hosting security** — Test ALB exposure, security group rules, S3 VPC Endpoint policy scope, TLS configuration
16. **DynamoDB GSI data exposure** — Verify projected attributes in TypeDateIndex don't expose sensitive data
17. **S3 checkpoint integrity** — Test agentic extraction checkpoint tampering
18. **CloudWatch log content** — Verify production log levels don't expose PII/document content

### Priority 5: Availability
19. **Rate limiting** — Test for DoS through batch operations (`delete-documents` with wildcards, `load-test`, `stop-workflows`)
20. **Resource exhaustion** — Test fine-tuning job creation limits, concurrent discovery jobs, agent chat session limits

---

*Document prepared from CHANGELOG.md analysis (v0.3.16 through v0.5.5), GraphQL schema review (`nested/appsync/src/api/schema.graphql`), RBAC documentation (`docs/rbac.md`), and migration guide (`docs/migration-v04-to-v05.md`).*
