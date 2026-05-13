---
name: prompt-caching-optimization
description: Reduce LLM token costs by enabling Bedrock prompt caching via the <<CACHEPOINT>> delimiter. Use when processing cost is a concern, especially with long prompts, few-shot examples, or high document volumes.
---

# Prompt Caching Optimization

## Problem

Every document processed through the IDP pipeline sends the full prompt (system instructions, task instructions, few-shot examples, schema descriptions) to the LLM. For extraction and classification, the static portions of these prompts are identical across every document — only the document content changes. Without caching, you pay full input token price for the same instructions on every single document.

Prompt caching stores the static portions of prompts and reuses them across requests. Cached read tokens are approximately 10x cheaper than standard input tokens. For high-volume processing or prompts with large few-shot examples (especially with images), this can significantly reduce costs.

## Symptoms

- Processing costs are high relative to document volume
- Prompts contain long static instructions, detailed schema descriptions, or few-shot examples with images
- The same extraction/classification prompts are used across hundreds or thousands of documents
- Cost breakdown shows high input token costs relative to output tokens

## Diagnosis

Use `get_evaluation_summary(batch_id)` to check current costs and cost breakdown.

Then inspect current prompts for caching opportunity:

```
config_edit(config_path, operations=[
    {"op": "get", "field": "extraction.task_prompt"},
    {"op": "get", "field": "classification.task_prompt"},
    {"op": "get", "field": "classes"}
])
```

Large prompts benefit most from caching. Check if few-shot examples are configured (high-value caching target) — classes with `x-aws-idp-examples` entries have the most to gain from caching.

## How It Works

Insert a `<<CACHEPOINT>>` delimiter in your prompt to separate static (cacheable) content from dynamic (per-document) content. Everything before the delimiter is cached and reused across requests. Everything after it is unique per document.

The IDP accelerator handles the caching mechanics automatically — you just need to place the delimiter correctly.

### Pricing Impact

Cached read tokens cost approximately 10x less than standard input tokens. Cache write tokens cost slightly more than standard input tokens (the first request pays a small premium to populate the cache). After the first request, all subsequent requests benefit from the reduced read price.

```
Standard input:      $X per token
Cache write (first): ~1.25× standard (one-time cost)
Cache read (reuse):  ~0.1× standard (10x savings on every subsequent request)
```

## Fix 1: Add CachePoint to Extraction Prompts

Place the `<<CACHEPOINT>>` delimiter after all static instructions and before the dynamic document content:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "You are an expert document analyst. Extract the requested fields accurately.\n\nEXTRACTION GUIDELINES:\n- Extract values exactly as they appear in the document unless a specific format is requested.\n- For fields with no matching value, return null.\n- For date fields, convert to YYYY-MM-DD format.\n- For numeric fields, extract only the numeric value without currency symbols.\n\nExtract the following fields:\n{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n\n<<CACHEPOINT>>\n\nHere is the document to analyze:\n{DOCUMENT_TEXT}\n\n{DOCUMENT_IMAGE}\n\nReturn your response as valid JSON."},
    {"op": "save"}
])
```

**Key placement rule**: Static content (instructions, guidelines, attribute descriptions) goes BEFORE `<<CACHEPOINT>>`. Dynamic content (`{DOCUMENT_TEXT}`, `{DOCUMENT_IMAGE}`) goes AFTER.

Note: `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` is static per class (same schema for every document of that class), so it belongs before the cachepoint.

## Fix 2: Add CachePoint to Classification Prompts

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.task_prompt", "value": "Classify this document into exactly one category from:\n{CLASS_NAMES_AND_DESCRIPTIONS}\n\nReturn your classification in JSON format with the document type.\n\n<<CACHEPOINT>>\n\nDocument to classify:\n{DOCUMENT_TEXT}\n\n{DOCUMENT_IMAGE}"},
    {"op": "save"}
])
```

## Fix 3: Combine CachePoint with Few-Shot Examples

Few-shot examples with images are the highest-value caching target because image tokens are expensive. Place examples before the cachepoint so they are cached across all documents:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "Extract the following fields from this {DOCUMENT_CLASS} document:\n\n{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n\nHere are examples of correct extractions:\n<few_shot_examples>\n{FEW_SHOT_EXAMPLES}\n</few_shot_examples>\n\n<<CACHEPOINT>>\n\nNow extract the attributes from this document:\n{DOCUMENT_TEXT}\n\n{DOCUMENT_IMAGE}\n\nReturn your response as valid JSON."},
    {"op": "save"}
])
```

The few-shot examples (including their images) are identical for every document of the same class, so caching them avoids re-sending those expensive image tokens on every request.

## Fix 4: CachePoint for System Prompts

System prompts are also cacheable. If your system prompt is long, add a cachepoint:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.system_prompt", "value": "You are an expert document analyst specializing in structured data extraction from business documents. You have deep expertise in identifying and extracting key fields from complex document layouts.\n\n<<CACHEPOINT>>"},
    {"op": "save"}
])
```

For short system prompts (1-2 sentences), caching provides minimal benefit — focus on task prompts first.

## Model Compatibility

CachePoint requires a compatible Bedrock model. As of the current IDP accelerator version, supported models include:

- `us.anthropic.claude-3-5-haiku-20241022-v1:0`
- `us.anthropic.claude-3-7-sonnet-20250219-v1:0`
- `us.amazon.nova-lite-v1:0`
- `us.amazon.nova-pro-v1:0`

**Important**: Model support for prompt caching evolves over time. Newer models (e.g., Claude Sonnet 4.5, Claude Haiku 4.5) may also support caching. If you are using a model not listed above, check the [Amazon Bedrock documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) for current cachepoint support. If the model does not support caching, the `<<CACHEPOINT>>` delimiter is simply ignored — it won't cause errors.

## When NOT to Use

- Very short prompts with minimal static content — the cache write overhead may not be worth it for a few hundred tokens
- Single-document processing (no reuse opportunity)
- If you are frequently changing prompts during active optimization iterations — the cache is invalidated on every prompt change, so you pay the write cost each time

## Interaction with Other Skills

- **`extraction-few-shot-examples`**: Few-shot examples with images are the highest-value caching target. Always combine few-shot examples with cachepoint.
- **`choosing-a-bedrock-model`**: Verify your chosen model supports cachepoint before adding delimiters.
- **`extraction-prompt-engineering`**: As you enrich field descriptions (making prompts longer), caching becomes more valuable.

## Verification

1. Run evaluation WITHOUT cachepoint, note `totalCost` and `costBreakdown`
2. Add `<<CACHEPOINT>>` delimiters to prompts
3. Upload updated config and re-run evaluation on the same test set
4. Compare costs using `get_evaluation_summary` on both batch IDs and comparing the `totalCost` values.
5. Verify accuracy is unchanged — cachepoint should not affect extraction or classification quality
6. Document cost savings in the optimization log
