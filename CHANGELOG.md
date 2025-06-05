Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Changelog

## [Unreleased]

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
- **OcrService**: Processes documents with AWS Textract and updates the Document with OCR results
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
