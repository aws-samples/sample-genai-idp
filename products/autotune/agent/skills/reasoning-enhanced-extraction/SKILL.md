---
name: reasoning-enhanced-extraction
description: Improve extraction and classification accuracy by adding reasoning/chain-of-thought instructions that require the LLM to evaluate evidence before making selections. Use when the LLM picks wrong candidate values for ambiguous fields, or when classification struggles with similar document types.
---

# Reasoning-Enhanced Extraction

## Problem

The LLM makes incorrect value selections on fields where multiple candidate values exist in the document, or where the correct value requires cross-referencing multiple parts of the document. Without explicit reasoning instructions, the LLM jumps to the first plausible-looking value rather than systematically evaluating all candidates against the field description.

Adding a reasoning component — requiring the LLM to think step-by-step and provide a reason for each entity value selection — has been shown in past engagements to improve accuracy on ambiguous fields, particularly for checkbox extraction, handwritten content interpretation, and fields where multiple similar values appear in the document.

## Symptoms

- Fields with multiple candidate values in the document have low accuracy (e.g., multiple dates, multiple names, multiple codes)
- The LLM consistently picks the wrong candidate from several plausible options
- Checkbox or selection fields are extracted incorrectly despite good OCR
- Accuracy is inconsistent across documents for the same field — sometimes right, sometimes wrong
- Fields requiring cross-referencing (e.g., matching a code to its description) score poorly

## Diagnosis

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_aggregated_summary(top_bottom_n=5)

# Download a failing document and compare extraction vs ground truth
client.download_single_document_results('batch-id', 'failing-doc.pdf', 'investigation/')
client.download_ground_truth('test-set-id', 'failing-doc.pdf', 'investigation/gt.json')
```

If the extracted value is a real value from the document (not hallucinated) but it's the *wrong* value from the document, reasoning can help the LLM make better selections.

## Fix 1: Add Reasoning to Extraction Task Prompt

Add step-by-step reasoning instructions to the extraction task prompt. This tells the LLM to evaluate candidates before committing to a value.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

current_prompt = config.get('extraction.task_prompt')

reasoning_instructions = '''

EXTRACTION REASONING PROCESS:
For each field, follow this process before selecting a value:
1. Identify ALL candidate values in the document that could match this field
2. For each candidate, evaluate how well it matches the field description
3. Select the candidate with the strongest match
4. If no candidate clearly matches, return null rather than guessing

Think step by step first, then provide your final answer.'''

config.set('extraction.task_prompt', current_prompt + reasoning_instructions)
config.save('workspace/updated-config.yaml')
```

## Fix 2: Add Reasoning for Checkbox/Selection Fields

For documents with checkboxes, radio buttons, or selection fields, reasoning is especially valuable because the LLM must interpret visual marks and associate them with the correct option.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

current_prompt = config.get('extraction.task_prompt')

checkbox_reasoning = '''

CHECKBOX AND SELECTION FIELD REASONING:
For fields determined by checkboxes, radio buttons, or selection marks:
1. Examine each option's checkbox area for visible marks (✓, ✗, x, filled circles, handwritten marks)
2. For ambiguous or overlapping marks, determine which option contains the majority of the mark
3. Consider the mark selected if it is primarily inside the checkbox or over the option text
4. Think from a human perspective — anticipate natural tendencies when marking checkboxes
5. Provide your reasoning for which option was selected before outputting the value'''

config.set('extraction.task_prompt', current_prompt + checkbox_reasoning)
config.save('workspace/updated-config.yaml')
```

## Fix 3: Add Reasoning to Classification

For classification, reasoning helps the LLM systematically evaluate document evidence before choosing a class. Add `<reasoning-guidelines>` and require a `classification_reason` field in the output.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

config.set('classification.task_prompt', '''<reasoning-guidelines>
When determining the document type:
- First identify the document's primary purpose and function
- Note specific visual elements (letterhead, forms, tables, signatures)
- Identify key textual indicators (terminology, phrases, structure)
- Consider the document's intended audience and use case
- Provide specific evidence from both visual and textual analysis
</reasoning-guidelines>

<document-types>
{CLASS_NAMES_AND_DESCRIPTIONS}
</document-types>

<output-format>
Return your classification as valid JSON following this exact structure:
{
  "classification_reason": "Detailed reasoning including specific visual and textual evidence that led to this classification",
  "class": "exact_document_type_from_list"
}
</output-format>

<<CACHEPOINT>>

<document-ocr-data>
{DOCUMENT_TEXT}
</document-ocr-data>

<document-image>
{DOCUMENT_IMAGE}
</document-image>

<final-instructions>
Analyze the document above by:
1. Examining both visual and textual features
2. Following the <reasoning-guidelines> to build your classification rationale
3. Selecting ONLY from document types in <document-types>
4. Providing clear reasoning with specific evidence BEFORE the classification
5. Outputting in the exact JSON format specified in <output-format>
</final-instructions>''')

config.save('workspace/updated-config.yaml')
```

The `classification_reason` field forces the LLM to articulate its evidence before committing to a class, which reduces impulsive misclassification.

## Tradeoffs

| Factor | Impact |
|--------|--------|
| Output tokens | Reasoning increases output length — more tokens = higher cost |
| Latency | Longer output = slower per-document processing |
| Accuracy | Most impactful on ambiguous fields; minimal benefit for simple/unambiguous fields |
| Model capability | Stronger models (Sonnet, Opus, Nova Premier) reason better than weaker ones |

**When reasoning is worth the cost:**
- Fields where the LLM must choose between multiple candidate values
- Checkbox/selection fields with ambiguous marks
- Complex documents where cross-referencing is needed
- Classification of confusable document types

**When reasoning is NOT worth the cost:**
- Simple fields with a single obvious value (e.g., a clearly labeled invoice number)
- High-volume, cost-sensitive processing of simple documents
- Fields that are already at high accuracy

## Interaction with Other Skills

- **`extraction-prompt-engineering`**: Descriptions tell the LLM *what* to extract; reasoning tells it *how to decide*. Use both together for maximum effect on ambiguous fields.
- **`visual-spatial-extraction-challenges`**: Reasoning is especially valuable for visual fields (checkboxes, spatial tables) where the LLM must interpret marks.
- **`choosing-a-bedrock-model`**: Stronger models reason better. If reasoning doesn't help with a weaker model, try upgrading before abandoning the technique.
- **`inference-parameter-tuning`**: Keep temperature low (0–0.2) when using reasoning to ensure deterministic chain-of-thought.
- **`prompt-caching-optimization`**: Reasoning instructions are static and cacheable. Place `<<CACHEPOINT>>` after reasoning guidelines but before document content.

## Verification

1. Run evaluation without reasoning as baseline
2. Add reasoning instructions to the extraction and/or classification prompt
3. Upload updated config and re-run evaluation
4. Compare per-field accuracy, focusing on the ambiguous fields that motivated the change
5. Check cost impact — compare total cost and output token counts between runs
6. If accuracy improved but cost is too high, consider applying reasoning only to the specific fields or tasks that benefit most
