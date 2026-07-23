---
title: "PII Anonymization"
---
# PII Anonymization

**PII Anonymization** is a bundled [Extension Feature](../feature-platform.md)
that detects and redacts personally identifiable information (PII) from source
documents **before** the accelerator's classification and extraction models see
them — so raw PII never transits a GenAI model. It is the reference example of a
**`preprocessing`** pipeline hook: a standalone extension point that runs first
in the workflow, before the BDA/pipeline routing, in both processing modes.

It reuses the document detection/redaction library from the AWS Labs
[pii-anonymizer](https://github.com/awslabs/pii-anonymizer) sample (Apache-2.0),
vendored into the feature so the accelerator owns and security-scans the code.

> **Not a sole compliance control.** LLM-based PII detection is probabilistic —
> missed PII is possible. Pair this with human verification for
> compliance-critical workflows. Position it as a strong risk-reduction layer,
> not a guarantee.

## Why use it

- **Unblocks GenAI adoption in regulated settings.** Healthcare, finance,
  insurance, and government teams that currently *can't* use GenAI extraction
  because raw PII can't transit a model can now redact first.
- **De-identified datasets as a deliverable** — safe for analytics, ML training,
  or sharing with third parties.
- **Dual-track access** — process both an original and a redacted copy, and scope
  each to different users via the existing config-version RBAC.
- **Structure-preserving synthetic redaction** keeps downstream extraction
  accuracy intact (unlike simple blackout).

## How it works

1. A document is uploaded under a config version that carries a `preprocessing`
   block and hook (created by the **Config Pairing** wizard).
2. The preprocessing hook runs first. It detects and redacts PII, then writes a
   **de-identified copy** into the Input bucket under the reserved
   `_pii_redacted/` prefix, tagged with S3 metadata pointing at a **companion**
   config version.
3. That upload re-triggers processing: the redacted copy is processed under the
   companion version (which has no preprocessing hook, so it is not redacted
   again — a reserved-prefix guard prevents any loop).
4. Depending on the **mode**, the original execution either halts or continues.

### Modes

| Mode | Original document | Redacted copy | When to use |
|------|-------------------|---------------|-------------|
| **Redacted only** | Halted, marked `REDACTED_SUPERSEDED` | Processed | PII must never reach the model or be stored in results |
| **Process both** | Processed | Processed | You need two result sets; scope each to different users |

## Enabling it — the Config Pairing wizard

Install the feature from the **Extensions → Browse catalog** page, then open its
page. The **Config Pairing** tab is the primary way to turn redaction on:

1. Pick one of your **existing** config versions as the base (your real
   extraction settings are preserved).
2. Choose a mode, a PII-detection model (Claude Haiku is the default — dense
   forms like W2s need a large output-token budget, and Nova Lite's smaller cap
   truncates the detection JSON, which the detector fails closed on), and a
   redaction style (synthetic or blackout).
3. Click **Create config pair**. The wizard creates two **non-active** versions:
   - `<base>__pii_redacted_only` (or `__pii_both`) — the *initiating* version,
     with the redaction hook.
   - `<base>__standard` — the *companion*, which processes the redacted copy.
4. Click **Activate** to make the initiating version active. New uploads under it
   are redacted first.

This clones on top of your existing config rather than forking a whole
configuration you'd have to keep in sync. (A minimal `pii-anonymizer-v<version>`
quick-start preset is also installed, non-active, for reference.)

### RBAC — two-track access

For **Process both**, the original is processed under `<base>__pii_both` and the
redacted copy under `<base>__standard`. Grant privileged reviewers access to the
original's config version and everyone else access to `<base>__standard` using
each user's **allowed config versions** (Configuration page → user scope). Note
this reuses the config-version scope as a data-sensitivity boundary.

## Redaction Report

The **Redaction Report** tab shows a **metadata-only** audit (no PII is ever
stored or displayed): per-document PII count, mode, companion version, redacted
copy location, and timestamp, with a time-window filter.

## Cost and latency

Redaction adds a detection pass per page **before** processing:

- **Text-native** documents (digital PDF, TXT, CSV) use lightweight text
  extraction — modest added cost.
- **Scanned/image** documents require the anonymizer's own Textract + vision
  pass, so **Redacted only** on scanned docs runs OCR twice, and **Process both**
  runs roughly twice the whole pipeline. Budget accordingly.

Claude Haiku is the default detection model (reliable on dense forms). Nova Lite
is cheaper and fine for lighter documents, but may truncate — and fail closed —
on dense multi-field pages.

## Supported formats (v1)

PDF (text and scanned/image), images (JPG/PNG/TIFF/BMP/WEBP), TXT, and CSV.
Office formats (DOCX/XLSX) are processed but lower-fidelity; audio is out of
scope.

## See also

- [Feature Platform](../feature-platform.md) — how extensions work.
- [Feature Platform developer guide](../feature-platform-developer-guide.md).
