# Gen AI Intelligent Document Processing (GenAIIDP)

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

**Questions?** [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws)

## Table of Contents

- [Introduction](#introduction)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
  - [Processing Your First Document](#processing-your-first-document)
- [Updating an Existing Deployment](#updating-an-existing-deployment)
- [Detailed Documentation](#detailed-documentation)
  - [Core Documentation](#core-documentation)
  - [Processing Patterns](#processing-patterns)
  - [Python Development](#python-development)
  - [Planning & Operations](#planning--operations)
- [Contributing](#contributing)
- [License](#license)

## Introduction

A scalable, serverless solution for automated document processing and information extraction using AWS services. This system combines OCR capabilities with generative AI to convert unstructured documents into structured data at scale.

https://github.com/user-attachments/assets/272b543b-e506-48ce-acc1-361422d22322

White-glove customization, deployment, and integration support for production use cases is also available through [AWS Professional Services](https://aws.amazon.com/professional-services/).

## Key Features

- **Serverless Architecture**: Built entirely on AWS serverless technologies including Lambda, Step Functions, SQS, and DynamoDB
- **Modular, pluggable patterns**: Pre-built processing patterns using state-of-the-art models and AWS services
- **Command Line Interface**: Programmatic batch processing with evaluation framework and analytics integration
- **Advanced Classification**: Support for page-level and holistic document packet classification
- **Few Shot Example Support**: Improve accuracy through example-based prompting
- **Custom Business Logic Integration**: Inject custom prompt generation logic via Lambda functions for specialized document processing
- **High Throughput Processing**: Handles large volumes of documents through intelligent queuing
- **Built-in Resilience**: Comprehensive error handling, retries, and throttling management
- **Cost Optimization**: Pay-per-use pricing model with built-in controls
- **Comprehensive Monitoring**: Rich CloudWatch dashboard with detailed metrics and logs
- **Web User Interface**: Modern UI for inspecting document workflow status and results
- **Human-in-the-Loop (HITL)**: Amazon A2I integration for human review workflows (Pattern 1 & Pattern 2)
  - **Note**: When deploying multiple patterns with HITL, reuse existing private workteam ARN due to AWS account limits
- **AI-Powered Evaluation**: Framework to assess accuracy against baseline data
- **Extraction Confidence Assessment**: LLM-powered assessment of extraction confidence with multimodal document analysis
- **Document Knowledge Base Query**: Ask questions about your processed documents

## Architecture Overview

![Architecture Diagram](./images/IDP.drawio.png)

The solution uses a modular architecture with nested CloudFormation stacks to support multiple document processing patterns while maintaining common infrastructure for queueing, tracking, and monitoring.

Current patterns include:
- Pattern 1: Packet or Media processing with Bedrock Data Automation (BDA)
- Pattern 2: OCR → Bedrock Classification (page-level or holistic) → Bedrock Extraction
- Pattern 3: OCR → UDOP Classification (SageMaker) → Bedrock Extraction

## Quick Start

To quickly deploy the GenAI-IDP solution in your AWS account:

1. Log into the [AWS console](https://console.aws.amazon.com/)
2. Choose the **Launch Stack** button below for your desired region:

| Region name           | Region code | Launch                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| US West (Oregon)      | us-west-2   | [![Launch Stack](https://cdn.rawgit.com/buildkite/cloudformation-launch-stack-button-svg/master/launch-stack.svg)](https://us-west-2.console.aws.amazon.com/cloudformation/home?region=us-west-2#/stacks/create/review?templateURL=https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml&stackName=IDP) |
| US East (N.Virginia)      | us-east-1   | [![Launch Stack](https://cdn.rawgit.com/buildkite/cloudformation-launch-stack-button-svg/master/launch-stack.svg)](https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/create/review?templateURL=https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main.yaml&stackName=IDP) |

3. When the stack deploys for the first time, you'll receive an email with a temporary password to access the web UI
4. Use this temporary password for your first login to set up a permanent password

### Processing Your First Document

After deployment, choose the processing method that fits your use case:

#### Method 1: Web UI (Interactive)

1. Open the Web UI URL from CloudFormation stack Outputs
2. Log in and click "Upload Document"
3. Upload a sample document:
   - For Patterns 1 & 2: [samples/lending_package.pdf](./samples/lending_package.pdf)
   - For Pattern 3: [samples/rvl_cdip_package.pdf](./samples/rvl_cdip_package.pdf)
4. Monitor processing and view results in the dashboard

#### Method 2: Direct S3 Upload (Simple)

1. Upload to the InputBucket (URL in CloudFormation Outputs)
2. Monitor via Step Functions console
3. Results appear in OutputBucket automatically

#### Method 3: IDP CLI (Batch/Programmatic)

For batch processing, automation, or evaluation workflows:

```bash
# Install CLI
cd idp_cli && pip install -e .

# Process documents
idp-cli run-inference \
    --stack-name <your-stack-name> \
    --dir ./samples/ \
    --monitor

# Download results
idp-cli download-results \
    --stack-name <your-stack-name> \
    --batch-id <batch-id> \
    --output-dir ./results/
```

**See [IDP CLI Documentation](./idp_cli/README.md)** for:
- CLI-based stack deployment and updates
- Batch document processing
- Complete evaluation workflows with baselines
- Athena and Agent Analytics integration
- CI/CD integration examples

See the [Deployment Guide](./docs/deployment.md#testing-the-solution) for more detailed testing instructions.

IMPORTANT: If you have not previously done so, you must [request access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) to the following Amazon Bedrock models:
- Amazon: All Nova models, plus Titan Text Embeddings V2
- Anthropic: Claude 3.x models, Claude 4.x models

## Updating an Existing Deployment

To update an existing GenAIIDP stack to a new version:

1. Navigate to CloudFormation in the AWS Management Console
2. Select your existing stack
3. Click "Update"
4. Select "Replace current template"
5. Enter the template URL: 
   - us-west-2: `https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml`
   - us-east-1: `https://s3.us-east-1.amazonaws.com/aws-ml-blog-us-east-1/artifacts/genai-idp/idp-main.yaml`
6. Follow the prompts to update your stack, reviewing any parameter changes
7. For detailed instructions, see the [Deployment Guide](./docs/deployment.md#updating-an-existing-stack)

For testing, use these sample files:
   - For Patterns 1 (BDA) and Pattern 2: Use [samples/lending_package.pdf](./samples/lending_package.pdf)
   - For Pattern 3 (UDOP): Use [samples/rvl_cdip_package.pdf](./samples/rvl_cdip_package.pdf)

For detailed deployment and testing instructions, see the [Deployment Guide](./docs/deployment.md).


## Detailed Documentation

### Core Documentation

- [Architecture](./docs/architecture.md) - Detailed component architecture and data flow
- [Deployment](./docs/deployment.md) - Build, publish, deploy, and test instructions
- [IDP CLI](./idp_cli/README.md) - Command line interface for batch processing and evaluation workflows
- [Web UI](./docs/web-ui.md) - Web interface features and usage
- [Agent Analysis](./docs/agent-analysis.md) - Natural language analytics and data visualization feature
- [Custom MCP Agent](./docs/custom-MCP-agent.md) - Integrating external MCP servers for custom tools and capabilities
- [Configuration](./docs/configuration.md) - Configuration and customization options
- [Discovery](./docs/discovery.md) - Pattern-neutral discovery process and BDA blueprint automation
- [Classification](./docs/classification.md) - Customizing document classification
- [Extraction](./docs/extraction.md) - Customizing information extraction
- [Human-in-the-Loop Review](./docs/human-review.md) - Human review workflows with Amazon A2I
- [Assessment](./docs/assessment.md) - Extraction confidence evaluation using LLMs
- [Evaluation Framework](./docs/evaluation.md) - Accuracy assessment system with analytics database and reporting
- [Knowledge Base](./docs/knowledge-base.md) - Document knowledge base query feature
- [Monitoring](./docs/monitoring.md) - Monitoring and logging capabilities
- [Reporting Database](./docs/reporting-database.md) - Analytics database for evaluation metrics and metering data
- [Troubleshooting](./docs/troubleshooting.md) - Troubleshooting and performance guides

### Processing Patterns

- [Pattern 1: BDA](./docs/pattern-1.md) - Packet or Media processing with Bedrock Data Automation (BDA)
- [Pattern 2: Textract + Bedrock](./docs/pattern-2.md) - OCR with Textract and generative AI with Bedrock
- [Pattern 3: Textract + UDOP + Bedrock](./docs/pattern-3.md) - OCR with Textract, UDOP Classification, and Bedrock extraction
- [Few-Shot Examples](./docs/few-shot-examples.md) - Implementing few-shot examples for improved accuracy

### Python Development

- [Using Notebooks with IDP Common Library](./docs/using-notebooks-with-idp-common.md) - Guide for using and creating Jupyter notebooks to experiment with the IDP Common Library
- [IDP Common Package](./lib/idp_common_pkg/README.md) - Documentation for the core library powering the accelerator

### Planning & Operations

- [Well-Architected Framework Assessment](./docs/well-architected.md) - Analysis based on AWS Well-Architected Framework
- [AWS Services & IAM Roles](./docs/aws-services-and-roles.md) - AWS services used and IAM role requirements
- [Cost Calculator](./docs/cost-calculator.md) - Framework for estimating solution costs

## Contributing

We welcome contributions to the GenAI Intelligent Document Processing accelerator! Whether you're fixing bugs, improving documentation, or proposing new features, your contributions are appreciated.

Please refer to our [Contributing Guide](./CONTRIBUTING.md) for detailed information on:

- Setting up your development environment
- Project structure
- Making and testing changes
- Pull request process
- Coding standards
  - Python code uses `ruff` for linting
  - UI code uses ESLint (`npm run lint` to verify)
- Documentation requirements
- Issue reporting guidelines

Thank you to everyone who has contributed to making this project better!

## License

This project is licensed under the terms specified in the LICENSE file.
