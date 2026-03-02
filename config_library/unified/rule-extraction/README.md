Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Rule Extraction Configuration

This directory contains the rule extraction configuration for the GenAI IDP Accelerator. This configuration is specifically designed for extracting business rules and compliance requirements from healthcare policy documents, medical coding guidelines, and regulatory documentation.

## Processing Mode

**Default Mode**: Pipeline (use_bda: false) — Uses Amazon Textract for OCR, then Bedrock LLM for classification and extraction. Set use_bda: true for BDA mode.

## Validation Level

**Level**: 2 - Comprehensive Testing

- **Testing Evidence**: This configuration has been tested with healthcare policy documents, medical coding guidelines (NCCI), and regulatory compliance documentation.
- **Known Limitations**: Performance may vary with complex nested rule structures, heavily formatted policy documents, or documents with poor image quality that affect OCR accuracy. Rule extraction accuracy depends on the clarity and structure of the source documentation.

## Overview

The rule extraction configuration is designed to handle policy and guideline documents typically encountered in:

- **Medical Coding Guidelines**: NCCI rules, CPT coding guidelines, modifier requirements
- **Healthcare Policy Documents**: Coverage policies, prior authorization requirements
- **Regulatory Compliance**: CMS guidelines, payer-specific policies
- **Business Rule Documentation**: Internal compliance rules, billing guidelines
- **Clinical Documentation Requirements**: Medical necessity criteria, documentation standards

It includes specialized settings for document classification and structured rule extraction using Amazon Bedrock models optimized for policy document processing.

## Key Components

### Document Classes

The configuration defines specialized document classes for policy and guideline documents, each with attributes for extracting structured rule information:

- **Policy Document**: Coverage policies, authorization requirements, eligibility criteria
- **Coding Guideline**: CPT codes, modifiers, bundling rules, global periods
- **Regulatory Document**: CMS guidelines, compliance requirements, documentation standards
- **Business Rule**: Internal policies, billing rules, claim submission requirements

### Classification Settings

- **Model**: Amazon Nova 2 Lite
- **Method**: Multimodal Page Level Classification
- **Temperature**: 0 (deterministic outputs)
- **Top-k**: 5
- **OCR Backend**: Amazon Textract with LAYOUT features

### Extraction Settings

- **Model**: Amazon Nova 2 Lite
- **Temperature**: 0 (consistent rule extraction)
- **Max Tokens**: 4000 (detailed rule descriptions)
- **Approach**: Structured extraction of rule components including rule text, conditions, exceptions, and supporting references

## Use Cases

This configuration is ideal for:

1. **Policy Digitization**: Converting PDF policy documents into structured, queryable rule databases
2. **Compliance Automation**: Extracting rules for automated validation systems
3. **Rule Management**: Building rule repositories from scattered policy documents
4. **Documentation Analysis**: Understanding and cataloging organizational policies
5. **Regulatory Tracking**: Monitoring changes in healthcare coding guidelines

## Configuration Files

- `config.yaml`: Main configuration file containing document classes, extraction schemas, and model settings

## Getting Started

1. Deploy the IDP stack with the IDP stack
2. Choose "rule-extraction" from the ConfigurationPreset dropdown
3. Upload policy or guideline documents to the input bucket
4. Extracted rules will be available in structured JSON format in the output bucket

## Related Configurations

- **rule-validation**: For validating documents against extracted rules
- **lending-package-sample**: For financial document processing
- **realkie-fcc-verified**: For general document classification and extraction

## Support

For questions or issues with this configuration, please refer to the main documentation or create an issue in the repository.
