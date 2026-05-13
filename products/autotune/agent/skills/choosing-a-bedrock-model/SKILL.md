---
name: choosing-a-bedrock-model
description: Guide for selecting Bedrock LLM models based on quality vs cost tradeoffs. Use when optimizing model selection for extraction, classification, or OCR.
---

# Choosing a Bedrock Model

## Problem

Selecting the right LLM model involves tradeoffs between accuracy, speed, and cost. Different tasks may warrant different model choices.

## Applies To

This guide applies to model selection for:
- **Extraction** (`extraction.model`) - extracting structured data from documents
- **Classification** (`classification.model`) - classifying document types
- **OCR** (`ocr.model_id`) - converting document images to text when using Bedrock OCR backend

For OCR specifically, vision-capable models are required. The Qwen vision-language model (`qwen.qwen3-vl-235b-a22b`) can be particularly effective for OCR tasks, especially for multilingual documents.

## Listing Available Models

List all vision-capable models (required for OCR and multimodal classification):
```bash
aws bedrock list-foundation-models --region us-east-1 --output json | \
  jq -r '.modelSummaries[] | select(.inputModalities[]? == "IMAGE") | "\(.providerName) | \(.modelId)"' | sort -u
```

List all text generation models:
```bash
aws bedrock list-foundation-models --region us-east-1 --output json | \
  jq -r '.modelSummaries[] | select(.outputModalities[]? == "TEXT") | "\(.providerName) | \(.modelId)"' | sort -u
```

Filter by provider (e.g., Anthropic):
```bash
aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic --output json | \
  jq -r '.modelSummaries[].modelId'
```

## Model Recommendations

| Tier | Model ID | Use Case |
|------|----------|----------|
| Best | `us.anthropic.claude-opus-4-6-v1` | Highest accuracy, complex documents |
| Very Good | `us.anthropic.claude-sonnet-4-6` | Best balance of quality and cost |
| Good | `us.amazon.nova-2-lite-v1:0` | Cost-effective, good accuracy |
| Fast/Cheap | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | High volume, simple documents |

**Important**: Do not use Claude models older than version 3.7 (e.g., avoid `claude-3-haiku`, `claude-3-5-sonnet`).

## Checking Pricing

Load pricing from the IDP source repository:

```python
import os
import yaml

# Load pricing data
idp_repo = os.environ.get('IDP_ACCELERATOR_SOURCE_REPOSITORY', '/home/ubuntu/gitlab/genaiic-idp-accelerator')
pricing_path = f"{idp_repo}/config_library/pricing.yaml"

with open(pricing_path) as f:
    data = yaml.safe_load(f)

# Structure: data['pricing'] is a list of dicts with 'name' and 'units'
# Filter to US Bedrock models
for entry in data['pricing']:
    if entry['name'].startswith('bedrock/us.'):
        model = entry['name'].replace('bedrock/', '')
        units = {u['name']: float(u['price']) for u in entry['units']}
        input_price = units.get('inputTokens', 0) * 1_000_000  # per 1M tokens
        output_price = units.get('outputTokens', 0) * 1_000_000
        print(f"{model}: ${input_price:.2f} / ${output_price:.2f} per 1M tokens (in/out)")
```

## Pricing Structure

The `pricing.yaml` file contains:
```yaml
pricing:
  - name: bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0
    units:
      - name: inputTokens
        price: "3.3E-6"      # Price per token
      - name: outputTokens
        price: "1.65E-5"
      - name: cacheReadInputTokens   # Optional, for prompt caching
        price: "3.3E-7"
      - name: cacheWriteInputTokens
        price: "4.125E-6"
```

Models are prefixed by region: `us.`, `eu.`, or `global.`

## Decision Guide

1. **Start with Nova 2 Lite** for initial testing - good balance
2. **Upgrade to Sonnet 4.5** if accuracy is insufficient
3. **Use Haiku 4.5** for high-volume simple extractions
4. **Reserve Opus** for complex edge cases or when accuracy is critical

## Applying Model Changes

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.model", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"op": "save"}
])
```
