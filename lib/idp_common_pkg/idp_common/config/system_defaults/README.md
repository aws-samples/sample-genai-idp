# System Defaults

This directory contains the default configuration files for the IDP Accelerator. These defaults are used as the base for all deployments, with pattern-specific and user-specific overrides applied on top.

## Modular Architecture

The defaults are organized into individual section files for maximum flexibility:

```
system_defaults/
   base.yaml                   # Composite (includes all modules)
   base-notes.yaml             # Configuration notes/description
   base-classes.yaml           # Document class definitions
   base-ocr.yaml               # Textract OCR configuration
   base-classification.yaml    # LLM classification settings
   base-extraction.yaml        # LLM extraction settings
   base-assessment.yaml        # LLM confidence scoring
   base-summarization.yaml     # Document summarization
   base-evaluation.yaml        # Evaluation/testing
   base-criteria-validation.yaml # Criteria validation
   base-agents.yaml            # Error analyzer, chat companion
   base-discovery.yaml         # Schema discovery
   pattern-1.yaml              # BDA pattern (selective inheritance)
   pattern-2.yaml              # Bedrock LLM pattern (full inheritance)
   README.md
```

## Inheritance System

Pattern files use `_inherits` directive to declare which modules to include:

### Full Inheritance (Pattern-2)
```yaml
# Pattern-2 needs everything
_inherits: base.yaml
```
Which is equivalent to:
```yaml
_inherits:
  - base-notes.yaml
  - base-classes.yaml
  - base-ocr.yaml
  - base-classification.yaml
  - base-extraction.yaml
  - base-assessment.yaml
  - base-summarization.yaml
  - base-evaluation.yaml
  - base-criteria-validation.yaml
  - base-agents.yaml
  - base-discovery.yaml
```

### Selective Inheritance (Pattern-1 - BDA)
```yaml
# Pattern-1 (BDA) - excludes OCR, classification, extraction
_inherits:
  - base-notes.yaml
  - base-classes.yaml
  - base-assessment.yaml
  - base-summarization.yaml
  - base-evaluation.yaml
  - base-criteria-validation.yaml
  - base-agents.yaml
  - base-discovery.yaml
```

BDA handles OCR, classification, and extraction internally, so it doesn't inherit those modules.

### Selective Inheritance (Pattern-3 - UDOP)
```yaml
# Pattern-3 (UDOP) - includes OCR and extraction, excludes classification only
_inherits:
  - base-notes.yaml
  - base-classes.yaml
  - base-ocr.yaml
  - base-extraction.yaml
  - base-assessment.yaml
  - base-summarization.yaml
  - base-evaluation.yaml
  - base-criteria-validation.yaml
  - base-agents.yaml
  - base-discovery.yaml
```

UDOP uses Textract for OCR, LLM for extraction, and its own fine-tuned model for classification only.

## Module Contents

| Module | Section | Description | Used By |
|--------|---------|-------------|---------|
| `base-notes.yaml` | `notes` | Configuration description | All patterns |
| `base-classes.yaml` | `classes` | Document class definitions | All patterns |
| `base-ocr.yaml` | `ocr` | Textract OCR | Pattern-2, Pattern-3 |
| `base-classification.yaml` | `classification` | LLM classification | Pattern-2 only |
| `base-extraction.yaml` | `extraction` | LLM extraction | Pattern-2, Pattern-3 |
| `base-assessment.yaml` | `assessment` | Confidence scoring | All patterns |
| `base-summarization.yaml` | `summarization` | Doc summarization | All patterns |
| `base-evaluation.yaml` | `evaluation` | Testing/evaluation | All patterns |
| `base-criteria-validation.yaml` | `criteria_validation` | Criteria checks | All patterns |
| `base-agents.yaml` | `agents` | Error analyzer, chat | All patterns |
| `base-discovery.yaml` | `discovery` | Schema discovery | All patterns |

## Merge Priority

Configuration values are merged in this priority order (highest first):

1. **User's custom config** - Values explicitly set by the user
2. **Pattern-specific file** - Values in pattern-X.yaml
3. **Inherited modules** - Values from base-*.yaml files
4. **Pydantic defaults** - Code-level fallbacks

## Using with CLI

```bash
# Generate minimal config template
idp-cli config-create --features min --pattern pattern-2 --output config.yaml

# Generate config with specific sections
idp-cli config-create --features ocr classification extraction --output config.yaml

# Validate config
idp-cli config-validate --custom-config ./config.yaml

# Deploy (automatically merges with defaults)
idp-cli deploy --stack-name my-idp --custom-config ./config.yaml --wait

# Download config from deployed stack
idp-cli config-download --stack-name my-stack --output config.yaml
```

## Example: Minimal User Config

Users only need to specify what differs from defaults:

```yaml
# my-config.yaml - minimal Pattern-2 config
notes: "My lending package processor"

classification:
  model: us.amazon.nova-lite-v1:0

extraction:
  model: us.amazon.nova-lite-v1:0

classes:
  - $id: W2
    type: object
    x-aws-idp-document-type: W2 Tax Form
    properties:
      employer_name:
        type: string
      employee_name:
        type: string
```

Everything else (OCR settings, prompts, assessment config, agents, etc.) comes from system defaults.