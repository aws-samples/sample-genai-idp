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

Use `get_evaluation_summary(batch_id)` to see per-field accuracy breakdown.

Look for the signature pattern:
- Top-level / document-level fields: high accuracy
- Array / per-entity fields: low accuracy
- Larger documents have worse per-entity accuracy than smaller ones

### Step 2: Check Entity Counts

Use `download_single_document_results(batch_id, 'complex-doc.pdf')` and `download_ground_truth(test_set_id, 'complex-doc.pdf')` to compare entity counts between extraction and ground truth. Use `execute_python_analysis` with the downloaded files to count entities in the ground truth array fields.

### Step 3: Check for Cross-Entity Confusion

Examine a few extracted entities and compare field values against the source document. If Program A's territory shows up under Program B, or dates are misaligned across entities, the LLM is losing track of which values belong to which entity.

## Fix 1: Restructure the Extraction Task Prompt

Guide the LLM to extract in a logical order within the single extraction call. Read the current prompt with `config_edit(config_path, [{"op": "get", "field": "extraction.task_prompt"}])`, then append hierarchical guidance:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended text below>"},
    {"op": "save"}
])
```

Text to append:

```
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
distinct combination. Do not merge them into one entry.
```

## Fix 2: Improve Array Field Schema Descriptions

Give the LLM explicit guidance about what constitutes a distinct entity:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.Programs.description",
     "value": "List of ALL programs/titles in the document. Each program that has ANY unique combination of rights, territories, dates, or terms MUST be a separate entry. If the same program title appears with different territorial rights or different time periods, create one entry per unique combination. Extract ALL entries — do not skip, summarize, or merge."},
    {"op": "set", "field": "classes.0.properties.Programs.x-aws-idp-list-item-description",
     "value": "Each item represents one program with a specific set of rights. If the same program has different rights for different territories or time periods, it appears as multiple items."},
    {"op": "save"}
])
```

## Fix 3: Use a Stronger Model for Complex Documents

More capable models handle long-context hierarchical extraction better:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.model", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"op": "save"}
])
```

See the `choosing-a-bedrock-model` skill for cost/quality tradeoffs.

## Fix 4: Ensure Sufficient Output Tokens

Documents with many entities produce large JSON outputs. Ensure max_tokens is high enough:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.max_tokens", "value": 65535},
    {"op": "save"}
])
```

See the `token-limit-fix` skill if output is being truncated.

## Fix 5: Separate Document-Level and Entity-Level Schemas

If the document type allows it, consider splitting into two document classes — one for document-level fields and one for entity-level fields. This only works in multi-class configurations where both classes can be applied to the same document:

- **Class 1**: Document-level metadata only (simpler extraction) — Properties: contract_type, date_executed, date_effective, parties, etc. No array fields.
- **Class 2**: Entity-level details only — Properties: the array of programs/items with per-entity fields. Task prompt can reference document-level context.

Use `config_edit` to set up both classes with their respective schemas.

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
