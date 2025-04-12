# Changelog


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
