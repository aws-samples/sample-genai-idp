---
name: multi-class-setup
description: Set up classification for multi-class document datasets. Use when dataset contains multiple document types that need classification before extraction.
---

# Multi-Class Setup

## Problem

Dataset contains documents of different types that need classification before extraction.

## Symptoms

- Ground truth files have different `document_class.type` values
- `DatasetAnalyzer.is_multi_class()` returns True
- Single-schema config gives 0% accuracy on documents of other classes

## Diagnosis

```python
from idpac import DatasetAnalyzer

analyzer = DatasetAnalyzer('/path/to/dataset')
print(f"Classes: {analyzer.get_class_names()}")
print(f"Is multi-class: {analyzer.is_multi_class()}")

errors = analyzer.validate_ground_truth_format()
if errors:
    print(f"Ground truth issues: {errors}")
```

## Fix

### 1. Generate Schemas for Each Class

```python
from idpac import DatasetAnalyzer, StandaloneDiscovery

analyzer = DatasetAnalyzer('/path/to/dataset')
samples = analyzer.get_samples_by_class(n=1)
gt_paths = analyzer.get_ground_truth_by_class(n=1)

discovery = StandaloneDiscovery(region='us-east-1')
schemas = discovery.discover_multi_class(samples, gt_paths)
```

### 2. Create Multi-Class Config

```python
from idpac import IDPConfig

config = IDPConfig.from_defaults('pattern-2')
for schema in schemas:
    config.add_class(schema)

# Validate before saving
result = config.validate()
if not result.is_valid:
    print(result)

config.save('workspace/config-multiclass-v1.yaml')
```

### 3. Add Class Descriptions

Each class should have a `description` field to help the classifier:

```python
for i, class_name in enumerate(config.get_class_names()):
    desc = f"Description of what makes {class_name} documents unique"
    config.set(f'classes.{i}.description', desc)
```

## Verification

1. Run evaluation on multi-class test set
2. Check `splitClassificationMetrics` for classification accuracy
3. Check `accuracyBreakdown` for per-class extraction accuracy
