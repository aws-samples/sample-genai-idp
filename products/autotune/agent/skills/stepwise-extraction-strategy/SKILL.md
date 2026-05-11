---
name: stepwise-extraction-strategy
description: Diagnose and mitigate complex document extraction failures caused by documents with many repeating entities or nested hierarchical structures. Use when single-pass extraction produces entry count mismatches, cross-entity confusion, or low accuracy on per-entity fields despite good document-level field accuracy.
---

# Stepwise Extraction Strategy

## Problem

Some documents contain hierarchical structures where many repeating entities (programs, line items, parties, claims) each have their own set of fields. When the LLM must extract both document-level metadata AND per-entity details in a single pass, it struggles with:

- Correctly identifying all entities (count mismatches)
- Keeping per-entity fields aligned (e.g., assigning the right territory to the right program)
- Maintaining accuracy as entity count grows (accuracy degrades beyond ~20-30 entities)
- Staying within output token limits for very large entity lists (100+ items)

Past engagements have shown that establishing document-level context first (contract type, parties, dates) provides an essential framework for interpreting entity-level details. A step-wise approach — document-level first, then entity identification, then per-entity extraction — yielded the highest accuracy on complex documents. However, the IDP accelerator performs a single extraction call per document class, so this skill focuses on maximizing what's achievable within that constraint and flagging when a custom pipeline is needed.

## Symptoms

- Document-level fields (contract type, dates, parties) have high accuracy (>90%) but per-entity fields (per-program rights, per-item details) have low accuracy
- Entity count mismatches: LLM extracts fewer or more entities than ground truth
- Cross-entity confusion: field values from one entity appear under another (e.g., Program A's territory assigned to Program B)
- Accuracy degrades as document complexity increases (more pages, more entities)
- Truncated JSON output on documents with many entities (see `token-limit-fix` skill)
- The same program/entity appears multiple times when rights vary by territory or time period, and the LLM fails to properly segment these into separate entries

## Diagnosis

### Step 1: Identify the Pattern

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')
result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_aggregated_summary(top_bottom_n=5)
```

Look for the signature pattern:
- Top-level / document-level fields: high accuracy
- Array / per-entity fields: low accuracy
- Larger documents have worse per-entity accuracy than smaller ones

### Step 2: Check Entity Counts

```python
import json

# Compare entity counts between extraction and ground truth
client.download_single_document_results('batch-id', 'complex-doc.pdf', 'investigation/')
client.download_ground_truth('test-set-id', 'complex-doc.pdf', 'investigation/gt.json')

with open('investigation/gt.json') as f:
    gt = json.load(f)

# Count entities in ground truth array field
gt_entities = gt.get('inference_result', {}).get('Programs', [])
print(f"Ground truth entity count: {len(gt_entities)}")

# Compare with extraction output
# If extraction has significantly fewer entities, single-pass is struggling
```

### Step 3: Check for Cross-Entity Confusion

Examine a few extracted entities and compare field values against the source document. If Program A's territory shows up under Program B, or dates are misaligned across entities, the LLM is losing track of which values belong to which entity.

## Fix 1: Restructure the Extraction Task Prompt

Guide the LLM to extract in a logical order within the single extraction call. This mimics step-wise extraction within the constraints of one prompt:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

current_prompt = config.get('extraction.task_prompt')

hierarchical_guidance = '''

EXTRACTION APPROACH FOR COMPLEX DOCUMENTS:
Follow this order when extracting from this document:

1. DOCUMENT-LEVEL FIELDS FIRST: Extract all top-level document metadata
   (contract type, execution date, effective date, parties) before examining
   individual entities/items.

2. ENTITY IDENTIFICATION: Identify ALL distinct entities (programs, items,
   claims, etc.) in the document. Count them carefully. Each entity that has
   ANY unique field value (different dates, territories, rights, etc.) must
   be a separate entry in the output array.

3. PER-ENTITY EXTRACTION: For each identified entity, extract its specific
   fields. Use the document-level context established in step 1 to resolve
   ambiguities. If a field value is not specified for a particular entity,
   check whether a document-level default applies.

CRITICAL: When the same item appears with different terms (e.g., different
territories, date ranges, or rights), create SEPARATE entries for each
distinct combination. Do not merge them into one entry.'''

config.set('extraction.task_prompt', current_prompt + hierarchical_guidance)
config.save('workspace/updated-config.yaml')
```

## Fix 2: Improve Array Field Schema Descriptions

Give the LLM explicit guidance about what constitutes a distinct entity and how to handle variations:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Describe the array field with explicit counting and segmentation guidance
config.set('classes.0.properties.Programs.description',
    'List of ALL programs/titles in the document. Each program that has ANY '
    'unique combination of rights, territories, dates, or terms MUST be a '
    'separate entry. If the same program title appears with different territorial '
    'rights or different time periods, create one entry per unique combination. '
    'Extract ALL entries — do not skip, summarize, or merge.')

# Add x-aws-idp-list-item-description for array items
config.set('classes.0.properties.Programs.x-aws-idp-list-item-description',
    'Each item represents one program with a specific set of rights. '
    'If the same program has different rights for different territories '
    'or time periods, it appears as multiple items.')

config.save('workspace/updated-config.yaml')
```

## Fix 3: Use a Stronger Model for Complex Documents

More capable models handle long-context hierarchical extraction better:

```python
config.set('extraction.model', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
# For the most complex documents:
config.set('extraction.model', 'us.anthropic.claude-opus-4-5-20251101-v1:0')
```

See the `choosing-a-bedrock-model` skill for cost/quality tradeoffs.

## Fix 4: Ensure Sufficient Output Tokens

Documents with many entities produce large JSON outputs. Ensure max_tokens is high enough:

```python
config.set('extraction.max_tokens', 65535)
```

See the `token-limit-fix` skill if output is being truncated.

## Fix 5: Separate Document-Level and Entity-Level Schemas

If the document type allows it, consider splitting into two document classes — one for document-level fields and one for entity-level fields. This only works in multi-class configurations where both classes can be applied to the same document:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Class 1: Document-level metadata only (simpler extraction)
# Properties: contract_type, date_executed, date_effective, parties, etc.
# No array fields — just the top-level metadata

# Class 2: Entity-level details only
# Properties: the array of programs/items with per-entity fields
# Task prompt can reference document-level context

# This approach requires post-processing to merge the two outputs
```

**Note**: This approach requires a post-processing Lambda hook to combine the outputs from both classes into a single result. It adds architectural complexity and may not be worth it unless the accuracy gap is significant.

## When to Flag for Human Review

If after applying Fixes 1-4, per-entity accuracy remains significantly below document-level accuracy (>15 point gap), and the documents routinely have 50+ entities, flag this to the human:

> "This dataset contains documents with complex hierarchical structures
> (averaging [N] entities per document, up to [max]). The IDP accelerator's
> single-pass extraction architecture is reaching its limits for this
> complexity level.
>
> Current results:
> - Document-level field accuracy: [X%]
> - Per-entity field accuracy: [Y%]
>
> I've optimized the prompts, schema descriptions, and model selection within
> the current architecture. To close the remaining accuracy gap, I recommend
> considering a custom multi-stage extraction pipeline where:
> 1. Stage 1 extracts document-level metadata
> 2. Stage 2 identifies all entities
> 3. Stage 3 extracts per-entity details with document-level context
>
> This would require custom infrastructure (e.g., Step Functions workflow)
> outside the standard IDP configuration. Would you like to proceed with
> the current config, or explore a custom pipeline approach?"

## Interaction with Other Skills

- **`token-limit-fix`**: Large entity counts often hit token limits. Apply that skill first if output is truncated.
- **`extraction-prompt-engineering`**: Enrich per-entity field descriptions to reduce ambiguity within the single-pass extraction.
- **`post-processing-task-decomposition`**: If entity-level fields need ID remapping or deduplication, combine this skill's prompt guidance with post-processing rules.
- **`nested-schema-design`**: Ensure array fields use proper `$defs`/`$ref` structure for structured entity extraction.
- **`choosing-a-bedrock-model`**: Stronger models handle hierarchical extraction better — consider upgrading for complex documents.

## Verification

1. Apply prompt restructuring and schema improvements
2. Re-run evaluation on the same test set
3. Compare per-entity field accuracy before and after
4. Check entity count alignment (extracted vs ground truth)
5. Spot-check a few complex documents for cross-entity confusion
6. If accuracy gap remains large, flag for human review with the recommendation above
