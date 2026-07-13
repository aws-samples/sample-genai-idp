# GenAI IDP Accelerator — Threat Model

## Document Information

| Field | Value |
|-------|-------|
| **Version** | 2.0 |
| **Last Updated** | 2025-03-19 |
| **System** | GenAI Intelligent Document Processing (IDP) Accelerator |
| **Architecture** | Unified (Pipeline + BDA modes) |
| **Methodology** | STRIDE |
| **Total Threats** | 64 |
| **Classification** | Internal |

## Overview

This directory contains the comprehensive threat model for the GenAI IDP Accelerator — a serverless intelligent document processing solution on AWS. The threat model covers the unified architecture, all processing modes, features, extensibility points, and integrations.

### Key Statistics

| Metric | Value |
|--------|-------|
| Threats identified | **62** |
| Critical risk | 5 |
| High risk | 19 |
| Medium risk | 28 |
| Low risk | 10 |
| Mitigated | 50 (81%) |
| Partially mitigated | 7 (11%) |
| Accepted | 5 (8%) |

## Directory Structure

```
threat-modeling/
├── README.md                                    ← You are here
├── threat-id-glossary.md                        ← All 62 threat IDs with cross-references
│
├── architecture/                                ← System architecture & data flows
│   ├── system-overview.md                       ← Unified architecture, components, trust boundaries
│   ├── data-flows.md                            ← All data flow diagrams with security analysis
│   ├── pipeline-mode.md                         ← Pipeline mode (Textract+Bedrock) threats
│   └── bda-mode.md                              ← BDA mode threats
│
├── feature-threats/                             ← Per-feature threat analysis
│   ├── agent-analysis.md                        ← Multi-agent AI system threats (AGT)
│   ├── companion-chat.md                        ← Conversational AI threats (CHAT)
│   ├── mcp-integration.md                       ← MCP / external tool threats (MCP)
│   ├── knowledge-base.md                        ← RAG / knowledge base threats (KB)
│   ├── rbac-authentication.md                   ← Auth & access control threats (AUTH)
│   ├── sdk-cli.md                               ← SDK/CLI programmatic access threats (SDK)
│   ├── lambda-hooks.md                          ← Customer extensibility threats (HOOK)
│   ├── web-ui.md                                ← Frontend & API threats (UI)
│   └── reporting-analytics.md                   ← Analytics, evaluation, discovery threats (RPT)
│
├── threat-analysis/                             ← Cross-cutting analysis
│   ├── stride-analysis.md                       ← Full STRIDE analysis across all components
│   └── threat-designer-results/
│       └── ai-generated-threats.md              ← AI-assisted threat identification notes
│
├── risk-assessment/
│   └── risk-matrix.md                           ← Complete risk register with scoring
│
└── deliverables/                                ← Executive deliverables
    ├── executive-summary.md                     ← Executive-level summary
    ├── implementation-guide.md                  ← Security controls implementation details
    └── threat-model.tc.json                     ← Threat Composer export (machine-readable)
```

## Quick Navigation

### Start Here
- **[Executive Summary](deliverables/executive-summary.md)** — High-level overview for stakeholders
- **[System Overview](architecture/system-overview.md)** — Architecture, components, and trust boundaries

### Architecture & Data Flows
- **[Data Flows](architecture/data-flows.md)** — All data flow diagrams with security analysis
- **[Pipeline Mode](architecture/pipeline-mode.md)** — Textract + Bedrock processing threats
- **[BDA Mode](architecture/bda-mode.md)** — Bedrock Data Automation threats

### Feature-Specific Threats
- **[Agent Analysis](feature-threats/agent-analysis.md)** — SQL injection, code execution, routing manipulation
- **[Companion Chat](feature-threats/companion-chat.md)** — Prompt injection, session hijacking, streaming
- **[MCP Integration](feature-threats/mcp-integration.md)** — Data exfiltration, tool injection, response injection
- **[Knowledge Base](feature-threats/knowledge-base.md)** — KB poisoning, RAG injection, data exposure
- **[RBAC & Auth](feature-threats/rbac-authentication.md)** — Privilege escalation, token theft, authz gaps
- **[SDK/CLI](feature-threats/sdk-cli.md)** — Credential exposure, supply chain, batch abuse
- **[Lambda Hooks](feature-threats/lambda-hooks.md)** — Hook exfiltration, tampering, IAM escalation
- **[Web UI](feature-threats/web-ui.md)** — XSS, presigned URL abuse, GraphQL abuse
- **[Reporting & Analytics](feature-threats/reporting-analytics.md)** — Data tampering, Athena exposure, discovery injection

### Cross-Cutting Analysis
- **[STRIDE Analysis](threat-analysis/stride-analysis.md)** — Full STRIDE across all components
- **[Risk Matrix](risk-assessment/risk-matrix.md)** — Complete risk register with scoring and recommendations
- **[Threat ID Glossary](threat-id-glossary.md)** — All 62 threat IDs with quick reference

### Implementation
- **[Implementation Guide](deliverables/implementation-guide.md)** — Security controls, configuration, and checklists
- **[Threat Composer JSON](deliverables/threat-model.tc.json)** — Machine-readable threat model export

## Threat Categories

| Prefix | Category | Count | Highest Risk | Document |
|--------|----------|-------|-------------|----------|
| PM | Pipeline Mode | 7 | Critical (8) | [pipeline-mode.md](architecture/pipeline-mode.md) |
| BDA | BDA Mode | 5 | Medium (4) | [bda-mode.md](architecture/bda-mode.md) |
| AGT | Agent Analysis | 5 | High (6) | [agent-analysis.md](feature-threats/agent-analysis.md) |
| CHAT | Companion Chat | 5 | Very High (9) | [companion-chat.md](feature-threats/companion-chat.md) |
| MCP | MCP Integration | 6 | Critical (8) | [mcp-integration.md](feature-threats/mcp-integration.md) |
| KB | Knowledge Base | 4 | High (6) | [knowledge-base.md](feature-threats/knowledge-base.md) |
| AUTH | Authentication/RBAC | 8 | High (6) | [rbac-authentication.md](feature-threats/rbac-authentication.md) |
| SDK | SDK/CLI | 4 | High (6) | [sdk-cli.md](feature-threats/sdk-cli.md) |
| HOOK | Lambda Hooks | 5 | Critical (8) | [lambda-hooks.md](feature-threats/lambda-hooks.md) |
| UI | Web UI | 5 | High (6) | [web-ui.md](feature-threats/web-ui.md) |
| RPT | Reporting/Analytics | 6 | High (6) | [reporting-analytics.md](feature-threats/reporting-analytics.md) |

## Top 5 Priority Threats

| # | ID | Threat | Risk | Status |
|---|-----|--------|------|--------|
| 1 | PM.T01 | Prompt injection via document content | 9 | Mitigated |
| 2 | CHAT.T01 | Prompt injection via chat messages | 9 | Mitigated |
| 3 | PM.T06 | Configuration tampering | 8 | Mitigated |
| 4 | MCP.T01 | Data exfiltration via MCP tools | 8 | Partially Mitigated |
| 5 | HOOK.T02 | Data exfiltration via post-processing hook | 8 | Partially Mitigated |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.1 | 2026-07-13 | RBAC doc updated to REST-dispatcher architecture (AppSync removed); added AUTH.T07 (config-version scope bypass / fail-open scope lookup) and AUTH.T08 (silently-ignored schema auth directives); documented the automated authorization test harness (`make api-test` / `make api-test-static`) as a control; 62 → 64 threats |
| 2.0 | 2025-03-19 | Complete rework: unified architecture, removed Pattern 3/SageMaker, added 9 feature-specific threat analyses (agents, chat, MCP, KB, RBAC, SDK, hooks, UI, reporting), expanded from 31 to 62 threats |
| 1.0 | 2024-12-01 | Initial threat model with 3 separate patterns (BDA, Textract+Bedrock, Textract+SageMaker+Bedrock) |
