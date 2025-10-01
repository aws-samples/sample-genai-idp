Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Supported Document Formats

The GenAI IDP solution supports a comprehensive range of document formats for text extraction and intelligent processing. This guide details all supported formats, their processing methods, and any special requirements.

## Format Categories

### PDF Documents (Core Support)

**`.pdf` - Portable Document Format**
- **Text-Native PDFs**: Direct text extraction with intelligent image filtering
- **Scanned/Image-Based PDFs**: Full OCR processing with AWS Textract or Amazon Bedrock
- **Processing**: Automatic detection determines optimal processing path
- **Special Features**:
  - Embedded image extraction and selective OCR
  - Table and form detection (with Textract TABLES/FORMS features)
  - Multi-page support with concurrent processing

**Key Features**:
```yaml
# PDF-specific configuration
ocr:
  backend: textract
  features:
    - name: TABLES
    - name: FORMS
  image:
    dpi: 150
    target_width: 951
    target_height: 1268
```

### Microsoft Office Formats

**`.docx`, `.doc` - Microsoft Word Documents**
- **Processing**: Native format parsing with python-docx library
- **Preserves**: Formatting, tables, headings, lists
- **Output**: Structured text with markdown formatting
- **Page Images**: Rendered as images for consistency

**Features Extracted**:
- Heading hierarchy (H1-H6)
- Paragraph formatting (bold, italic, underline)
- Tables with borders and cell alignment
- Lists (bulleted and numbered)
- Text alignment (left, center, right, justify)

**`.xlsx`, `.xls` - Microsoft Excel Spreadsheets**
- **Processing**: pandas-based parsing with openpyxl library
- **Preserves**: Multi-sheet structure, data types, formatting
- **Output**: Markdown tables with type-aware alignment
- **Special Handling**:
  - Numeric formatting with thousands separators
  - Date formatting (YYYY-MM-DD)
  - Currency detection and right-alignment
  - Empty cell handling

**Excel Processing Example**:
```python
# Automatic type detection and formatting
Original: 1234.5678
Output:   1,234.57

Original: 2024-01-15
Output:   2024-01-15

Original: $99.99
Output:   $99.99 (right-aligned)
```

### Text-Based Formats (Automatic Support)

All text-based formats are processed automatically without additional libraries:

**Plain Text**
- `.txt` - Plain text files
- `.log` - Log files

**Markup Languages**
- `.md`, `.markdown` - Markdown
- `.html`, `.htm` - HTML
- `.xml` - XML
- `.rst` - reStructuredText
- `.asciidoc`, `.adoc` - AsciiDoc
- `.tex` - LaTeX (source only, not compiled)

**Structured Data**
- `.json` - JSON
- `.yaml`, `.yml` - YAML

**Programming Languages**
- `.py` - Python
- `.js` - JavaScript
- `.java` - Java
- `.c`, `.cpp`, `.h`, `.hpp` - C/C++
- `.cs` - C#
- `.rb` - Ruby
- `.php` - PHP
- `.go` - Go
- `.rs` - Rust
- `.sql` - SQL

**Configuration Files**
- `.ini` - INI configuration
- `.conf`, `.config` - Generic configuration
- `.env` - Environment variables
- `.toml` - TOML
- `.properties` - Java properties

**Processing**: All text-based formats are decoded as UTF-8 and converted to standardized page images with monospace font rendering.

### Tabular Data Formats

**`.csv` - Comma-Separated Values**
- **Processing**: pandas with intelligent type inference
- **Output**: Formatted markdown tables
- **Features**:
  - Automatic date parsing
  - Numeric type detection
  - Header row identification
  - Thousands separator formatting

**`.tsv` - Tab-Separated Values**
- **Processing**: Same as CSV with tab delimiter
- **Output**: Formatted markdown tables
- **Use Case**: Alternative to CSV for data with commas

**CSV/TSV Configuration**:
```yaml
# Pandas automatically handles:
# - Type inference
# - Date parsing
# - Null value handling
# - Column alignment based on data type
```

### Rich Text Formats (Optional Libraries)

**`.rtf` - Rich Text Format**
- **Library**: `striprtf` (optional)
- **Installation**: `pip install striprtf`
- **Fallback**: Basic regex-based text extraction without library
- **Processing**: Extracts plain text, removes control words
- **Output**: Plain text pages

**Installation**:
```bash
pip install striprtf
```

**Without Library**: System falls back to basic regex parsing that removes RTF control codes.

### OpenDocument Formats (Optional Library)

**`.odt` - OpenDocument Text**
- **Library**: `odfpy` (required for ODT support)
- **Installation**: `pip install odfpy`
- **Processing**: Native ODT parsing
- **Features**:
  - Paragraph extraction
  - Heading hierarchy
  - Text structure preservation
- **Output**: Structured text pages

**Installation**:
```bash
pip install odfpy
```

**Without Library**: Returns error message suggesting library installation.

### eBook Formats (Optional Libraries)

**`.epub` - EPUB eBooks**
- **Libraries**: `ebooklib` and `beautifulsoup4` (both required)
- **Installation**: `pip install ebooklib beautifulsoup4`
- **Processing**: HTML content extraction with structure preservation
- **Features**:
  - Chapter detection
  - Title extraction
  - Heading hierarchy (H1-H3)
  - Paragraph and list extraction
- **Output**: Markdown-formatted pages

**Installation**:
```bash
pip install ebooklib beautifulsoup4
```

**EPUB Processing**:
```python
# Extracted structure
# Title
## Chapter 1 Heading
Paragraph content...

## Chapter 2 Heading
More content...
```

**`.mobi` - Kindle Format**
- **Status**: Limited support
- **Recommendation**: Convert to EPUB using Calibre
- **Current Behavior**: Returns message suggesting format conversion
- **Reason**: MOBI is proprietary and complex to parse

**Conversion Workflow**:
```bash
# Using Calibre (recommended)
ebook-convert input.mobi output.epub

# Then upload EPUB to IDP system
```

### Proprietary Formats

**`.pages` - Apple Pages**
- **Status**: Not supported
- **Reason**: Proprietary Apple format without public documentation
- **Recommendation**: Export as PDF or DOCX from Pages app
- **Current Behavior**: Returns message suggesting format export

**Export from Pages**:
1. Open document in Pages
2. File → Export To → PDF or Word
3. Upload exported file to IDP system

### Image Formats

All common image formats are supported with direct OCR processing:

**Raster Formats**:
- `.jpg`, `.jpeg` - JPEG images
- `.png` - PNG images
- `.gif` - GIF images
- `.bmp` - Bitmap images
- `.tiff`, `.tif` - TIFF images
- `.webp` - WebP images

**Processing**:
- Original format preserved
- Optional resizing based on configuration
- OCR via Textract or Bedrock
- Format-specific content-type handling

## File Type Detection

The system uses intelligent multi-stage detection:

### 1. Extension-Based Detection (Primary)

```python
filename = "report.docx"
# Detected as: docx (Word document)
```

### 2. Magic Byte Detection (Fallback)

Used when extension is ambiguous or missing:

```python
# PDF magic bytes
b"%PDF" → pdf

# ZIP-based formats
b"PK" → Further inspection:
    b"xl/" → xlsx
    b"word/" → docx
    b"mimetype" + "opendocument" → odt
    b"mimetype" + "epub" → epub

# RTF magic bytes
b"{\\rtf" → rtf
```

### 3. Content-Based Detection (Last Resort)

```python
# Try UTF-8 decoding
try:
    content.decode("utf-8")
    # Treat as plain text
except UnicodeDecodeError:
    # Default to PDF processing
```

## Processing Pipeline

All document formats follow this unified pipeline:

```
1. Upload → S3 Input Bucket
           ↓
2. Type Detection → _detect_file_type()
           ↓
3. Format Router → _process_non_pdf_document()
           ↓
4. Format-Specific Converter:
   - PDF → Text extraction or OCR
   - DOCX → convert_word_to_pages()
   - XLSX → convert_excel_to_pages()
   - CSV → convert_csv_to_pages()
   - TXT → convert_text_to_pages()
   - RTF → convert_rtf_to_pages()
   - ODT → convert_odt_to_pages()
   - EPUB → convert_epub_to_pages()
           ↓
5. Page Generation → Standardized images (8.5" x 11")
           ↓
6. Text Extraction → Structured text output
           ↓
7. Downstream Processing → Classification, Extraction, etc.
```

## Output Format

All formats produce consistent output:

### Page Images
- **Format**: JPEG
- **Size**: 8.5" x 11" at configured DPI
- **Quality**: 95% JPEG quality
- **Location**: `s3://{bucket}/{prefix}/pages/{page_id}/image.jpg`

### Extracted Text
- **Format**: Plain text or markdown
- **Structure**: Preserved where possible
- **Location**: `s3://{bucket}/{prefix}/pages/{page_id}/result.json`

### Metadata
- **Page Numbers**: Sequential (1-based)
- **Confidence**: 99.0 for converted documents
- **URIs**: S3 paths to all artifacts

**Example Output Structure**:
```json
{
  "pages": {
    "1": {
      "page_id": "1",
      "image_uri": "s3://bucket/doc/pages/1/image.jpg",
      "raw_text_uri": "s3://bucket/doc/pages/1/rawText.json",
      "parsed_text_uri": "s3://bucket/doc/pages/1/result.json",
      "text_confidence_uri": "s3://bucket/doc/pages/1/textConfidence.json"
    }
  }
}
```

## Installation Requirements

### Core Dependencies (Pre-installed)

These are already included in the solution:

```bash
pip install PyMuPDF pandas python-docx openpyxl Pillow textractor
```

### Optional Format Support

Install based on your document types:

**Rich Text Format**:
```bash
pip install striprtf
```

**OpenDocument**:
```bash
pip install odfpy
```

**EPUB eBooks**:
```bash
pip install ebooklib beautifulsoup4
```

**All Optional Formats**:
```bash
pip install striprtf odfpy ebooklib beautifulsoup4
```

### Docker/Lambda Deployment

Update your `requirements.txt`:

```txt
# Core (already included)
PyMuPDF>=1.23.0
pandas>=2.0.0
python-docx>=0.8.11
openpyxl>=3.1.0
Pillow>=10.0.0

# Optional format support
striprtf>=0.0.26
odfpy>=1.4.1
ebooklib>=0.18
beautifulsoup4>=4.12.0
```

## Configuration

### DPI Settings

Control image quality for converted documents:

```yaml
ocr:
  image:
    dpi: 150  # Default (balance of quality and size)
```

**DPI Guidelines**:
- `100`: Low quality, small files, fast processing
- `150`: Recommended default
- `200`: High quality for detailed documents
- `300`: Very high quality, large files

### Format-Specific Settings

Currently, format conversion uses default settings. Future versions may support:

```yaml
document_conversion:
  word:
    preserve_formatting: true
    include_headers_footers: true
  excel:
    include_formulas: false
    max_sheets: 10
  epub:
    extract_metadata: true
    include_toc: true
```

## Usage Examples

### Basic Processing

No configuration needed - automatic format detection:

```python
from idp_common.ocr import OcrService
from idp_common.models import Document

# Initialize service
ocr_service = OcrService(config=config)

# Process any supported format
document = Document(
    input_bucket="my-bucket",
    input_key="documents/report.docx"  # Automatically detected and processed
)

result = ocr_service.process_document(document)
```

### Format-Specific Processing

```python
# Word document
doc = Document(input_bucket="bucket", input_key="contract.docx")
result = ocr_service.process_document(doc)

# Excel spreadsheet
doc = Document(input_bucket="bucket", input_key="data.xlsx")
result = ocr_service.process_document(doc)

# Markdown file
doc = Document(input_bucket="bucket", input_key="readme.md")
result = ocr_service.process_document(doc)

# EPUB ebook (requires ebooklib)
doc = Document(input_bucket="bucket", input_key="book.epub")
result = ocr_service.process_document(doc)
```

### Checking Supported Formats

```python
supported_formats = [
    # Core formats
    "pdf", "docx", "doc", "xlsx", "xls", "txt", "csv", "tsv",
    # Markup
    "md", "html", "xml", "rst", "asciidoc",
    # Programming
    "py", "js", "java", "sql",
    # Config
    "ini", "yaml", "json", "env",
    # Rich text (optional)
    "rtf", "odt", "epub",
    # Images
    "jpg", "png", "gif", "bmp", "tiff", "webp"
]
```

## Error Handling

### Graceful Degradation

The system handles errors gracefully:

**Missing Optional Library**:
```python
# RTF without striprtf library
# → Falls back to basic regex parsing

# ODT without odfpy
# → Returns error message with installation instructions

# EPUB without ebooklib
# → Returns error message with installation instructions
```

**Corrupted Files**:
```python
# Corrupted document
# → Creates empty page with error message
# → Logs error for troubleshooting
# → Continues processing other pages
```

**Unsupported Formats**:
```python
# Unknown format
# → Attempts UTF-8 text extraction
# → Falls back to PDF processing
# → Logs warning with filename
```

### Error Messages

**Example Error Outputs**:

```json
{
  "text": "Error: odfpy library required for ODT files. Install with: pip install odfpy"
}
```

```json
{
  "text": "MOBI format not fully supported. Please convert to EPUB or PDF format."
}
```

## Performance Characteristics

### Processing Speed by Format

| Format | Speed | Notes |
|--------|-------|-------|
| PDF (text) | ⚡⚡⚡⚡⚡ | Direct extraction, fastest |
| TXT, CSV | ⚡⚡⚡⚡ | Simple parsing |
| DOCX, XLSX | ⚡⚡⚡ | Format parsing overhead |
| PDF (scanned) | ⚡⚡ | OCR processing required |
| RTF | ⚡⚡⚡ | Regex parsing (lightweight) |
| ODT | ⚡⚡ | ZIP extraction + XML parsing |
| EPUB | ⚡⚡ | ZIP extraction + HTML parsing |

### Memory Usage

| Format | Memory | Notes |
|--------|--------|-------|
| TXT, CSV, TSV | Low | Streaming possible |
| PDF | Medium | Page-by-page processing |
| DOCX, XLSX | Medium | Loaded into memory |
| ODT, EPUB | Medium | ZIP extraction + parsing |
| Images | Variable | Depends on image size |

## Best Practices

### 1. Use Native Formats When Possible

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

### 3. Install Optional Libraries

For production deployments:

```bash
# Include all optional libraries for maximum compatibility
pip install striprtf odfpy ebooklib beautifulsoup4
```

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

### 5. Validate Critical Formats

Test format processing in development:

```python
# Test each format type you expect
test_documents = [
    "sample.pdf",
    "sample.docx",
    "sample.xlsx",
    "sample.csv",
    "sample.md"
]

for doc in test_documents:
    result = process_document(doc)
    validate_output(result)
```

## Troubleshooting

### Issue: Format Not Detected

**Symptoms**: File processed incorrectly or as wrong type

**Solutions**:
1. Check file extension is correct
2. Verify file is not corrupted
3. Check file magic bytes match extension
4. Try renaming with correct extension

### Issue: Missing Text from Document

**Symptoms**: Blank or partial text extraction

**Solutions**:
1. Verify source document has text (not scanned image)
2. Check for encoding issues (non-UTF-8 text files)
3. Increase DPI for better OCR quality
4. Check logs for parsing errors

### Issue: Poor Image Quality

**Symptoms**: Blurry or pixelated page images

**Solutions**:
```yaml
ocr:
  image:
    dpi: 200  # Increase from 150
```

### Issue: Library Import Errors

**Symptoms**: "Error: library required for X files"

**Solutions**:
```bash
# Install missing library
pip install <library-name>

# Verify installation
python -c "import <library>; print(<library>.__version__)"

# Rebuild Lambda layer if using Lambda
./build_lambda_layer.sh
```

## Limitations

### Current Limitations

1. **No Audio/Video**: Multimedia content not supported
2. **No Archives**: Must extract .zip, .tar before upload
3. **No Executables**: Binary executables not processed
4. **Complex Layouts**: Multi-column layouts may lose reading order
5. **Embedded Objects**: OLE objects in Office docs not extracted

### Format-Specific Limitations

**PDF**:
- Password-protected PDFs require decryption
- Form fields may not preserve interactivity
- Annotations not extracted

**DOCX/XLSX**:
- Macros not executed
- Embedded charts rendered as images
- Complex formatting may be simplified

**EPUB**:
- DRM-protected files not supported
- Interactive elements not preserved
- CSS styling not rendered

## Future Enhancements

Planned improvements:

1. **PowerPoint Support**: `.pptx`, `.ppt` presentation formats
2. **Archive Support**: Process .zip files containing multiple documents
3. **Email Formats**: `.eml`, `.msg` support
4. **Enhanced MOBI**: Native Kindle format parsing
5. **Better Layout**: Improved multi-column text extraction
6. **Metadata Extraction**: Document properties and metadata
7. **Format Validation**: Pre-processing format verification

## See Also

- [Text Extraction Guide](./text-extraction.md) - Text-native PDF processing
- [Configuration Guide](./configuration.md) - System configuration options
- [OCR Image Sizing](./ocr-image-sizing-guide.md) - Image optimization
- [Troubleshooting](./troubleshooting.md) - Common issues and solutions
