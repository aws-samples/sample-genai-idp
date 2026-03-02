Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# GenAI IDP Accelerator Configuration Library

This directory serves as a centralized repository for configuration files used with the GenAI Intelligent Document Processing (IDP) Accelerator. It contains various configuration examples for different use cases, allowing users to quickly adapt the accelerator to their specific needs.

## Purpose

The Configuration Library:

- Provides ready-to-use configuration examples for common document processing scenarios
- Demonstrates best practices for configuring the GenAI IDP Accelerator
- Serves as a knowledge base of proven configurations for specific use cases
- Enables teams to share and reuse successful configurations
- Showcases advanced features like few-shot example prompting for improved accuracy

## Processing Modes

The unified architecture supports two processing modes, controlled by the `use_bda` flag:

- **Pipeline mode** (`use_bda: false`, default) — Uses Amazon Textract for OCR, then Bedrock LLM (Nova or Claude) for classification, extraction, assessment, and summarization step by step.
- **BDA mode** (`use_bda: true`) — Uses Bedrock Data Automation for end-to-end processing.

All presets default to pipeline mode. To switch to BDA mode, simply set `use_bda: true` in your configuration — the same class schemas work with both modes.

## System Defaults and Configuration Inheritance

Configurations in this library **inherit from system defaults**, meaning you only need to specify what differs from the defaults. This makes configurations:

- **Simpler** - Only specify `notes`, `classes`, and any intentional overrides
- **Maintainable** - Changes to system defaults automatically apply to all configs
- **Focused** - Easy to see what makes each configuration unique

### Minimal Configuration Example

```yaml
# All settings inherit from system defaults
use_bda: false
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

### Override Example

To override a specific setting:

```yaml
notes: "Configuration with custom classification method"

# Override just the classification method - everything else uses defaults
classification:
  classificationMethod: textbasedHolisticClassification

classes:
  # ... your document classes
```

### System Default Files

System defaults are located in:
```
lib/idp_common_pkg/idp_common/config/system_defaults/
├── pattern-1.yaml    # BDA mode defaults
├── pattern-2.yaml    # Pipeline mode defaults
```

## Few-Shot Example Support

The accelerator supports few-shot example prompting to improve processing accuracy by providing concrete examples of documents and their expected outputs. This is demonstrated in the `unified/rvl-cdip-with-few-shot-examples/` configuration.

## Validation Levels

To help users understand the reliability and testing status of each configuration, we use the following validation level indicators:

- **Level 0 - Experimental**: Configuration has been created but not systematically tested
- **Level 1 - Basic Testing**: Configuration has been tested with a small set of documents
- **Level 2 - Comprehensive Testing**: Configuration has been tested with a diverse set of documents and has shown consistent performance
- **Level 3 - Production Validated**: Configuration has been used in production environments with documented performance metrics

Each configuration's README.md should include its validation level and supporting evidence.

## Directory Structure

```
config_library/
├── README.md                      # This file
├── TEMPLATE_README.md             # Template for new configuration READMEs
├── unified/                       # Configuration presets (use_bda toggles BDA vs pipeline)
│   ├── README.md
│   ├── bank-statement-sample/
│   ├── docsplit/
│   ├── healthcare-multisection-package/
│   ├── lending-package-sample/
│   ├── lending-package-sample-govcloud/
│   ├── ocr-benchmark/
│   ├── realkie-fcc-verified/
│   ├── rule-extraction/
│   ├── rule-validation/
│   ├── rvl-cdip/
│   └── rvl-cdip-with-few-shot-examples/
```

Each configuration directory contains:
- `config.yaml` - The configuration file
- `README.md` - Documentation with validation level
- `samples/` - (Optional) Sample documents for testing

## Creating a New Configuration

To add a new configuration to the library:

1. **Create a new directory** with a descriptive name that reflects the use case:
   ```
   mkdir -p config_library/unified/your_use_case_name
   ```

2. **Create a minimal configuration** - Start with just `notes` and `classes`:
   ```yaml
   use_bda: false
   notes: "Description of your use case"
   
   classes:
     - $schema: https://json-schema.org/draft/2020-12/schema
       $id: YourDocType
       type: object
       x-aws-idp-document-type: YourDocType
       description: "Document description"
       properties:
         # ... your fields
   ```

3. **Add overrides only if needed** - Most configurations don't need to override defaults

4. **Create a README.md** in your use case directory using the TEMPLATE_README.md as a guide. Include:
   - Description of the use case
   - Validation level with supporting evidence
   - Key changes made to the configuration
   - Findings and results
   - Any limitations or considerations

5. **Include sample documents** in a samples/ directory to demonstrate the configuration's effectiveness

6. **Test your configuration** thoroughly before contributing

### Adding Few-Shot Examples

To add few-shot examples to your configuration:

1. **Create example images**: Collect clear, representative document images for each class
2. **Define examples**: Add `x-aws-idp-examples` to each class with:
   - `classPrompt`: Text describing the document class
   - `attributesPrompt`: Expected attribute extraction in JSON format  
   - `imagePath`: Path to the example document image
   - `name`: Descriptive name for the example
3. **Update prompts**: Ensure task prompts include `{FEW_SHOT_EXAMPLES}` placeholder
4. **Test thoroughly**: Validate that examples improve accuracy

## Naming Conventions

- Use lowercase for directory names
- Use hyphens to separate words in directory names
- Choose descriptive names that reflect the use case (e.g., `lending-package-sample`, `bank-statement-sample`)
- Keep names concise but informative

## Best Practices

### Document Classes

- Define classes with clear, specific descriptions
- Include all relevant attributes for each class
- Provide detailed descriptions for each attribute to guide extraction
- Use JSON Schema extensions like `x-aws-idp-evaluation-method` for evaluation

### Few-Shot Examples

- **Quality Examples**: Use clear, representative examples of each document type
- **Diverse Examples**: Include examples that cover edge cases and variations
- **Accurate Labels**: Ensure `attributesPrompt` values are correct and consistent
- **Image Quality**: Use high-resolution, clear images for examples
- **Balanced Coverage**: Provide examples for your most important document classes

### Prompts (Overrides Only)

- Only override prompts when the default behavior doesn't meet your needs
- Keep prompts clear and focused
- Include specific instructions for handling edge cases
- Use consistent formatting and structure
- Include `{FEW_SHOT_EXAMPLES}` placeholder where appropriate

### Model Selection

- Choose models appropriate for the complexity of your task
- Consider cost vs. performance tradeoffs
- Document the rationale for model selection

### Configuration Management

- Document all significant overrides in your README
- Include version information when applicable
- Note any dependencies or requirements

## Contributing

When contributing a new configuration:

1. Ensure your configuration follows the structure and naming conventions
2. Include comprehensive documentation in your README.md with validation level
3. Test your configuration with representative documents
4. Document performance metrics and findings
5. Include sample documents for demonstration and testing
6. If using few-shot examples, demonstrate the capability works correctly

By following these guidelines, we can build a valuable library of configurations that benefit the entire GenAI IDP Accelerator community.
