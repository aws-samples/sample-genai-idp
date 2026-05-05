# IDP Discovery Extension - Testing Feedback

**Date:** 2026-02-05

---

## Testing Methodology

**Dataset:** 45 PNG images from 9 known document classes (5 documents each)
- Classes: BANK_CHECK, COMMERCIAL_LEASE_AGREEMENT, CREDIT_CARD_STATEMENT, DELIVERY_NOTE, EQUIPMENT_INSPECTION, GLOSSARY, PETITION_FORM, REAL_ESTATE, SHIFT_SCHEDULE

**Setup:**
1. Created S3 bucket `idp-discovery-test-20260205`
2. Uploaded test images to `s3://idp-discovery-test-20260205/input/`

**Command:**
```bash
python workflow/graph.py --s3_uri s3://idp-discovery-test-20260205/input/ --sample_size 45 --bedrock_region us-east-1
```

---

## Results

### Clustering Performance: Excellent

The tool correctly identified 9 clusters with exactly 5 documents each - a perfect match to the ground truth distribution.

### Schema Generation: 8/9 Successful

| Ground Truth | Discovered | Match |
|--------------|------------|-------|
| BANK_CHECK | Bank Check | ✓ Exact |
| COMMERCIAL_LEASE_AGREEMENT | California Commercial Lease Agreement | ✓ Good |
| CREDIT_CARD_STATEMENT | Bank Transaction Activity Report | ~ Partial |
| DELIVERY_NOTE | Delivery Note | ✓ Exact |
| EQUIPMENT_INSPECTION | Medical Equipment Inspection Checklist | ✓ Good |
| GLOSSARY | (failed - image too large) | ✗ Failed |
| PETITION_FORM | Democratic Designating Petition | ✓ Good |
| REAL_ESTATE | Real Estate Market Analysis Report | ✓ Good |
| SHIFT_SCHEDULE | Staff Shift Schedule | ✓ Exact |

---

## Feedback

### 1. Bloated requirements.txt

The `requirements.txt` pulls in ~3GB+ of CUDA dependencies (`nvidia-cuda-*`, `nvidia-cudnn-*`, etc.) even when not using local models. These come from the `colpali` dependency which is only needed for the optional `colidefics` local embedding model.

**Recommendation:** Split into `requirements.txt` (Bedrock-only) and `requirements-local.txt` (local model support).

### 2. Should be a separate project

This code is standalone - no shared dependencies with `idp_common`, output is manually copied to IDP config, and it has different runtime requirements (strands-agents, torch, etc.).

**Recommendation:** Keep as a separate repository until properly integrated into IDP.

### 3. Cohere embed model fails in us-west-2

Running with `--bedrock_region us-west-2` fails:
```
ValidationException: Invocation of model ID cohere.embed-v4:0 with on-demand throughput isn't supported.
```

**Workaround:** Use `--bedrock_region us-east-1`.

**Recommendation:** Document this or auto-detect/fallback to a working region.

### 4. Image size limit causes schema generation failure

One cluster (GLOSSARY) failed: `image exceeds 5 MB maximum: 5657288 bytes > 5242880 bytes`

**Recommendation:** Resize/compress images before sending to Bedrock, or skip oversized images and use other samples from the cluster.

### 5. Class naming is overly specific

Discovered names are too specific to samples:
- "California Commercial Lease Agreement" vs generic "COMMERCIAL_LEASE_AGREEMENT"
- "Democratic Designating Petition" vs generic "PETITION_FORM"

**Recommendation:** Add option to generate more generic/normalized class names.

---

## Open Questions

### Why does this tool implement its own discovery?

IDP already has a discovery feature that generates JSON schemas from documents. This tool implements a completely separate discovery mechanism using Strands agents + Claude vision rather than calling the existing IDP discovery Lambda.cd

**Questions to resolve:**
- Which discovery implementation produces better schemas?
- Why was a separate implementation created instead of reusing/extending the existing one?
- Should we unify them into a single discovery approach?

**Suggested next step:** Run a comparison test - use both discovery methods on the same document samples and evaluate the output schemas for completeness, accuracy, and usability.
