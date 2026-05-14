---
name: multilingual-documents
description: Handle documents in non-English languages. Use when documents contain languages not supported by Textract, requiring Bedrock OCR instead.
---

# Multilingual Document Handling

## Problem

Documents contain text in languages other than English, which may require Bedrock OCR instead of Textract.

## When to Use This Skill

- Dataset contains documents in non-English languages
- Textract is returning poor/garbled results on foreign language documents
- Extraction accuracy is low and documents appear to be in another language

## Language Support Reference

### Amazon Textract Supported Languages

**Printed text extraction** (DetectDocumentText, AnalyzeDocument):
- English
- Spanish  
- German
- French
- Italian
- Portuguese

**Handwriting extraction**: English only

**Invoices/Receipts** (AnalyzeExpense): English only

**Identity Documents** (AnalyzeID): English only

**Queries**: English only

### Languages NOT Supported by Textract

These require Bedrock OCR:
- **Chinese** (Mandarin, Cantonese)
- **Japanese**
- **Korean**
- **Arabic**
- **Hebrew**
- **Hindi**
- **Thai**
- **Vietnamese**
- **Russian**
- Most other non-Latin scripts

### Bedrock OCR Language Support

Claude models can process documents in virtually any language, including all those not supported by Textract. Use Bedrock OCR when:
- Documents contain Chinese, Japanese, Korean, Arabic, or other unsupported languages
- Documents mix multiple languages
- Textract is producing garbled output

## Diagnosis

### Step 1: Identify Document Languages

Look for signs of non-English text:
- Non-Latin characters (Chinese, Japanese, Korean, Arabic, Cyrillic, etc.)
- Right-to-left text (Arabic, Hebrew)
- Garbled/nonsensical Textract output (indicates unsupported language)

### Step 2: Check Current OCR Configuration

```
config_edit(config_path, operations=[{"op": "get", "field": "ocr.backend"}])
```

### Step 3: Evaluate OCR Quality

If using Textract on unsupported languages, you'll see:
- Garbled or missing text in extraction results
- Very low extraction accuracy
- Empty or nonsensical field values
- Characters replaced with similar-looking Latin characters

## Fixes

### Fix 1: Switch to Bedrock OCR

```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.backend", "value": "bedrock"},
    {"op": "set", "field": "ocr.model_id", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"op": "save"}
])
```

### Fix 2: Use Language-Specific Prompts

Adjust extraction prompts to handle the target language:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt",
     "value": "Extract the following fields from this document. The document is in Mandarin Chinese. Return field values in their original language."},
    {"op": "save"}
])
```

Or request translation in the prompt:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt",
     "value": "Extract the following fields from this document. The document may be in Mandarin Chinese. Translate all extracted values to English."},
    {"op": "save"}
])
```

## Decision Tree

```
Document contains non-English text?
│
├─ YES: What language?
│   │
│   ├─ Textract-supported (Spanish, German, French, Italian, Portuguese)
│   │   └─ Use Textract OCR (default) - faster and cheaper
│   │
│   └─ NOT Textract-supported (Chinese, Japanese, Korean, Arabic, etc.)
│       └─ Use Bedrock OCR (required)
│
└─ NO (English only)
    └─ Use Textract OCR (default)
```

## Cost/Performance Considerations

| OCR Backend | Speed | Cost | Language Support |
|-------------|-------|------|------------------|
| Textract | Faster | Lower | Limited (6 languages) |
| Bedrock | Slower | Higher | Comprehensive |

Use Textract when possible for supported languages. Switch to Bedrock only when necessary.

## Common Pitfalls

1. **Using Textract for unsupported languages**: Will produce garbled/unusable output
2. **Assuming Textract supports all languages**: Check the supported list above
3. **Mixed-language documents**: Use Bedrock OCR to be safe
4. **Forgetting to update prompts**: May need language-specific instructions for best results

## References

- [Amazon Textract Supported Languages](https://docs.aws.amazon.com/textract/latest/dg/supported-languages.html)
- Textract supports: English, Spanish, German, French, Italian, Portuguese (printed text only)
- Handwriting, Invoices/Receipts, Identity Documents, and Queries are English-only
