---
name: multi-class-setup
description: Set up classification for multi-class document datasets. Use when dataset contains multiple document types that need classification before extraction.
---

# Multi-Class Setup

## Problem

Dataset contains documents of different types that need classification before extraction.

## Symptoms

- Ground truth files have different `document_class.type` values
- `analyze_dataset` reports the dataset as multi-class
- Single-schema config gives 0% accuracy on documents of other classes

## Diagnosis

Use `analyze_dataset(dataset_path)` after downloading the test set with `download_test_set(test_set_id)`. This will report the dataset mode (single-class, multi-class, or packet-splitting), class names, and any ground truth validation errors.

## Fix

### 1. Generate Schemas for Each Class

Use `run_multi_class_discovery(dataset_path)` to discover schemas for all classes and create a config automatically. This requires the dataset to be downloaded locally first.

### 2. Create Multi-Class Config

The `run_multi_class_discovery` tool creates the config for you. After it runs, validate it:

```
validate_config(config_path)
auto_fix_config(config_path)
```

### 3. Add Class Descriptions

Each class should have a `description` field to help the classifier:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.description", "value": "Description of what makes this document type unique"},
    {"op": "set", "field": "classes.1.description", "value": "Description of what makes this document type unique"},
    {"op": "save"}
])
```

## Verification

1. Run evaluation on multi-class test set
2. Check `splitClassificationMetrics` for classification accuracy
3. Check `accuracyBreakdown` for per-class extraction accuracy
