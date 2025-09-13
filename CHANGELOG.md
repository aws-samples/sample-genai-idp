Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Changelog

## [Unreleased]

## [0.3.15]

### Added

- **Intelligent Document Discovery Module for Automated Configuration Generation**
  - Added Discovery module that automatically analyzes document samples to identify structure, field types, and organizational patterns
  - **Pattern-Neutral Design**: Works across all processing patterns (1, 2, 3) with unified discovery process and pattern-specific implementations
  - **Dual Discovery Methods**: Discovery without ground truth (exploratory analysis) and with ground truth (optimization using labeled data)
  - **Automated Blueprint Creation**: Pattern 1 includes zero-touch BDA blueprint generation with intelligent change detection and version management
  - **Web UI Integration**: Real-time discovery job monitoring, interactive results review, and seamless configuration integration
  - **Advanced Features**: Multi-model support (Nova, Claude), customizable prompts, configurable parameters, ground truth processing, schema conversion, and lifecycle management
  - **Key Benefits**: Rapid new document type onboarding, reduced time-to-production, configuration optimization, and automated workflow bootstrapping
  - **Use Cases**: New document exploration, configuration improvement, rapid prototyping, and document understanding
  - **Documentation**: Guide in `docs/discovery.md` with architecture details, best practices, and troubleshooting

- **Optional Pattern-2 Regex-Based Classification for Enhanced Performance**
  - Added support for optional regex patterns in document class definitions for performance optimization
  - **Document Name Regex**: Match against document ID/name to classify all pages without LLM processing when all pages should be the same class
  - **Document Page Content Regex**: Match against page text content during multi-modal page-level classification for fast page classification
  - **Key Benefits**: Significant performance improvements and cost savings by bypassing LLM calls for pattern-matched documents, deterministic classification results for known document patterns, seamless fallback to existing LLM classification when regex patterns don't match
  - **Configuration**: Optional `document_name_regex` and `document_page_content_regex` fields in class definitions with automatic regex compilation and validation
  - **Logging**: Comprehensive info-level logging when regex patterns match for observability and debugging
  - **CloudFormation Integration**: Updated Pattern-2 schema to support regex configuration through the Web UI
  - **Demonstration**: New `step2_classification_with_regex.ipynb` notebook showcasing regex configuration and performance comparisons
  - **Documentation**: Enhanced classification module README and main documentation with regex usage examples and best practices
  
- **Windows WSL Development Environment Setup Guide**
  - Added WSL-based development environment setup guide for Windows developers in `docs/setup-development-env-WSL.md`
  - **Key Features**: Automated setup script (`wsl_setup.sh`) for quick installation of Git, Python, Node.js, AWS CLI, and SAM CLI
  - **Integrated Workflow**: Development setup combining Windows tools (VS Code, browsers) with native Linux environment
  - **Target Use Cases**: Windows developers needing Linux compatibility without Docker Desktop or VM overhead

### Fixed
- **Throttling Error Detection and Retry Logic for Assessment Functions** - [GitHub Issue #45](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/45)
  - **Assessment Function**: Enhanced throttling detection to check for throttling errors returned in `document.errors` field in addition to thrown exceptions, raising `ThrottlingException` to trigger Step Functions retry when throttling is detected
  - **Granular Assessment Task Caching**: Fixed caching logic to properly cache successful assessment tasks when there are ANY failed tasks (both exception-based and result-based failures), enabling efficient retry optimization by only reprocessing failed tasks while preserving successful results
  - **Impact**: Improved resilience for throttling scenarios, reduced redundant processing during retries, and better Step Functions retry behavior

- **Security Vulnerability Mitigation - Package Updates**

- **GovCloud Compatibility - Hardcoded Service Domain References**
  - Fixed hardcoded `amazonaws.com` references in CloudFormation templates that prevented GovCloud deployment
  - Updated all service principals and endpoints to use dynamic `${AWS::URLSuffix}` expressions for automatic region-based resolution
  - **Templates Updated**: `template.yaml` (main template), `patterns/pattern-3/sagemaker_classifier_endpoint.yaml`
  - **Services Fixed**: EventBridge, Cognito, SageMaker, ECR, CloudFront, CodeBuild, AppSync, Lambda, DynamoDB, CloudWatch Logs, Glue
  - Resolves GitHub Issue #50 - templates now deploy correctly in both standard AWS and GovCloud regions

- **Bug Fixes and Code Improvements**
  - Fixed HITL processing errors in both Pattern-1 (DynamoDB validation with empty strings) and Pattern-2 (string indices error in A2I output processing)
  - Fixed Step Function UI issues including auto-refresh button auto-disable and fetch failures for failed executions with datetime serialization errors
  - Cleaned up unused Step Function subscription infrastructure and removed duplicate code in Pattern-2 HITL function
  - Expanded UI Visual Editor bounding box size with padding for better visibility and user interaction
  - Fixed bug in list of models supporting cache points - previously claude 4 sonnet and opus had been excluded.
  - Validations added at the assessment step for checking valid json response. The validation fails after extraction/assessment is complete if json parsing issues are encountered.


## [0.3.14]

### Added
- Support for 1m token context for Claude Sonnet 4
- Video demo of "Chat with Document" in [./docs/web-ui.md](./docs/web-ui.md)
- **Human-in-the-Loop (HITL) Support Extended to Pattern-2**
  - Added HITL review capabilities for Pattern-2 (Textract + Bedrock processing) using Amazon SageMaker Augmented AI (A2I)
  - Enables human validation and correction when extraction confidence falls below configurable threshold
  - Includes same features as Pattern-1 HITL: automatic triggering, review portal integration, and seamless result updates
  - Documentation and video demo in [./docs/human-review.md](./docs/human-review.md)

### Removed
- Windows development environment guide and setup script removed as it proved insufficiently robust

### Fixed
- Fix 1-click Launch URL output from the GovCloud template generation script
- Add Agent Analytics to architecture diagram
- Fix various UX and error reporting issues with the new Python publish script
- Simplify UDOP model path construction and avoid invalid default for regions other than us-east-1 and us-west-2
- Permission regression from previous release affecting "Chat with Document"


## [0.3.13]

### Added

- **External MCP Agent Integration for Custom Tool Extension**
  - Added External MCP (Model Context Protocol) Agent support that enables integration with custom MCP servers to extend IDP capabilities
  - **Cross-Account Integration**: Host MCP servers in separate AWS accounts or external infrastructure with secure OAuth authentication using AWS Cognito
  - **Dynamic Tool Discovery**: Automatically discovers and integrates available tools from MCP servers through the IDP web interface
  - **Secure Authentication Flow**: Uses AWS Cognito User Pools for OAuth bearer token authentication with proper token validation
  - **Configuration Management**: JSON array configuration in AWS Secrets Manager supporting multiple MCP server connections with optional custom agent names and descriptions
  - **Real-time Integration**: Tools become immediately available through the IDP web interface after configuration

- **AWS GovCloud Support with Automated Template Generation**
  - Added GovCloud compatibility through `scripts/generate_govcloud_template.py` script
  - **ARN Partition Compatibility**: All templates updated to use `arn:${AWS::Partition}:` for both commercial and GovCloud regions
  - **Headless Operation**: Automatically removes UI-related resources (CloudFront, AppSync, Cognito, WAF) for GovCloud deployment
  - **Core Functionality Preserved**: All 3 processing patterns and complete 6-step pipeline (OCR, Classification, Extraction, Assessment, Summarization, Evaluation) remain fully functional
  - **Automated Workflow**: Single script orchestrates build + GovCloud template generation + S3 upload with deployment URLs
  - **Enterprise Ready**: Enables headless document processing for government and enterprise environments requiring GovCloud compliance
  - **Documentation**: New `docs/govcloud-deployment.md` with deployment guide, architecture differences, and access methods

- **Pattern-2 and Pattern-3 Assessment now generate geometry (bounding boxes) for visualization in UI 'Visual Editor' (parity with Pattern-1)**
  - Added comprehensive spatial localization capabilities to both regular and granular assessment services
  - **Automatic Processing**: When LLM provides bbox coordinates, automatically converts to UI-compatible (Visual Edit) geometry format without any configuration
  - **Universal Support**: Works with all attribute types - simple attributes, nested group attributes (e.g., CompanyAddress.State), and list attributes
  - **Enhanced Prompts**: Updated assessment task prompts with spatial-localization-guidelines requesting bbox coordinates in normalized 0-1000 scale
  - **Demo Notebooks**: Assessment notebooks now showcase automatic bounding box processing

- **New Python-Based Publishing System**
  - Replaced `publish.sh` bash script with new `publish.py` Python script
  - Rich console interface with progress bars, spinners, and colored output using Rich library
  - Multi-threaded artifact building and uploading for significantly improved performance
  - Native support for Linux, macOS, and Windows environments

- **Windows Development Environment Setup Guide and Helper Script**
  - New `scripts/dev_setup.bat` (570 lines) for complete Windows development environment configuration

- **OCR Service Default Image Sizing for Resource Optimization**
  - Implemented automatic default image size limits (951×1268) when no image sizing configuration is provided
  - **Key Benefits**: Reduction in vision model token consumption, prevents OutOfMemory errors during concurrent processing, improves processing speed and reduces bandwidth usage

### Changed

- **Reverted to python3.12 runtime to resolve build package dependency problems**

### Fixed
- **Improved Visual Edit bounding box position when using image zoom or pan**



## [0.3.12]

### Added

- **Custom Prompt Generator Lambda Support for Patterns 2 & 3**
  - Added `custom_prompt_lambda_arn` configuration field to enable injection of custom business logic into extraction processing
  - **Key Features**: Lambda interface with all template placeholders (DOCUMENT_TEXT, DOCUMENT_CLASS, ATTRIBUTE_NAMES_AND_DESCRIPTIONS, DOCUMENT_IMAGE), URI-based image handling for JSON serialization, comprehensive error handling with fail-fast behavior, scoped IAM permissions requiring GENAIIDP-* function naming
  - **Use Cases**: Document type-specific processing rules, integration with external systems for customer configurations, conditional processing based on document content, regulatory compliance and industry-specific requirements
  - **Demo Resources**: Interactive notebook demonstration (`step3_extraction_with_custom_lambda.ipynb`), SAM deployment template for demo Lambda function, comprehensive documentation and examples in `notebooks/examples/demo-lambda/`
  - **Benefits**: Custom business logic without core code changes, backward compatible (existing deployments unchanged), robust JSON serialization handling all object types, complete observability with detailed logging

- **Refactored Document Classification Service for Enhanced Boundary Detection**
  - Consolidated `multimodalPageLevelClassification` and the experimental `multimodalPageBoundaryClassification` (from v0.3.11) into a single enhanced `multimodalPageLevelClassification` method
  - Implemented BIO-like sequence segmentation with document boundary indicators: "start" (new document) and "continue" (same document)
  - Automatically segments multi-document packets, even when they contain multiple documents of the same type
  - Added comprehensive classification guide with method comparisons and best practices
  - **Benefits**: Simplified codebase with single multimodal classification method, improved handling of complex document packets, maintains backward compatibility
  - **No Breaking Changes**: Existing configurations work unchanged, no configuration updates required

- **Enhanced A2I Template and Workflow Management**
  - Enhanced A2I template with improved user interface and clearer instructions for reviewers
  - Added comprehensive instructions for reviewers in A2I template to guide the review process
  - Implemented capture of failed review tasks with proper error handling and logging
  - Added workflow orchestration control to stop processing when reviewer rejects A2I task
  - Removed automatic A2I task creation when Pattern-1 Bedrock Data Automation (BDA) fails to classify document to appropriate Blueprint

- **Dynamic Cost Calculation for Metering Data**
  - Added automated unit cost and estimated cost calculation to metering table with new `unit_cost` and `estimated_cost` columns
  - Dynamic pricing configuration loading from configuration
  - Enhanced cost analysis capabilities with comprehensive Athena queries for cost tracking, trend analysis, and efficiency metrics
  - Automatic cost calculation as `estimated_cost = value × unit_cost` for all metering records
  
- **Configuration-Based Summarization Control**
  - Summarization can now be enabled/disabled via configuration file `summarization.enabled` property instead of CloudFormation stack parameter
  - **Key Benefits**: Runtime control without stack redeployment, zero LLM costs when disabled, simplified state machine architecture, backward compatible defaults
  - **Implementation**: Always calls SummarizationStep but service skips processing when `enabled: false`
  - **Cost Optimization**: When disabled, no LLM API calls or S3 operations are performed
  - **Configuration Example**: Set `summarization.enabled: false` to disable, `enabled: true` to enable (default)

- **Configuration-Based Assessment Control**
  - Assessment can now be enabled/disabled via configuration file `assessment.enabled` property instead of CloudFormation stack parameter
  - **Key Benefits**: Runtime control without stack redeployment, zero LLM costs when disabled, simplified state machine architecture, backward compatible defaults
  - **Implementation**: Always calls AssessmentStep but service skips processing when `enabled: false`
  - **Cost Optimization**: When disabled, no LLM API calls or S3 operations are performed
  - **Configuration Example**: Set `assessment.enabled: false` to disable, `enabled: true` to enable (default)

- **New guides for setting up development environments**
  - EC2-based Linux development environment
  - MacOS development environment

### Removed
- **CloudFormation Parameters**: Removed `IsSummarizationEnabled` and `IsAssessmentEnabled` parameters from all pattern templates
- **Related Conditions**: Removed parameter conditions and state machine definition substitutions for both features
- **Conditional Logic**: Eliminated complex conditional logic from state machine definitions for summarization and assessment steps

### ⚠️ Breaking Changes
- **Configuration Migration Required**: When updating a stack that previously had `IsSummarizationEnabled` or `IsAssessmentEnabled` set to `false`, these features will now default to `enabled: true` after the update. To maintain the disabled behavior:
  1. Update your configuration file to set `summarization.enabled: false` and/or `assessment.enabled: false` as needed
  2. Save the configuration changes immediately after the stack update
  3. This ensures continued cost optimization by preventing unexpected LLM API calls
- **Action Required**: Review your current CloudFormation parameter settings before updating and update your configuration accordingly to preserve existing behavior

### Changed
- **Updated Python Lambda Runtime to 3.13**

### Fixed
- **Fixed B615 "Unsafe Hugging Face Hub download without revision pinning" security finding in Pattern-3 fine-tuning module** - Added revision pinning with to prevent supply chain attacks and ensure reproducible deployments
- **Fixed CloudWatch Log Group Missing Retention regression**
- **Security: Cross-Site Scripting (XSS) Vulnerability in FileViewer Component** - Fixed high-risk XSS vulnerability in `src/ui/src/components/document-viewer/FileViewer.jsx` where `innerHTML` was used with user-controlled data
- **Add permissions boundary support to new Lambda function roles introduced in previous releases**
- **Fixed OutOfMemory Errors in Pattern-2 OCR Lambda for Large High-Resolution Documents**
  - **Root Cause**: Processing large PDFs with high-resolution images (7469×9623 pixels) caused memory spikes when 20 concurrent workers each held ~101MB images simultaneously, exceeding the 4GB Lambda memory limit
  - **Optimal Solution**: Refactored image extraction to render directly at target dimensions using PyMuPDF matrix transformations, completely eliminating oversized image creation

## [0.3.11]

### Added

- **Chat with Document** now available at the bottom of the each Document Detail page.
- **Anthropic Claude Opus 4.1** model available in configuration for all document processing steps
- **Browser tab icon** now features a blue background with a white "IDP"
- **Experimental new classification method** - multimodalPageBoundaryClassification - for detecting section boundaries during page level classification.

## [0.3.10]

### Added

- **Agent Analysis Feature for Natural Language Document Analytics**
  - Added integrated AI-powered analytics agent that enables natural language querying of processed document data
  - **Key Capabilities**: Convert natural language questions to SQL queries, generate interactive visualizations and tables, explore database schema automatically
  - **Secure Architecture**: All Python code execution happens in isolated AWS Bedrock AgentCore sandboxes, not in Lambda functions
  - **Multi-Tool Agent System**: Database discovery tool for schema exploration, Athena query tool for SQL execution, secure code sandbox for data transfer, Python visualization tool for charts and tables
  - **Example Use Cases**: Query document processing volumes and trends, analyze confidence scores and extraction accuracy, explore document classifications and content patterns, generate custom charts and data tables
  - **Sample W2 Test Data**: Includes 20 synthetic W2 tax documents for testing analytics capabilities
  - **Configurable Models**: Supports multiple AI models including Claude 3.7 Sonnet (default), Claude 3.5 Sonnet, Nova Pro/Lite, and Haiku
  - **Web UI Integration**: Accessible through "Document Analytics" section with real-time progress display and query history

- **Automatic Glue Table Creation for Document Sections**
  - Added automatic creation of AWS Glue tables for each document section type (classification) during processing
  - Tables are created dynamically when new section types are encountered, eliminating manual table creation
  - Consistent lowercase naming convention for tables ensures compatibility with case-sensitive S3 paths
  - Tables are configured with partition projection for efficient date-based queries without manual partition management
  - Automatic schema evolution - tables update when new fields are detected in extraction results

## [0.3.9]

### Added
- **Optional Permissions Boundary Support for Enterprise Deployments**
  - Added `PermissionsBoundaryArn` parameter to all CloudFormation templates for organizations with Service Control Policies (SCPs) requiring permissions boundaries
  - Comprehensive support for both explicit IAM roles and implicit roles created by AWS SAM functions and statemachines`
  - Conditional implementation ensures backward compatibility - when no permissions boundary is provided, roles deploy normally

### Added
- IDP Configuration and Prompting Best Practices documentation [doc](./docs/idp-configuration-best-practices.md)

### Changed

- Updated lending_package.pdf sample with more realistic driver's license image

### Fixed
- Issue #27 - removed idp_common bedrock client region default to us-west-2 - PR #28



## [0.3.8]

### Added

- **Lending Package Configuration Support for Pattern-2**
  - Added new `lending-package-sample` configuration to Pattern-2, providing comprehensive support for lending and financial document processing workflows
  - New default configuration for Pattern-2 stack deployments, optimized for loan applications, mortgage processing, and financial verification documents
  - Previous `rvl-cdip-sample` configuration remains available by selecting `rvl-cdip-package-sample` for the `Pattern2Configuration` parameter when deploying or updating stacks

- **Text Confidence View for Document Pages**
  - Added support for displaying OCR text confidence data through new `TextConfidenceUri` field
  - New "Text Confidence View" option in the UI pages panel alongside existing Markdown and Text views
  - Fixed issues with view persistence - Text Confidence View button now always visible with appropriate messaging when content unavailable
  - Fixed view toggle behavior - switching between views no longer closes the viewer window
  - Reordered view buttons to: Markdown View, Text Confidence View, Text View for better user experience

- **Enhanced OCR DPI Configuration for PDF files**
  - DPI for PDF image conversion is now configurable in the configuration editor under OCR image processing settings
  - Default DPI improved from 96 to 150 DPI for better default quality and OCR accuracy
  - Configurable through Web UI without requiring code changes or redeployment

### Changed

- **Converted text confidence data format from JSON to markdown table for improved readability and reduced token usage**
  - Removed unnecessary "page_count" field
  - Changed "text_blocks" array to "text" field containing a markdown table with Text and Confidence columns
  - Reduces prompt size for assessment service while improving UI readability
  - OCR confidence values now rounded to 1 decimal point (e.g., 99.1, 87.3) for cleaner display
  - Markdown table headers now explicitly left-aligned using `|:-----|:-----------|` format for consistent appearance

- **Simplified OCR Service Initialization**
  - OCR service now accepts a single `config` dictionary parameter for cleaner, more consistent API
  - Aligned with classification service pattern for better consistency across IDP services
  - Backward compatibility maintained - old parameter pattern still supported with deprecation warning
  - Updated all lambda functions and notebooks to use new simplified pattern
- Removed fixed image target_height and target_width from default configurations, so images are processed in original resolution by default.

- **Updated Default Configuration for Pattern1 and Pattern2**
  - Changed default configuration for new stacks from "default" to "lending-package-sample" for both Pattern1 and Pattern2
  - Maintains backward compatibility for stack updates by keeping the parameter value "default" mapped to the rvl-cdip-sample for pattern-2.

- **Reduce assessment step costs**
  - Default model for granular assessment is now `us.amazon.nova-lite-v1:0` - experimentation recommended
  - Improved placement of <<CACHEPOINT>> tags in assessment prompt to improve utilization of prompt caching

### Fixed

- **Fixed Image Resizing Behavior for High-Resolution Documents**
  - Fixed issue where empty strings in image configuration were incorrectly resizing images to default 951x1268 pixels instead of preserving original resolution
  - Empty strings (`""`) in `target_width` and `target_height` configuration now preserve original document resolution for maximum processing accuracy
- Fixed issue where PNG files were being unnecessarily converted to JPEG format and resized to lower resolution with lost quality
- Fixed issue where PNG and JPG image files were not rendering inline in the Document Details page
- Fixed issue where PDF files were being downloaded instead of displayed inline
- Fixed pricing data for cacheWrite tokens for Amazon Nova models to resolve innacurate cost estimation in UI.


## [0.3.7]

### Added

- **Criteria Validation Service Class**
  - New  document validation service that evaluates documents against dynamic business rules using Large Language Models (LLMs)
  - **Key Capabilities**: Dynamic business rules configuration, asynchronous processing with concurrent criteria evaluation, intelligent text chunking for large documents, multi-file processing with summarization, comprehensive cost and performance tracking
  - **Primary Use Cases**: Healthcare prior authorization workflows, compliance validation, business rule enforcement, quality assurance, and audit preparation
  - **Architecture Features**: Seamless integration with IDP pipeline using common Bedrock client, unified metering with automatic token usage tracking, S3 operations using standardized file operations, configuration compatibility with existing IDP config system
  - **Advanced Features**: Configurable criteria questions without code changes, robust error handling with graceful degradation, Pydantic-based input/output validation with automatic data cleaning, comprehensive timing metrics and token usage tracking
  - **Limitation**: Python idp_common support only, not yet implemented within deployed pattern workflows.


- **Document Process Flow Visualization**
  - Added interactive visualization of Step Functions workflow execution for document processing
  - Visual representation of processing steps with status indicators and execution details
  - Detailed step information including inputs, outputs, and error messages
  - Timeline view showing chronological execution of all processing steps
  - Auto-refresh capability for monitoring active executions in real-time
  - Support for Map state visualization with iteration details
  - Error diagnostics with detailed error messages for troubleshooting
  - Automatic selection of failed steps for quick issue identification

- **Granular Assessment Service for Scalable Confidence Evaluation**
  - New granular assessment approach that breaks down assessment into smaller, focused tasks for improved accuracy and performance
  - **Key Benefits**: Better accuracy through focused prompts, cost optimization via prompt caching, reduced latency through parallel processing, and scalability for complex documents
  - **Task Types**: Simple batch tasks (groups 3-5 simple attributes), group tasks (individual group attributes), and list item tasks (individual list items for maximum accuracy)
  - **Configuration**: Configurable batch sizes (`simple_batch_size`, `list_batch_size`) and parallel processing (`max_workers`) for performance tuning
  - **Prompt Caching**: Leverages LLM caching capabilities with cached base content (document context, images, OCR data) and dynamic task-specific content
  - **Use Cases**: Ideal for bank statements with hundreds of transactions, documents with 10+ attributes, complex nested structures, and performance-critical scenarios
  - **Backward Compatibility**: Maintains same interface as standard assessment service with seamless migration path
  - **Enhanced Documentation**: Comprehensive documentation in `docs/assessment.md` and example notebooks for both standard and granular approaches

- **Reporting Database now has Document Sections Tables to enable querying across document fields**
  - Added comprehensive document sections storage system that automatically creates tables for each section type (classification)
  - **Dynamic Table Creation**: AWS Glue Crawler automatically discovers new section types and creates corresponding tables (e.g., `invoice`, `receipt`, `bank_statement`)
  - **Configurable Crawler Schedule**: Support for manual, every 15 minutes, hourly, or daily (default) crawler execution via `DocumentSectionsCrawlerFrequency` parameter
  - **Partitioned Storage**: Data organized by section type and date for efficient querying with Amazon Athena

- **Partition Projections for Evaluation and Metering tables**
  - **Automated Partition Management**: Eliminates need for `MSCK REPAIR TABLE` operations with projection-based partition discovery
  - **Performance Benefits**: Athena can efficiently prune partitions based on date ranges without manual partition loading
  - **Backward Compatibility Warning**: The partition structure change from `year=2024/month=03/day=15/` to `date=2024-03-15/` means that data saved in the evaluation or metering tables prior to v0.3.7 will not be visible in Athena queries after updating. To retain access to historical data, you can either:
    - Manually reorganize existing S3 data to match the new partition structure
    - Create separate Athena tables pointing to the old partition structure for historical queries


- **Optimize the classification process for single class configurations in Pattern-2**
  - Detects when only a single document class is defined in the configuration
  - Automatically classifies all document pages as that single class
  - Creates a single section containing all pages
  - Bypasses the backend service calls (Bedrock or SageMaker) completely
  - Logs an INFO message indicating the optimization is active

- **Skip the extraction process for classes with no attributes in Pattern 2/3**
  - Add early detection logic in extraction class to check for empty/missing attributes
  - Return zero metering data and empty JSON results when no attributes defined

- **Enhanced State Machine Optimization for Very Large Documents**
  - Improved document compression to store only section IDs rather than full section objects
  - Modified state machine workflow to eliminate nested result structures and reduce payload size
  - Added OutputPath filtering to remove intermediate results from state machine execution
  - Streamlined assessment step to replace extraction results instead of nesting them
  - Resolves "size exceeding the maximum number of bytes service limit" errors for documents with 500+ pages

### Changed
- **Default behavior for image attachment in Pattern-2 and Pattern3**
  - If the prompt contains a `{DOCUMENT_IMAGE}` placeholder, keep the current behavior (insert image at placeholder)
  - If the prompt does NOT contain a `{DOCUMENT_IMAGE}` placeholder, do NOT attach the image at all
  - Previously, if the (classification or extraction) prompt did NOT contain a `{DOCUMENT_IMAGE}` placeholder, the image was appended at the end of the content array anyway
- **Modified default assessment prompt for token efficiency**
  - Removed `confidence_reason` from output to avoid consuming unnecessary output tokens
  - Refactored task_prompt layout to improve <<CACHEPOINT>> placement for efficiency when granular mode is enabled or disabled
- **Enhanced .clinerules with comprehensive memory bank workflows**
  - Enhanced Plan Mode workflow with requirements gathering, reasoning, and user approval loop

### Fixed
- Fixed UI list deletion issue where empty lists were not saved correctly - #18
- Improve structure and clarity for idp_common Python package documentation
- Improved UI in View/Edit Configuration to clarify that Class and Attribute descriptions are used in the classification and extraction prompts
- Automate UI updates for field "HITL (A2I) Status" in the Document list and document details section.
- Fixed image display issue in PagesPanel where URLs containing special characters (commas, spaces) would fail to load by properly URL-encoding S3 object keys in presigned URL generation

## [0.3.6]

### Fixed
- Update Athena/Glue table configuration to use Parquet format instead of JSON #20
- Cloudformation Error when Changing Evaluation Bucket Name #19

### Added
- **Extended Document Format Support in OCR Service**
  - Added support for processing additional document formats beyond PDF and images:
    - Plain text (.txt) files with automatic pagination for large documents
    - CSV (.csv) files with table visualization and structured output
    - Excel workbooks (.xlsx, .xls) with multi-sheet support (each sheet as a page)
    - Word documents (.docx, .doc) with text extraction and visual representation
  - **Key Features**:
    - Consistent processing model across all document formats
    - Standard page image generation for all formats
    - Structured text output in formats compatible with existing extraction pipelines
    - Confidence metrics for all document types
    - Automatic format detection from file content and extension
  - **Implementation Details**:
    - Format-specific processing strategies for optimal results
    - Enhanced text rendering for plain text documents
    - Table visualization for CSV and Excel data
    - Word document paragraph extraction with formatting preservation
    - S3 storage integration matching existing PDF processing workflow

## [0.3.5]

### Added
- **Human-in-the-Loop (HITL) Support - Pattern 1**
  - Added comprehensive Human-in-the-Loop review capabilities using Amazon SageMaker Augmented AI (A2I)
  - **Key Features**:
    - Automatic triggering when extraction confidence falls below configurable threshold
    - Integration with SageMaker A2I Review Portal for human validation and correction
    - Configurable confidence threshold through Web UI Portal Configuration tab (0.0-1.0 range)
    - Seamless result integration with human-verified data automatically updating source results
  - **Workflow Integration**: 
    - HITL tasks created automatically when confidence thresholds are not met
    - Reviewers can validate correct extractions or make necessary corrections through the Review Portal
    - Document processing continues with human-verified data after review completion
  - **Configuration Management**:
    - `EnableHITL` parameter for feature toggle
    - Confidence threshold configurable via Web UI without stack redeployment
    - Support for existing private workforce work teams via input parameter
  - **CloudFormation Output**: Added `SageMakerA2IReviewPortalURL` for easy access to review portal
  - **Known Limitations**: Current A2I version cannot provide direct hyperlinks to specific document tasks; template updates require resource recreation
- **Document Compression for Large Documents - all patterns**
  - Added automatic compression support to handle large documents and avoid exceeding Step Functions payload limits (256KB)
  - **Key Features**:
    - Automatic compression (default trigger threshold of 0KB enables compression by default)
    - Transparent handling of both compressed and uncompressed documents in Lambda functions
    - Temporary S3 storage for compressed document state with automatic cleanup via lifecycle policies
  - **New Utility Methods**:
    - `Document.load_document()`: Automatically detects and decompresses document input from Lambda events
    - `Document.serialize_document()`: Automatically compresses large documents for Lambda responses
    - `Document.compress()` and `Document.decompress()`: Compression/decompression methods
  - **Lambda Function Integration**: All relevant Lambda functions updated to use compression utilities
  - **Resolves Step Functions Errors**: Eliminates "result with a size exceeding the maximum number of bytes service limit" errors for large multi-page documents
- **Multi-Backend OCR Support - Pattern 2 and 3**
  - Textract Backend (default): Existing AWS Textract functionality
  - Bedrock Backend: New LLM-based OCR using Claude/Nova models
  - None Backend: Image-only processing without OCR
- **Bedrock OCR Integration - Pattern 2 and 3**
  - Customizable system and task prompts for OCR optimization
  - Better handling of complex documents, tables, and forms
  - Layout preservation capabilities
- **Image Preprocessing - Pattern 2**
  - Adaptive Binarization: Improves OCR accuracy on documents with:
    - Uneven lighting or shadows
    - Low contrast text
    - Background noise or gradients
  - Optional feature with configurable enable/disable
- **YAML Parsing Support for LLM Responses - Pattern 2 and 3**
  - Added comprehensive YAML parsing capabilities to complement existing JSON parsing functionality
  - New `extract_yaml_from_text()` function with robust multi-strategy YAML extraction:
    - YAML in ```yaml and ```yml code blocks
    - YAML with document markers (---)
    - Pattern-based YAML detection using indentation and key indicators
  - New `detect_format()` function for automatic format detection returning 'json', 'yaml', or 'unknown'
  - New unified `extract_structured_data_from_text()` wrapper function that automatically detects and parses both JSON and YAML formats
  - **Token Efficiency**: YAML typically uses 10-30% fewer tokens than equivalent JSON due to more compact syntax
  - **Service Integration**: Updated classification service to use the new unified parsing function with automatic fallback between formats
  - **Comprehensive Testing**: Added 39 new unit tests covering all YAML extraction strategies, format detection, and edge cases
  - **Backward Compatibility**: All existing JSON functionality preserved unchanged, new functionality is purely additive
  - **Intelligent Fallback**: Robust fallback mechanism handles cases where preferred format fails (e.g., JSON requested as YAML falls back to JSON)
  - **Production Ready**: Handles malformed content gracefully, comprehensive error handling and logging
  - **Example Notebook**: Added `notebooks/examples/step3_extraction_using_yaml.ipynb` demonstrating YAML-based extraction with automatic format detection and token efficiency benefits

### Fixed
- **Enhanced JSON Extraction from LLM Responses (Issue #16)**
  - Modularized duplicate `_extract_json()` functions across classification, extraction, summarization, and assessment services into a common `extract_json_from_text()` utility function
  - Improved multi-line JSON handling with literal newlines in string values that previously caused parsing failures
  - Added robust JSON validation and multiple fallback strategies for better extraction reliability
  - Enhanced string parsing with proper escape sequence handling for quotes and newlines
  - Added comprehensive unit tests covering various JSON formats including multi-line scenarios

## [0.3.4]

### Added
- **Configurable Image Processing and Enhanced Resizing Logic**
  - **Improved Image Resizing Algorithm**: Enhanced aspect-ratio preserving scaling that only downsizes when necessary (scale factor < 1.0) to prevent image distortion
  - **Configurable Image Dimensions**: All processing services (Assessment, Classification, Extraction, OCR) now support configurable image dimensions through configuration with default 951×1268 resolution
  - **Service-Specific Image Optimization**: Each service can use optimal image dimensions for performance and quality tuning
  - **Enhanced OCR Service**: Added configurable DPI for PDF-to-image conversion and optional image resizing with dual image strategy (stores original high-DPI images while using resized images for processing)
  - **Runtime Configuration**: No code changes needed to adjust image processing - all configurable through service configuration
  - **Backward Compatibility**: Default values maintain existing behavior with no immediate action required for existing deployments
- **Enhanced Configuration Management**
  - **Save as Default**: New button to save current configuration as the new default baseline with confirmation modal and version upgrade warnings
  - **Export Configuration**: Export current configuration to local files in JSON or YAML format with customizable filename
  - **Import Configuration**: Import configuration from local JSON or YAML files with automatic format detection and validation
  - Enhanced Lambda resolver with deep merge functionality for proper default configuration updates
  - Automatic custom configuration reset when saving as default to maintain clean state
- **Nested Attribute Groups and Lists Support**
  - Enhanced document configuration schema to support complex nested attribute structures with three attribute types:
    - **Simple attributes**: Single-value extractions (existing behavior)
    - **Group attributes**: Nested object structures with sub-attributes (e.g., address with street, city, state)
    - **List attributes**: Arrays with item templates containing multiple attributes per item (e.g., transactions with date, amount, description)
  - **Web UI Enhancements**: Configuration editor now supports viewing and editing nested attribute structures with proper validation
  - **Extraction Service Updates**: Enhanced `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` placeholder processing to generate formatted prompts for nested structures
  - **Assessment Service Enhancements**: Added support for nested structure confidence evaluation with recursive processing of group and list attributes, including proper confidence threshold application from configuration
  - **Evaluation Service Improvements**: 
    - Implemented pattern matching for list attributes (e.g., `Transactions[].Date` maps to `Transactions[0].Date`, `Transactions[1].Date`)
    - Added data flattening for complex extraction results using dot notation and array indices
    - Fixed numerical sorting for list items (now sorts 0, 1, 2, ..., 10, 11 instead of alphabetically)
    - Individual evaluation methods applied per nested attribute (EXACT, FUZZY, SEMANTIC, etc.)
  - **Documentation**: Comprehensive updates to evaluation docs and README files with nested structure examples and processing explanations
  - **Use Cases**: Enables complex document processing for bank statements (account details + transactions), invoices (vendor info + line items), and medical records (patient info + procedures)

- **Enhanced Documentation and Examples**
  - New example notebooks with improved clarity, modularity, and documentation

- **Evaluation Framework Enhancements**
  - Added confidence threshold to evaluation outputs to enable prioritizing accuracy results for attributes with higher confidence thresholds

- **Comprehensive Metering Data Collection**
  - The system now captures and stores detailed metering data for analytics, including:
    - Which services were used (Textract, Bedrock, etc.)
    - What operations were performed (analyze_document, Claude, etc.)
    - How many resources were consumed (pages, tokens, etc.)

- **Reporting Database Documentation**
  - Added comprehensive reporting database documentation

### Changed
- Pin packages to tested versions to avoid vulnerability from incompatible new package versions.
- Updated reporting data to use document's queued_time for consistent timestamps
- Create new extensible SaveReportingData class in idp_common package for saving evaluation results to Parquet format
- Remove save_to_reporting from evaluation_function and replace with Lambda invocation, for smaller Lambda packages and better modularity.
- Harden publish process and avoid package version bloat by purging previous build artifacts before re-building

### Fixed
- Defend against non-numeric confidence_threshold values in the configuration - avoid float conversion or numeric comparison exceptions in Assessement step
- Prevent creation of empty configuration fields in UI
- Firefox browser issues with signed URLs (PR #14)
- Improved S3 Partition Key Format for Better Date Range Filtering:
  - Updated reporting data partition keys to use YYYY-MM format for month and YYYY-MM-DD format for day
  - Enables easier date range filtering in analytics queries across different months and years
  - Partition structure now: `year=2024/month=2024-03/day=2024-03-15/` instead of `year=2024/month=03/day=15/`

## [0.3.3]

### Added

- **Amazon Nova Model Fine-tuning Support**
  - Added comprehensive `ModelFinetuningService` class for managing Nova model fine-tuning workflows
  - Support for fine-tuning Amazon Nova models (Nova Lite, Nova Pro) using Amazon Bedrock
  - Complete end-to-end workflow including dataset preparation, job creation, provisioned throughput management, and inference
  - CLI tools for fine-tuning workflow:
    - `prepare_nova_finetuning_data.py` - Dataset preparation from RVL-CDIP or custom datasets
    - `create_finetuning_job.py` - Fine-tuning job creation with automatic IAM role setup
    - `create_provisioned_throughput.py` - Provisioned throughput management for fine-tuned models
    - `inference_example.py` - Model inference and evaluation with comparison capabilities
  - CloudFormation integration with new parameters:
    - `CustomClassificationModelARN` - Support for custom fine-tuned classification models in Pattern-2
    - `CustomExtractionModelARN` - Support for custom fine-tuned extraction models in Pattern-2
  - Automatic integration of fine-tuned models in classification and extraction model selection dropdowns
  - Comprehensive documentation in `docs/nova-finetuning.md` with step-by-step instructions
  - Example notebooks:
    - `finetuning_dataset_prep.ipynb` - Interactive dataset preparation
    - `finetuning_model_service_demo.ipynb` - Service usage demonstration
    - `finetuning_model_document_classification_evaluation.ipynb` - Model evaluation
  - Built-in support for Bedrock fine-tuning format with multi-modal capabilities
  - Data splitting and validation set creation
  - Cost optimization features including provisioned throughput deletion
  - Performance metrics and accuracy evaluation tools

- **Assessment Feature for Extraction Confidence Evaluation (EXPERIMENTAL)**
  - Added new assessment service that evaluates extraction confidence using LLMs to analyze extraction results against source documents
  - Multi-modal assessment capability combining text analysis with document images for comprehensive confidence scoring
  - UI integration with explainability_info display showing per-attribute confidence scores, thresholds, and explanations
  - Optional deployment controlled by `IsAssessmentEnabled` parameter (defaults to false)
  - Added e2e-example-with-assessment.ipynb notebook for testing assessment workflow

- **Enhanced Evaluation Framework with Confidence Integration**
  - Added confidence fields to evaluation reports for quality analysis
  - Automatic extraction and display of confidence scores from assessment explainability_info
  - Enhanced JSON and Markdown evaluation reports with confidence columns
  - Backward compatible integration - shows "N/A" when confidence data unavailable

- **Evaluation Analytics Database and Reporting System**
  - Added comprehensive ReportingDatabase (AWS Glue) with structured evaluation metrics storage
  - Three-tier analytics tables: document_evaluations, section_evaluations, and attribute_evaluations
  - Automatic partitioning by date and document for efficient querying with Amazon Athena
  - Detailed metrics tracking including accuracy, precision, recall, F1 score, execution time, and evaluation methods
  - Added evaluation_reporting_analytics.ipynb notebook for comprehensive performance analysis and visualization
  - Multi-level analytics with document, section, and attribute-level insights
  - Visual dashboards showing accuracy distributions, performance trends, and problematic patterns
  - Configurable filters for date ranges, document types, and evaluation thresholds
  - Integration with existing evaluation framework - metrics automatically saved to database
  - ReportingDatabase output added to CloudFormation template for easy reference

### Fixed
- Fixed build failure related to pandas, numpy, and PyMuPDF dependency conflicts in the idp_common_pkg package
- Fixed deployment failure caused by CodeBuild project timeout, by raising TimeoutInMinutes property
- Added missing cached token metrics to CloudWatch dashboards
- Added Bedrock model access prerequisite to README and deployment doc.

## [0.3.2]

### Added

- **Cost Estimator UI Feature for Context Grouping and Subtotals**
  - Added context grouping functionality to organize cost estimates by logical categories (e.g. OCR, Classification, etc.)
  - Implemented subtotal calculations for better cost breakdown visualization

- **DynamoDB Caching for Resilient Classification**
  - Added optional DynamoDB caching to the multimodal page-level classification service to improve efficiency and resilience
  - Cache successful page classification results to avoid redundant processing during retries when some pages fail due to throttling
  - Exception-safe caching preserves successful work even when individual threads or the overall process fails
  - Configurable via `cache_table` parameter or `CLASSIFICATION_CACHE_TABLE` environment variable
  - Cache entries scoped to document ID and workflow execution ARN with automatic TTL cleanup (24 hours)
  - Significant cost reduction and improved retry performance for large multi-page documents

### Fixed
- "Use as Evaluation Baseline" incorrectly sets document status back to QUEUED. It should remain as COMPLETED.


## [0.3.1]

### Added

- **{DOCUMENT_IMAGE} Placeholder Support in Pattern-2**
  - Added new `{DOCUMENT_IMAGE}` placeholder for precise image positioning in classification and extraction prompts
  - Enables strategic placement of document images within prompt templates for enhanced multimodal understanding
  - Supports both single images and multi-page documents (up to 20 images per Bedrock constraints)
  - Full backward compatibility - existing prompts without placeholder continue to work unchanged
  - Seamless integration with existing `{FEW_SHOT_EXAMPLES}` functionality
  - Added warning logging when image limits are exceeded to help with debugging
  - Enhanced documentation across classification.md, extraction.md, few-shot-examples.md, and pattern-2.md

### Fixed
- When encountering excessive Bedrock throttling, service returned 'unclassified' instead of retrying, when using multi-modal page level classification method.
- Minor documentation issues.

## [0.3.0]

### Added

- **Visual Edit Feature for Document Processing**
  - Interactive visual interface for editing extracted document data combining document image display with overlay annotations and form-based editing.
  - Split-Pane Layout, showing page image(s) and extraction inference results side by side 
  - Zoom & Pan Controls for page image
  - Bounding Box Overlay System (Pattern-1 BDA only)
  - Confidence Scores (Pattern-1 BDA only)
  - **User Experience Benefits**
    - Visual context showing exactly where data was extracted from in original documents
    - Precision editing with visual verification ensuring accuracy of extracted data
    - Real-time visual connection between form fields and document locations
    - Efficient workflow eliminating context switching between viewing and editing

- **Enhanced Few Shot Example Support in Pattern-2**
  - Added comprehensive few shot learning capabilities to improve classification and extraction accuracy
  - Support for example-based prompting with concrete document examples and expected outputs
  - Configuration of few shot examples through document class definitions with `examples` field
  - Each example includes `name`, `classPrompt`, `attributesPrompt`, and `imagePath` parameters
  - **Enhanced imagePath Support**: Now supports single files, local directories, or S3 prefixes with multiple images
    - Automatic discovery of all image files with supported extensions (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`)
    - Images sorted alphabetically in prompt by filename for consistent ordering
  - Automatic integration of examples into classification and extraction prompts via `{FEW_SHOT_EXAMPLES}` placeholder
  - Demonstrated in `config_library/pattern-2/few_shot_example` configuration with letter, email, and multi-page bank-statement examples
  - Environment variable support for path resolution (`CONFIGURATION_BUCKET` and `ROOT_DIR`)
  - Updated documentation in classification and extraction README files and Pattern-2 few-shot examples guide

- **Bedrock Prompt Caching Support**
  - Added support for `<<CACHEPOINT>>` delimiter in prompts to enable Bedrock prompt caching
  - Prompts can now be split into static (cacheable) and dynamic sections for improved performance and cost optimization
  - Available in classification, extraction, and summarization prompts across all patterns
  - Automatic detection and processing of cache point delimiters in BedrockClient

- **Configuration Library Support**
  - Added `config_library/` directory with pre-built configuration templates for all patterns
  - Configuration now loaded from S3 URIs instead of being defined inline in CloudFormation templates
  - Support for multiple configuration presets per pattern (e.g., default, checkboxed_attributes_extraction, medical_records_summarization, few_shot_example)
  - New `ConfigurationDefaultS3Uri` parameter allows specifying custom S3 configuration sources
  - Enhanced configuration management with separation of infrastructure and business logic

### Fixed
- **Lambda Configuration Reload Issue**
  - Fixed lambda functions loading configuration globally which prevented configuration updates from being picked up during warm starts

### Changed
- **Simplified Model Configuration Architecture**
  - Removed individual model parameters from main template: `Pattern1SummarizationModel`, `Pattern2ClassificationModel`, `Pattern2ExtractionModel`, `Pattern2SummarizationModel`, `Pattern3ExtractionModel`, `Pattern3SummarizationModel`, `EvaluationLLMModelId`
  - Model selection now handled through enum constraints in UpdateSchemaConfig sections within each pattern template
  - Added centralized `IsSummarizationEnabled` parameter (true|false) to control summarization functionality across all patterns
  - Updated all pattern templates to use new boolean parameter instead of checking if model is "DISABLED"
  - Refactored IsSummarizationEnabled conditions in all pattern templates to use the new parameter
  - Maintained backward compatibility while significantly reducing parameter complexity

- **Documentation Restructure**
  - Simplified and condensed README
  - Added new ./docs folder with detailed documentation
  - New Contribution Guidelines
  - GitHub Issue Templates
  - Added documentation clarifying the separation between GenAIIDP solution issues and underlying AWS service concerns

## [0.2.20]
### Added
- Added document summarization functionality
  - New summarization service with default model set to Claude 3 Haiku
  - New summarization function added to all patterns
  - Added end-to-end document summarization notebook example
- Added Bedrock Guardrail integration
  - New parameters BedrockGuardrailId and BedrockGuardrailVersion for optional guardrail configuration
  - Support for applying guardrails in Bedrock model invocations (except classification)
  - Added guardrail functionality to Knowledge Base queries
  - Enhanced security and content safety for model interactions
- Improved performance with parallelized operations
  - Enhanced EvaluationService with multi-threaded processing for faster evaluation
    - Parallel processing of document sections using ThreadPoolExecutor
    - Intelligent attribute evaluation parallelization with LLM-specific optimizations
    - Dynamic batch sizing based on workload for optimal resource utilization
  - Reimplemented Copy to Baseline functionality with asynchronous processing
    - Asynchronous Lambda invocation pattern for processing large document collections
    - EvaluationStatus-based progress tracking and UI integration
    - Batch-based S3 object copying for improved efficiency
    - File operation batching with optimal batch size calculation
- Fine-grained document status tracking for UI real-time progress updates
  - Added status transitions (QUEUED → STARTED → RUNNING → OCR → CLASSIFYING → EXTRACTING → POSTPROCESSING → SUMMARIZING → COMPLETE)
- Default OCR configuration now includes LAYOUT, TABLES, SIGNATURE, and markdown generation now supports tables (via textractor[pandas])
- Added document reprocessing capability to the UI - New "Reprocess" button with confirmation dialog
  
### Changed
- Refactored code for better maintainability
- Updated UI components to support markdown table viewing
- Set default evaluation model to Claude 3 Haiku
- Improved AppSync timeout handling for long-running file copy operations
- Added security headers to UI application per security requirements
- Disabled GraphQL introspection for AppSync API to enhance security
- Added LogLevel parameter to main stack (default WARN level)
- Integration of AppSync helper package into idp_common_pkg
- Various bug fixes and improvements
- Enhanced the Hungarian evaluation method with configurable comparators
- Added dynamic UI form fields based on evaluation method selection
- Fixed multi-page standard output BDA processing in Pattern 1

## [0.2.19]
- Added enhanced EvaluationService with smart attribute discovery and evaluation
  - Automatically discovers and evaluates attributes not defined in configuration
  - Applies default semantic evaluation to unconfigured attributes using LLM method
  - Handles all attribute cases: in both expected/actual, only in expected, only in actual
  - Added new demo notebook examples showing smart attribute discovery in action
- Added SEMANTIC evaluation method using embedding-based comparison


## [0.2.18]
- Improved error handling in service classes
- Support for enum config schema and corresponding picklist in UI. Used for Textract feature selection.
- Removed LLM model choices preserving only multi-modal modals that support multiple image attachments
- Added support for textbased holistic packet classification in Pattern 2
- New holistic classification method in ClassifierService for multi-document packet processing
- Added new example notebook "e2e-holistic-packet-classification.ipynb" demonstrating the holistic classification approach
- Updated Pattern 2 template with parameter for ClassificationMethod selection (multimodalPageLevelClassification or textbasedHolisticClassification)
- Enhanced documentation and READMEs with information about classification methods
- Reorganized main README.md structure for improved navigation and readability

## [0.2.17]

### Enhanced Textract OCR Features
- Added support for Textract advanced features (TABLES, FORMS, SIGNATURES, LAYOUT)
- OCR results now output in rich markdown format for better visualization
- Configurable OCR feature selection through schema configuration
- Improved metering and tracking for different Textract feature combinations

## [0.2.16] 

### Add additional model choice
- Claude, Nova, Meta, and DeepSeek model selection now available

### New Document-Based Architecture

The `idp_common_pkg` introduces a unified Document model approach for consistent document processing:

#### Core Classes
- **Document**: Central data model that tracks document state through the entire processing pipeline
- **Page**: Represents individual document pages with OCR results and classification
- **Section**: Represents logical document sections with classification and extraction results

#### Service Classes
- **OcrService**: Processes documents with AWS Textract or Amazon Bedrock and updates the Document with OCR results
- **ClassificationService**: Classifies document pages/sections using Bedrock or SageMaker backends
- **ExtractionService**: Extracts structured information from document sections using Bedrock

### Pattern Implementation Updates
- Lambda functions refactored, and significantly simplified, to use Document and Section objects, and new Service classes

### Key Benefits

1. **Simplified Integration**: Consistent interfaces make service integration straightforward
2. **Improved Maintainability**: Unified data model reduces code duplication and complexity
3. **Better Error Handling**: Standardized approach to error capture and reporting
4. **Enhanced Traceability**: Complete document history throughout the processing pipeline
5. **Flexible Backend Support**: Easy switching between Bedrock and SageMaker backends
6. **Optimized Resource Usage**: Focused document processing for better performance
7. **Granular Package Installation**: Install only required components with extras syntax

### Example Notebook

A new comprehensive Jupyter notebook demonstrates the Document-based workflow:
- Shows complete end-to-end processing (OCR → Classification → Extraction)
- Uses AWS services (S3, Textract, Bedrock)
- Demonstrates Document object creation and manipulation
- Showcases how to access and utilize extraction results
- Provides a template for custom implementations
- Includes granular package installation examples (`pip install "idp_common_pkg[ocr,classification,extraction]"`)

This refactoring sets the foundation for more maintainable, extensible document processing workflows with clearer data flow and easier troubleshooting.

### Refactored publish.sh script
 - improved modularity with functions
 - improved checksum logic to determine when to rebuild components
