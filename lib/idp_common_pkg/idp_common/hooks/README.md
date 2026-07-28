# Pipeline Hook Helpers

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

Helpers for authoring **pipeline-hook Lambdas** — the functions the unified
workflow invokes at its extension points, via the host's pipeline-hooks
dispatcher (`patterns/unified/src/pipeline_hooks_function`).

A hook may simply observe the pipeline, or hand a **modified `Document`** back
for the next step to consume. This module makes that round-trip safe in two
calls.

## Installation

```
pip install "idp_common[core]"
```

No extra dependencies beyond core — the helpers only touch `Document` and S3.

## Quick start

```python
from idp_common.hooks import load_hook_document, updated_document_result

def lambda_handler(event, context):
    document = load_hook_document(event)     # resolves compressed refs for you

    for section in document.sections:
        if section.classification == "Unknown":
            section.classification = classify_with_my_rules(section)

    return updated_document_result(document, rulesApplied=True)
```

Set the `WORKING_BUCKET` env var on the hook Lambda (from the host's
`<MainStackName>-WorkingBucketName` export) so compressed documents resolve.

## API

### `load_hook_document(event, working_bucket=None) -> Document`

Resolves the hook event's `document` payload to a full `Document`, handling both
shapes the dispatcher may send:

| Payload shape | Handling |
|---|---|
| Compressed reference (`{compressed: true, s3_uri, ...}`) — the common case | Fetched from the working bucket |
| Inline document dict | Parsed directly |

`working_bucket` defaults to the `WORKING_BUCKET` env var. Raises `ValueError`
if the event has no usable document, or if a compressed reference arrives with
no bucket to resolve it from — failing loudly beats returning a half-empty
document the hook would then hand back as an "update".

### `updated_document_result(document, working_bucket=None, size_threshold_kb=200, **extra) -> dict`

Builds the hook response that hands `document` to the next workflow step, under
the `updatedDocument` key the dispatcher reads. Documents under
`size_threshold_kb` are returned inline (the dispatcher spills them to S3
itself); larger ones are compressed here, keeping the hook's synchronous
response well under Lambda's 6 MB limit at any document size.

`**extra` is merged into the response — your own result fields, and/or
`halt=True` at the `preprocessing` point:

```python
return updated_document_result(document, halt=True, redactedKey=key)
```

### `UPDATED_DOCUMENT_KEY`

The response key the dispatcher reads a modified document from
(`"updatedDocument"`). Deliberately not `"document"`, so a read-only hook that
echoes its input cannot accidentally start mutating the pipeline.

## Why use these helpers

- **The event rarely contains the document itself.** It's usually a small
  compressed reference; `load_hook_document` hides the difference.
- **Building a `Document` from scratch loses data.** `metering`, `errors`,
  `hitl_metadata`, and `processing_issues` are silently dropped. Load → mutate →
  return preserves them.
- **The dispatcher only honors one key.** Returning any other shape leaves the
  pipeline's document untouched.

## Guardrails

The dispatcher **refuses** an update that violates any of these, keeping the
pre-hook document and recording the reason in
`$.HookResults.<point>.Payload.results[].documentUpdateRejected`. It never fails
the workflow over a bad update:

| Rule | Why |
|---|---|
| `id` / `input_key` / `input_bucket` / `output_bucket` are immutable | The tracking-table row and output S3 prefixes are keyed off them |
| `sections` in a compressed reference must be a list of section-id strings | The workflow's `ProcessSections` Map iterates it directly |
| `config_version` is preserved | It resolves hooks for the rest of the pipeline |
| Inline documents capped at 5 MB | Bounded by Lambda's 6 MB response limit |

The dispatcher also **carries forward** the state machine's routing control
fields — `use_bda` and `bda_project_arn`. These ride on the document payload
(injected by the queue processor from the resolved config) but are *not*
`Document` model fields, so the load → mutate → return round-trip drops them.
Left dropped, `use_bda` would fail the execution at the BDA/pipeline routing
Choice. You get them back automatically; set one explicitly to override.

## Hook-point scope

Where a mutation reaches depends on the point:

| Point | Scope | Propagates to |
|---|---|---|
| `preprocessing` | Whole document, pre-OCR | Everything downstream |
| `postOcr` | Whole document + page results | Classification onward |
| `postClassification` | Whole document | The section Map fan-out and everything after |
| `postExtraction` | **A single section** (runs inside the Map) | Assessment; only `sections[0]` + `metering` merge into the final document |
| `postRuleValidation` | Whole document | Summarization, evaluation, final output |
| `postSummarization` | Whole document | Evaluation and the final workflow output |

## See also

- [Feature Platform → Pipeline hooks](../../../../docs/feature-platform.md#pipeline-hooks) — full contract
- [Feature Platform developer guide](../../../../docs/feature-platform-developer-guide.md) — registering a hook
- [Document model](../README.md) — what you can mutate
