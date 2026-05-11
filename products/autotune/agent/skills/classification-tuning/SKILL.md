---
name: classification-tuning
description: Improve classification accuracy for multi-class datasets. Use when documents are being misclassified, causing extraction to use the wrong schema.
---

# Classification Tuning

## Problem

Documents are being classified incorrectly, causing extraction to use wrong schema and produce 0% accuracy.

## Symptoms

- Low `splitClassificationMetrics.accuracy` in evaluation results
- Some classes have high extraction accuracy, others have 0%
- Individual document results show wrong `document_class`

## Diagnosis

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_classification_summary()
```

Check which classes have low accuracy - if extraction accuracy is 0% but other classes are high, it's likely misclassification.

## Fix

### 1. Improve Class Descriptions

Add clear, discriminative descriptions to each class schema. The `{CLASS_NAMES_AND_DESCRIPTIONS}` placeholder in the classification prompt pulls from these.
*CRITICAL* Do NOT make any assumptions about what is in the class based on the name of the class. For all intents and purposes, the class names could be randomized. In order to build a better description, you should look at a few sample documents of that class if they are available and try to write descriptions which balance being specific to that class without overfitting to those specific documents. If you do not have access to those documents, stop and ask for a human's advice by prompting them that you need to improve the description of a certain class of document and asking them how they would do it.

**Template:**
```
[Document type] with [key structural feature]. Contains [distinctive content].
Distinguished from similar documents by [unique characteristic].
```

**Example:**
```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

config.set('classes.0.description',
    'Invoice requesting payment - shows amount DUE, has payment terms, '
    'includes line items with quantities and prices, no payment confirmation')

config.set('classes.1.description', 
    'Receipt confirming payment - shows amount PAID, has transaction/confirmation ID, '
    'marked as paid/complete, may show payment method used')
```

**For confusable classes**, explicitly contrast them:
```python
config.set('classes.2.description',
    'Delivery note documenting shipped items - focuses on quantities delivered '
    'and shipping details. Unlike invoices, does NOT include prices or payment terms')
```

### 2. Use Stronger Classification Model

```python
config.set('classification.model', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
```

### 3. Apply Negative Prompting

When two classes are frequently confused, positive descriptions alone may not be enough. Negative prompting explicitly tells the classifier what a class is NOT. In past engagements, adding negative prompts resolved persistent misclassification between similar document types (e.g., request forms being misclassified as result reports because both contain similar terminology).

**In class descriptions** — add "this is NOT" statements:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Request form kept getting classified as a results report
config.set('classes.0.description',
    'A test request form submitted by a physician to order a specific test. '
    'Contains patient demographics, ordering physician info, and test selections. '
    'This is NOT a test results report — it does not contain test outcomes, '
    'findings, or diagnostic conclusions.')

config.set('classes.1.description',
    'A test results report containing diagnostic findings and conclusions. '
    'This is NOT a request form — it does not contain test order checkboxes '
    'or ordering physician signature blocks.')
```

**In the classification task prompt** — add cross-cutting negative instructions:

```python
current_prompt = config.get('classification.task_prompt')

negative_guidance = '''

IMPORTANT DISTINCTIONS:
- A request/order form asks for something to be done. A results report shows what was found. Do not confuse these even though both reference the same test names.
- A cover letter accompanies other documents. It is not the document it describes.'''

config.set('classification.task_prompt', current_prompt + negative_guidance)
config.save('workspace/updated-config.yaml')
```

**When to use negative prompting:**
- Two specific classes are consistently confused in the classification summary
- The confused classes share terminology or subject matter but serve different purposes
- Positive descriptions have already been improved but confusion persists

### 4. Use Structure-Based Differentiation

When document content overlaps between classes, describe the document's physical structure and format as a classification signal. Documents that contain similar words often have very different layouts, and the LLM can use structural cues to distinguish them.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Clinical notes vs. formal letters — similar medical content, different structure
config.set('classes.0.description',
    'Clinical notes written in free-form narrative style. Typically has a '
    'dated header with patient name, followed by unstructured paragraphs of '
    'clinical observations. No formal letter formatting — no recipient address '
    'block, no salutation line, no signature block with credentials.')

config.set('classes.1.description',
    'A formal letter of medical necessity in standard business letter format. '
    'Has a recipient address block at the top, a salutation line (e.g., '
    '"Dear...", "To Whom It May Concern"), structured body paragraphs, and '
    'a closing with physician signature and credentials. Unlike clinical notes, '
    'this is addressed TO someone.')

config.save('workspace/updated-config.yaml')
```

**Structural features to describe:**
- Document format (form with fields, letter with address block, narrative text, table-heavy)
- Header/footer patterns (letterhead, page numbers, document ID stamps)
- Section organization (numbered sections, free-form, tabular)
- Signature/authentication elements (signature blocks, notary stamps, checkboxes)
- Visual layout (multi-column, single column, form grid)

**When to use:**
- Classes share similar terminology but have different physical formats
- Content-based descriptions aren't sufficient to distinguish classes
- Documents have strong visual/structural differences that are easy to describe in words

### 5. Customize Classification Prompt

If default prompt isn't working, customize while keeping the placeholder:

```python
config.set('classification.task_prompt', '''
Classify this document into exactly one category from:
{CLASS_NAMES_AND_DESCRIPTIONS}

Examine the document's header, structure, and key terminology.
Return your classification in the specified JSON format.
''')
```

## Verification

1. Deploy updated config
2. Re-run evaluation
3. Compare `splitClassificationMetrics.accuracy` before/after
4. Check that previously misclassified documents now have correct class
