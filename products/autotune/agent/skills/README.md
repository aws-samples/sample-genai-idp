# IDPAC Skills Repository

**Copyright © Amazon.com and Affiliates**: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties. See the [LICENSE](LICENSE) file for details.

Reusable skills for optimizing [IDP Accelerator](https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws) configurations. Each skill provides targeted diagnosis and fixes for common issues.

## What are Skills?

Skills are self-contained knowledge modules that the `idpac-optimizer` agent reads on-demand when encountering specific issues. Each skill includes:

- **SKILL.md**: Problem description, diagnosis steps, and fix instructions
- **Implementation code**: Python examples using the `idpac` package

## Available Skills

| Skill | Description |
|-------|-------------|
| `json-output-fix` | Fix JSON parsing failures from LLMs wrapping output in markdown/XML |
| `token-limit-fix` | Fix truncated output for documents with many line items |
| `idp-analytics` | Query document processing analytics via IDP's MCP server |
| `multi-class-setup` | Set up classification for multi-class document datasets |
| `classification-tuning` | Improve classification accuracy when documents are misclassified |
| `extraction-prompt-engineering` | Improve per-field extraction accuracy by enriching schema descriptions with domain context, examples, formatting rules, and enum/dropdown values |
| `inference-parameter-tuning` | Tune temperature, top_p, and max_tokens for deterministic extraction and classification |
| `evaluation-method-tuning` | Tune per-field evaluation methods, thresholds, and weights to get accurate accuracy measurements |
| `ocr-configuration` | Configure OCR settings including backend selection (Textract vs Bedrock), features, and image processing |
| `choosing-a-bedrock-model` | Guide for selecting Bedrock LLM models based on quality vs cost tradeoffs |
| `document-packet-splitting-tuning` | Improve document packet classification accuracy for boundary detection, type assignment, and segment grouping |
| `multilingual-documents` | Handle documents in non-English languages requiring Bedrock OCR instead of Textract |
| `ground-truth-quality-analysis` | Diagnose ground truth quality issues that cause artificially low accuracy |
| `post-processing-task-decomposition` | Split complex extraction into simpler LLM extraction plus post-processing rules |
| `sparse-field-metric-selection` | Guide metric selection (Accuracy vs F1) based on field population density |
| `visual-spatial-extraction-challenges` | Mitigate challenges with fields requiring complex visual parsing (checkboxes, diagrams, spatial tables) |
| `classification-strategy-selection` | Choose and configure classification strategy: method selection (holistic vs page-level), context pages, max pages limit, regex bypass, and few-shot examples |
| `nested-schema-design` | Design nested schemas using $defs/$ref for grouped fields and arrays, with correct evaluation method layering |
| `stepwise-extraction-strategy` | Diagnose and mitigate extraction failures on complex documents with many repeating entities or nested hierarchical structures |
| `boolean-field-extraction` | Improve extraction accuracy for boolean/yes-no fields, handling N/A vs No distinction, explicit vs implied values, and normalization |
| `data-completeness-analysis` | Analyze field population rates across a dataset to identify ground truth gaps, distinguish missing annotations from intentionally empty fields, and prioritize optimization effort |
| `iterative-schema-refinement` | **META-SKILL**: Orchestrates other skills into a systematic optimization process based on field category performance patterns. Read this first to plan optimization strategy. |
| `prompt-caching-optimization` | Reduce LLM token costs by enabling Bedrock prompt caching via the `<<CACHEPOINT>>` delimiter, especially effective with few-shot examples |
| `extraction-few-shot-examples` | Improve extraction accuracy by providing concrete example documents with expected outputs for complex or domain-specific document types |
| `conditional-ocr-cost-optimization` | Identify opportunities to skip OCR/extraction for document classes that only need classification (requires custom pipeline work — flags to human) |
| `confidence-threshold-tuning` | Configure assessment confidence scoring and per-field thresholds for HITL routing. Use after extraction accuracy is stable to define automation boundaries |
| `reasoning-enhanced-extraction` | Improve extraction and classification accuracy by adding reasoning/chain-of-thought instructions that require the LLM to evaluate evidence before making selections |
| `no-ground-truth-optimization` | Best-effort config optimization when no ground truth baselines are available — qualitative analysis workflow, convergence signals, and applicable skills |

## How to Use Skills

### 1. Clone or symlink into agent workspace

```bash
cd /path/to/idp-auto-configurator/

# Option A: Clone directly
git clone <idpac-skills-repo-url> .kiro/skills

# Option B: Symlink if already cloned elsewhere
ln -s /path/to/idpac-skills .kiro/skills
```

### 2. Agent reads skills on-demand

The `idpac-optimizer` agent automatically reads this README which tells it what skills are available, along with an extremely brief description of what each skill does and when it should be used.

The `idpac-optimizer` agent will read full relevant SKILL.md files only as necessary during its optimization workflow.

### 3. SKILL.md Structure

```markdown
---
name: skill-name
description: Brief description
---

# Skill Name

## Problem
What issue this skill addresses

## Symptoms
How to identify the issue

## Diagnosis
Steps to confirm the root cause

## Fix
Implementation instructions with code examples

## Verification
How to confirm the fix worked
```
