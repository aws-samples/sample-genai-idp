# Evaluation Service

The Evaluation Service component provides functionality to evaluate document extraction results by comparing extracted attributes against expected values.

## Features

- Compares document extraction results with expected (ground truth) results
- Supports multiple evaluation methods:
  - Exact match - Character-for-character comparison after normalizing whitespace and punctuation
  - Numeric exact match - Value-based comparison after normalizing numeric formats
  - Fuzzy string matching - Similarity-based matching with configurable thresholds
  - Hungarian algorithm - Optimal matching for lists of values
  - Semantic similarity - Meaning-based comparison using Bedrock Titan embeddings
  - LLM-based semantic evaluation - Advanced meaning comparison with explanation using Bedrock models
- Smart attribute discovery and evaluation:
  - Automatically discovers attributes in the extraction results not defined in the configuration
  - Handles attributes found only in expected data, only in actual data, or in both
  - Applies default comparison method (LLM) for unconfigured attributes with clear indication
- Calculates key metrics including:
  - Precision, Recall, and F1 score
  - Accuracy and Error rates
  - False alarm rate and False discovery rate
- Generates rich, visual evaluation reports with:
  - Color-coded status indicators
  - Performance ratings
  - Progress bar visualizations
  - Detailed attribute comparisons
- Supports both JSON and Markdown report formats
- Fully integrated with the Document model architecture

## Usage

```python
from idp_common.models import Document, Status
from idp_common import ocr, classification, extraction, evaluation

# Get configuration (with evaluation methods specified)
config = {
    "evaluation": {
        "llm_method": {
            "model": "anthropic.claude-3-sonnet-20240229-v1:0",
            "temperature": 0.0,
            "top_k": 250,
            "system_prompt": "You are an evaluator that helps determine if the predicted and expected values match...",
            "task_prompt": "I need to evaluate attribute extraction for a document of class: {DOCUMENT_CLASS}..."
        }
    },
    "classes": [
        {
            "name": "invoice",
            "attributes": [
                {
                    "name": "invoice_number",
                    "description": "The unique identifier for the invoice",
                    "evaluation_method": "EXACT"  # Use exact string matching
                },
                {
                    "name": "amount_due",
                    "description": "The total amount to be paid",
                    "evaluation_method": "NUMERIC_EXACT"  # Use numeric comparison
                },
                {
                    "name": "vendor_name",
                    "description": "Name of the vendor",
                    "evaluation_method": "FUZZY",  # Use fuzzy matching
                    "evaluation_threshold": 0.8  # Minimum similarity threshold
                },
                {
                    "name": "line_items",
                    "description": "List of items in the invoice",
                    "evaluation_method": "SEMANTIC",  # Use embedding-based semantic matching
                    "evaluation_threshold": 0.8  # Minimum similarity threshold
                },
                {
                    "name": "transaction_list",
                    "description": "List of transactions from the invoice",
                    "evaluation_method": "HUNGARIAN",  # Use Hungarian algorithm for list matching
                    "hungarian_comparator": "EXACT"  # Use exact string comparison (default)
                },
                {
                    "name": "payment_methods",
                    "description": "List of payment methods accepted",
                    "evaluation_method": "HUNGARIAN",  # Use Hungarian algorithm with fuzzy matching
                    "hungarian_comparator": "FUZZY",  # Use fuzzy string comparison
                    "evaluation_threshold": 0.7  # Similarity threshold for fuzzy matching
                },
                {
                    "name": "amounts",
                    "description": "List of monetary amounts",
                    "evaluation_method": "HUNGARIAN",  # Use Hungarian algorithm with numeric matching
                    "hungarian_comparator": "NUMERIC"  # Use numeric comparison after normalization
                },
                {
                    "name": "notes",
                    "description": "Additional notes about the invoice",
                    "evaluation_method": "LLM"  # Use LLM-based evaluation (default method, also used when evaluation_method is missing)
                }
            ]
        }
    ]
}

# Create evaluation service
evaluation_service = evaluation.EvaluationService(config=config)

# Evaluate documents (stores results in S3 by default)
result_document = evaluation_service.evaluate_document(
    actual_document=processed_document,
    expected_document=expected_document
)

# Access evaluation report URI
evaluation_report_uri = result_document.evaluation_report_uri

# You can also access the evaluation result directly
evaluation_result = result_document.evaluation_result
overall_metrics = evaluation_result.overall_metrics
section_results = evaluation_result.section_results

# Or skip storage if needed (for quick memory-only evaluations)
memory_only_document = evaluation_service.evaluate_document(
    actual_document=processed_document,
    expected_document=expected_document,
    store_results=False
)
```

## Evaluation Methods

The service supports multiple evaluation methods that can be configured for each attribute:

- `EXACT`: Exact string match (after normalizing whitespace and punctuation)
- `NUMERIC_EXACT`: Exact match for numeric values (after normalizing currency symbols)
- `FUZZY`: Fuzzy string matching with configurable evaluation_threshold
- `HUNGARIAN`: Optimal matching for lists of values using the Hungarian algorithm with configurable comparator types:
  - `EXACT`: Default comparator for exact string matching (after normalization)
  - `FUZZY`: Fuzzy string matching with configurable threshold
  - `NUMERIC`: Numeric comparison after normalizing currency symbols and formats
- `SEMANTIC`: Efficient semantic similarity comparison using Bedrock Titan embeddings (amazon.titan-embed-text-v1)
- `LLM`: LLM-based evaluation using Bedrock models (Claude or Titan) for semantically comparable values with detailed explanations

### Semantic vs LLM Evaluation

The service offers two approaches for semantic evaluation:

- **SEMANTIC Method**: Uses embedding-based comparison with Bedrock Titan embeddings
  - Faster and more cost-effective than LLM-based evaluation
  - Provides similarity scores without explanations
  - Great for high-volume comparisons where speed is important
  - Configurable threshold for matching sensitivity
  
- **LLM Method**: Uses Bedrock Claude or other LLM models
  - Provides detailed reasoning for why values match or don't match
  - Better at handling implicit/explicit information differences
  - More nuanced understanding of semantic equivalence
  - Ideal for cases where understanding the rationale is important
  - Used as the default method for attributes discovered in the data but not in the configuration

## Output

The evaluation produces:

1. **JSON Results**: Detailed evaluation results with metrics
2. **Markdown Report**: Human-readable report with tables and summaries

## Metrics

The evaluation calculates the following metrics:

- **Precision**: Accuracy of positive predictions (TP / (TP + FP))
- **Recall**: Coverage of actual positive cases (TP / (TP + FN))
- **F1 Score**: Harmonic mean of precision and recall
- **Accuracy**: Overall correctness (TP + TN) / (TP + TN + FP + FN)
- **False Alarm Rate (FAR)**: Rate of false positives among negatives (FP / (FP + TN))
  - Measures how often the system extracts information that wasn't present in the document
- **False Discovery Rate (FDR)**: Rate of false positives among positive predictions (FP / (FP + TP))
  - Measures what proportion of the extracted information is incorrect

These metrics are calculated at both the attribute level (per field), section level (per document class), and document level (overall performance).

## Visual Reporting

The evaluation module produces richly formatted Markdown reports with:

1. **Summary Dashboard**:
   - Overall match rate with visual progress bar
   - Color-coded indicators for key metrics (🟢 Excellent, 🟡 Good, 🟠 Fair, 🔴 Poor)
   - Fraction of matched attributes (e.g., 8/10 attributes matched)

2. **Performance Tables**:
   - Metrics tables with value ratings
   - First-column status indicators (✅/❌) for immediate identification of matches
   - Detailed attribution of evaluation methods used for each field, including:
     - Method types (EXACT, FUZZY, HUNGARIAN, etc.)
     - Thresholds for fuzzy and semantic matching methods
     - Comparator types for the Hungarian method
     - Combined display for HUNGARIAN with FUZZY comparator showing both comparator type and threshold

3. **Method Explanations**:
   - Clear documentation of evaluation methods
   - Descriptions of scoring mechanisms
   - Guidance on interpreting results
   - Indications for attributes that were discovered in the data but not in the configuration

Examples of method display in reports:
- `EXACT` - Simple exact matching
- `FUZZY (threshold: 0.8)` - Fuzzy matching with threshold
- `HUNGARIAN (comparator: EXACT)` - Hungarian algorithm with exact matching
- `HUNGARIAN (comparator: FUZZY, threshold: 0.7)` - Hungarian with fuzzy matching and threshold
- `HUNGARIAN (comparator: NUMERIC)` - Hungarian with numeric comparison

The reports are designed to provide both at-a-glance performance assessment and detailed diagnostic information.

## Auto-Discovery of Attributes

The EvaluationService can automatically discover and evaluate attributes that exist in the data but are not defined in the configuration:

```python
# Sample extracted data may have more attributes than configured
actual_results = {
    "invoice_number": "INV-12345",          # In configuration
    "amount_due": 1250.00,                  # In configuration
    "issue_date": "2023-01-15",             # Not in configuration
    "due_date": "2023-02-15"                # Not in configuration
}

expected_results = {
    "invoice_number": "INV-12345",          # In configuration
    "amount_due": "$1,250.00",              # In configuration 
    "issue_date": "01/15/2023",             # Not in configuration
    "reference_number": "REF-98765"         # Not in configuration, missing in actual
}

# The service will:
# 1. Evaluate invoice_number and amount_due using methods in configuration
# 2. Discover issue_date (in both) and evaluate using LLM (default method)
# 3. Discover due_date (only in actual) and evaluate as not matched
# 4. Discover reference_number (only in expected) and evaluate as not matched
# 5. Add "[Default method - attribute not specified in the configuration]" to reason for discovered attributes
```

This capability is particularly useful for:
- Exploratory evaluation when the complete schema is not yet defined
- Handling variations in extraction outputs that may contain additional information
- Identifying potential new attributes to add to the configuration
- Ensuring all extracted data is evaluated, even without explicit configuration