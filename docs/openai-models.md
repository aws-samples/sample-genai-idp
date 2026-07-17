---
title: "OpenAI GPT-5.x Models"
---

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# OpenAI GPT-5.x Models (GPT-5.4 / GPT-5.5 / GPT-5.6)

The GenAIIDP accelerator supports OpenAI's frontier models on Amazon Bedrock:
**GPT-5.4** (`openai.gpt-5.4`), **GPT-5.5** (`openai.gpt-5.5`), and the
**GPT-5.6** family — **Sol** (`openai.gpt-5.6-sol`, flagship reasoning),
**Terra** (`openai.gpt-5.6-terra`, GPT-5.5-class quality at roughly half the
cost), and **Luna** (`openai.gpt-5.6-luna`, fastest / lowest cost).

Unlike every other model in the accelerator, these are **not** served on the
Bedrock Converse / InvokeModel APIs. They are available only on the
**`bedrock-mantle` endpoint via the OpenAI Responses API**. The accelerator
hides this difference behind the existing `idp_common` Bedrock client: when a
model ID starting with `openai.gpt-5` is selected, `BedrockClient.invoke_model`
transparently routes the request to a SigV4-signed HTTP call against
`bedrock-mantle` (see `idp_common/bedrock/openai_responses.py`) and returns the
same response/metering shape every service already expects — so no per-service
code changes are required.

> **TL;DR** — all GPT-5.x models work for **OCR, classification, extraction,
> assessment, summarization, evaluation, and Chat-with-Document**. They do
> **not** work for **agentic extraction**, **Discovery**, or **Policy
> Discovery**, and are available in **US regions only**. GPT-5.6 adds prompt
> caching (see below). See the support matrix below.

## At a glance

| | GPT-5.4 | GPT-5.5 | GPT-5.6 Sol | GPT-5.6 Terra | GPT-5.6 Luna |
|---|---|---|---|---|---|
| Model ID | `openai.gpt-5.4` | `openai.gpt-5.5` | `openai.gpt-5.6-sol` | `openai.gpt-5.6-terra` | `openai.gpt-5.6-luna` |
| Context window | 272K | 272K | 272K | 272K | 272K |
| Max output tokens (capped by accelerator) | 128,000 | 128,000 | 128,000 | 128,000 | 128,000 |
| Endpoint | `bedrock-mantle` (Responses API) | ← | ← | ← | ← |
| In-Region availability | `us-east-1`, `us-east-2`, `us-west-2`, `us-gov-west-1` | `us-east-1`, `us-east-2` | `us-east-1`, `us-east-2` | `us-east-1`, `us-east-2`, `us-west-2` | `us-east-1`, `us-east-2`, `us-west-2` |
| Geo / Global cross-region inference | Not available | ← | ← | ← | ← |
| Service tier | Standard only | ← | ← | ← | ← |
| Prompt caching | Automatic (prefix > 1,024 tokens) | Automatic | **Explicit** breakpoints | **Explicit** | **Explicit** |
| Price / 1M (in / cache-read / out) | $2.75 / $0.275 / $16.50 | $5.50 / $0.55 / $33.00 | $5.50 / $0.55 / $33.00 | $2.75 / $0.28 / $16.50 | $1.10 / $0.11 / $6.60 |

There are **no** `eu.*` or `global.*` variants and **no** `:1m` context suffix —
the model IDs carry no region prefix. GPT-5.6 Sol is **not** available in
`us-west-2` (Terra and Luna are). GovCloud (`us-gov-west-1`) offers GPT-5.4 only.

## Prompt caching

`GPT-5.4`/`GPT-5.5` cache **automatically** — any prompt prefix over ~1,024
tokens is eligible for reuse with **no request changes** (the cache is populated
server-side after the prefix is first seen, so hits register on repeat calls),
and there is **no separate cache-write charge**. `<<CACHEPOINT>>` markers are
simply stripped for these models. (Verified live for GPT-5.5: `cached_tokens`
began registering on a repeated >1,024-token prefix with `cache_write_tokens`
staying 0.)

`GPT-5.6` (Sol/Terra/Luna) uses **explicit** caching: place a `<<CACHEPOINT>>`
marker at the end of the static portion of your prompt and the client translates
it into the Responses API's `prompt_cache_options` / `prompt_cache_breakpoint`
fields with a deterministic `prompt_cache_key` derived from the cached prefix.
Cache reads are billed at a 90% discount; GPT-5.6 also has a (30-minute)
cache-write price (reflected in `config_library/pricing.yaml`). Both are metered
via `cacheReadInputTokens` / `cacheWriteInputTokens`.

> **Token accounting note.** The OpenAI Responses `usage.input_tokens` is the
> *total* prompt size and already **includes** the cached / cache-written
> tokens. The accelerator's metering reports `inputTokens` as the **disjoint**
> fresh (uncached) count — `input_tokens − cached − cache_write` — so a cached
> token is billed once (at the cache rate), not twice. This matches the Bedrock
> Converse convention the cost model assumes. Verified live: a warm GPT-5.6
> extraction with `input_tokens=4508` / `cached=3193` reports
> `inputTokens=1315` + `cacheReadInputTokens=3193` (which reconcile to 4508).

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
| Prompt caching (`<<CACHEPOINT>>`) | ✅ (5.6) / auto (5.4/5.5) | GPT-5.6 translates `<<CACHEPOINT>>` into explicit Responses cache breakpoints; GPT-5.4/5.5 cache automatically for prefixes > 1,024 tokens (markers stripped). See [Prompt caching](#prompt-caching). |
| Service tiers (`:priority` / `:flex`) | ❌ | Standard tier only. |
| `temperature` / `top_p` / `top_k` | ❌ | These are reasoning models; sampling parameters are ignored. Use `reasoning_effort` instead. |
| EU / global cross-region inference | ❌ | US (and us-gov) in-region only; hidden in EU-region deployments. |

## Reasoning effort

GPT-5.x are reasoning models — they reject `temperature` / `top_p` / `top_k` and
are instead tuned with **reasoning effort**. Each model-selectable service (OCR,
classification, extraction, assessment, summarization, evaluation, and
Chat-with-Document) exposes a `reasoning_effort` config field.

`reasoning_effort` applies to **any reasoning-capable model**, not just OpenAI:

| Model family | Allowed values | Mechanism |
|---|---|---|
| OpenAI GPT-5.x | `minimal`, `low`, `medium`, `high` | Responses API `reasoning.effort` |
| Claude Sonnet 5 / Sonnet 4.6 / Opus 4.5–4.8 / Fable 5 | `low`, `medium`, `high`, `xhigh`, `max` | Bedrock Converse `output_config.effort` |

It is **ignored** by models without an effort control — Amazon Nova, Claude
Sonnet 4.5, and Claude Haiku 4.5. In the config UI, the **Reasoning effort**
selector appears only when the section's selected model supports it.

**Extraction defaults to `low`.** A full effort sweep (5 extraction methods ×
{low, medium, high, xhigh} × 2 datasets × 20 docs) found higher effort adds
output-token cost with negligible extraction-accuracy gain, so `low` keeps the
Claude Sonnet 5 default affordable. Raise it per-config for genuinely
reasoning-heavy documents. Other services default to `medium`.

```yaml
extraction:
  model: "openai.gpt-5.4"
  reasoning_effort: "high"   # OpenAI: minimal | low | medium | high

# or, for a reasoning-capable Claude model:
extraction:
  model: "us.anthropic.claude-sonnet-5"
  reasoning_effort: "low"    # Claude: low | medium | high | xhigh | max
```

## Regional availability and routing

GPT-5.4 is available in `us-east-1`, `us-east-2`, `us-west-2`, and
`us-gov-west-1`; GPT-5.5 in `us-east-1` and `us-east-2`. For GPT-5.6, Sol is in
`us-east-1` and `us-east-2`; Terra and Luna add `us-west-2`. There is no EU
availability and no geo/global cross-region inference, and GovCloud offers
GPT-5.4 only.

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

Pricing for all `bedrock/openai.gpt-5.*` models is defined in
`config_library/pricing.yaml` and matches OpenAI first-party rates on Bedrock
(in-region on-demand, per 1M tokens):

| Model | Input | Cache write (30m) | Cache read | Output |
|---|---|---|---|---|
| GPT-5.4 | $2.75 | — | $0.275 | $16.50 |
| GPT-5.5 | $5.50 | — | $0.55 | $33.00 |
| GPT-5.6 Sol | $5.50 | $6.88 | $0.55 | $33.00 |
| GPT-5.6 Terra | $2.75 | $3.44 | $0.28 | $16.50 |
| GPT-5.6 Luna | $1.10 | $1.38 | $0.11 | $6.60 |

GPT-5.4/5.5 cache automatically and have no cache-write cost. GPT-5.6 caches via
explicit breakpoints and bills a 30-minute cache-write. Confirm against the
[Amazon Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) if rates
change.

## Choosing a model

Use GPT-5.4/5.5 for OCR, classification, extraction, assessment, summarization,
evaluation, or chat where their reasoning quality helps and inputs are text or
page images. For workloads that require **whole-PDF ingestion** (Discovery,
Policy Discovery) or **agentic extraction**, choose a Claude or Nova model,
which accept PDF document blocks natively and support the Converse/Strands
paths.
