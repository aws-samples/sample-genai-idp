## [Unreleased]

### Added

- **1S-TopK Extraction — Single-Step Extraction + Confidence Assessment** — combines document field extraction and per-field confidence scoring into a single LLM call, eliminating the separate assessment step and cutting total LLM invocations in half for extraction workflows. Activated by setting `extraction.mode: simple` + `extraction.confidence.mode: integrated`. The extraction prompt instructs the LLM to return its top-K guesses with probabilities (G1/P1 through GK/PK) for each field. A new `topk_resolver` module then:
  - Resolves candidates into the standard `inference_result` (taking G1 as the extracted value) + `explainability_info` (using P1 as confidence, with per-field thresholds from `x-aws-idp-confidence-threshold` in the schema)
  - Preserves the full candidate data in `metadata.topk_candidates` for auditability
  - Handles both scalar fields and array items (e.g., LineItems) — each sub-attribute within list items gets individual candidate resolution
  - Marks `metadata.assessment_method: "1s_topk"` so the downstream assessment Lambda auto-skips when `explainability_info` is already present

  **How to enable:** Set `extraction.mode: simple` and `extraction.confidence.mode: integrated` in the configuration. The UI will show the "Task prompt (1-Stage TopK extraction + confidence)" textarea for customization.

  **Contract:** The LLM output must use the key naming pattern `G<N>` for candidate values and `P<N>` for probabilities (e.g., `G1`/`P1` for one candidate, up to `G4`/`P4` for four candidates). The number of candidates is flexible — `G1`/`P1` alone is valid for a single candidate. The default prompt template requests 4 candidates, but custom prompts can request fewer. The parser requires at minimum `G1` and `P1` to identify the TopK format.

  **Key files:**
  - `lib/idp_common_pkg/idp_common/extraction/topk_resolver.py` — core candidate resolution logic, `CandidateGuesses` Pydantic model
  - `lib/idp_common_pkg/idp_common/extraction/service.py` — integration in `_split_inline_confidence()` to detect and resolve TopK responses
  - `lib/idp_common_pkg/idp_common/extraction/prompt_assembly.py` — selects TopK prompt for `simple + integrated`
  - `lib/idp_common_pkg/idp_common/extraction/__init__.py` — public exports (`is_topk_response`, `resolve_candidates`, `CandidateGuesses`, `build_extraction_model`)
  - `lib/idp_common_pkg/idp_common/config/models.py` — `task_prompt_extraction_with_confidence_topk` field on `ExtractionConfig`
  - `lib/idp_common_pkg/idp_common/config/system_defaults/base-extraction.yaml` — TopK prompt template
  - `patterns/unified/template.yaml` — UI schema for the TopK prompt field
  - `config_library/unified/realkie-fcc-verified/config-1s-topk-with-ocr-image.yaml` — reference configuration
  - `notebooks/misc/e2e-example-with-1s-topk.ipynb` — end-to-end demo notebook
  - `samples/fcc-invoices-*.pdf` — sample FCC invoice document for testing

  **Output format:** The final `result.json` has the same `inference_result` + `explainability_info` structure as the separate assessment mode. Fully backward-compatible — downstream consumers (evaluation, reporting, UI, HITL) work unchanged.

  See the [sample config](config_library/unified/realkie-fcc-verified/config-1s-topk-with-ocr-image.yaml) and [demo notebook](notebooks/misc/e2e-example-with-1s-topk.ipynb) for usage examples.

  **Known issue:** The UI Configuration form validates that `extraction.max_tokens` is set (marked as required in the template schema). The system defaults intentionally omit `max_tokens` (it is resolved dynamically per model at runtime). When creating a new config version via the UI with `simple + integrated` mode, manually set `max_tokens` (e.g., `40000`) in the Extraction section to pass validation.
