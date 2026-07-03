---
title: "OpenAI GPT-5.x Models"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# OpenAI GPT-5.x Models (GPT-5.4 / GPT-5.5)

The GenAIIDP accelerator supports OpenAI's frontier models **GPT-5.4**
(`openai.gpt-5.4`) and **GPT-5.5** (`openai.gpt-5.5`) on Amazon Bedrock.

Unlike every other model in the accelerator, these are **not** served on the
Bedrock Converse / InvokeModel APIs. They are available only on the
**`bedrock-mantle` endpoint via the OpenAI Responses API**. The accelerator
hides this difference behind the existing `idp_common` Bedrock client: when a
model ID starting with `openai.gpt-5` is selected, `BedrockClient.invoke_model`
transparently routes the request to a SigV4-signed HTTP call against
`bedrock-mantle` (see `idp_common/bedrock/openai_responses.py`) and returns the
same response/metering shape every service already expects — so no per-service
code changes are required.

> **TL;DR** — GPT-5.4/5.5 work for **OCR, classification, extraction,
> assessment, summarization, evaluation, and Chat-with-Document**. They do
> **not** work for **agentic extraction**, **Discovery**, or **Policy
> Discovery**, and are available in **US regions only**. See the support matrix
> below.

## At a glance

| | GPT-5.4 | GPT-5.5 |
|---|---|---|
| Model ID | `openai.gpt-5.4` | `openai.gpt-5.5` |
| Context window | 272K tokens | 272K tokens |
| Max output tokens (capped by accelerator) | 128,000 | 128,000 |
| Endpoint | `bedrock-mantle` (OpenAI Responses API) | `bedrock-mantle` (OpenAI Responses API) |
| In-Region availability | `us-east-2`, `us-west-2`, `us-gov-west-1` | `us-east-2` |
| Geo / Global cross-region inference | Not available | Not available |
| Service tier | Standard only | Standard only |

There are **no** `eu.*` or `global.*` variants and **no** `:1m` context suffix —
the model IDs carry no region prefix.

## What is supported

| Capability | Supported? | Notes |
|---|---|---|
| OCR (Bedrock backend) | ✅ | Image + text input |
| Classification | ✅ | Page-level and holistic |
| Extraction (standard) | ✅ | Text + page images |
| Confidence (assessment) | ✅ | `separate` and `integrated` modes on the simple (non-agentic) path |
| Summarization | ✅ | |
| Evaluation (LLM method) | ✅ | |
| Chat-with-Document | ✅ | **Streaming** — token deltas stream to the UI via the Responses SSE stream |
| Text input | ✅ | |
| Image input | ✅ | Page images are sent as image content |
| Reasoning effort control | ✅ | New `reasoning_effort` config field (see below) |
| Guardrails | ✅ | Applied via the standard headers on the mantle endpoint |

## What is NOT supported

| Capability | Supported? | Why / what happens |
|---|---|---|
| **Agentic extraction** (`extraction.agentic.enabled: true`) | ❌ | The agentic path uses the Strands framework over the Converse API, which GPT-5.x doesn't support. This combination is a **hard error** in `idp-cli config-validate` and **raises at runtime**. |
| **Discovery** (classes / without- & with-ground-truth / auto-split) | ❌ | Discovery ingests whole PDFs as Converse `document` blocks, which the Responses API cannot accept (text + image only). Rejected by `config-validate` and **guarded at runtime**. |
| **Policy / Rule Discovery** | ❌ | Same PDF-document-block limitation; agentic rule discovery also uses Strands. Rejected by `config-validate` and guarded at runtime. |
| PDF `document` input blocks | ❌ | The Responses API accepts text and images only. Pipelines that need whole-PDF ingestion should use a Claude or Nova model. |
| Prompt caching (`<<CACHEPOINT>>`) | ❌ | Not supported by these models; `<<CACHEPOINT>>` markers are stripped automatically. |
| Service tiers (`:priority` / `:flex`) | ❌ | Standard tier only. |
| `temperature` / `top_p` / `top_k` | ❌ | These are reasoning models; sampling parameters are ignored. Use `reasoning_effort` instead. |
| EU / global cross-region inference | ❌ | US (and us-gov) in-region only; hidden in EU-region deployments. |

## Reasoning effort

GPT-5.x are reasoning models — they reject `temperature` / `top_p` / `top_k` and
are instead tuned with **reasoning effort**. Each model-selectable service (OCR,
classification, extraction, assessment, summarization, evaluation, and
Chat-with-Document) exposes a `reasoning_effort` config field. Allowed values:
`minimal`, `low`, `medium`, `high` (default `medium`). It is an **OpenAI-only**
parameter — ignored by Anthropic / Nova and other model families.

```yaml
extraction:
  model: "openai.gpt-5.4"
  reasoning_effort: "high"   # minimal | low | medium | high
```

## Regional availability and routing

GPT-5.5 is available in `us-east-2` only; GPT-5.4 in `us-east-2`, `us-west-2`,
and `us-gov-west-1`. There is no EU availability and no geo/global cross-region
inference.

If the IDP stack is deployed in a region where the selected model is not
available, the accelerator routes the `bedrock-mantle` request to a
known-available region (logging a warning about cross-region data movement). To
pin the region explicitly, set `BEDROCK_MANTLE_REGION`. EU-region deployments
**hide** these models from the configuration picklists entirely (they are not
callable there). See [EU Region Model Support](eu-region-model-support.md).

## IAM

Lambda execution roles that perform generation are granted the
`bedrock-mantle:CreateInference` action (plus `GetProject` / `ListProjects` /
`ListTagsForResources`) — equivalent to the AWS-managed
`AmazonBedrockMantleInferenceAccess` policy. When routing Bedrock through a
cross-account hub role, that role must also grant these `bedrock-mantle` actions
— see [Cross-Account Bedrock](cross-account-bedrock.md).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `BEDROCK_MANTLE_REGION` | Pin the `bedrock-mantle` region for all GPT-5.x calls | Derived from the stack region with a per-model fallback |
| `BEDROCK_MANTLE_SIGNING_NAME` | SigV4 signing service name | `bedrock-mantle` |
| `BEDROCK_MANTLE_REASONING_EFFORT` | Global fallback reasoning effort when a service config omits `reasoning_effort` | `medium` |

## Pricing

Pricing for `bedrock/openai.gpt-5.4` and `bedrock/openai.gpt-5.5` is defined in
`config_library/pricing.yaml` and matches OpenAI first-party rates on Bedrock
(per 1M tokens):

| Model | Input | Cached input | Output |
|---|---|---|---|
| GPT-5.4 | $2.75 | $0.275 | $16.50 |
| GPT-5.5 | $5.50 | $0.55 | $33.00 |

Confirm against the [Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/)
if rates change.

## Choosing a model

Use GPT-5.4/5.5 for OCR, classification, extraction, assessment, summarization,
evaluation, or chat where their reasoning quality helps and inputs are text or
page images. For workloads that require **whole-PDF ingestion** (Discovery,
Policy Discovery) or **agentic extraction**, choose a Claude or Nova model,
which accept PDF document blocks natively and support the Converse/Strands
paths.
