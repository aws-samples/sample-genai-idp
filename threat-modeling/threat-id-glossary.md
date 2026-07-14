# Threat ID Glossary

## Document Information

| Field | Value |
|-------|-------|
| **Document Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **Classification** | Internal |
| **Total Threat IDs** | 64 |

## 1. Threat ID Naming Convention

Threat IDs follow the pattern: `{CATEGORY}.T{NN}`

| Prefix | Category | Scope | Document |
|--------|----------|-------|----------|
| **PM** | Pipeline Mode | Textract + Bedrock processing threats | [pipeline-mode.md](architecture/pipeline-mode.md) |
| **BDA** | BDA Mode | Bedrock Data Automation processing threats | [architecture/bda-mode.md](architecture/bda-mode.md) |
| **AGT** | Agent Analysis | Multi-agent AI system threats | [feature-threats/agent-analysis.md](feature-threats/agent-analysis.md) |
| **CHAT** | Companion Chat | Conversational AI and streaming threats | [feature-threats/companion-chat.md](feature-threats/companion-chat.md) |
| **MCP** | MCP Integration | Model Context Protocol / external tool threats | [feature-threats/mcp-integration.md](feature-threats/mcp-integration.md) |
| **KB** | Knowledge Base | RAG and knowledge base threats | [feature-threats/knowledge-base.md](feature-threats/knowledge-base.md) |
| **AUTH** | Authentication/RBAC | Identity, authorization, and access threats | [feature-threats/rbac-authentication.md](feature-threats/rbac-authentication.md) |
| **SDK** | SDK/CLI | Programmatic access and automation threats | [feature-threats/sdk-cli.md](feature-threats/sdk-cli.md) |
| **HOOK** | Lambda Hooks | Customer-managed extensibility threats | [feature-threats/lambda-hooks.md](feature-threats/lambda-hooks.md) |
| **UI** | Web UI | Frontend and API threats | [feature-threats/web-ui.md](feature-threats/web-ui.md) |
| **RPT** | Reporting/Analytics | Data analytics, evaluation, and discovery threats | [feature-threats/reporting-analytics.md](feature-threats/reporting-analytics.md) |

## 2. Complete Threat ID Reference

### PM — Pipeline Mode (7 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| PM.T01 | Prompt injection via document content | Tampering, EoP | 9 (Very High) |
| PM.T02 | OCR manipulation / adversarial documents | Tampering | 4 (Medium) |
| PM.T03 | Model output manipulation / hallucination | Tampering, ID | 6 (High) |
| PM.T04 | Cross-step data poisoning | Tampering | 3 (Medium) |
| PM.T05 | Textract service dependency | DoS | 4 (Medium) |
| PM.T06 | Configuration tampering | Tampering, EoP | 8 (Critical) |
| PM.T07 | Few-shot example poisoning | Tampering | 2 (Low) |

### BDA — BDA Mode (5 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| BDA.T01 | BDA service opacity | ID, Repudiation | 4 (Medium) |
| BDA.T02 | BDA output format mapping errors | Tampering | 2 (Low) |
| BDA.T03 | BDA project configuration tampering | Tampering, EoP | 3 (Medium) |
| BDA.T04 | BDA service availability | DoS | 4 (Medium) |
| BDA.T05 | S3 cross-access via BDA | ID | 2 (Low) |

### AGT — Agent Analysis (5 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| AGT.T01 | SQL injection via natural language | Tampering, ID | 6 (High) |
| AGT.T02 | Arbitrary code execution via AgentCore | Tampering, EoP | 4 (Medium) |
| AGT.T03 | Agent routing manipulation | EoP | 4 (Medium) |
| AGT.T04 | Conversation history poisoning | Tampering | 2 (Low) |
| AGT.T05 | Cross-user data leakage via Athena | ID | 6 (High) |

### CHAT — Companion Chat (5 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| CHAT.T01 | Prompt injection via chat messages | Tampering, EoP | 9 (Very High) |
| CHAT.T02 | Conversation session hijacking | Spoofing, ID | 3 (Medium) |
| CHAT.T03 | Real-time subscription eavesdropping | ID | 3 (Medium) |
| CHAT.T04 | Conversation history data exposure | ID | 3 (Medium) |
| CHAT.T05 | Streaming response denial of service | DoS | 4 (Medium) |

### MCP — MCP Integration (6 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| MCP.T01 | Data exfiltration via MCP tools | ID | 8 (Critical) |
| MCP.T02 | Malicious tool injection | Tampering, EoP | 3 (Medium) |
| MCP.T03 | MCP response injection | Tampering | 6 (High) |
| MCP.T04 | Unauthorized external service access | Spoofing, EoP | 6 (High) |
| MCP.T05 | External MCP client abuse | Spoofing, DoS | 4 (Medium) |
| MCP.T06 | AgentCore gateway lifecycle attacks | DoS, Tampering | 2 (Low) |

### KB — Knowledge Base (4 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| KB.T01 | Knowledge Base poisoning | Tampering | 6 (High) |
| KB.T02 | RAG context injection | Tampering, EoP | 6 (High) |
| KB.T03 | OpenSearch Serverless data exposure | ID | 2 (Low) |
| KB.T04 | Excessive RAG retrieval | ID, DoS | 2 (Low) |

### AUTH — Authentication & RBAC (8 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| AUTH.T01 | Privilege escalation via group manipulation | EoP | 4 (Critical severity) |
| AUTH.T02 | JWT token theft / replay | Spoofing | 6 (High) |
| AUTH.T03 | Insufficient authorization granularity | EoP | 6 (High) |
| AUTH.T04 | Cognito user pool misconfiguration | Spoofing, ID | 3 (Medium) |
| AUTH.T05 | Refresh token abuse | Spoofing | 3 (Medium) |
| AUTH.T06 | Cross-tenant data access (multi-stack) | ID | 2 (Low) |
| AUTH.T07 | Config-version scope bypass (fail-open scope lookup) | EoP, ID | 6 (High) |
| AUTH.T08 | Silently-ignored schema authorization directives | EoP | 6 (High) |

### SDK — SDK/CLI (4 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| SDK.T01 | Credential exposure on developer machines | ID | 6 (High) |
| SDK.T02 | Insecure automation pipelines | Spoofing, ID | 6 (High) |
| SDK.T03 | SDK supply chain attack | Tampering | 3 (Medium) |
| SDK.T04 | Batch processing abuse | DoS | 4 (Medium) |

### HOOK — Lambda Hooks (5 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| HOOK.T01 | Malicious customer code execution | Tampering, EoP | 4 (Critical severity) |
| HOOK.T02 | Data exfiltration via post-processing hook | ID | 8 (Critical) |
| HOOK.T03 | Inference hook result tampering | Tampering | 3 (Medium) |
| HOOK.T04 | Hook Lambda timeout / failure cascade | DoS | 4 (Medium) |
| HOOK.T05 | Privilege escalation via hook IAM role | EoP | 3 (Medium) |

### UI — Web UI (5 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| UI.T01 | Cross-site scripting (XSS) | Tampering, ID | 6 (High) |
| UI.T02 | Presigned URL abuse | Spoofing, Tampering | 2 (Low) |
| UI.T03 | GraphQL API abuse | Tampering, ID | 4 (Medium) |
| UI.T04 | CloudFront distribution misconfiguration | ID | 2 (Low) |
| UI.T05 | Client-side configuration exposure | ID | 2 (Low) |

### RPT — Reporting & Analytics (6 threats)

| ID | Short Name | STRIDE | Risk |
|----|-----------|--------|------|
| RPT.T01 | Reporting data tampering | Tampering, Repudiation | 2 (Low) |
| RPT.T02 | Athena query data exposure | ID | 6 (High) |
| RPT.T03 | Glue catalog manipulation | Tampering | 2 (Low) |
| RPT.T04 | Evaluation data manipulation | Tampering | 3 (Medium) |
| RPT.T05 | Discovery prompt injection via sample docs | Tampering, EoP | 6 (High) |
| RPT.T06 | Test Studio uncontrolled processing costs | DoS | 4 (Medium) |

## 3. STRIDE Abbreviations

| Abbreviation | Full Name |
|-------------|-----------|
| **S** | Spoofing |
| **T** | Tampering |
| **R** | Repudiation |
| **ID** | Information Disclosure |
| **DoS** | Denial of Service |
| **EoP** | Elevation of Privilege |
