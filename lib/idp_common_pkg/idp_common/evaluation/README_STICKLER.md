# SticklerEvaluationService

The `SticklerEvaluationService` is an evaluation service that uses the [Stickler library](https://github.com/awslabs/stickler) for advanced validation rules and custom evaluation criteria. It provides the same interface as the standard `EvaluationService` but leverages Stickler's powerful comparison capabilities.

## Features

- **JSON Configuration**: Define evaluation models using JSON configuration
- **Advanced Comparators**: Use Stickler's built-in comparators (Exact, Fuzzy, Numeric, Levenshtein, etc.)
- **Nested Structure Support**: Handle complex nested data structures
- **List Matching**: Automatic Hungarian algorithm for optimal list matching
- **Flexible Validation**: Custom validation rules per document class

## Installation

The Stickler library must be installed to use this service:

```bash
pip install stickler-eval
```

Or install from the local stickler directory:

```bash
pip install -e ./stickler
```

## Configuration

The service is configured using a JSON structure that defines Stickler models for each document class:

```python
config = {
    "stickler_models": {
        "invoice": {
            "model_name": "Invoice",
            "match_threshold": 0.8,
            "fields": {
                "invoice_number": {
                    "type": "str",
                    "comparator": "ExactComparator",
                    "threshold": 1.0,
                    "weight": 3.0
                },
                "total_amount": {
                    "type": "float",
                    "comparator": "NumericComparator",
                    "comparator_config": {"tolerance": 0.01},
                    "threshold": 0.95,
                    "weight": 2.0
                },
                "customer": {
                    "type": "structured_model",
                    "threshold": 0.8,
                    "weight": 2.0,
                    "fields": {
                        "name": {
                            "type": "str",
                            "comparator": "LevenshteinComparator",
                            "threshold": 0.8,
                            "weight": 1.0
                        },
                        "address": {
                            "type": "str",
                            "comparator": "FuzzyComparator",
                            "threshold": 0.7,
                            "weight": 0.8
                        }
                    }
                },
                "line_items": {
                    "type": "list_structured_model",
                    "weight": 2.0,
                    "match_threshold": 0.7,
                    "fields": {
                        "product": {
                            "type": "str",
                            "comparator": "FuzzyComparator",
                            "threshold": 0.8,
                            "weight": 1.0
                        },
                        "quantity": {
                            "type": "int",
                            "comparator": "NumericComparator",
                            "threshold": 1.0,
                            "weight": 0.8
                        },
                        "price": {
                            "type": "float",
                            "comparator": "NumericComparator",
                            "threshold": 0.95,
                            "weight": 1.2
                        }
                    }
                }
            }
        }
    }
}
```

## Usage

### Basic Usage

```python
from idp_common.evaluation import SticklerEvaluationService
from idp_common.models import Section

# Initialize the service with configuration
service = SticklerEvaluationService(region="us-east-1", config=config)

# Create a section to evaluate
section = Section(
    section_id="section1",
    classification="invoice",
    page_ids=["page1"]
)

# Expected and actual extraction results
expected_results = {
    "invoice_number": "INV-2024-001",
    "total_amount": 1247.50,
    "customer": {
        "name": "Acme Corporation",
        "address": "123 Business St, Suite 100"
    },
    "line_items": [
        {"product": "Widget A", "quantity": 5, "price": 29.99},
        {"product": "Widget B", "quantity": 10, "price": 12.99}
    ]
}

actual_results = {
    "invoice_number": "INV-2024-001",
    "total_amount": 1247.48,
    "customer": {
        "name": "ACME Corp",
        "address": "123 Business Street, Ste 100"
    },
    "line_items": [
        {"product": "Widget B", "quantity": 10, "price": 12.99},  # Reordered
        {"product": "Widget A", "quantity": 5, "price": 29.99}
    ]
}

# Evaluate the section
result = service.evaluate_section(
    section=section,
    expected_results=expected_results,
    actual_results=actual_results
)

# Access results
print(f"Section: {result.section_id}")
print(f"Metrics: {result.metrics}")
for attr in result.attributes:
    print(f"  {attr.name}: matched={attr.matched}, score={attr.score:.3f}")
```

### Document-Level Evaluation

```python
from idp_common.models import Document, Section

# Evaluate a complete document
document_result = service.evaluate_document(
    document_id="doc123",
    sections=[section1, section2],
    expected_results_uri="s3://bucket/ground-truth/doc123.json",
    actual_results_uri="s3://bucket/inference/doc123.json"
)

# Access overall metrics
print(f"Overall Precision: {document_result.overall_metrics['precision']:.3f}")
print(f"Overall Recall: {document_result.overall_metrics['recall']:.3f}")
print(f"Overall F1 Score: {document_result.overall_metrics['f1_score']:.3f}")
```

## Available Comparators

Stickler provides several built-in comparators:

- **ExactComparator**: Exact string matching (case-sensitive)
- **LevenshteinComparator**: Edit distance-based string comparison
- **FuzzyComparator**: Fuzzy string matching using rapidfuzz
- **NumericComparator**: Numeric comparison with optional tolerance
- **SemanticComparator**: Semantic similarity (requires embeddings)

## Field Types

- **str**: String fields
- **int**: Integer fields
- **float**: Floating-point fields
- **bool**: Boolean fields
- **structured_model**: Nested object (group of fields)
- **list_structured_model**: List of objects (uses Hungarian matching)

## Comparison with EvaluationService

| Feature | EvaluationService | SticklerEvaluationService |
|---------|-------------------|---------------------------|
| Configuration | YAML-based | JSON-based (Stickler format) |
| Comparators | Built-in (EXACT, FUZZY, LLM, etc.) | Stickler comparators |
| List Matching | Hungarian with custom comparators | Stickler's Hungarian implementation |
| Nested Structures | Flattened with dot notation | Native nested support |
| Weights | Not supported | Field-level weights |
| Thresholds | Per-method thresholds | Per-field thresholds |

## Benefits

1. **Flexible Configuration**: Define validation rules in JSON without code changes
2. **Advanced Matching**: Leverage Stickler's sophisticated comparison algorithms
3. **Business-Weighted Scoring**: Assign importance weights to critical fields
4. **List Reordering**: Automatic optimal matching for lists regardless of order
5. **Nested Support**: Natural handling of complex nested structures

## Example Configuration Files

See the `config_library/pattern-2/fcc-invoices/` directory for example Stickler configurations.

## Testing

Run the unit tests:

```bash
pytest lib/idp_common_pkg/tests/unit/evaluation/test_stickler_service.py -v
```

## References

- [Stickler Documentation](https://github.com/awslabs/stickler)
- [Stickler Dynamic Model Creation](../../stickler/docs/StructuredModel_Dynamic_Creation.md)
- [IDP Evaluation Documentation](./README.md)
