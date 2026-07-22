# Vendored code provenance

The `pii_anonymizer/` subtree is a **vendored subset** of the AWS Labs
**pii-anonymizer** sample, copied into this feature so the accelerator owns,
lints, and security-scans the code rather than depending on an unpublished,
untagged sample repository.

| | |
|---|---|
| **Upstream** | https://github.com/awslabs/pii-anonymizer |
| **License** | Apache-2.0 (see `LICENSE`, `NOTICE`) |
| **Vendored commit** | `60ed2fdf6d303b9a4f1d6862efd22b9e89cb9aa5` |
| **Commit date** | 2026-07-17 |
| **Vendored on** | 2026-07-22 |
| **Upstream layout** | contents of `src/` (import root) |

## What was vendored

Only the **document** detection + redaction closure (PDF, images, TXT, CSV,
XLSX, DOCX). Traced by import graph from the format processors:

```
core/        pii_detector, synthetic_pii_generator, text_replacer, prompts, value_categorizer
helpers/     model_config_helper, model_router, threaded_detector, text_chunker,
             token_tracker, pdf_processor, textract_helper, page_type_checker,
             font_config, config_loader, pricing.yaml
processors/  pdf_text_processor, txt_processor, tabular_processor, word_processor,
             pdf_image_processor, image_processor
redaction/   pdf_redactor
validation/  model_schemas, pdf_validator, document_validator
```

## What was deliberately EXCLUDED (not part of the document closure)

- `processors/audio_processor.py` — audio (MP3/WAV) redaction; the accelerator
  has no audio pipeline, and it pulls in `ffmpeg`.
- `handlers/*` — upstream's Lambda handlers (we have our own hook handler).
- `infra/*` — upstream's SQS/DynamoDB orchestration (the accelerator provides it).
- `helpers/observability.py` — AWS X-Ray wrapper; nothing in the closure imports it.
- `helpers/throttle_handler.py`, `helpers/log_scrubber.py` — not in the closure.
- `core/redactor.py` — the standalone Step-3 redactor; nothing in the closure
  imports it (the processors call `redaction/pdf_redactor` and the text replacers).

The upstream `src/__init__.py` eagerly re-exported the whole package (including
the excluded modules); it was replaced here with an empty marker
(`pii_anonymizer/__init__.py`) because the vendored submodules import each other
with **absolute** names (`from core...`, `from helpers...`) rooted at
`pii_anonymizer/`, which is placed on `sys.path` at runtime.

## Import root

`pii_anonymizer/` is added to `sys.path` so `core`, `helpers`, `processors`,
`redaction`, `validation` resolve as top-level packages — matching how the
upstream Lambda runs (`src/` as the import root). See `hook/handler.py`.

## Local modifications

None to the copied module bodies (kept byte-for-byte to ease re-sync).
Only `pii_anonymizer/__init__.py` was replaced (see above). Any future local
patch MUST be recorded here with a rationale so re-sync can re-apply it.

## Re-syncing from upstream

Use the `.claude/skills/sync-pii-anonymizer.md` skill (or run it manually): it
re-clones upstream, diffs the vendored files against the recorded commit, and
re-copies the closure, flagging any newly-added intra-project imports that would
expand the closure. After a re-sync: bump the commit SHA above, re-run the
import smoke test, `make lint`, and the hook unit tests, then SRT-scan.
