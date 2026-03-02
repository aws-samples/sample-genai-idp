# Fake W-2 Tax Form Configuration

**Validation Level**: Verified with HuggingFace ground truth

## Description

Configuration for evaluating extraction accuracy on synthetic US W-2 tax form documents from the [Fake W-2 Tax Form Dataset](https://huggingface.co/datasets/singhsays/fake-w2-us-tax-form-dataset) (originally from [Kaggle](https://www.kaggle.com/datasets/mcvishnu1/fake-w2-us-tax-form-dataset), CC0: Public Domain).

## Dataset

- **2,000 documents** (1,800 train + 100 test + 100 validation)
- **45 ground truth fields** per document covering all standard W-2 boxes
- **Synthetic data** — no PII concerns
- **Single document type**: W2

## Fields

| Category | Fields |
|----------|--------|
| Employer Info | EIN, name, street address, city/state/zip |
| Employee Info | SSN, name, street address, city/state/zip |
| Control | Control number |
| Federal Wages (boxes 1,3,5,7,8) | Wages, SS wages, Medicare wages, SS tips, allocated tips |
| Federal Taxes (boxes 2,4,6) | Federal tax, SS tax, Medicare tax |
| Benefits (boxes 10,11) | Dependent care, nonqualified plans |
| Codes (boxes 12a-d) | Code letter + value (4 entries) |
| Checkboxes (box 13) | Statutory employee, retirement plan, third-party sick pay |
| State/Local #1 (boxes 15-20) | State, state ID, state wages, state tax, local wages, local tax, locality |
| State/Local #2 (boxes 15-20) | Same fields for second jurisdiction |

## Usage

Import this configuration from the Configuration Library in the Web UI, or use with:

```
idp-cli config-upload --stack-name <your-stack> --config-file config_library/unified/fake-w2/config.yaml
```

Then select the "Fake-W2-Tax-Forms" test set in Test Studio to run extraction evaluation.
