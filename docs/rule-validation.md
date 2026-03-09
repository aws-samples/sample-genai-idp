# Rule Validation

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

## Overview

Rule Validation automatically checks if your documents meet specific business rules and compliance requirements. It uses AI to evaluate documents against predefined criteria, making it useful for any industry that needs to validate documents against policies or regulations.

**Common Uses:**
- Healthcare: Checking prior authorizations, validating medical coding rules
- Financial Services: Verifying loan applications, checking compliance
- Legal: Reviewing contract clauses, ensuring regulatory compliance
- Insurance: Validating claims, checking policy compliance
- Manufacturing: Quality control checks, specification compliance

The healthcare examples we provide show what's possible, but you can customize this for any industry.

## Getting Started

### How to Enable Rule Validation

Rule Validation is available in **Pipeline mode** (the default processing mode). You can enable it in two ways:

**Option 1: During Stack Deployment**
- When deploying the CloudFormation stack, select the **rule-validation** configuration preset
- In the configuration dropdown, select **rule-validation**
- The stack deploys with rule validation enabled

**Option 2: Import After Deployment**
- Open the IDP-ACC Web UI
- Navigate to Configuration → Import
- Select **rule-validation** from the Config Library
- Toggle on Rule Validation

### Two-Step Process for Any Industry

Rule validation works for any industry using this two-step process:

#### Step 1: Extract Rules from Your Policy Documents (Optional)

**What you need:**
- A policy document containing your rules (PDF format)
  - Examples: compliance manuals, regulatory guidelines, coding policies, underwriting rules

**How to do it:**
1. **Enable Rule Extraction**
   - Option A: Deploy stack with the **rule-extraction** configuration preset
   - Option B: Import **rule-extraction** from Config Library in the UI

2. **Upload Your Policy Document**
   - Click "Upload Document" in the Web UI
   - Select your policy document
   - System automatically extracts structured rules

3. **Review and Export Rules**
   - View extracted rule types and individual rules
   - Review for accuracy
   - Copy the rules you want to use for validation

**Skip this step if:** You already have your rules in a structured format.

#### Step 2: Validate Your Documents Against Rules

**What you need:**
- Rules to validate against (from Step 1 or your own structured rules)
- Documents to validate (PDF format)
  - Examples: applications, claims, authorization requests, contracts

**How to do it:**
1. **Enable Rule Validation**
   - Option A: Deploy stack with the **rule-validation** configuration preset
   - Option B: Import **rule-validation** from Config Library in the UI

2. **Configure Document Schema**
   - Go to Configuration → **Document Schema** tab
   - Define your document sections (e.g., Applicant Info, Financial Data, Supporting Docs)
   - Specify what attributes to extract from each section
   - These extracted attributes provide context to the AI for better validation

3. **Configure Rule Schema**
   - Go to Configuration → **Rule Schema** tab
   - Paste the rules from Step 1 (or your own rules)
   - Organize into rule types
   - Add detailed descriptions for each rule

4. **Upload and Process Documents**
   - Upload documents to validate
   - System automatically processes and validates against your rules
   - View results showing Pass/Fail for each rule with detailed reasoning

**Coming Soon**: We're working on combining both steps into a single unified application.

### Quick Start with Healthcare Example

Want to see it in action first? We provide a complete healthcare example with sample documents and pre-configured rules. See the [Healthcare Example](#healthcare-prior-authorization-example) section below for step-by-step instructions using:
- **Sample prior authorization document**: `samples/rule-validation/respiratory_pa_packet.pdf`
  - Synthetic multi-page respiratory therapy prior authorization request
  - Contains multiple sections: patient information, clinical information, evidence documents, operative logs, and claims data
- **Sample NCCI policy manual**: `samples/rule-validation/NCCI Medicare Policy Manual.pdf`
  - Source: [CMS NCCI Policy Manual Chapter 5 (2024)](https://www.cms.gov/files/document/medicare-ncci-policy-manual-2024-chapter-5.pdf)
  - Contains medical coding rules and guidelines
- Pre-configured rule extraction and validation configs

## Key Features

- **Multi-Level Validation Workflow**: Section-level evaluation, rule type consolidation, and orchestrated summary generation
- **Asynchronous Processing**: Concurrent evaluation of multiple rules with built-in rate limiting
- **Intelligent Chunking**: Page-aware text chunking that preserves page boundaries and context
  - `chunks_created: 0` = No chunking (section processed as whole)
  - `chunks_created: 2+` = Section split into multiple chunks with 10% overlap
- **Customizable Recommendations**: User-defined recommendation options (e.g., Pass/Fail, Compliant/Non-Compliant)
- **Dynamic Statistics**: Automatic generation of recommendation counts based on actual results
- **Comprehensive Tracking**: Token usage, timing metrics, supporting page references, and chunking metadata
- **Dual Output Formats**: JSON for programmatic access and Markdown for human review
- **Robust Error Handling**: Graceful degradation with fallback responses

## Architecture

### Rule Validation Workflow

1. **Section-Level Evaluation**: Each document section is evaluated against all configured rule types
   - Rules are processed concurrently with semaphore-based rate limiting
   - Page-aware chunking handles large sections while preserving context
   - Results stored in S3 for each section

2. **Rule Type Consolidation**: Multiple section responses are consolidated per rule
   - LLM analyzes all evidence across sections
   - Generates single consolidated recommendation per rule
   - Aggregates supporting page references

3. **Orchestrated Summary Generation**: Final summary with statistics and reports
   - Dynamic recommendation counts (e.g., {"Pass": 10, "Fail": 2})
   - Overall statistics by rule type
   - JSON and Markdown output formats

### State Machine Integration

Rule validation is integrated into the pipeline mode workflow after extraction:

```
OCR → Classification → Extraction → Rule Validation → Orchestration
```

The workflow uses AWS Step Functions Map state to process sections in parallel, then consolidates results in a final orchestration step.

## Configuration

### Two-Step Rule Validation Approach

Rule validation uses a two-step approach to improve accuracy and handle large documents effectively:

1. **Fact Extraction**: Extracts relevant facts from document sections
2. **Orchestrator**: Consolidates facts and makes final compliance decisions

This separation provides several benefits:
- Large documents can be processed in chunks without losing context
- Fact-finding is separated from decision-making for clearer reasoning
- Multiple pieces of evidence are synthesized into accurate compliance determinations

### Basic Configuration

Configure rule validation in your pattern configuration file:

```yaml
rule_validation:
  enabled: true
  semaphore: 5  # Max concurrent API calls
  max_chunk_size: 8000  # Characters per chunk
  overlap_percentage: 10  # Chunk overlap for context
  
  recommendation_options: |
    Pass: The requirement criteria are fully met.
    Fail: The requirement is partially met or requires additional information.
    Information Not Found: No relevant data exists in the user history.
  
  # Step 1: Fact Extraction Configuration
  fact_extraction:
    model: us.anthropic.claude-sonnet-4-5-20250929-v1:0
    temperature: 0.0
    top_k: 20
    top_p: 0.01
    max_tokens: 4096
    system_prompt: |
      You are a specialized fact extraction assistant...
    task_prompt: |
      Extract relevant facts from the document text for the given rule.
      Document Text: {DOCUMENT_TEXT}
      Rule Type: {rule_type}
      Rule: {rule}
  
  # Step 2: Orchestrator Configuration
  rule_validation_orchestrator:
    model: us.anthropic.claude-sonnet-4-5-20250929-v1:0
    temperature: 0.0
    top_k: 20
    top_p: 0.01
    max_tokens: 4096
    system_prompt: |
      You are a compliance decision orchestrator...
    task_prompt: |
      Based on the extracted evidence, determine compliance.
      Extracted Evidence: {extracted_evidence}
      Policy Class: {policy_class}
      Rule: {rule}
```

### Configuration Parameters

**Common Parameters** (top level):
- `enabled`: Turns rule validation on or off
- `semaphore`: Maximum number of concurrent API calls (default: 5)
- `max_chunk_size`: Maximum characters per chunk (default: 8000)
- `overlap_percentage`: Percentage of overlap between chunks to preserve context (default: 10%)
- `recommendation_options`: Custom recommendation categories for your use case

**Fact Extraction Parameters**:
- `model`: The LLM model to use for extracting facts
- `temperature`: Controls randomness in responses (0.0 = fully deterministic)
- `system_prompt`: Defines the role and behavior of the fact extraction assistant
- `task_prompt`: Instructions for extracting facts, with these placeholders:
  - `{DOCUMENT_TEXT}`: The actual document content
  - `{rule_type}`: The category of rule being evaluated
  - `{rule}`: The specific rule text

**Orchestrator Parameters**:
- `model`: The LLM model to use for making compliance decisions
- `temperature`: Controls randomness in responses (0.0 = fully deterministic)
- `system_prompt`: Defines the role and behavior of the compliance orchestrator
- `task_prompt`: Instructions for making decisions, with these placeholders:
  - `{extracted_evidence}`: Facts gathered from all chunks and sections
  - `{policy_class}`: The category of rule being evaluated
  - `{rule}`: The specific rule text

### Rule Classes

Define rule types and specific rules to evaluate:

```yaml
rule_classes:
  - rule_type: "global_periods"
    questions:
      - "If a procedure has a global period of 000 or 010 days, it is defined as a minor surgical procedure..."
      - "If a procedure has a global period of 090 days, it is defined as a major surgical procedure..."
  
  - rule_type: "same_day_service_rules"
    questions:
      - "Since National Correct Coding Initiative (NCCI) Procedure-to-Procedure (PTP) edits are applied..."
```

### Document Classes

Specify which document types should be validated:

```yaml
classes:
  - name: "PA-Administrative"
    description: "Prior Authorization administrative information"
    attributes:
      - name: "patient_name"
        description: "Full name of the patient"
      - name: "insurance_policy_number"
        description: "Insurance policy or member ID"
```

## Customizing Recommendation Options

The default recommendation options are Pass/Fail/Information Not Found, but you can customize these for your specific use case:

### Healthcare Compliance Example

```yaml
rule_validation:
  recommendation_options: |
    Compliant: Fully meets regulatory requirements.
    Non-Compliant: Does not meet requirements.
    Requires Review: Manual review needed.
    Not Applicable: Rule does not apply to this case.
```

### Financial Audit Example

```yaml
rule_validation:
  recommendation_options: |
    Approved: All criteria satisfied.
    Rejected: Criteria not met.
    Pending: Additional documentation required.

rule_classes:
  - rule_type: "loan_eligibility"
    questions:
      - "Applicant must have minimum credit score of 650..."
      - "Debt-to-income ratio must not exceed 43%..."
  
  - rule_type: "documentation_requirements"
    questions:
      - "Two years of tax returns must be provided..."
      - "Proof of employment must be current within 30 days..."
```

The statistics in the final summary will automatically use your custom options:

```json
{
  "recommendation_counts": {
    "Compliant": 15,
    "Non-Compliant": 3,
    "Requires Review": 2
  }
}
```

## Rule Configuration Best Practices

### Writing Effective Rules

1. **Be Specific**: Include clear criteria and conditions
   ```yaml
   questions:
     - "If a procedure has a global period of 090 days AND an E&M service is performed on the same date..."
   ```

2. **Provide Context**: Include relevant definitions and examples
   ```yaml
   questions:
     - "CPT code 31500 describes an emergency endotracheal intubation. For example, if intubation is performed in a rapidly deteriorating patient..."
   ```

3. **Structure Complex Rules**: Use JSON format for rules with multiple components
   ```yaml
   questions:
     - |
       {
         "cpt_codes_affected": ["31500"],
         "rule_text": "If laryngoscopy is required...",
         "bundled_services": ["laryngoscopy for elective or emergency placement"],
         "separately_reportable_conditions": ["intubation in rapidly deteriorating patient"]
       }
   ```

### Organizing Rule Types

Group related rules into logical rule types:

```yaml
rule_classes:
  - rule_type: "eligibility_rules"
    questions:
      - "Patient must be enrolled in insurance plan..."
      - "Coverage must be active on date of service..."
  
  - rule_type: "medical_necessity"
    questions:
      - "Procedure must be medically necessary..."
      - "Documentation must support diagnosis..."
```

## Output Formats

### JSON Output

Located at `s3://{bucket}/{document_id}/rule_validation/consolidated/consolidated_summary.json`:

```json
{
  "document_id": "doc_123",
  "overall_status": "COMPLETE",
  "total_rule_types": 4,
  "overall_statistics": {
    "total_rules": 15,
    "recommendation_counts": {
      "Pass": 12,
      "Fail": 2,
      "Information Not Found": 1
    }
  },
  "rule_summary": {
    "global_periods": {
      "status": "COMPLETE",
      "total_rules": 2,
      "Pass": 2,
      "Fail": 0
    }
  },
  "supporting_pages": ["1", "2", "3", "5"]
}
```

### Markdown Output

Located at `s3://{bucket}/{document_id}/rule_validation/consolidated/consolidated_summary.md`:

```markdown
# Rule Validation Summary

**Document ID:** doc_123
**Status:** COMPLETE
**Total Rule Types:** 4

## Overall Statistics

**Total Rules:** 15
**Pass:** 12
**Fail:** 2
**Information Not Found:** 1

## Rule Type: global_periods

**Total Rules:** 2
**Pass:** 2

### Rules

| Rule | Recommendation | Reasoning | Supporting Pages |
|------|----------------|-----------|------------------|
| Minor surgery rule | Pass | Evidence found on page 1... | 1, 3 |
```

## Performance Optimization

### Rate Limiting

Control concurrent API calls to prevent throttling:

```yaml
rule_validation:
  semaphore: 5  # Adjust based on your API limits
```

### Prompt Caching

Place static content before the `<<CACHEPOINT>>` marker and dynamic content after:

```yaml
task_prompt: |
  You are an insurance evaluator...
  
  <<CACHEPOINT>>
  
  {recommendation_options}
  
  <user_history>
  {DOCUMENT_TEXT}
  </user_history>
```

This caches the static instructions and only processes the dynamic document content, reducing costs.

### Chunking Configuration

Adjust chunking parameters for your document sizes:

```yaml
rule_validation:
  max_chunk_size: 8000  # Increase for longer documents
  overlap_percentage: 10  # Increase for more context preservation
```

## Integration with Extraction

Rule validation works seamlessly with extraction results:

1. **Extraction Phase**: Extracts structured data from documents
2. **Rule Validation Phase**: Validates extracted data against business rules
3. **Combined Output**: Both extraction and validation results available in document object

Access both results:

```python
# Extraction results
extraction_uri = section.extraction_result_uri
extraction_data = s3.get_json_content(extraction_uri)

# Rule validation results
validation_uri = document.rule_validation_result.output_uri
validation_data = s3.get_json_content(validation_uri)
```

## Monitoring and Debugging

### CloudWatch Metrics

Monitor rule validation performance:
- Execution duration per section
- Token usage and costs
- Error rates and types

### Logs

Check CloudWatch logs for:
- `rule-validation-function`: Section-level evaluation logs
- `rule-validation-orchestration-function`: Orchestration logs

### Common Issues

**High Token Usage**: 
- Reduce `max_chunk_size`
- Optimize rule descriptions
- Use prompt caching effectively

**Slow Processing**:
- Increase `semaphore` value
- Reduce number of rules
- Use faster model (e.g., Claude Haiku)

**Inconsistent Results**:
- Set `temperature: 0` for deterministic output
- Improve rule clarity and specificity
- Add more context in rule descriptions

## Cost Considerations

Rule validation costs depend on:
- Number of rules evaluated
- Document size and chunking
- Model selection
- Prompt caching effectiveness

**Cost Optimization Tips**:
1. Use prompt caching (can reduce costs by 50-90%)
2. Choose appropriate model (Haiku for simple rules, Sonnet for complex)
3. Minimize rule redundancy
4. Optimize chunk sizes to reduce API calls

## API Reference

For detailed API documentation, see the [Rule Validation Module README](../lib/idp_common_pkg/idp_common/rule_validation/README.md).

## Examples

### Healthcare Prior Authorization Example

We provide a complete healthcare example demonstrating prior authorization validation against NCCI medical coding rules.

**Sample Documents:**
- **Prior Authorization Document**: `samples/rule-validation/respiratory_pa_packet.pdf`
  - Synthetic multi-page respiratory therapy prior authorization request
  - Contains multiple sections:
    - Patient Information (demographics, insurance details)
    - Clinical Information (diagnoses, medical history)
    - Evidence Documents (supporting clinical documentation)
    - Operative Logs (procedure details, CPT codes)
    - Claims Data (billing information, service dates)
  
- **NCCI Policy Manual**: `samples/rule-validation/NCCI Medicare Policy Manual.pdf`
  - National Correct Coding Initiative policy reference
  - Source: [CMS NCCI Policy Manual Chapter 5 (2024)](https://www.cms.gov/files/document/medicare-ncci-policy-manual-2024-chapter-5.pdf)
  - Contains medical coding rules, bundling guidelines, and compliance requirements

**Configuration Files:**
- **Step 1 - Rule Extraction**: `config_library/unified/rule-extraction/config.yaml`
- **Step 2 - Rule Validation**: `config_library/unified/rule-validation/config.yaml`

This example includes:
- NCCI coding rules
- Global period validation
- Same-day service rules
- Bundling and component service rules
- Prior authorization document classes

**Note**: This is a reference implementation. You can replace these rules with your own domain-specific requirements.

### Testing with Notebooks

For hands-on examples, see:
`notebooks/misc/e2e-holistic-packet-classification-rule-validation.ipynb`

This notebook demonstrates:
- Loading and configuring rule validation
- Processing document sections
- Consolidating results
- Viewing output formats

## Best Practices

1. **Start Simple**: Begin with a few clear rules and expand gradually
2. **Test Thoroughly**: Validate rules against known good/bad examples
3. **Monitor Costs**: Track token usage and optimize as needed
4. **Use Caching**: Always place static content before `<<CACHEPOINT>>`
5. **Clear Recommendations**: Define unambiguous recommendation options
6. **Document Rules**: Include context and examples in rule descriptions
7. **Version Control**: Track rule changes and their impact on results
8. **Regular Review**: Periodically review and update rules based on results
