# Changelog

## [Unreleased]


## [0.2.20]
### Added
- Added document summarization functionality
  - New summarization service with default model set to Claude 3 Haiku
  - New summarization function added to all patterns
  - Added end-to-end document summarization notebook example
- Integration of AppSync helper package into idp_common_pkg
- Enhanced the Hungarian evaluation method with configurable comparators
  - Added support for EXACT, FUZZY, and NUMERIC comparators for Hungarian method
  - Implemented a flexible comparator pattern similar to GenAIDP
  - Added dynamic UI form fields based on evaluation method selection
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
  - Added status transitions (QUEUED → STARTED → RUNNING → COMPLETE) for all patterns
- Fixed multi-page standard output BDA processing in Pattern 1
  - Refactored ProcessResults function to correctly handle multi-page result.json files
- Default OCR configuration now includes LAYOUT, TABLES, SIGNATURE, and markdown generation now supports tables (via textractor[pandas])
- Added document reprocessing capability to the UI
  - Implemented reprocess button with confirmation dialog
  - Added backend API for document reprocessing
  
### Changed
- Refactored code for better maintainability
- Updated UI components to support markdown table viewing
- Set default evaluation model to Claude 3 Haiku
- Improved AppSync timeout handling for long-running file copy operations
- Added security headers to UI application per security requirements
- Disabled GraphQL introspection for AppSync API to enhance security
- Added LogLevel parameter to main stack (default WARN level)
- Various bug fixes and improvements

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
