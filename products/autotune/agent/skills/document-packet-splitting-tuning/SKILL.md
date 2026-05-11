---
name: document-packet-splitting-tuning
description: Comprehensive revision skill for improving document packet classification accuracy. Use to detect and correct errors in document segmentation, type classification, and output formatting. Activate when page-level boundary detection, document type assignment, or segment grouping accuracy needs improvement.
---

# Document Packet Splitting Tuning

## Symptoms

- Low `page_level_accuracy` in splitClassificationMetrics (< 80%)
- Low `split_accuracy_without_order` or `split_accuracy_with_order`
- Sections have wrong page counts compared to ground truth
- Pages assigned to wrong document class

## Diagnosis

### Step 1: Get Current Metrics

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_split_summary()
```

### Step 2: Identify the Problem Type

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Low page_level_accuracy | Classification model/prompts weak | Improve class descriptions, use stronger model |
| split_accuracy << page_accuracy | Section boundary detection failing | Check sectionSplitting config |
| with_order << without_order | Page order within sections wrong | Usually not tunable, may be data issue |

### Step 3: Examine Failing Documents

```python
# Download ground truth for a failing packet
result = client.download_ground_truth_all_sections('test-set-id', 'packet_0001.pdf', './gt/')
print(f"Downloaded {result['count']} sections")

# Compare with inference results
client.download_single_document_results('batch-id', 'packet_0001.pdf', './inference/')
```

---

## Segmentation Skills

### Boundary Detection Tuning

Improve detection of where one document ends and another begins within a document packet. Apply when documents are being incorrectly merged across boundaries or split mid-document.

Look for new document signals including but not limited to:

- New letterheads, logos, or headers
- New titles or cover pages
- Change in dates, parties, or reference numbers
- Significant formatting or layout shifts
- New greeting lines or sign-off blocks

### Same-Type Adjacency Splitting

Improve separation of distinct documents that share the same document type and appear adjacent in the packet. Apply when two or more separate documents of the same type are incorrectly combined into a single segment.

Key indicators of distinct same-type documents:

- Different reference or case numbers
- Different dates or signatories
- Different subject entities or parties
- Repeated introductory or closing structures
- Restarted page numbering or section numbering

### Shuffled Page Reordering

Improve handling of out-of-order or shuffled pages within a document packet. Apply when pages that logically belong to the same document are scattered across the packet.

Use these signals to identify co-belonging pages:

- Matching headers, footers, or watermarks
- Continuation of numbered lists, sections, or paragraphs
- Cross-references to content on other pages
- Consistent formatting, fonts, and layout
- Matching document identifiers or metadata

### Blank Page Attribution

Improve correct attribution of blank pages to the preceding document segment. Apply when blank pages are incorrectly assigned to the following document or cause boundary detection errors.

Rules:

- A blank page always belongs to the document segment immediately before it
- A blank page never starts a new document segment
- Multiple consecutive blank pages all belong to the same preceding segment
- Blank pages are included in the ordinal_end_page calculation of the preceding segment

### Content Continuity Assessment

Improve the ability to assess whether consecutive pages share semantic continuity. Apply when pages belonging to the same document are incorrectly split into separate segments.

Indicators of continuity:

- Sentences or paragraphs that continue across page breaks
- Ongoing numbered sections or bullet lists
- Consistent topic, subject matter, or narrative thread
- Tables or figures that span multiple pages
- References such as "continued on next page" or "see above"

---

## Classification Skills

### Document Type Matching Accuracy

Improve accuracy of mapping document segments to the correct document type from the allowed type list. Apply when documents are being assigned the wrong type code or when ambiguous documents are misclassified.

Rules:

- Only assign types explicitly listed in the `<document-types>` reference
- Never invent or fabricate a type code
- When ambiguous, compare the candidate segment against each possible type definition and select the closest semantic match
- If no type fits well and "other" is available, use "other"
- Verify the final type code is an exact string match to the allowed list

### Domain Template Recognition

Improve recognition of domain-specific document templates and layouts. Apply when the agent fails to identify well-known document formats from their structural and visual cues.

Common domain patterns to recognize:

- **Financial:** invoices, purchase orders, bank statements, tax forms
- **Legal:** contracts, affidavits, court filings, powers of attorney
- **Medical:** lab reports, discharge summaries, prescriptions, insurance claims
- **Insurance:** policy declarations, certificates of insurance, claim forms
- **Real Estate:** deeds, appraisals, closing disclosures, title commitments
- **Correspondence:** letters, memos, emails, notices

### Multi-Signal Boundary Reasoning

Improve the ability to weigh multiple signals simultaneously when determining document boundaries. Apply when single-signal reliance causes incorrect splits or merges.

The revision agent must consider all of the following together:

- Content topic and subject matter shifts
- Visual and formatting changes
- Header and footer pattern changes
- Metadata differences such as dates and reference numbers
- Logical document structure completeness
- No single signal should override all others; use preponderance of evidence

---

## Validation Skills

### Output Schema Compliance

Improve structural correctness of the classification JSON output. Apply as a final validation pass before returning results.

Check for:

- Every page in the packet is assigned to exactly one document segment
- No page ranges overlap between segments
- No pages are missing or skipped
- `ordinal_start_page` ≤ `ordinal_end_page` for every segment
- `local_doc_id` follows the format `{doc_type_id}-##` with correct 01-based numbering
- Every `document_type` value exactly matches an entry in the `<document-types>` list
- JSON is syntactically valid and conforms to the expected schema

### Classification Self-Verification

Improve the agent's ability to review and self-correct its own classification output before finalizing. Apply as the last step in the revision pipeline.

The revision agent must:

1. Re-read the first and last page of each classified segment to confirm they belong
2. Check the boundary between every adjacent segment pair by reading the last page of segment N and the first page of segment N+1 to confirm they are truly different source documents. For each segment, verify the assigned `document_type` by comparing page content against the type definition
3. Identify any segment where two distinct documents may have been incorrectly merged, especially same-type adjacent source documents. Identify any adjacent segments that should have been combined into one source document. Produce a corrected classification with a brief justification for each change made

---

## Revision Agent Execution Order

The revision agent must apply these skills in the following sequence:

### Step 1: SEGMENTATION REVIEW

- Run content continuity assessment across all pages
- Run boundary detection tuning at each current segment boundary
- Run same-type adjacency splitting on adjacent same-type segments
- Run shuffled page reordering to check for misplaced pages
- Run blank page attribution to verify blank page assignments

### Step 2: CLASSIFICATION REVIEW

- Run document type matching accuracy on each segment
- Run domain template recognition for ambiguous segments
- Run multi-signal boundary reasoning for uncertain boundaries

### Step 3: VALIDATION

- Run output schema compliance checks
- Run classification self-verification end-to-end

**Important:** If any step produces a correction, re-run from Step 1 to ensure cascading errors are resolved. Limit to a maximum of 3 revision passes.

---

## Fixes

### Fix 1: Improve Class Descriptions for Page-Level Classification

Page-level classification sees ONE page at a time. Descriptions should focus on visual/structural cues visible on a single page:

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# BAD: describes multi-page document characteristics
config.set('classes.0.description', 'A multi-page invoice with cover letter')

# GOOD: describes single-page visual cues
config.set('classes.0.description',
    'Invoice page - contains line items with prices, quantities, totals. '
    'Look for: invoice number, vendor/customer info, itemized list, amounts. '
    'May have "INVOICE" header, company logo, payment terms.')

config.set('classes.1.description',
    'Letter page - formal correspondence with letterhead, date, salutation, '
    'body text, signature block. Look for: "Dear...", formal closing like '
    '"Sincerely", handwritten or typed signature.')

config.save('workspace/updated-config.yaml')
```

### Fix 2: Use Stronger Classification Model

```python
config.set('classification.model', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
config.save('workspace/updated-config.yaml')
```

### Fix 3: Add More Distinctive Class Descriptions

If two classes are being confused, make their descriptions more distinctive:

```python
# Find which classes are confused by examining inference results
# Then update descriptions to highlight differences

config.set('classes.0.description',
    'Invoice page - MUST have itemized line items with prices. '
    'Contains: invoice number, quantities, unit prices, totals, tax.')

config.set('classes.1.description', 
    'Receipt page - simpler than invoice, usually single transaction. '
    'Contains: store name, date, items purchased, total amount paid.')
```

### Fix 4: Use Per-Page Section Splitting

When LLM-determined boundary detection consistently fails — especially for packets where each page is a separate logical document (single-page forms, certificates, maintenance records) — switch to per-page section splitting. This treats every page as its own section, bypassing boundary detection entirely.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Switch to per-page splitting
config.set('classification.sectionSplitting', 'page')

config.save('workspace/updated-config.yaml')
```

**Available section splitting strategies:**

| Strategy | Behavior | Best For |
|----------|----------|----------|
| `llm_determined` (default) | LLM detects boundaries via Start/Continue signals, groups consecutive same-type pages | Multi-page documents within packets |
| `page` | Each page becomes a separate section | Single-page forms, certificates, records bundled together |
| `disabled` | Entire document as one section, majority voting for class | Single-document files that shouldn't be split |

**When to use `page` mode:**
- Documents in the packet are predominantly single-page (forms, certificates, cards)
- LLM boundary detection is merging pages that should be separate sections
- `split_accuracy` is significantly lower than `page_level_accuracy` and boundary tuning hasn't helped
- The packet contains many documents of the same type adjacent to each other (e.g., multiple task cards in a row), causing the LLM to merge them into one section

In a past engagement with complex bundled documents, per-page splitting outperformed LLM-determined boundaries because the documents were predominantly single-page forms that the LLM kept incorrectly merging.

**When NOT to use `page` mode:**
- Documents in the packet span multiple pages (multi-page contracts, reports)
- You need the LLM to group related pages into sections
- Page-level accuracy is the bottleneck (per-page splitting won't help if pages are misclassified)

## Verification

After applying fixes:

1. Upload updated config:
   ```python
   client.upload_config('workspace/updated-config.yaml', config_version='<version>', description='Tuned class descriptions')
   ```

2. Re-run evaluation:
   ```python
   result = client.run_evaluation('test-set-id', context='Tuned class descriptions', config_version='<version>')
   batch_id = result['batch_id']
   ```

3. Compare metrics:
   ```python
   new_summary = client.get_evaluation_summary(batch_id, 'results/new_summary.json')
   new_result = EvaluationResult.from_aggregated_file('results/new_summary.json')
   new_result.print_split_summary()
   ```

4. Success criteria:
   - page_level_accuracy > 85%
   - split_accuracy_without_order > 75%
   - Improvement over baseline
