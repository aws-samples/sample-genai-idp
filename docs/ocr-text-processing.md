Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# OCR and Text Processing

The GenAI IDP solution supports 50+ document formats with intelligent processing optimized for each format type. The system features a hybrid PDF processing approach that dramatically reduces costs by directly extracting text from text-native PDFs while selectively processing only content-relevant embedded images.

## Supported Formats

### Core Formats (No Additional Dependencies)

All core formats work without any optional libraries:

**PDF Documents** - `.pdf` (Hybrid Processing)
- **Text-Native PDFs**: Direct text extraction with intelligent image filtering (no OCR for text)
- **Scanned/Image PDFs**: Full OCR processing with AWS Textract or Amazon Bedrock
- **Automatic Detection**: System determines optimal processing path based on extractable text content

**Microsoft Office**
- Word Documents (`.docx`, `.doc`) - Native format parsing preserving headings, tables, formatting
- Excel Spreadsheets (`.xlsx`, `.xls`) - Multi-sheet support with type-aware formatting

**Text and Tabular Formats**
- Plain Text: `.txt`, `.log`, `.md`, `.html`, `.xml`, `.rst`, `.json`, `.yaml`
- Tabular Data: `.csv`, `.tsv` with pandas-based intelligent type inference
- Programming Languages: `.py`, `.js`, `.java`, `.c`, `.cpp`, `.cs`, `.rb`, `.php`, `.go`, `.rs`, `.sql`
- Configuration Files: `.ini`, `.conf`, `.env`, `.toml`, `.properties`

**Image Formats**
- All common formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`

### Optional Format Support (Enhanced with Libraries)

The following formats work **without** optional libraries using built-in Python fallback methods, but provide higher quality results when optional libraries are installed:

**`.rtf`** - Rich Text Format
- **With `striprtf`**: High-quality RTF parsing
- **Without library**: Regex-based text extraction (built-in fallback)
- **Installation**: `pip install striprtf`

**`.odt`** - OpenDocument Text
- **With `odfpy`**: Full ODT structure parsing
- **Without library**: ZIP extraction + XML parsing using built-in modules (fallback)
- **Installation**: `pip install odfpy`

**`.epub`** - EPUB eBooks
- **With `ebooklib` + `beautifulsoup4`**: Proper EPUB parsing with structure
- **Without libraries**: ZIP extraction + HTML stripping using built-in modules (fallback)
- **Installation**: `pip install ebooklib beautifulsoup4`

**Important**: Fallback methods use **only Python built-in modules** (`zipfile`, `xml.etree.ElementTree`, `re`) - no additional dependencies required for basic functionality.

### Limited/Not Supported

**`.mobi`** - Kindle Format
- Limited support (proprietary format)
- **Recommendation**: Convert to EPUB using Calibre (`ebook-convert input.mobi output.epub`)

**`.pages`** - Apple Pages
- Not supported (proprietary Apple format)
- **Recommendation**: Export as PDF or DOCX from Pages app

## Security Compliance

**Government/Enterprise Ready**: The system is designed for security-conscious deployments:

1. **Optional Libraries Are Truly Optional**: Core functionality works without any optional libraries
2. **Built-in Fallbacks**: ODT/EPUB fallback processing uses only Python standard library modules
3. **Graceful Degradation**: Files in optional formats are processed with fallback methods if libraries aren't installed
4. **Clear Audit Trail**: All library usage and fallback methods are logged

**Dependencies Summary**:
- **Required (Pre-installed)**: `PyMuPDF`, `pandas`, `python-docx`, `openpyxl`, `Pillow`, `textractor`
- **Optional (Enhanced quality)**: `striprtf`, `odfpy`, `ebooklib`, `beautifulsoup4`
- **Fallback (Zero dependencies)**: Built-in Python modules only

## Hybrid PDF Processing

### How It Works

The system automatically detects whether a PDF contains machine-readable text (text-native) or requires OCR (scanned):

```python
if text_extraction_service.is_pdf_text_native(pdf_bytes):
    # Extract text directly, OCR only embedded images
    manifest = text_extraction_service.extract_manifest(pdf_bytes, s3_prefix)
else:
    # Traditional full-page OCR processing
    process_as_scanned_pdf()
```

**Detection Criteria**: A PDF is text-native if it contains more than 100 characters of extractable text (configurable threshold).

**Typical Savings**: 94% reduction in OCR API calls for text-native PDFs with embedded logos and decorative elements.

### Structured Manifest Generation

For text-native PDFs, the system extracts all content types in reading order:

**Supported Content Types**:
- `text` - Regular text blocks extracted directly from PDF structure
- `table` - Structured tables with preserved row/column structure
- `image` - Embedded images (filtered) with OCR text extraction
- `formula` - Mathematical formulas from vector drawings with OCR
- `form_field` - Interactive PDF form fields with values
- `metadata` - Document-level metadata (title, author, dates)

**Proximity Grouping**: Nearby fragmented elements (split formulas, adjacent images) are automatically grouped before OCR to preserve context and reduce API calls.

### Intelligent Image Filtering

Not all images in PDFs are content-relevant. The system applies multiple heuristics to exclude decorative elements:

**Filtering Criteria**:
- **Size**: Images < 150x150 pixels or < 22,500 pixels² area (logos, icons)
- **Position**: Header zone (top 15%), footer zone (bottom 15%), side margins (left/right 10%)
- **Aspect Ratio**: Extreme ratios > 10:1 (decorative lines, banners)
- **OCR Content**: Images with < 10 characters of OCR text (likely decorative)

**Result**: Only meaningful images (charts, diagrams, screenshots) undergo OCR processing.

### Cost Savings Example

```
Document: 50-page contract with:
- 50 pages of text (directly extracted - 0 OCR calls)
- 20 company logos (filtered - 0 OCR calls)
- 15 decorative elements (filtered - 0 OCR calls)
- 5 diagrams with content (processed - 5 OCR calls)

Traditional Approach: 85 OCR calls
Hybrid Approach: 5 OCR calls
Savings: 94% reduction
```

## Configuration

### Image Filter Settings

Customize filtering behavior for different document types:

**Default (Balanced)**:
```yaml
text_extraction:
  image_filter:
    min_width: 150
    min_height: 150
    min_area: 22500
    max_aspect_ratio: 10.0
    header_footer_margin: 0.15
    side_margin: 0.10
    min_ocr_text_length: 10
```

**Conservative (Scientific/Medical)**:
```yaml
text_extraction:
  image_filter:
    min_width: 80
    min_height: 80
    min_area: 6400
    header_footer_margin: 0.10
    side_margin: 0.05
    min_ocr_text_length: 3
```

**Aggressive (Marketing/Legal)**:
```yaml
text_extraction:
  image_filter:
    min_width: 300
    min_height: 300
    min_area: 90000
    header_footer_margin: 0.25
    side_margin: 0.15
    min_ocr_text_length: 30
```

**Disable Filtering**:
```yaml
text_extraction:
  image_filter: false  # Include all images
```

### DPI Settings

Control image quality for converted documents:

```yaml
ocr:
  image:
    dpi: 150  # Default (recommended)
    # 100: Low quality, fast
    # 200: High quality for detailed documents
    # 300: Very high quality, large files
```

### Text Threshold

Adjust text-native detection sensitivity:

```python
TextExtractionService(
    ocr_service=ocr_service,
    text_length_threshold=200  # Require 200 chars (default: 100)
)
```

## Installation

### Core Dependencies (Pre-installed)

These are required and already included in the solution:

```bash
pip install PyMuPDF pandas python-docx openpyxl Pillow textractor
```

### Optional Format Support (Enhanced Quality)

Install only if you need the highest quality parsing for these formats:

```bash
# Rich text format (RTF has built-in fallback)
pip install striprtf

# OpenDocument (ODT has built-in fallback)
pip install odfpy

# EPUB eBooks (EPUB has built-in fallback)
pip install ebooklib beautifulsoup4

# All optional formats
pip install striprtf odfpy ebooklib beautifulsoup4
```

**Note**: Even without these libraries, the system will process these formats using built-in Python modules with graceful degradation in quality.

### Docker/Lambda Deployment

For production deployments:

```txt
# Core dependencies (required)
PyMuPDF>=1.23.0
pandas>=2.0.0
python-docx>=0.8.11
openpyxl>=3.1.0
Pillow>=10.0.0
textractor>=1.0.0

# Optional dependencies (enhanced quality, security review recommended)
# striprtf>=0.0.26
# odfpy>=1.4.1
# ebooklib>=0.18
# beautifulsoup4>=4.12.0
```

## Usage

### Basic Processing

Automatic format detection—no configuration needed:

```python
from idp_common.ocr import OcrService
from idp_common.models import Document

# Process any supported format
document = Document(
    input_bucket="my-bucket",
    input_key="documents/report.docx"
)
result = ocr_service.process_document(document)
```

### Programmatic Filter Control

```python
filter_config = {
    "min_width": 100,
    "min_height": 100,
    "min_ocr_text_length": 5,
}

service = TextExtractionService(
    ocr_service=ocr_service,
    image_filter_config=filter_config
)
```

## Monitoring and Logging

### Debug Logging

Enable detailed filtering decisions:

```python
import logging
logging.getLogger("idp_common.text_extraction").setLevel(logging.DEBUG)
```

**Example Logs**:
```
INFO - Processing as text-native PDF.
INFO - Manifest extraction complete: 450 items (425 text, 20 images, 5 tables)
DEBUG - Grouped 45 drawings into 8 groups
DEBUG - Filtering image: too small (120x80, minimum 150x150)
DEBUG - Filtering image: in header zone (top at 5.2% of page)
DEBUG - Image passed filters: 800x600, position (25%, 45%), OCR length 145
WARNING - odfpy library not available, trying fallback method
INFO - Converted ODT using fallback method with 243 text elements
```

### Key Metrics

Track performance through CloudWatch:
- `OCR/native/direct_extraction/pages` - Pages processed via text extraction
- `OCR/textract/detect_document_text/pages` - Pages processed via OCR
- Images filtered vs. processed ratio

## Troubleshooting

### Important Images Being Filtered

**Symptoms**: Small diagrams or charts not appearing in output

**Solution**: Reduce size thresholds
```yaml
text_extraction:
  image_filter:
    min_width: 80
    min_height: 80
```

### Logos Still Being Processed

**Symptoms**: Company logos appearing in output

**Solution**: Increase margin thresholds
```yaml
text_extraction:
  image_filter:
    header_footer_margin: 0.20
    side_margin: 0.15
```

### PDF Not Detected as Text-Native

**Symptoms**: Document with text being processed as scanned

**Check**:
1. Can you select text in a PDF viewer?
2. Is text threshold too high? (Check logs for character count)

**Solution**: Lower text threshold
```python
TextExtractionService(text_length_threshold=50)
```

### Format Not Detected

**Symptoms**: File processed incorrectly

**Solutions**:
1. Verify file extension is correct
2. Check file is not corrupted
3. Try renaming with correct extension

### Optional Format Processing Quality

**Symptoms**: ODT/EPUB text extraction is lower quality

**Explanation**: System is using built-in fallback methods (no optional libraries installed)

**Solution**: Install optional libraries for higher quality
```bash
# For ODT
pip install odfpy

# For EPUB
pip install ebooklib beautifulsoup4
```

**Note**: Fallback processing still works and extracts text—just with less formatting preservation.

## Performance Characteristics

### Processing Speed by Format

| Format | Speed | Notes |
|--------|-------|-------|
| PDF (text-native) | ⚡⚡⚡⚡⚡ | Direct extraction (3-5x faster) |
| TXT, CSV | ⚡⚡⚡⚡ | Simple parsing |
| DOCX, XLSX | ⚡⚡⚡ | Format parsing overhead |
| PDF (scanned) | ⚡⚡ | OCR processing required |
| RTF (fallback) | ⚡⚡⚡ | Regex parsing (lightweight) |
| ODT (fallback) | ⚡⚡ | ZIP + XML extraction |
| EPUB (fallback) | ⚡⚡ | ZIP + HTML stripping |

### Scalability

The hybrid system scales linearly:
- **Large text-native PDFs**: Excellent performance
- **Mixed-content PDFs**: Moderate performance improvement
- **Image-heavy PDFs**: Less benefit (more images to process)

## Best Practices

### 1. Use Native Formats

**Preferred**:
- PDF (text-native) over scanned PDFs
- DOCX over DOC
- XLSX over XLS or CSV (if formatting matters)
- EPUB over MOBI

### 2. Pre-process Documents

**Before Upload**:
- Convert proprietary formats (Pages → PDF/DOCX)
- Merge multiple files into single PDFs
- Optimize image sizes
- Remove password protection

### 3. Security Review Optional Libraries

For government/enterprise deployments:

**Audit optional libraries before installation**:
```bash
# Review library dependencies
pip show striprtf odfpy ebooklib beautifulsoup4

# Check for known vulnerabilities
pip-audit
```

**Deploy without optional libraries if:**
- Security review requires minimal dependencies
- ODT/EPUB formats are not primary use case
- Built-in fallback quality is acceptable

### 4. Monitor Format Distribution

Track which formats are being processed:

```python
# CloudWatch custom metric
format_counts = {
    "pdf": 1500,
    "docx": 450,
    "xlsx": 200,
    "csv": 150,
    "txt": 100,
    "other": 50
}
```

### 5. Tune for Document Types

Different document types need different settings:
- **Contracts/Legal**: Aggressive filtering (few meaningful images)
- **Scientific Papers**: Conservative filtering (many small charts/diagrams)
- **Marketing Materials**: Very aggressive filtering (many decorative elements)
- **Technical Manuals**: Moderate filtering (balance of text and diagrams)

## Limitations

### Current Limitations

1. **Complex Layouts**: Multi-column layouts may lose reading order
2. **Password-Protected PDFs**: Require decryption first
3. **No Archives**: Must extract .zip, .tar before upload
4. **Embedded Objects**: OLE objects in Office docs not extracted

### Format-Specific

- **PDF**: Annotations not extracted, form interactivity not preserved
- **DOCX/XLSX**: Macros not executed, embedded charts rendered as images
- **EPUB**: DRM-protected files not supported, CSS styling not rendered
- **ODT/EPUB (Fallback)**: Advanced formatting may be simplified without optional libraries

### Fallback Method Limitations

When using built-in fallbacks (without optional libraries):
- **ODT**: Basic text extraction only, advanced formatting lost
- **EPUB**: HTML stripped to plain text, structure simplified
- **Quality**: Acceptable for basic text extraction, not ideal for formatting-critical documents

## Backward Compatibility

The hybrid system maintains full backward compatibility:

**Page Artifacts** (same structure for all processing paths):
- `pages/{page_id}/image.jpg` - Page image
- `pages/{page_id}/result.json` - Extracted text
- `pages/{page_id}/rawText.json` - Raw OCR response
- `pages/{page_id}/textConfidence.json` - Confidence data

**Document Model** (unchanged):
```python
document.pages[page_id].text_uri  # Points to extracted text
document.pages[page_id].image_uri  # Points to page image
```

Downstream processing (extraction, classification, assessment) works identically with all document types and processing paths.

## See Also

- [Configuration Guide](./configuration.md) - General system configuration
- [Extraction Guide](./extraction.md) - Information extraction from documents
- [OCR Image Sizing Guide](./ocr-image-sizing-guide.md) - Image optimization for OCR
- [Troubleshooting Guide](./troubleshooting.md) - Common issues and solutions
