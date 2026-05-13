---
name: inference-parameter-tuning
description: Tune LLM inference parameters (temperature, top_p, max_tokens) for extraction and classification tasks. Use when extraction output is inconsistent, non-deterministic, or when optimizing for accuracy vs creativity tradeoff.
---

# Inference Parameter Tuning

## Problem

Default inference parameters may not be optimal for document extraction. Lower temperature and top_p settings produce more deterministic, accurate outputs for structured extraction tasks, while defaults tuned for general conversation introduce unnecessary randomness.

## Symptoms

- Extraction results vary between runs on the same document
- LLM occasionally produces creative interpretations instead of exact values
- Output format compliance is inconsistent (sometimes valid JSON, sometimes not)
- Accuracy plateaus despite good prompts and schema descriptions

## When to Apply

Apply this skill when:
- You've already optimized prompts and schema descriptions but accuracy is still not improving
- You notice non-deterministic behavior across evaluation runs
- The task is structured extraction (not creative/generative) and you want maximum consistency

## Recommended Settings

### For Extraction Tasks

Extraction is a deterministic task — you want the LLM to faithfully copy values from the document, not generate creative responses. Use low temperature and top_p:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.temperature", "value": 0.2},
    {"op": "set", "field": "extraction.top_p", "value": 0.6},
    {"op": "save"}
])
```

For maximum determinism (e.g., when debugging or establishing baselines):

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.temperature", "value": 0},
    {"op": "set", "field": "extraction.top_p", "value": 0},
    {"op": "save"}
])
```

### For Classification Tasks

Classification is also deterministic — use low settings:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.temperature", "value": 0},
    {"op": "set", "field": "classification.top_p", "value": 0},
    {"op": "save"}
])
```

### For OCR (Bedrock backend)

When using Bedrock LLM for OCR, you want faithful text reproduction:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.temperature", "value": 0},
    {"op": "set", "field": "ocr.top_p", "value": 0},
    {"op": "save"}
])
```

## Parameter Reference

| Parameter | Range | Effect |
|-----------|-------|--------|
| `temperature` | 0.0–1.0 | Controls randomness. 0 = most deterministic, 1 = most random |
| `top_p` | 0.0–1.0 | Nucleus sampling. Lower = considers fewer token candidates |
| `max_tokens` | model-dependent | Maximum output length. Too low → truncated JSON |

## Decision Guide

| Scenario | temperature | top_p |
|----------|-------------|-------|
| Structured extraction (default recommendation) | 0.2 | 0.6 |
| Maximum determinism / debugging | 0 | 0 |
| Complex documents needing some flexibility | 0.5 | 0.9 |

Avoid high temperature (>0.7) for extraction tasks — it introduces hallucination risk with no benefit for structured data extraction.

## Verification

1. Run evaluation with default parameters, record accuracy
2. Apply recommended low temperature/top_p settings
3. Re-run evaluation on same test set
4. Compare overall and per-field accuracy
5. Optionally run twice with temperature=0 to confirm deterministic output
