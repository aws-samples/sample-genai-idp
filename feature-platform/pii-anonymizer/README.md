# PII Anonymization — IDP Accelerator Extension

Detects and redacts PII from source documents **before** the accelerator's
classification and extraction models see them, so raw PII never transits a GenAI
model. Built on a new standalone **`preprocessing`** pipeline hook that runs
first — before the BDA/pipeline routing — in both processing modes.

Reuses the document detection/redaction library from the AWS Labs
[pii-anonymizer](https://github.com/awslabs/pii-anonymizer) sample (Apache-2.0),
**vendored** under `hook/vendor/` so the accelerator owns and security-scans it.
See `hook/vendor/PROVENANCE.md` and the `sync-pii-anonymizer` Claude skill for
the re-sync procedure.

## How it works

1. A document is uploaded under a config version that carries a `preprocessing`
   block + hook (created by the Config Pairing wizard).
2. The `preprocessing` hook (`hook/handler.py`) runs first. It detects + redacts
   PII and writes a **de-identified copy** into the Input bucket beside the
   original with a `(REDACTED)` marker in its name (e.g. `report(REDACTED).pdf`),
   stamped with S3 metadata `config-version=<companion>`.
3. That upload re-triggers processing — the redacted copy is processed under the
   **companion** config version (which has **no** preprocessing hook, so it is
   not redacted again; a `(REDACTED)`-marker guard is the belt-and-suspenders).
4. Depending on **mode**, the hook either halts the original execution
   (`redacted_only` → the original is marked `REDACTED_SUPERSEDED`) or lets it
   run too (`redacted_and_unredacted` → original + redacted processed separately).

## Modes

| Mode | Original | Redacted copy | Use case |
|------|----------|---------------|----------|
| `redacted_only` | halted (`REDACTED_SUPERSEDED`) | processed | PII must never reach the model / be stored in results |
| `redacted_and_unredacted` | processed | processed | Two result sets; scope each to different users via `allowedConfigVersions` RBAC |

## Config Pairing wizard (primary UX)

The feature UI's **Config Pairing** tab clones an admin's **existing** working
config version into a matched pair:

- `<base>__pii_redacted_only` / `<base>__pii_both` — *initiating* version: the
  base + a `preprocessing` block (mode, detection model, redaction style,
  companion pointer) + the resolved `preprocessing.preHook` entry.
- `<base>__standard` — *companion* version: the base with **no** preprocessing
  block/hook; the redacted copy is processed under it.

Both are created **non-active**; the admin activates the initiating version
(one click in the wizard). This keeps the customer's real extraction settings
authoritative and layers redaction on top.

A minimal `config-preset/pii-preprocessing.yaml` is also installed as a
non-active `pii-anonymizer-v<version>` quick-start reference.

## Redaction Report

The **Redaction Report** tab shows a **metadata-only** audit (no PII is stored):
per-document PII count, mode, companion version, redacted-copy key, timestamp.
Backed by the feature API (`/report`) over the feature-owned audit table.

## Cost note

Redaction adds a detection pass per page **before** processing. On scanned
documents the anonymizer runs its own Textract + vision pass, so `redacted_only`
on scanned docs OCRs twice, and `redacted_and_unredacted` runs ~2× the whole
pipeline. Nova Lite is the cost-sensitive default detection model.

## Formats (v1)

PDF (redacted PDF out — always via the image path so the copy is a real,
flattened PDF with no leaked text layer), images (JPG/PNG/TIFF/BMP/WEBP), TXT,
CSV. Office formats (DOCX/XLSX) work via the vendored processors but are lower-fidelity;
audio is out of scope.

## Not a sole compliance control

LLM-based PII detection is probabilistic. Pair with human verification for
compliance-critical use — position as strong risk-reduction, not a guarantee.

## Layout

```
feature.yaml              # manifest (preprocessing hook + writes-documents)
template.yaml             # hook Lambda + deps layer + audit table + API + ui-deployer
config-preset/pii-preprocessing.yaml
hook/handler.py           # the preprocessing hook (+ vendor/ closure)
feature-api/handler.py    # Redaction Report API
feature-ui/               # Config Pairing wizard + Redaction Report (UMD bundle)
ui-deployer/handler.py    # install-time registration + preset apply
```

## Tests

```bash
(cd hook && python -m pytest tests -q)
(cd feature-api && python -m pytest tests -q)
(cd ui-deployer && python -m pytest tests -q)
(cd feature-ui && npm ci && npm run build)   # tsc --noEmit + vite
```
