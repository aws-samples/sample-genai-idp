Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Configuration and Customization

The GenAIIDP solution provides multiple configuration approaches to customize document processing behavior to suit your specific needs.

> **📝 Note:** Starting with version 0.3.21, document class definitions use **JSON Schema** format instead of the legacy custom format. See [json-schema-migration.md](json-schema-migration.md) for migration details and format comparison. Legacy configurations are automatically migrated on first use.

## Pattern Configuration via Web UI

The web interface allows real-time configuration updates without stack redeployment:

- **Document Classes**: Define and modify document categories and their descriptions (using JSON Schema format)
- **Extraction Attributes**: Configure fields to extract for each document class (defined as JSON Schema properties)
- **Few Shot Examples**: Upload and configure example documents to improve accuracy (supported in Pattern 2)
- **Model Selection**: Choose between available Bedrock models for classification and extraction
- **Prompt Engineering**: Customize system and task prompts for optimal results
- **OCR Features**: Configure Textract features (TABLES, FORMS, SIGNATURES, LAYOUT) for enhanced data capture
- **Evaluation Methods**: Set evaluation methods and thresholds for each attribute
- **Summarization**: Configure model, prompts, parameters, and enable/disable document summarization via the `enabled` property

### Configuration Versions

The solution supports **multiple named configuration versions**, enabling you to maintain independent configuration snapshots for A/B testing, environment separation, and iterative prompt tuning — all without redeploying the stack. Each version stores a complete, self-contained configuration. The active version determines which configuration is used for new document processing.

Key capabilities:
- **Create, edit, and delete** configuration versions with unique names and descriptions
- **Activate** any version to make it the default for new processing
- **Compare** versions side-by-side to see differences (exportable as CSV/JSON)
- **Track** which version was used for each processed document and test run
- **Select** a specific version when uploading documents, running tests, or using the CLI

For comprehensive documentation, see [configuration-versions.md](configuration-versions.md).

### Configuration Management Features

- **Save Changes**: Save your current configuration changes. The button is **enabled only when you have unsaved changes** (comparing your edits against the last saved configuration). After a successful save, a confirmation banner is displayed.
- **Unsaved Changes Indicator**: Individual fields with unsaved edits display an orange dot next to the field label, and an info banner with a "Discard changes" button appears when the configuration form has unsaved edits.
- **Browser Navigation Guard**: The browser warns before leaving the page when unsaved configuration changes exist (both on browser close/refresh and SPA navigation).
- **Save as Default**: Save your current version's configuration as the new default baseline. This replaces the existing default configuration. **Warning**: Default configurations may be overwritten during solution upgrades - export your configuration first for backup.
- **Restore Default (All)**: Reset the current version's configuration back to the default values, replacing all customizations.
- **Refresh**: Reload the configuration from the server. Use this to sync your view with the latest saved configuration, discard unsaved local changes, or verify your configuration after external updates.
- **Export Configuration**: Download your current configuration to local files in JSON or YAML format with customizable filenames. Use this to backup configurations before upgrades or share configurations between environments.
- **Import Configuration**: Upload configuration files from your local machine OR import from the Configuration Library:
  - **From Local File**: Upload configuration files from your computer in JSON or YAML format with automatic format detection and validation
  - **From Configuration Library**: Browse and import pre-configured document processing workflows from the solution's built-in configuration library
    - **Pattern-Filtered**: Only shows configurations compatible with your currently deployed pattern (Pattern 1, 2, or 3)
    - **Dual Format Support**: Automatically detects and imports both `config.yaml` and `config.json` formats
    - **README Preview**: View markdown-formatted documentation before importing to understand configuration purpose and features
    - **Format Indicators**: Visual badges show file format (YAML/JSON) and README availability
    - **Library Contents**: Includes sample configurations like lending-package-sample, bank-statement-sample, rvl-cdip, criteria-validation, and more
  - **Important**: Importing a configuration **replaces** your existing custom configuration entirely. Any prior customizations not included in the imported file will be reset to defaults. Export your current configuration first if you want to preserve it.

Configuration changes are validated and applied immediately, with rollback capability if issues arise. See [web-ui.md](web-ui.md) for details on using the administration interface.

### Configuration Management via CLI

The IDP CLI provides command-line tools for configuration management:

- **`idp-cli config-create`**: Generate configuration templates from system defaults
- **`idp-cli config-validate`**: Validate configuration files against schemas
- **`idp-cli config-download`**: Download configuration from deployed stacks
- **`idp-cli config-upload`**: Upload configuration to deployed stacks

See [idp-cli.md](idp-cli.md#config-create) for complete command documentation.

## Custom Configuration Path

The solution now supports specifying a custom configuration file location via the `CustomConfigPath` CloudFormation parameter. This allows you to use your own configuration files stored in S3 instead of the default configuration library.

### Usage

When deploying the stack, you can specify a custom configuration file:

```yaml
CustomConfigPath: "s3://my-bucket/custom-config/config.yaml"
```

**Key Features:**
- **Override Default Configuration**: When specified, your custom configuration completely replaces the default pattern configuration
- **S3 URI Format**: Accepts standard S3 URI format (e.g., `s3://my-bucket/custom-config/config.yaml`)
- **Least-Privilege Security**: IAM permissions are conditionally granted only to the specific S3 bucket and object you specify
- **All Patterns Supported**: Works with Pattern 1 (BDA), Pattern 2 (Textract + Bedrock), and Pattern 3 (Textract + UDOP + Bedrock)

**Security Benefits:**
- Eliminates wildcard S3 permissions (`arn:aws:s3:::*/*`)
- Conditional IAM access only when CustomConfigPath is specified
- Proper S3 URI to ARN conversion for least-privilege compliance
- Passes security scans with minimal required permissions

**Configuration File Requirements:**
- Must be valid YAML format
- Only needs to include `notes`, `classes`, and any settings that differ from system defaults (see "System Defaults and Configuration Inheritance" below)
- Follow the same structure as the configuration files in the `config_library` directory

Leave the `CustomConfigPath` parameter empty (default) to use the standard configuration library included with the solution.

## System Defaults and Configuration Inheritance

The GenAI IDP Accelerator uses a **system defaults** architecture where configurations inherit from pattern-specific default files. This means user configurations only need to specify differences from the defaults, making them simpler and more maintainable.

### How It Works

1. **System defaults** are loaded first from `lib/idp_common_pkg/idp_common/config/system_defaults/`:
   - `pattern-1.yaml` - BDA mode defaults (used when `use_bda: true`)
   - `pattern-2.yaml` - Pipeline mode defaults (used when `use_bda: false`)

2. **User configurations** are merged on top, overriding only the specified values

3. **Result**: A complete configuration with user customizations applied to system defaults

### Minimal Configuration Example

A user configuration only needs:

```yaml
notes: "My document processing configuration"

classes:
  - $schema: https://json-schema.org/draft/2020-12/schema
    $id: Invoice
    type: object
    x-aws-idp-document-type: Invoice
    description: "A billing document"
    properties:
      invoice_number:
        type: string
        description: "Unique invoice identifier"
```

All other settings (OCR, classification, extraction, assessment, evaluation, summarization, discovery, agents) are inherited from the pattern's system defaults.

### Override Example

To override specific settings while keeping others at defaults:

```yaml
notes: "Configuration with custom classification method"

# Override just the classification method
classification:
  classificationMethod: textbasedHolisticClassification

# Override assessment to enable granular mode
assessment:
  granular:
    enabled: true

classes:
  # ... your document classes
```

### Benefits

- **Simpler configs** - Only specify what makes your use case unique
- **Maintainable** - System default updates automatically apply to all configs
- **Focused** - Easy to see what customizations are active
- **Version-safe** - Defaults evolve with the solution while custom overrides remain stable

### Configuration Library

The `config_library/` directory contains example configurations demonstrating this inheritance pattern. Each config contains:
- `notes:` - Description of the configuration
- `classes:` - Document class definitions (JSON Schema format)
- **Overrides** - Only settings that differ from system defaults

See the [config_library README](../config_library/README.md) for available configurations and usage examples.

## Summarization Configuration

### Enable/Disable Summarization

Summarization can be controlled via the configuration file rather than CloudFormation stack parameters. This provides more flexibility and eliminates the need for stack redeployment when changing summarization behavior.

**Configuration-based Control (Recommended):**
```yaml
summarization:
  enabled: true  # Set to false to disable summarization
  model: us.anthropic.claude-3-7-sonnet-20250219-v1:0
  temperature: 0.0
  # ... other summarization settings
```

**Key Benefits:**
- **Runtime Control**: Enable/disable without stack redeployment
- **Cost Optimization**: Zero LLM costs when disabled (`enabled: false`)
- **Simplified Architecture**: No conditional logic in state machines
- **Backward Compatible**: Defaults to `enabled: true` when property is missing

**Behavior When Disabled:**
- Summarization lambda is still called (minimal overhead)
- Service immediately returns with logging: "Summarization is disabled in configuration"
- No LLM API calls or S3 operations are performed
- Document processing continues to completion

**Note:** Prior to v0.4.0, this feature was controlled by the `IsSummarizationEnabled` CloudFormation parameter. The configuration-based approach provides runtime control without requiring stack redeployment.

## Assessment Configuration

### Enable/Disable Assessment

Similar to summarization, assessment can now be controlled via the configuration file rather than CloudFormation stack parameters. This provides more flexibility and eliminates the need for stack redeployment when changing assessment behavior.

**Configuration-based Control (Recommended):**
```yaml
assessment:
  enabled: true  # Set to false to disable assessment
  model: us.amazon.nova-lite-v1:0
  temperature: 0.0
  # ... other assessment settings
```

**Key Benefits:**
- **Runtime Control**: Enable/disable without stack redeployment
- **Cost Optimization**: Zero LLM costs when disabled (`enabled: false`)
- **Simplified Architecture**: No conditional logic in state machines
- **Backward Compatible**: Defaults to `enabled: true` when property is missing

**Behavior When Disabled:**
- Assessment lambda is still called (minimal overhead)
- Service immediately returns with logging: "Assessment is disabled via configuration"
- No LLM API calls or S3 operations are performed
- Document processing continues to completion

**Note:** Prior to v0.4.0, this feature was controlled by the `IsAssessmentEnabled` CloudFormation parameter. The configuration-based approach provides runtime control without requiring stack redeployment.

### Advanced Assessment Configuration

For complex documents with many attributes, enable granular assessment for improved accuracy and performance:

```yaml
assessment:
  enabled: true
  model: us.amazon.nova-lite-v1:0
  granular_mode: true  # Enable granular assessment
  simple_batch_size: 5  # Group simple attributes (3-5 recommended)
  list_batch_size: 1    # Process list items individually for accuracy
  max_workers: 10       # Parallel processing threads
```

**Benefits:**
- Better accuracy through focused prompts
- Cost optimization via prompt caching
- Reduced latency through parallel processing
- Scalability for documents with 100+ attributes

**Ideal For:**
- Bank statements with hundreds of transactions
- Documents with 10+ attributes
- Complex nested structures
- Performance-critical scenarios

For detailed information, see [assessment.md](assessment.md).

## Stack Parameters

Key parameters that can be configured during CloudFormation deployment:

### General Parameters
- `AdminEmail`: Administrator email for web UI access
- `AllowedSignUpEmailDomain`: Optional domain(s) allowed for web UI user signup
- `MaxConcurrentWorkflows`: Control concurrent document processing (default: 100)
- `DataRetentionInDays`: Set retention period for documents and tracking records (default: 365 days)
- `ErrorThreshold`: Number of workflow errors that trigger alerts (default: 1)
- `ExecutionTimeThresholdMs`: Maximum acceptable execution time before alerting (default: 30000 ms)
- `LogLevel`: Set logging level (DEBUG, INFO, WARN, ERROR)
- `WAFAllowedIPv4Ranges`: IP restrictions for web UI access (default: allow all)
- `CloudFrontPriceClass`: Set CloudFront price class for UI distribution
- `CloudFrontAllowedGeos`: Optional geographic restrictions for UI access
- `CustomConfigPath`: Optional S3 URI to a custom configuration file that overrides pattern presets. Leave blank to use selected pattern configuration. Example: s3://my-bucket/custom-config/config.yaml

### Integration and Tracing Parameters
- `EnableXRayTracing`: Enable X-Ray tracing for Lambda functions and Step Functions (default: true). Provides distributed tracing capabilities for debugging and performance analysis.
- `EnableMCP`: Enable Model Context Protocol (MCP) integration for external application access via AWS Bedrock AgentCore Gateway (default: true). See [mcp-integration.md](mcp-integration.md) for details.
- `EnableECRImageScanning`: Enable automatic vulnerability scanning for Lambda container images in ECR for Patterns 1-3 (default: false). Recommended for production deployments but may impact deployment reliability. See [troubleshooting.md](troubleshooting.md) for guidance.

### Pattern Selection
- `IDPPattern`: Select processing pattern:
  - Unified: Supports both BDA and Pipeline processing modes via `use_bda` flag

### Pattern-Specific Parameters
- **Configuration Preset**: `ConfigurationPreset` — Select from available presets (lending-package-sample, bank-statement-sample, etc.)
- **BDA Project ARN**: Optional existing Bedrock Data Automation project ARN (for BDA mode)
- **Custom Model ARNs**: Optional custom fine-tuned classification/extraction model ARNs

> **Note**: The processing mode (BDA vs Pipeline) is controlled by the `use_bda` flag in the configuration, not by deployment parameters. See the [architecture docs](./architecture.md) for details.

- **Pattern 3 (Textract + UDOP + Bedrock)**

### Optional Features
- `EvaluationBaselineBucketName`: Optional existing bucket for ground truth data
- `DocumentKnowledgeBase`: Enable document knowledge base functionality
- `KnowledgeBaseModelId`: Bedrock model for knowledge base queries
- `PostProcessingLambdaHookFunctionArn`: Optional Lambda ARN for custom post-processing (see [post-processing-lambda-hook.md](post-processing-lambda-hook.md) for detailed implementation guidance)
- `BedrockGuardrailId`: Optional Bedrock Guardrail ID to apply
- `BedrockGuardrailVersion`: Version of Bedrock Guardrail to use

For details on processing modes, see [architecture.md](architecture.md). For legacy pattern-specific references, see [pattern-1.md](pattern-1.md) (BDA) and [pattern-2.md](pattern-2.md) (Pipeline).

## High Volume Processing

### Request Service Quota Limits

For high-volume document processing, consider requesting increases for these service quotas:

- **Lambda Concurrent Executions**: Default 1,000 per region
- **Step Functions Executions**: Default 25,000 per second (Standard workflow)
- **Bedrock Model Invocations**: Varies by model and region
  - Claude models: Typically 5-20 requests per minute by default
  - Titan models: 15-30 requests per minute by default
- **SQS Message Rate**: Default 300 per second for FIFO queues
- **TextractLimitPage API**: 15 transactions per second by default
- **DynamoDB Read/Write Capacity**: Uses on-demand capacity by default

Use the AWS Service Quotas console to request increases before deploying for production workloads. See [monitoring.md](monitoring.md) for details on monitoring your resource usage and quotas.

### Cost Estimation

The solution provides built-in cost estimation capabilities:

- Real-time cost tracking for Bedrock model usage
- Per-document processing cost breakdown
- Historical cost analysis and trends
- Budget alerts and threshold monitoring

See [COST_CALCULATOR.md](../COST_CALCULATOR.md) for detailed cost analysis across different processing volumes.

## Bedrock Guardrail Integration

The solution supports Amazon Bedrock Guardrails for content safety and compliance across all patterns:

### How Guardrails Work

Guardrails provide:
- **Content Filtering**: Block harmful, inappropriate, or sensitive content
- **Topic Restrictions**: Prevent processing of specific topic areas
- **Data Protection**: Redact or block personally identifiable information (PII)
- **Custom Filters**: Define organization-specific content policies

### Configuring Guardrails

Guardrails are configured with two CloudFormation parameters:
- `BedrockGuardrailId`: The ID (not name) of an existing Bedrock Guardrail
- `BedrockGuardrailVersion`: The version of the guardrail to use (e.g., "DRAFT" or "1")

This applies guardrails to all Bedrock model interactions, including:
- Document extraction (all patterns)
- Document summarization (all patterns) 
- Document classification (Pattern 2 only)
- Knowledge base queries (if enabled)

### Best Practices

1. **Test Thoroughly**: Validate guardrail behavior with representative documents
2. **Monitor Impact**: Track processing latency and accuracy changes
3. **Regular Updates**: Review and update guardrail policies as requirements evolve
4. **Compliance Alignment**: Ensure guardrails align with organizational compliance requirements

For more information on creating and managing Guardrails, see the [Amazon Bedrock documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html).

## Concurrency and Throttling Management

The solution implements sophisticated concurrency control and throttling management:

### Throttling and Retry (Bedrock, Textract, SageMaker)

- **Exponential Backoff**: Automatic retry with increasing delays
- **Jitter Addition**: Random delay variation to prevent thundering herd
- **Circuit Breaker**: Temporary halt on repeated failures
- **Rate Limiting**: Configurable request rate controls

The solution tracks metrics for throttling events and successful retries, viewable in the CloudWatch dashboard.

### Step Functions Retry Configuration

The Step Functions state machine includes comprehensive retry policies for API failures:

```json
{
  "Retry": [
    {
      "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException"],
      "IntervalSeconds": 2,
      "MaxAttempts": 6,
      "BackoffRate": 2
    },
    {
      "ErrorEquals": ["States.TaskFailed"],
      "IntervalSeconds": 1,
      "MaxAttempts": 3,
      "BackoffRate": 2
    }
  ]
}
```

### Concurrency Control

- **Workflow Limits**: Maximum concurrent Step Function executions, controlled by `MaxConcurrentWorkflows` parameter
- **Lambda Concurrency**: Per-function concurrent execution limits
- **Queue Management**: SQS visibility timeout (30 seconds) and message batching
- **Dynamic Scaling**: Automatic adjustment based on queue depth and in-flight workflows

## Document Status Tracking

The solution provides multiple ways to track document processing status:

### Using the Web UI

The web UI dashboard provides a real-time view of document processing status, including:
- Document status (queued, processing, completed, failed)
- Processing time
- Classification results
- Extraction results
- Error details (if applicable)

See [web-ui.md](web-ui.md) for details on using the dashboard.

### Using the Lookup Script

Use the included script to check document processing status via CLI:

```bash
bash scripts/lookup_file_status.sh <DOCUMENT_KEY> <STACK_NAME>
```

### Response Format

Status lookup returns comprehensive information:

```json
{
  "document_key": "example.pdf",
  "status": "COMPLETED",
  "workflow_arn": "arn:aws:states:...",
  "start_time": "2024-01-01T12:00:00Z",
  "end_time": "2024-01-01T12:05:30Z",
  "processing_time_seconds": 330,
  "pages_processed": 15,
  "document_class": "BankStatement",
  "attributes_found": 12,
  "output_location": "s3://output-bucket/results/example.json",
  "error_details": null
}
```

## Evaluation Extensions in JSON Schema

Document class schemas support evaluation-specific extensions for fine-grained control over accuracy assessment. These extensions work with the [Stickler](https://github.com/awslabs/stickler)-based evaluation framework to provide flexible, business-aligned evaluation capabilities.

### Available Extensions

- `x-aws-idp-evaluation-method`: Comparison method (EXACT, FUZZY, NUMERIC_EXACT, SEMANTIC, LLM, HUNGARIAN)
- `x-aws-idp-evaluation-threshold`: Minimum score to consider a match (0.0-1.0)
- `x-aws-idp-evaluation-weight`: Field importance for weighted scoring (default: 1.0, higher values = more important)

### Example Configuration

```yaml
classes:
  - $schema: "https://json-schema.org/draft/2020-12/schema"
    x-aws-idp-document-type: "Invoice"
    x-aws-idp-evaluation-match-threshold: 0.8  # Document-level threshold
    properties:
      invoice_number:
        type: string
        x-aws-idp-evaluation-method: EXACT
        x-aws-idp-evaluation-weight: 2.0  # Critical field - double weight
      invoice_date:
        type: string
        x-aws-idp-evaluation-method: FUZZY
        x-aws-idp-evaluation-threshold: 0.9
        x-aws-idp-evaluation-weight: 1.5  # Important field
      vendor_name:
        type: string
        x-aws-idp-evaluation-method: FUZZY
        x-aws-idp-evaluation-threshold: 0.85
        x-aws-idp-evaluation-weight: 1.0  # Normal weight (default)
      vendor_notes:
        type: string
        x-aws-idp-evaluation-method: SEMANTIC
        x-aws-idp-evaluation-threshold: 0.7
        x-aws-idp-evaluation-weight: 0.5  # Less critical - half weight
```

### Stickler Backend Integration

The evaluation framework uses [Stickler](https://github.com/awslabs/stickler) as its evaluation engine. The `SticklerConfigMapper` automatically translates these IDP extensions to Stickler's native format, providing:

- **Field-level weighting** for business-critical attributes
- **Optimal list matching** using the Hungarian algorithm
- **Extensible comparator system** with exact, fuzzy, numeric, semantic, and LLM-based comparison
- **Native JSON Schema support** with $ref resolution

### Benefits

1. **Business Alignment**: Weight critical fields higher to ensure evaluation scores reflect business priorities
2. **Flexible Comparison**: Choose the right evaluation method for each field type
3. **Tunable Thresholds**: Set field-specific thresholds for matching sensitivity
4. **Dynamic Schema Generation**: Auto-generates evaluation schema from baseline data when configuration is missing (for development/prototyping)

For detailed evaluation capabilities and best practices, see [evaluation.md](evaluation.md).

## Section Splitting Strategies

Pattern-2 and Pattern-3 support configurable strategies for how classified pages are grouped into document sections. This is controlled by the `sectionSplitting` configuration field:

### Available Strategies

- **`disabled`**: Treats the entire document as a single section with the first detected class. Simplest approach for single-document processing.
  
- **`page`**: Creates one section per page, preventing automatic joining of same-type documents. Useful for deterministic processing of documents containing multiple forms of the same type (e.g., multiple W-2s, multiple invoices in one packet).
  
- **`llm_determined`** (default): Uses LLM boundary detection with "Start"/"Continue" indicators to intelligently segment multi-document packets. Best for complex scenarios where document boundaries are not obvious.

### Configuration Example

```yaml
classification:
  sectionSplitting: page  # or "disabled", "llm_determined"
```

### Use Cases

- **Single Document Processing**: Use `disabled` for simplicity
- **Multiple Same-Type Forms**: Use `page` for deterministic splitting (resolves Issue #146)
- **Complex Multi-Document Packets**: Use `llm_determined` for intelligent boundary detection

For more details on classification methods and section splitting, see [classification.md](classification.md).

### Page Limit Configuration

Control how many pages are used during document classification to optimize performance and costs:

```yaml
classification:
  maxPagesForClassification: "ALL"  # or "1", "2", "3", etc.
```

**Behavior:**
- **"ALL"** (default): Uses all pages for classification
- **Numeric value**: Classifies only the first N pages, then applies that classification to the entire document

**Important:** When using a numeric limit, the classification result from the first N pages is applied to ALL pages, effectively forcing a single class/section for the entire document.

**Use Cases:**
- Performance optimization for large documents
- Cost reduction for documents with consistent patterns
- Simplified processing for homogeneous document types

## Prompt Optimization

### Bedrock Prompt Caching

The solution supports Bedrock prompt caching to reduce costs and improve performance by caching static portions of prompts. This feature is available across all patterns for classification, extraction, assessment, and summarization.

#### How It Works

Insert a `<<CACHEPOINT>>` delimiter in your prompt to separate static (cacheable) content from dynamic content:

```yaml
extraction:
  task_prompt: |
    You are an expert document analyst. Follow these rules:
    - Extract exact values from the document
    - Preserve formatting as it appears
    
    <<CACHEPOINT>>
    
    Document to process:
    {DOCUMENT_TEXT}
```

Everything **before** the `<<CACHEPOINT>>` delimiter is cached and reused across similar requests, while content after it remains dynamic. This can significantly reduce token costs and improve response times.

#### Best Practices

1. **Place Static Content First**: Instructions, rules, schemas, and examples should come before the cachepoint
2. **Dynamic Content Last**: Document text, images, and variable data should come after the cachepoint
3. **Cache Hit Optimization**: Keep static content consistent across requests for maximum cache utilization

#### Benefits

- **Cost Savings**: Cached tokens cost significantly less than regular input tokens
- **Performance**: Reduced processing time for cached content
- **Token Efficiency**: Particularly beneficial for long system prompts or few-shot examples

For pricing details on cached tokens, see [cost-calculator.md](cost-calculator.md).

## Regex-Based Classification (Pattern-2)

Pattern-2 supports optional regex patterns in document class definitions for performance optimization and deterministic classification when patterns are known.

### Configuration

Add regex patterns to your class definitions:

```yaml
classes:
  - name: W2 Tax Form
    description: IRS Form W-2 Wage and Tax Statement
    document_name_regex: "^w2_.*\\.pdf$"  # Matches filenames starting with "w2_"
    document_page_content_regex: "Form W-2.*Wage and Tax Statement"
    
  - name: Invoice
    description: Commercial invoice
    document_name_regex: "^invoice_\\d{6}\\.pdf$"  # Matches invoice_123456.pdf
    document_page_content_regex: "^INVOICE\\s+#\\d+"
```

### Classification Logic

1. **Document Name Matching**: If `document_name_regex` matches the document filename, all pages are classified as that type without LLM processing
2. **Page Content Matching**: During multimodal page-level classification, if `document_page_content_regex` matches page text, that page is classified without LLM processing
3. **Fallback**: If no regex matches, standard LLM classification is used

### Benefits

- **Performance**: Significant speed improvements by bypassing LLM calls for known patterns
- **Cost Savings**: Reduced token consumption for documents matching regex patterns
- **Deterministic**: Consistent classification results for known document patterns
- **Backward Compatible**: Seamless fallback to LLM classification when patterns don't match

### Monitoring

The system logs INFO-level messages when regex patterns match, providing visibility into optimization effectiveness.

For examples and demonstrations, see the `step2_classification_with_regex.ipynb` notebook.

## OCR Backend Configuration (Pattern-2 and Pattern-3)

Patterns 2 and 3 support multiple OCR backend engines for flexible document processing:

### Available Backends

- **Textract** (default): AWS Textract with advanced feature support (TABLES, FORMS, SIGNATURES, LAYOUT)
- **Bedrock**: LLM-based OCR using Claude/Nova models with customizable prompts for better handling of complex documents
- **None**: Image-only processing without OCR (useful for pure visual analysis)

### Configuration Example

```yaml
ocr:
  backend: textract  # or "bedrock", "none"
  
  # For Bedrock backend:
  bedrock_model: us.anthropic.claude-3-5-sonnet-20241022-v2:0
  system_prompt: "You are an OCR expert..."
  task_prompt: "Extract all text from this document..."
```

### Bedrock OCR Benefits

- Better handling of complex layouts and tables
- Customizable extraction logic through prompts
- Layout preservation capabilities
- Support for documents with challenging formatting

For more details on OCR configuration and feature selection, see the pattern-specific documentation.

## Custom Prompt Lambda (Pattern-2 and Pattern-3)

Patterns 2 and 3 support injection of custom business logic into the extraction process through a Lambda function.

### Configuration

Add the Lambda ARN to your extraction configuration:

```yaml
extraction:
  custom_prompt_lambda_arn: arn:aws:lambda:us-west-2:123456789012:function:GENAIIDP-MyCustomLogic
```

### Lambda Interface

Your Lambda receives:
- All template placeholders (DOCUMENT_TEXT, DOCUMENT_CLASS, ATTRIBUTE_NAMES_AND_DESCRIPTIONS, DOCUMENT_IMAGE)
- Complete document context
- Configuration parameters

The Lambda should return modified prompt content or additional context.

### Use Cases

- Document type-specific processing rules
- Integration with external systems for customer configurations
- Conditional processing based on document content
- Regulatory compliance and industry-specific requirements

### Requirements

- Lambda function name must start with `GENAIIDP-` prefix for IAM permissions
- Function must handle JSON serialization for image URIs
- Implement comprehensive error handling (fail-fast behavior)

### Demo Resources

See `notebooks/examples/demo-lambda/` for:
- Interactive demonstration notebook (`step3_extraction_with_custom_lambda.ipynb`)
- SAM deployment template for example Lambda
- Complete documentation and examples

For more details, see [extraction.md](extraction.md).

### Review Agent Model (Agentic Extraction)

For agentic extraction workflows, you can specify a separate model for reviewing extraction work:

```yaml
extraction:
  model: us.amazon.nova-pro-v1:0
  review_agent_model: us.anthropic.claude-3-7-sonnet-20250219-v1:0  # Optional
```

If not specified, defaults to the main extraction model. This allows using a more powerful model for validation while using a cost-effective model for initial extraction.

**Benefits:**
- Cost optimization by using different models for different tasks
- Enhanced accuracy with specialized review model
- Flexibility in model selection for extraction vs. validation

**Use Cases:**
- Use Nova Pro for extraction, Claude Sonnet for review
- Balance between cost and accuracy requirements
- Experimentation with different model combinations

## Cost Tracking and Optimization

The solution includes built-in cost tracking capabilities:

- **Per-document cost metrics**: Track token usage and API calls per document
- **Real-time dashboards**: Monitor costs in the CloudWatch dashboard
- **Cost estimation**: Configuration includes pricing estimates for each component

For detailed cost analysis and optimization strategies, see [cost-calculator.md](cost-calculator.md).

## Image Processing Configuration

The solution supports configurable image dimensions across all processing services (OCR, classification, extraction, and assessment) to optimize performance and accuracy for different document types.

### New Default Behavior (Preserves Original Resolution)

**Important Change**: As of the latest version, empty strings or unspecified image dimensions now preserve the original document resolution instead of resizing to default dimensions.

```yaml
# Preserves original image resolution (recommended for high-accuracy processing)
classification:
  image:
    target_width: ""     # Empty string = no resizing
    target_height: ""    # Empty string = no resizing

extraction:
  image:
    target_width: ""     # Preserves original resolution
    target_height: ""    # Preserves original resolution

assessment:
  image:
    target_width: ""     # No resizing applied
    target_height: ""    # No resizing applied
```

### Custom Image Dimensions

You can still specify exact dimensions when needed for performance optimization:

```yaml
# Custom dimensions for specific requirements
classification:
  image:
    target_width: "1200"   # Resize to 1200 pixels wide
    target_height: "1600"  # Resize to 1600 pixels tall

# Performance-optimized dimensions
extraction:
  image:
    target_width: "800"    # Smaller for faster processing
    target_height: "1000"  # Maintains good quality
```

### Image Resizing Features

- **Aspect Ratio Preservation**: Images are resized proportionally without distortion
- **Smart Scaling**: Only downsizes images when necessary (scale factor < 1.0)
- **High-Quality Resampling**: Better visual quality after resizing
- **Original Format Preservation**: Maintains PNG, JPEG, and other formats when possible

### Configuration Benefits

- **High-Resolution Processing**: Empty strings preserve full document resolution for maximum OCR accuracy
- **Service-Specific Tuning**: Each service can use optimal image dimensions
- **Runtime Configuration**: No code changes needed to adjust image processing
- **Backward Compatibility**: Existing numeric values continue to work as before
- **Memory Optimization**: Configurable dimensions allow resource optimization

### Best Practices

1. **Use Empty Strings for High Accuracy**: For critical documents requiring maximum OCR accuracy, use empty strings to preserve original resolution
2. **Specify Dimensions for Performance**: For high-volume processing, consider smaller dimensions to improve speed
3. **Test Different Settings**: Evaluate the trade-off between accuracy and performance for your specific document types
4. **Monitor Resource Usage**: Higher resolution images consume more memory and processing time

### Migration from Previous Versions

**Previous Behavior**: Empty strings defaulted to 951x1268 pixel resizing
**New Behavior**: Empty strings preserve original image resolution

If you were relying on the previous default resizing behavior, explicitly set dimensions:

```yaml
# To maintain previous default behavior
classification:
  image:
    target_width: "951"
    target_height: "1268"
```

## Additional Configuration Resources

The solution provides additional configuration options through:

- Configuration files in the `config_library` directory
- Pattern-specific settings in each pattern's subdirectory
- Environment variables for Lambda functions
- CloudWatch alarms and notification settings

See the [README.md](../README.md) for a high-level overview of the solution architecture and components.