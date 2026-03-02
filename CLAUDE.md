# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GenAI Intelligent Document Processing (GenAIIDP) is a serverless solution for automated document processing using AWS services. It combines OCR with generative AI to extract structured data from unstructured documents at scale.

The system uses a modular architecture with nested CloudFormation stacks supporting multiple document processing patterns while maintaining common infrastructure for queueing, tracking, and monitoring.

## Build & Development Commands

### Building and Publishing

Build and publish deployment artifacts to S3:

```bash
# Primary build script (recommended)
python3 publish.py <cfn_bucket_basename> <cfn_prefix> <region> [--verbose]

# Example
python3 publish.py idp-1234567890 idp us-east-1

# With verbose output for debugging build failures
python3 publish.py idp-1234567890 idp us-east-1 --verbose

# Legacy build script
./publish.sh <cfn_bucket_basename> <cfn_prefix> <region>
```

The build process:
- Checks system dependencies (AWS CLI, SAM CLI, Docker, Python 3.11+, Node.js 22.12+)
- Builds CloudFormation templates and assets using SAM
- Pattern-2 functions are built as container images; Pattern-1 and Pattern-3 use ZIP-based Lambdas
- Uploads artifacts to S3 bucket named `<cfn_bucket_basename>-<region>`

### Code Quality & Linting

```bash
# Run all linting and formatting (includes UI)
make lint

# Fast lint (skips UI lint if unchanged via checksum)
make fastlint

# Python linting only
make ruff-lint

# Python formatting only
make format

# Type checking with basedpyright
make typecheck
make typecheck-stats

# UI linting (checks for changes via checksum)
make ui-lint

# UI build verification
make ui-build

# CI/CD linting (check-only, no modifications)
make lint-cicd
```

### Testing

```bash
# Run all tests (idp_common_pkg + idp_cli)
make test

# Run tests in idp_common_pkg only
cd lib/idp_common_pkg && make test

# Run unit tests only
cd lib/idp_common_pkg && make test-unit

# Run integration tests (requires AWS resources)
cd lib/idp_common_pkg && make test-integration

# Run idp_cli tests
cd idp_cli && python -m pytest -v

# Run specific test markers
pytest -m "unit"
pytest -m "integration"
```

### IDP CLI Commands

The IDP CLI is used for programmatic deployment and batch processing:

```bash
# Install CLI
make setup

# Deploy a new stack
idp-cli deploy \
    --stack-name my-idp-stack \
    --pattern pattern-2 \
    --admin-email your.email@example.com \
    --max-concurrent 100 \
    --wait

# Deploy with custom configuration
idp-cli deploy \
    --stack-name my-idp-stack \
    --pattern pattern-2 \
    --custom-config ./config_library/pattern-2/bank-statement-sample/config.yaml \
    --wait

# Process documents in batch
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

### Local Lambda Testing

```bash
cd patterns/pattern-2/
sam build
sam local invoke OCRFunction -e ../../testing/OCRFunction-event.json --env-vars ../../testing/env.json
```

### Development Setup

```bash
# Install idp_common library in edit mode with all dependencies
cd lib/idp_common_pkg && make dev
```

## Architecture Overview

### Nested Stack Architecture

The solution uses a modular architecture with the main template (`template.yaml`) and nested pattern stacks:

**Main Stack** (`template.yaml`) - Pattern-agnostic resources:
- S3 Buckets (Input, Output, Working, Configuration, Evaluation Baseline)
- SQS Queues and Dead Letter Queues
- DynamoDB Tables (Execution Tracking, Concurrency, Configuration)
- Lambda Functions (Queue Processing, Queue Sending, Workflow Tracking, Document Status Lookup, Evaluation, UI Integration)
- CloudWatch Alarms and Dashboard
- Web UI Infrastructure (CloudFront, S3 for static assets, CodeBuild)
- Authentication (Cognito User Pool, Identity Pool)
- AppSync GraphQL API (for UI-backend communication)

**Pattern Stacks** (`patterns/pattern-*/template.yaml`) - Pattern-specific resources:
- Step Functions State Machine
- Pattern-specific Lambda Functions (OCR, Classification, Extraction)
- Pattern-specific CloudWatch Dashboard
- Model Endpoints and Configurations

### Processing Patterns

1. **Pattern 1: Bedrock Data Automation (BDA)**
   - Uses AWS Bedrock Data Automation for end-to-end processing
   - Handles packet or media documents with integrated OCR, classification, and extraction
   - Location: `patterns/pattern-1/`

2. **Pattern 2: Textract + Bedrock**
   - OCR with Amazon Textract
   - Classification with Bedrock (page-level or holistic)
   - Extraction with Bedrock
   - Supports few-shot examples
   - Location: `patterns/pattern-2/`

3. **Pattern 3: Textract + UDOP + Bedrock**
   - OCR with Amazon Textract
   - Classification with UDOP model on SageMaker
   - Extraction with Bedrock

### Document Processing Flow

1. Documents uploaded to Input S3 bucket trigger EventBridge events
2. Queue Sender Lambda records event in tracking table and sends to SQS
3. Queue Processor Lambda:
   - Picks up messages in batches
   - Manages workflow concurrency using DynamoDB counter
   - Starts Step Functions executions
4. Step Functions workflow runs pattern-specific processing steps
5. Results written to Output S3 bucket
6. Workflow completion events update tracking and metrics

### Key Libraries

**`idp_common_pkg`** (`lib/idp_common_pkg/`):
- Core shared library powering the accelerator
- Modular installation: Install only needed components to minimize Lambda package size
  - `pip install "idp_common[core]"` - minimal dependencies
  - `pip install "idp_common[ocr]"` - OCR support
  - `pip install "idp_common[classification]"` - Classification support
  - `pip install "idp_common[extraction]"` - Extraction support
  - `pip install "idp_common[evaluation]"` - Evaluation support
  - `pip install "idp_common[all]"` - everything
- Components: OCR, Classification, Extraction, Evaluation, Summarization, AppSync integration, Reporting, BDA integration
- Configuration management via DynamoDB
- Document models and data structures

**`idp_cli`** (`idp_cli/`):
- Command-line interface for deployment and batch processing
- Stack deployment and updates
- Batch document processing
- Evaluation workflows
- Analytics integration

### Web UI

- React-based interface using Cloudscape Design System
- Vite build system
- Node.js 22.12+ and npm required
- Authentication via AWS Amplify v6 and Cognito
- Real-time document status via AppSync GraphQL subscriptions
- Location: `src/ui/`

## Configuration System

Configuration is managed via DynamoDB Configuration Table with two record types:
- **Default**: Built-in pattern configurations from `config_library/`
- **Custom**: User-provided overrides (via CustomConfigPath parameter or CLI)

Configuration presets available:
- **Pattern 1**: `lending-package-sample`, `realkie-fcc-verified`
- **Pattern 2**: `lending-package-sample`, `rvl-cdip`, `rvl-cdip-with-few-shot-examples`, `bank-statement-sample`, `realkie-fcc-verified`
- **Pattern 3**: `rvl-cdip`

Custom configurations override selected pattern presets when specified.

## Development Practices

### Code Quality Standards

- **Python**:
  - PEP 8 style guidelines
  - Linting with `ruff` configured in `ruff.toml`
  - Type checking with `basedpyright` configured in `pyrightconfig.json`
  - Line length: 88 characters
  - Target version: Python 3.12

- **JavaScript/TypeScript**:
  - ESLint configuration in `src/ui/.eslintrc`
  - Run `npm run lint` in `src/ui/` to verify

### Testing Standards

- Tests located in `lib/idp_common_pkg/tests/` and `idp_cli/tests/`
- Use pytest markers: `@pytest.mark.unit` and `@pytest.mark.integration`
- Integration tests require AWS resources

### Git Workflow

- Main development branch: `develop`
- Create feature branches with prefixes: `feature/`, `fix/`, `docs/`
- PRs should target `develop` branch

## Important Implementation Details

### Pattern-2 Container Deployment

Pattern-2 functions are deployed as container images (not ZIP files) due to size constraints. The build process:
1. Builds container images using Docker
2. Pushes images to ECR
3. Lambda functions reference ECR image URIs

Ensure Docker is running and you have ECR permissions when building Pattern-2.

### GovCloud Compatibility

The codebase maintains GovCloud compatibility:
- Use `arn:${AWS::Partition}:` instead of hardcoded `arn:aws:`
- Use `${AWS::URLSuffix}` instead of hardcoded `amazonaws.com`
- Validation enforced via `make check-arn-partitions`

### Nested Template Generation

AppSync resources are split into a nested template to work around CloudFormation resource limits:
- Script: `scripts/generate_nested_template.py`
- Generated template: `nested/appsync-nested-template.yaml`
- Automatically extracted from main template during build

### Lambda Layer Dependencies

Lambda functions reference the `idp_common_pkg` library:
- In `requirements.txt`: `../../lib/idp_common_pkg[extraction]`
- Use modular installation to minimize package size
- The library path is relative from Lambda source directories

### UI Checksum Optimization

The build system uses checksums to avoid rebuilding UI unnecessarily:
- Checksum stored in `src/ui/.checksum` and root `.checksum`
- `make ui-lint` skips linting if checksum unchanged
- Speeds up CI/CD and local development

## Sample Documents

Testing samples available in `samples/`:
- **Pattern 1 & 2**: `lending_package.pdf`
- **Pattern 3**: `rvl_cdip_package.pdf`

## Validation Scripts

- `scripts/sdlc/validate_buildspec.py` - Validates CodeBuild buildspec files
- `scripts/sdlc/validate_service_role_permissions.py` - Verifies IAM service role permissions
- `scripts/sdlc/typecheck_pr_changes.py` - Type checks only changed files in PRs

## AWS Service Requirements

### Required Bedrock Model Access

Request access to these models in Amazon Bedrock before deployment:
- **Amazon**: All Nova models, Titan Text Embeddings V2
- **Anthropic**: Claude 3.x models, Claude 4.x models

### Key AWS Services Used

- Amazon Bedrock (Foundational Models, Data Automation, Knowledge Bases)
- Amazon Textract
- Amazon SageMaker (for Pattern-3 UDOP endpoint)
- AWS Lambda
- AWS Step Functions
- Amazon S3
- Amazon SQS
- Amazon DynamoDB
- Amazon CloudWatch
- AWS AppSync
- Amazon Cognito
- Amazon CloudFront
- Amazon EventBridge
- Amazon SNS
- Amazon Glue (for evaluation analytics)
- Amazon Athena (for evaluation reporting)

## Troubleshooting

### Build Failures

Use `--verbose` flag with publish.py to see detailed error messages:
```bash
python3 publish.py idp-1234567890 idp us-east-1 --verbose
```

### Pattern-2 Container Build Issues

Ensure:
- Docker daemon is running
- AWS credentials have ECR permissions
- Sufficient disk space for container images

### UI Build Issues

Check:
- Node.js version >= 22.12.0
- Run `npm ci` in `src/ui/` to install dependencies
- Check `src/ui/.checksum` if builds are being skipped unexpectedly