<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Multi-Use-Case Integration Test Results

> **Stack:** `idp-genaiidp` (Pattern 2, `lending-package-sample` preset, `us-east-1`)
> **Date:** March 4, 2026
> **Branch:** `pr/multi-use-case-support`

This document captures the integration test results from a live deployed stack, validating the multi-use-case feature end-to-end.

## 1. Stack Deployment & Update

| Step | Result |
|------|--------|
| Published artifacts via `publish.py` | Success |
| Updated stack with new template (`ConfigurationPreset`, `UseCaseConfigs` parameters) | Success |
| Legacy parameters (`Pattern1Configuration`, `Pattern2Configuration`, etc.) correctly replaced | Verified |
| Stack reached `UPDATE_COMPLETE` | Verified |

## 2. Use Case Registration (CLI)

Tested via `scripts/manage_use_cases.py` against the deployed Configuration DynamoDB table.

| Test | Result | Details |
|------|--------|---------|
| Register `retail-banking/mortgage-processing` | Pass | Name: "Mortgage Processing", config with custom extraction temperature |
| Register `insurance/claims-processing` | Pass | Name: "Insurance Claims", config with custom confidence threshold |
| List use cases | Pass | Both use cases returned with correct metadata |
| Re-register existing use case (update) | Pass | Name/description updated, no duplicate created |
| Delete use case | Pass | Removed from registry, verified via list |
| Re-register after delete | Pass | Clean re-registration |

## 3. Configuration Isolation

| Test | Result | Details |
|------|--------|---------|
| `get-config` for `retail-banking/mortgage-processing` | Pass | Returns merged config with UC-specific overrides |
| `get-config` for `insurance/claims-processing` | Pass | Returns different merged config with its own overrides |
| Config inheritance from global default | Pass | Unspecified fields correctly inherited from Global Default |
| UC-specific overrides applied | Pass | Temperature, confidence thresholds, document classes differ per UC |
| OCR backend shared across use cases | Pass | Both UCs use same OCR settings from global config |

## 4. Document Processing with Use-Case Routing

### 4a. Routed Documents (S3 key prefix routing)

| Document | S3 Key | Result |
|----------|--------|--------|
| `lending_package.pdf` | `retail-banking/mortgage-processing/lending_package.pdf` | Processed successfully |
| `lending_package.pdf` (insurance) | `insurance/claims-processing/lending_package_insurance.pdf` | Processed successfully |

**Verification:**
- Queue Sender Lambda logs confirmed extraction of `business_unit_id` and `use_case_id` from S3 key
- Queue Processor logs confirmed `use_case_context` construction and config resolution
- Step Functions executions completed with `SUCCEEDED` status
- Output S3 keys preserved use-case prefix structure

### 4b. Flat Key Documents (backward compatibility)

| Document | S3 Key | Result |
|----------|--------|--------|
| `lending_package.pdf` | `lending_package_flat.pdf` | Processed with global default config |

**Verification:**
- `use_case_context` was empty (`{}`) in Step Functions input
- Global default configuration applied (not use-case-scoped)
- Processing completed successfully — identical to pre-feature behavior

## 5. Step Functions Workflow Verification

| Check | Result |
|-------|--------|
| Routed doc has `use_case_context: {"business_unit_id": "retail-banking", "use_case_id": "mortgage-processing"}` | Pass |
| Flat doc has `use_case_context: {}` | Pass |
| All executions reached `SUCCEEDED` | Pass |
| Context propagated through OCR → Classification → Extraction → ProcessResults | Pass |

## 6. Output Validation

Checked S3 output and `result.json` files for processed sections.

| Check | Result |
|-------|--------|
| Output files land under correct S3 prefix | Pass |
| `result.json` contains valid extraction data | Pass |
| Classification uses use-case-scoped document types | Pass |
| `document_class.type` populated for each section | Pass |

## 7. DynamoDB State Verification

| Check | Result |
|-------|--------|
| `UseCaseRegistry` item contains both registered use cases | Pass |
| `UC#retail-banking#mortgage-processing#Default` config exists | Pass |
| `UC#insurance#claims-processing#Default` config exists | Pass |
| Tracking table entries contain `BusinessUnitId` and `UseCaseId` attributes | Pass |
| Documents indexed by use case in tracking table (GSI) | Pass |

## 8. Reprocessing

| Test | Result | Details |
|------|--------|---------|
| Reprocess document via Lambda (`ReprocessDocument`) | Pass | Used `objectKeys` (plural) payload format |
| Reprocessed document completed with same use-case routing | Pass | `use_case_context` preserved on resubmission |

## 9. AppSync API

| Operation | Result | Details |
|-----------|--------|---------|
| `listUseCases` query | Pass | Returns registered use cases |
| `listDocumentsByUseCase` query | Pass | Filters documents by BU/UC |
| `getUseCaseConfiguration` query | Pass | Returns merged config for specific UC |
| `updateUseCaseConfiguration` mutation | Pass (after fix) | Fixed `config_type` discriminator issue |
| `createUseCase` mutation | Pass | Registers use case via GraphQL |

## 10. Error Handling & Edge Cases

| Test | Result | Details |
|------|--------|---------|
| Invalid BU/UC IDs (containing `#` or `/`) | Rejected | `ValueError` raised with clear message |
| Reserved IDs (`DEFAULT`, `default`, `DEFAULT_*`) | Rejected | Case-insensitive rejection works |
| Empty name on registration | Rejected (after fix) | Added validation for non-empty name |
| Non-string BU/UC IDs | Rejected | Type validation works |
| Single-segment S3 key | Pass | Treated as flat key, no routing |
| Two-segment S3 key | Pass | Treated as flat key (needs 3+ segments) |

## 11. Unit Test Suite

```
1007 passed, 29 skipped, 0 failures
```

Key test files for multi-use-case:

| File | Tests | Status |
|------|-------|--------|
| `test_use_case_config.py` | 70 | All pass |
| `test_multi_use_case_e2e.py` | 25 | All pass |
| `test_processresults_use_case.py` | 17 | All pass |
| `test_configuration_sync.py` | 4 (1 skipped) | All pass |
| `test_dynamic_schema_generation.py` | 11 | All pass |

## CI Verification

| Check | Result |
|-------|--------|
| `ruff check` (no --fix) | Pass |
| `ruff format --check` | Pass |
| Unit tests with coverage (`pytest -m unit --cov`) | 757 passed, 22 skipped |
| Full unit test suite | 1007 passed, 29 skipped |
| `typecheck-pr` | No new errors introduced (3 pre-existing errors in unchanged files) |
