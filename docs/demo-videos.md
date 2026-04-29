---
title: "Demo Videos"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Demo Videos

This page contains all demonstration videos for the GenAI Intelligent Document Processing (GenAIIDP) accelerator, organized by feature category.

## Table of Contents

- [Overview & Getting Started](#overview--getting-started)
- [External Presentations & Demos](#external-presentations--demos)
- [Document Processing Patterns](#document-processing-patterns)
- [Web User Interface](#web-user-interface)
- [Command Line Interface (CLI)](#command-line-interface-cli)
- [AI Agents & Analytics](#ai-agents--analytics)
- [Role-Based Access Control (RBAC)](#role-based-access-control-rbac)
- [Configuration & Management](#configuration--management)
- [Evaluation & Testing](#evaluation--testing)
- [Rule Validation](#rule-validation)
- [Integration & Extensions](#integration--extensions)

---

## Overview & Getting Started

### Solution Overview
A scalable, serverless solution for automated document processing and information extraction using AWS services.

**Duration**: ~3 minutes


https://github.com/user-attachments/assets/fc2652b5-a9cc-42d7-9975-887c8320a2f5


**Related Documentation**: [README.md](../README.md)

---

## External Presentations & Demos

This section features comprehensive presentations and live demonstrations from AWS events, conferences, and technical sessions.

### Healthcare Document Processing with GenAI IDP
A comprehensive technical session demonstrating how AWS's GenAI Intelligent Document Processing (GenAIIDP) solution revolutionizes healthcare document processing. The solution combines Amazon Textract and Bedrock to automatically process complex medical documents, transforming days-long manual processes into minutes.

**Key Topics Covered:**
- Automated classification and data extraction for medical documents
- Criteria validation while maintaining HIPAA compliance
- Live demonstrations and architecture deep-dives
- Implementation strategies for scalable document processing pipelines
- Integration patterns with existing healthcare systems
- Best practices for ROI optimization
- Eliminating document processing bottlenecks with regulatory compliance

**Duration**: ~1 hour

**Platform**: YouTube

[![Healthcare Document Processing Demo](https://img.youtube.com/vi/7CbJoeEFyZg/maxresdefault.jpg)](https://www.youtube.com/live/7CbJoeEFyZg?t=1174s)

[Watch on YouTube](https://www.youtube.com/live/7CbJoeEFyZg?t=1174s)

**Replicate This Demo**: You can now run this exact healthcare demo yourself using the pre-configured sample and config files included in the repository:
- **Sample Document**: [healthcare-multisection-package.pdf](../samples/healthcare-multisection-package.pdf)
- **Configuration**: [Pattern-2 Healthcare Config](../config_library/unified/healthcare-multisection-package/config.yaml)

These are the same files used in the video demonstration and can be deployed with the IDP CLI or web UI.

---

## Document Processing Patterns

### Pattern 1: Bedrock Data Automation (BDA) Workflow
Overview of BDA-based document processing with asynchronous job management and EventBridge integration.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/24547356-6d68-4935-b0fd-ddeed9c25ba8

**Related Documentation**: [Pattern 1 Documentation](./pattern-1.md)

---

## Web User Interface

### Human-in-the-Loop (HITL) Review
Built-in review portal for validating and correcting extracted information with role-based access control.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/0bf14b62-99dc-4538-a015-d8b89fa2f1f0

**Related Documentation**: [Human Review Documentation](./human-review.md)

---

### Chat with Document Feature
Interactive document Q&A using Nova Pro model to answer questions about specific documents.

**Duration**: ~2 minutes

https://github.com/user-attachments/assets/50607084-96d6-4833-85a6-3dc0e72b28ac

**Related Documentation**: [Web UI Documentation - Chat with Document](./web-ui.md#chat-with-document)

---

## Command Line Interface (CLI)

### IDP CLI Overview
Batch document processing with live progress monitoring, comprehensive status tracking, and evaluation framework.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/3d448a74-ba5b-4a4a-96ad-ec03ac0b4d7d

**Related Documentation**: [IDP CLI Documentation](./idp-cli.md)

---

### Rerun Inference Feature
Leverage existing OCR data to rapidly iterate on classification and extraction configurations without reprocessing.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/28deadbb-378b-42b7-a5e2-f929af9b0e41

**Related Documentation**: [IDP CLI - Rerun Inference](./idp-cli.md#rerun-inference)

---

## AI Agents & Analytics

### Agent Companion Chat
Multi-turn conversational AI assistant with specialized agents for analytics, troubleshooting, and code assistance.

**Duration**: ~5 minutes

https://github.com/user-attachments/assets/c48b9e48-e0d4-457c-8c95-8cdb7a9d332b

**Related Documentation**: [Agent Companion Chat Documentation](./agent-companion-chat.md)

---

### Agent Analysis Feature (Original)
Natural language querying with automated SQL generation and interactive visualizations.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/e2dea2c5-5eb1-42f6-9af5-469afd2135a7

**Related Documentation**: [Agent Analysis Documentation](./agent-analysis.md)

---

### Error Analyzer (Troubleshooting Tool)
AI-powered troubleshooting using Amazon Bedrock to diagnose document processing failures automatically.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/78764207-0fcf-4523-ad12-f428581a685f

**Related Documentation**: [Error Analyzer Documentation](./error-analyzer.md)

---

## Role-Based Access Control (RBAC)

### RBAC Demo
Role-based access control for managing user permissions and access to document processing features, configurations, and review workflows.

https://github.com/user-attachments/assets/a1e9ce1a-1b2e-4e98-a387-d2e48d7e557d

**Related Documentation**: [RBAC Documentation](./rbac.md)

---

## Configuration & Management

### Discovery Module
Intelligent document analysis that automatically identifies structures and creates processing blueprints, including pattern-neutral discovery and pattern-specific implementations.

#### Multi-Document Collection Discovery
**Duration**: ~4 minutes

https://github.com/user-attachments/assets/9c3923fb-f4ff-43cd-a563-44c7c6132921

#### Single Document Discovery
**Duration**: ~4 minutes

https://github.com/user-attachments/assets/b0bc5df0-cd8f-472c-98c6-299ac3a9bd43

**Related Documentation**: [Discovery Module Documentation](./discovery.md)

---

### BDA IDP Sync Feature
Bidirectional synchronization between BDA blueprints and IDP document classes with parallel processing.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/6016614d-e582-4956-8c39-c189a52f63c6

**Related Documentation**: [Discovery - BdaIDP Sync](./discovery.md#bdaidp-sync-feature)

---

### Configuration Versions
Manage multiple configuration snapshots for A/B testing, environment separation, and safe rollback.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/b1e0cf16-d2c4-4927-a9ec-767b8ac49c9d

**Related Documentation**: [Configuration Versions Documentation](./configuration-versions.md)

---

### JSON Schema Migration
Migration from legacy custom format to industry-standard JSON Schema with automatic backward compatibility.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/ee817858-8285-4087-9b25-2c7c5bea65df

**Related Documentation**: [JSON Schema Migration Guide](./json-schema-migration.md)

---

### Custom Model Fine-Tuning
Fine-tune Amazon Nova models for document classification using your own labeled Test Sets — validate data, generate training data, train via Bedrock, and deploy a custom model endpoint.

https://github.com/user-attachments/assets/e82c7be0-ee73-4ad7-8537-87ecf6a1a4c8

**Related Documentation**: [Custom Model Fine-Tuning Documentation](./custom-model-finetuning.md)

---

### Excluding Static Pages (Instructions, Legal, Boilerplate)
Mark a document class with `x-aws-idp-exclude-from-processing: true` and the pipeline skips that class's sections through extraction, assessment, summarization, rule validation, and evaluation — zero LLM calls on boilerplate pages. Demo uses a DS-11 U.S. Passport Application (4 static instruction pages + 2 applicant-data pages).

https://github.com/user-attachments/assets/3c5106ee-ffaf-48d0-ac57-6de78a221474

**Related Documentation**: [Excluding Static Pages](./classification.md#excluding-static-pages-eg-instructions-legal-boilerplate)

---

## Evaluation & Testing

### Evaluation Framework
Stickler-based evaluation with field-level comparison, multiple evaluation methods, and comprehensive metrics.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/0ff17f3e-1eb5-4883-9d6f-3d4e4e84cbea

**Related Documentation**: [Evaluation Framework Documentation](./evaluation.md)

---

### Document Split Classification Metrics
Evaluation of page-level classification accuracy, document grouping, and page order preservation.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/289cc6a7-3d83-488b-a4b1-4b749858cd9e

**Related Documentation**: [Evaluation - Document Split Metrics](./evaluation.md#document-split-classification-metrics)

---

### Test Studio
Comprehensive interface for managing test sets, running benchmark tests, and analyzing results.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/7c5adf30-8d5c-4292-93b0-0149506322c7

**Related Documentation**: [Test Studio Documentation](./test-studio.md)

---

### Test Studio - RealKIE-FCC-Verified Dataset
Using the pre-deployed RealKIE-FCC-Verified benchmark dataset with 75 invoice documents.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/d952fd37-1bd0-437f-8f67-5a634e9422e0

**Related Documentation**: [Test Studio - Pre-Deployed Test Sets](./test-studio.md#pre-deployed-test-sets)

---

### Creating Custom Test Sets with Ground Truth
End-to-end workflow for creating your own test set from scratch — configure for high accuracy, discover the schema, process and review documents, save ground truth, and compare model accuracy vs. cost.

https://github.com/user-attachments/assets/d5e0d590-ce8b-4e14-b2b7-8bde31e57ec2

**Related Documentation**: [Creating Custom Test Sets](./creating-custom-test-sets.md)

---

### Adding Documents to Existing Test Sets
Incrementally grow test sets over time by adding newly reviewed documents with ground truth — with automatic baseline filtering, time-based file selection, and prepopulated file patterns.

https://github.com/user-attachments/assets/bcd18e62-4795-44ea-9554-637062fd21d7

**Related Documentation**: [Creating Custom Test Sets - Incrementally Growing Your Test Set](./creating-custom-test-sets.md#incrementally-growing-your-test-set)

---

## Rule Validation

### Rule Validation Demo
Automatically validate documents against business rules and compliance requirements using AI. Includes rule extraction from policy documents, configurable rule schemas, and detailed Pass/Fail reporting with supporting evidence.

https://github.com/user-attachments/assets/5d115b90-ff52-4e17-ab70-d259efe5a183

**Related Documentation**: [Rule Validation Documentation](./rule-validation.md)

---

## Integration & Extensions

### MCP Integration
Model Context Protocol integration enabling external applications like Amazon Quick Suite to access IDP data.


#### Demo with Quick Suite
**Duration**: ~3 minutes  

https://github.com/user-attachments/assets/529ce6ad-1062-4af5-97c1-86c3a47ac12c

#### Demo with Cline 
**Duration**: ~5 minutes  

https://github.com/user-attachments/assets/28d3a358-7aec-4c40-9081-ad4683d2a89f


**Related Documentation**: [MCP Server Documentation](./mcp-server.md)

---

### Custom MCP Agent Integration
Extend IDP with custom tools by connecting to your own MCP servers with OAuth authentication.

**Duration**: ~4 minutes

https://github.com/user-attachments/assets/630ec15d-6aef-4e57-aa01-40c8663a5510

**Related Documentation**: [Custom MCP Agent Documentation](./custom-MCP-agent.md)

---

### Document Knowledge Base Query
Natural language querying of processed document collections with AI-powered responses and citations.

**Duration**: ~3 minutes

https://github.com/user-attachments/assets/991b4112-0fc9-4e4d-98ab-ef4e3cbae04a

**Related Documentation**: [Knowledge Base Documentation](./knowledge-base.md)

---

## Additional Resources

For more information about the GenAI IDP Accelerator:

- **Main Documentation**: [README.md](../README.md)
- **Architecture Guide**: [Architecture Documentation](./architecture.md)
- **Deployment Guide**: [Deployment Documentation](./deployment.md)
- **Configuration Guide**: [Configuration Documentation](./configuration.md)

## Feedback

If you have questions about any of these features or suggestions for new demo videos, please:
- Open an issue on [GitHub](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues)
- Contact AWS Professional Services for concierge support
