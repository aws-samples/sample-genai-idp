Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# GenAIIDP Documentation

This folder contains detailed documentation on various aspects of the GenAI Intelligent Document Processing solution.

## Pattern Comparison

The solution offers three deployment patterns, each optimized for different use cases:

| Feature | Pattern 1: BDA | Pattern 2: Bedrock | Pattern 3: UDOP + Bedrock |
|---------|----------------|-------------------|--------------------------|
| **Ingestion** | S3 → BDA Project | S3 → Step Functions | S3 → Step Functions |
| **OCR** | Managed by BDA | Textract or Bedrock | Textract |
| **Classification** | BDA Blueprints | Bedrock (Nova/Claude) | SageMaker UDOP |
| **Extraction** | BDA Blueprints | Bedrock (Nova/Claude) | Bedrock (Claude) |
| **Configuration** | BDA Console | IDP Config File | IDP Config File |
| **Vector Storage** | OpenSearch or S3 | OpenSearch or S3 | OpenSearch or S3 |
| **Best For** | Quick start, pre-built templates | Full customization, prompt control | ML model fine-tuning |
| **Setup Complexity** | Low | Medium | High |

### Processing Flow Comparison

**Pattern 1: Bedrock Data Automation**
```
S3 Upload → BDA Invoke → [BDA Processing] → Completion Handler → Results
            (async)       ↓
                    EventBridge Notification
```
- **Pro**: Fully managed, minimal configuration
- **Con**: Less control over processing steps

**Pattern 2: Bedrock-Only**
```
S3 Upload → OCR → Classification → Extraction → Assessment (optional) → Results
            ↓      ↓                ↓            ↓
         Textract  Bedrock LLM    Bedrock LLM  Bedrock LLM
         or Bedrock
```
- **Pro**: Full control, customizable prompts, multi-model support
- **Con**: Requires configuration and tuning

**Pattern 3: UDOP + Bedrock**
```
S3 Upload → OCR → Classification → Extraction → Results
            ↓      ↓                ↓
         Textract  SageMaker UDOP  Bedrock Claude
```
- **Pro**: Fine-tuned classification, highest accuracy potential
- **Con**: Requires model training and SageMaker endpoint

### Quick Selection Guide

**Choose Pattern 1 if:**
- ✅ You want quick deployment with minimal configuration
- ✅ Standard document types (invoices, forms, etc.)
- ✅ Pre-built BDA blueprints meet your needs

**Choose Pattern 2 if:**
- ✅ You need custom classification logic
- ✅ You want to control extraction prompts
- ✅ You need multi-page document analysis
- ✅ You want to test multiple Bedrock models

**Choose Pattern 3 if:**
- ✅ You have labeled training data
- ✅ Classification accuracy is critical
- ✅ You need specialized document type detection
- ✅ You have ML expertise for model fine-tuning

### Vector Storage Backend Options

All patterns support optional **Document Knowledge Base** functionality with two vector storage backends:

| Backend | Latency | Cost Model | Storage Cost | Best For |
|---------|---------|------------|--------------|----------|
| **OpenSearch Serverless** | Sub-millisecond | Always On | Higher | Real-time apps, frequent queries |
| **S3 Vectors** | Sub-second | On Demand | 40-60% lower | Cost optimization, batch queries |

**Configuration:**
```yaml
ShouldUseDocumentKnowledgeBase: "true"  # Enable knowledge base
KnowledgeBaseVectorStore: "OPENSEARCH_SERVERLESS"  # or "S3_VECTORS"
```

**Choose OpenSearch Serverless if:**
- ✅ You need ultra-fast query responses
- ✅ Users query the knowledge base frequently
- ✅ Real-time performance is critical
- ✅ Budget allows for continuous capacity costs

**Choose S3 Vectors if:**
- ✅ Cost optimization is a priority
- ✅ Sub-second latency is acceptable
- ✅ Queries are less frequent or batch-oriented
- ✅ You want 40-60% lower storage costs

Both backends support the same features: natural language queries, document citations, follow-up questions, and integration with all three deployment patterns. See [Knowledge Base Guide](./knowledge-base.md) for detailed documentation.

## Documentation Structure

### Getting Started
- [Architecture](./architecture.md) - Detailed component architecture and data flow
- [Deployment](./deployment.md) - Build, publish, deploy, and test instructions
- [Web UI](./web-ui.md) - Web interface features and usage

### Deployment Patterns
- [Pattern 1: Bedrock Data Automation](./pattern-1.md) - Fully managed BDA workflow
- [Pattern 2: Bedrock-Only](./pattern-2.md) - Full control with Bedrock models
- [Pattern 3: UDOP + Bedrock](./pattern-3.md) - Fine-tuned classification with ML models

### Document Processing
- [Supported Formats](./supported-formats.md) - Comprehensive guide to supported document formats
- [Text Extraction](./text-extraction.md) - Text-native PDF processing and intelligent image filtering
- [OCR Image Sizing Guide](./ocr-image-sizing-guide.md) - Image optimization for OCR processing

### Core Features
- [Agent Analysis](./agent-analysis.md) - Natural language analytics and data visualization feature
- [Knowledge Base](./knowledge-base.md) - Document knowledge base query feature
- [Post-Processing Lambda Hook](./post-processing-lambda-hook.md) - Custom downstream processing integration
- [Evaluation Framework](./evaluation.md) - Accuracy assessment system
- [Assessment Feature](./assessment.md) - Extraction confidence evaluation using LLMs

### Configuration and Customization
- [Configuration](./configuration.md) - Configuration and customization options
- [Classification](./classification.md) - Customizing document classification
- [Extraction](./extraction.md) - Customizing information extraction
- [Criteria Validation](./criteria-validation.md) - Document validation against business rules using LLMs

### Operations
- [Monitoring](./monitoring.md) - Monitoring and logging capabilities
- [Troubleshooting](./troubleshooting.md) - Troubleshooting and performance guides

## Screenshots and Diagrams

The documentation references several screenshots and diagrams from the `../images` folder:

- Architecture diagrams (`IDP.drawio.png`, etc.)
- Pattern-specific diagrams (`IDP-Pattern1-BDA.drawio.png`, etc.)
- Web UI screenshots (`WebUI.png`)
- Dashboard screenshots (`Dashboard1.png`, `Dashboard2.png`, `Dashboard3.png`)

## Contributing to Documentation

When updating these documents:

1. Keep content concise and focused on the specific topic
2. Include relevant screenshots and diagrams where helpful
3. Use markdown formatting for readability
4. Cross-reference other documents where appropriate
