# OmniAI OCR Benchmark Configuration

This configuration is designed for the **OmniAI OCR Benchmark dataset** from HuggingFace (`getomni-ai/ocr-benchmark`), filtered to include only the most representative document formats with consistent schemas.

## Dataset Overview

The OCR Benchmark dataset contains diverse document types with ground truth JSON extraction data. This configuration includes the **9 document formats** with the most samples (formats with >5 samples per schema), totaling **293 pre-selected images**.

## Document Classes

| Class | Description | Key Fields |
|-------|-------------|------------|
| **BANK_CHECK** | Bank checks with MICR encoding | checks[] (bank, personal info, payee, amount, MICR) |
| **COMMERCIAL_LEASE_AGREEMENT** | Commercial property leases | lessor/lessee info, premises, lease terms, rent |
| **CREDIT_CARD_STATEMENT** | Account statements | accountNumber, period, transactions[] |
| **DELIVERY_NOTE** | Shipping/delivery documents | header (from/to), items[] with product specs |
| **EQUIPMENT_INSPECTION** | Inspection reports | equipmentInfo, checkpoints[], overallStatus |
| **GLOSSARY** | Alphabetized term lists | title, pageNumber, glossarySections[] |
| **PETITION_FORM** | Election petition forms | header, candidate, witness, signatures[] |
| **REAL_ESTATE** | Real estate transaction data | transactions[], transactionsByCity[] |
| **SHIFT_SCHEDULE** | Employee scheduling | title, facility, employees[] with shifts |


## Processing Mode

**Default Mode**: Pipeline (use_bda: false). Set use_bda: true for BDA mode.

## Validation Level

**Level**: 2 - Minimal Testing

- **Testing Evidence**: This configuration has been lightly tested with the RealKIE-FCC-Verified Dataset. 
- **Known Limitations**: Performance may vary - consider this configuration a starting point. We welome Pull Requests to improve the accuracy.