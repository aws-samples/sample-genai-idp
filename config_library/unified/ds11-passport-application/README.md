# DS-11 U.S. Passport Application Sample

This sample configuration demonstrates the **excluded-class feature** — a way
to tell the IDP pipeline that a particular document class contains only
static/boilerplate pages (instructions, legal warnings, cover pages, tax
notices, etc.) and should be skipped during extraction, assessment,
summarization, rule validation, and evaluation.

## What it demonstrates

`samples/DS11-USPassportApplication.pdf` is a 6-page US State Department
passport application form in which:

| Page | Content | Nature |
|------|------------------------------------------------------|------------------|
| 1 | WARNING: False statements… legal warning | Static legal |
| 2 | Passport fee and payment instructions | Static instructions |
| 3 | DS-11 FEDERAL TAX LAW (Section 6039E) notice | Static legal |
| 4 | DS-11 ACTS OR CONDITIONS affidavit | Static oath |
| 5 | APPLICATION FOR A U.S. PASSPORT (form front) | Dynamic form |
| 6 | Travel Plans / Permanent Address (form back) | Dynamic form |

This config is a **minimal override config** — it only declares `notes` +
`classes`. All other settings (`classification:`, `extraction:`,
`assessment:`, `summarization:`, `ocr:`, `evaluation:`) are inherited
from the bundled system defaults via `merge_config_with_defaults()` at
deploy time (production) or at notebook-load time (demos). You only
need to declare the classes you care about.

With this config:

1. The classifier sees **two** classes, `PassportApplicationInstructions`
   and `PassportApplication`.
2. The **primary classification mechanism** is the LLM multimodal
   page-level classifier: each page is sent (image + OCR text) to
   Bedrock and the best-matching class is chosen using the class
   `description` field. This is robust to form revisions, OCR quirks,
   and wording differences.
3. The **optional regex fast-path** on the excluded class
   (`x-aws-idp-document-page-content-regex`) short-circuits pages whose
   OCR text matches a known stable boilerplate phrase. If the regex
   misses, the LLM still catches the page via the description. The
   regex is narrowly scoped to a single conservative anchor; see the
   comment in `config.yaml` for details.
4. The document is segmented into two sections via the existing BIO-like
   section-boundary logic. The classification service propagates the
   `excluded` flag from the class config onto the `Section`.
5. Downstream services (extraction, assessment, summarization, rule
   validation) see `section.excluded == True` and **skip** those
   sections. They still write a small `result.json` stub so the UI and
   reporting database have something to show:

   ```json
   {
     "status": "skipped_excluded_class",
     "stage": "extraction",
     "section_id": "1",
     "classification": "PassportApplicationInstructions",
     "excluded": true,
     "exclusion_reason": "instructions",
     "page_ids": ["1", "2", "3", "4"],
     "message": "Section 1 classified as 'PassportApplicationInstructions' …"
   }
   ```

6. The evaluation service filters excluded sections out of the
   precision/recall/F1 calculation and appends an **Excluded Sections**
   table to the markdown report so nothing is silently dropped.

7. The UI renders excluded sections in the Sections panel with a grey
   `Skipped: instructions` badge next to the class name.

## How to try it

### 1. As a library / test fixture

```bash
# From the repo root
python -c "
from idp_common.models import Document, Section
from idp_common.section_exclusion import is_section_excluded, build_skipped_stub_result

doc = Document(id='ds11-demo')
sec = Section(
    section_id='1',
    classification='PassportApplicationInstructions',
    page_ids=['1','2','3','4'],
    excluded=True,
    exclusion_reason='instructions',
)
assert is_section_excluded(sec)
print(build_skipped_stub_result(doc, sec, stage='extraction'))
"
```

### 2. In a live deployment

1. Load this config into your stack:

   ```bash
   idp-cli configuration create \\
     --stack-name <your-stack> \\
     --version-name ds11 \\
     --path config_library/unified/ds11-passport-application/config.yaml
   idp-cli configuration activate --stack-name <your-stack> --version-name ds11
   ```

2. Upload `samples/DS11-USPassportApplication.pdf` through the web UI or
   CLI, and inspect the resulting sections in the Sections panel — the
   first section (pages 1–4) will display a **Skipped: instructions**
   badge and the extraction/summary panels for that section will show
   the skipped-stub message. Only the second section (pages 5–6) will
   be extracted.

## Key schema extensions

Two new class-level extensions power the feature:

| Key | Type | Meaning |
|-----|------|---------|
| `x-aws-idp-exclude-from-processing` | boolean | When `true`, downstream services skip sections classified as this class. |
| `x-aws-idp-exclusion-reason` | string | Optional short reason (`"instructions"`, `"legal"`, `"cover-page"`) shown in UI badges and evaluation reports. |

The existing
`x-aws-idp-document-page-content-regex` extension is used as a fast path
so the LLM doesn't have to classify boilerplate pages that clearly
contain anchor phrases from the form template.

## Notes & caveats

- The regex fast path relies on OCR text being available. When OCR is
  disabled (e.g. image-only mode), the LLM still recognizes
  `PassportApplicationInstructions` visually thanks to the detailed
  class `description`.
- The `properties: {}` on the excluded class is intentional — there's
  nothing to extract from boilerplate pages. The classifier doesn't
  require properties.
- Regex patterns can be tuned to match additional state-department
  revisions of DS-11. The (`?is`) flags make matching case-insensitive
  and tolerant of OCR line-break artefacts.
