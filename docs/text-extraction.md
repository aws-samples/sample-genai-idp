Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Text-Native PDF Processing and Intelligent Image Filtering

The GenAI IDP solution includes an intelligent text extraction system that optimizes processing for text-native PDFs by directly extracting machine-readable text while selectively processing only content-relevant embedded images. This feature significantly reduces processing costs and improves efficiency for documents with extractable text.

## Overview

Traditional document processing treats all PDFs the same way, converting every page to an image and performing OCR. This approach is inefficient for text-native PDFs (those with selectable text), which represent a large percentage of modern business documents.

The text extraction system:
- **Automatically detects** text-native vs. scanned PDFs
- **Directly extracts** machine-readable text without OCR
- **Intelligently filters** embedded images to process only content-relevant images
- **Performs OCR** only on meaningful images (charts, diagrams, screenshots)
- **Excludes** decorative elements (logos, watermarks, headers/footers)

## How It Works

### 1. PDF Type Detection

When a PDF document enters the processing pipeline, the system:

```python
# Automatic detection
if text_extraction_service.is_pdf_text_native(pdf_bytes):
    # Process as text-native PDF with intelligent routing
    manifest = text_extraction_service.extract_manifest(pdf_bytes, s3_prefix)
else:
    # Process as scanned PDF with full OCR
    # Traditional image-based processing
```

**Text-Native Criteria**: A PDF is considered text-native if it contains more than 100 characters of extractable text (configurable threshold).

### 2. Manifest Generation

For text-native PDFs, the system generates a structured manifest of all content blocks in reading order:

```python
manifest = [
    {
        "type": "text",
        "content": "This is a paragraph of text...",
        "page": 1,
        "bbox": (x0, y0, x1, y1)
    },
    {
        "type": "image",
        "content": "OCR text extracted from image...",
        "image_bytes": b"...",
        "s3_key": "document/images/image_1.png",
        "page": 1,
        "bbox": (x0, y0, x1, y1)
    },
    # ... more blocks in order
]
```

### 3. Intelligent Image Filtering

Not all images in a PDF are content-relevant. The system applies multiple heuristics to filter out:

#### Size-Based Filtering
- **Small images** (< 150x150 pixels or < 22,500 pixels² area)
- Common for logos, icons, and decorative elements

#### Position-Based Filtering
- **Header zone**: Top 15% of page (company logos, page headers)
- **Footer zone**: Bottom 15% of page (page numbers, copyright notices)
- **Side margins**: Left/right 10% of page width (watermarks, margin decorations)

#### Aspect Ratio Filtering
- **Extreme ratios** (> 10:1 width/height or height/width)
- Typically decorative lines, banners, or dividers

#### OCR Content Filtering
- **Minimal text** (< 10 characters of OCR-extracted text)
- Images without meaningful text content are often decorative

### 4. Selective OCR Processing

Only images that pass the filtering criteria undergo OCR processing:

```python
for item in manifest:
    if item["type"] == "image":
        # Image already passed filtering - perform OCR
        ocr_text = ocr_service.get_text_from_image(item["image_bytes"])

        # Upload image to S3
        s3.write_content(
            item["image_bytes"],
            output_bucket,
            item["s3_key"]
        )
```

## Configuration

### Image Filter Configuration

Customize filtering behavior through the OCR service configuration:

```yaml
ocr:
  backend: textract
  # ... other OCR settings ...

text_extraction:
  image_filter:
    min_width: 150              # Minimum width in pixels
    min_height: 150             # Minimum height in pixels
    min_area: 22500             # Minimum area (width × height)
    max_aspect_ratio: 10.0      # Maximum aspect ratio
    header_footer_margin: 0.15  # Top/bottom margin (% of page)
    side_margin: 0.10           # Left/right margin (% of page)
    min_ocr_text_length: 10     # Minimum OCR text characters
```

### Conservative Filtering (Medical/Scientific Documents)

For documents with small but important diagrams:

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

### Aggressive Filtering (Marketing Documents)

For documents with many logos and decorative elements:

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

### Disable Filtering

To include all images (no filtering):

```yaml
text_extraction:
  image_filter: false
```

## Benefits

### Cost Reduction

**Traditional Approach** (All Pages as Images):
- 20-page PDF = 20 OCR API calls
- 100% of embedded images processed

**Text Extraction Approach** (Text-Native PDF):
- 20-page PDF = 0 OCR API calls for text
- Only content-relevant images processed (typically 10-30% of total images)

**Example Savings**:
```
Document: 50-page contract with:
- 50 pages of text (directly extracted)
- 20 company logos (filtered)
- 15 decorative elements (filtered)
- 5 diagrams with content (processed)

OCR Calls Saved: 80 → 5 (94% reduction)
```

### Performance Improvements

- **Faster Processing**: Direct text extraction is orders of magnitude faster than OCR
- **Lower Latency**: No waiting for OCR API responses for text pages
- **Reduced Storage**: Fewer images stored in S3
- **Better RAG Performance**: Only meaningful images in vector embeddings

### Quality Improvements

- **Preserves Text Fidelity**: Direct text extraction is 100% accurate (no OCR errors)
- **Maintains Structure**: Text blocks, paragraphs, and reading order preserved
- **Focuses Resources**: OCR processing concentrated on complex visual content

## Processing Pipeline

### Text-Native PDF Flow

```
1. PDF Upload → S3 Input Bucket
                ↓
2. Detection → is_pdf_text_native()?
                ↓ Yes
3. Text Extraction → extract_manifest()
                ↓
4. Per Block Processing:
   - Text Block → Direct extraction
   - Image Block → Filter → OCR (if passed) → Upload to S3
                ↓
5. Page Artifacts → Create compatibility artifacts
                ↓
6. Downstream Processing → Extraction, Classification, etc.
```

### Image Filtering Decision Tree

```
Image Detected
    ↓
Size Check → Too small? → FILTER
    ↓ No
Position Check → In header/footer/margin? → FILTER
    ↓ No
Aspect Ratio Check → Extreme ratio? → FILTER
    ↓ No
OCR Processing → Extract text
    ↓
OCR Content Check → Too little text? → FILTER
    ↓ No
✓ INCLUDE → Upload to S3 and add to manifest
```

## Logging and Debugging

The system provides detailed logging for troubleshooting:

### Info Level Logs
```
INFO - Processing as text-native PDF.
INFO - Manifest extraction complete: 450 items (425 text blocks, 25 images)
INFO - Skipping non-content image on page 3 (likely logo/decorative element)
```

### Debug Level Logs
```
DEBUG - Performing OCR on image candidate from page 5
DEBUG - Filtering image: too small (120x80, minimum 150x150)
DEBUG - Filtering image: in header zone (top at 5.2% of page)
DEBUG - Filtering image: minimal OCR text (3 chars, minimum 10)
DEBUG - Image passed filters: 800x600, position (25%, 45%), OCR length 145
```

Enable debug logging in your configuration:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Backward Compatibility

The text extraction system maintains full backward compatibility:

### Page Artifacts

Text-native PDFs still generate the same page artifacts as scanned PDFs:
- `pages/{page_id}/image.jpg` - Page image
- `pages/{page_id}/result.json` - Extracted text
- `pages/{page_id}/rawText.json` - Raw OCR response (placeholder for text-native)
- `pages/{page_id}/textConfidence.json` - Confidence data

### Document Structure

The `Document` model remains unchanged:
```python
document.pages[page_id].text_uri  # Points to extracted text
document.pages[page_id].image_uri  # Points to page image
```

### Downstream Processing

Extraction, classification, and assessment services work identically with text-native and scanned PDFs.

## Advanced Features

### Custom Text Threshold

Adjust the text detection threshold:

```python
from idp_common.text_extraction import TextExtractionService

service = TextExtractionService(
    ocr_service=ocr_service,
    text_length_threshold=200  # Require 200 chars to classify as text-native
)
```

### Programmatic Filter Control

Configure filters programmatically:

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

### Disable Filtering for Specific Documents

```python
# Process without filtering
service = TextExtractionService(
    ocr_service=ocr_service,
    image_filter_config=False  # Include all images
)
```

## Monitoring and Metrics

Track text extraction performance through CloudWatch metrics:

### Key Metrics

- **OCR/native/direct_extraction/pages** - Pages processed via text extraction
- **OCR/textract/detect_document_text/pages** - Pages processed via OCR
- Images filtered vs. processed ratio
- Processing time comparisons

### Cost Analysis

Compare processing costs before and after text extraction:

```python
# Traditional OCR approach
traditional_cost = num_pages * textract_page_cost

# Text extraction approach
text_extraction_cost = content_images * textract_page_cost

savings_percentage = (1 - text_extraction_cost/traditional_cost) * 100
```

## Best Practices

### 1. Use Default Settings Initially

Start with default filter settings and adjust based on your document characteristics:

```yaml
text_extraction:
  image_filter:  # Use defaults
```

### 2. Monitor Filtering Decisions

Enable DEBUG logging for a sample of documents to understand filtering behavior:

```python
logging.getLogger("idp_common.text_extraction").setLevel(logging.DEBUG)
```

### 3. Tune for Document Types

Different document types may need different settings:

- **Contracts/Legal**: Aggressive filtering (few meaningful images)
- **Scientific Papers**: Conservative filtering (many small charts/diagrams)
- **Marketing Materials**: Very aggressive filtering (many decorative elements)
- **Technical Manuals**: Moderate filtering (balance of text and diagrams)

### 4. Test Edge Cases

Test with documents that have:
- Watermarks across entire page
- Company logos on every page
- Small but important diagrams
- Dense image layouts

### 5. Validate Filtering Results

Periodically review filtered images to ensure important content isn't being excluded:

```bash
# Check filtering statistics in logs
grep "Skipping non-content image" application.log | wc -l
grep "Successfully processed content image" application.log | wc -l
```

## Troubleshooting

### Issue: Important Images Being Filtered

**Symptoms**: Small diagrams or charts not appearing in output

**Solution**: Reduce size thresholds
```yaml
text_extraction:
  image_filter:
    min_width: 80
    min_height: 80
    min_area: 6400
```

### Issue: Logos Still Being Processed

**Symptoms**: Company logos appearing in image output

**Solution**: Increase margin thresholds
```yaml
text_extraction:
  image_filter:
    header_footer_margin: 0.20
    side_margin: 0.15
```

### Issue: Too Many Images Filtered

**Symptoms**: Content-rich images missing

**Solution**: Reduce OCR text threshold
```yaml
text_extraction:
  image_filter:
    min_ocr_text_length: 3
```

### Issue: PDF Not Detected as Text-Native

**Symptoms**: Document with text being processed as scanned

**Check**:
1. Does PDF have selectable text? (Try selecting text in PDF viewer)
2. Is text threshold too high? (Check logs for character count)
3. Is PDF actually scanned? (Some scanned PDFs have minimal OCR'd text)

**Solution**: Lower text threshold
```python
TextExtractionService(text_length_threshold=50)
```

## Limitations

### Current Limitations

1. **Form Fields**: Complex form layouts may not preserve exact positioning
2. **Multi-Column Text**: Reading order may vary for complex layouts
3. **Rotated Text**: Text rotation may affect extraction
4. **Vector Graphics**: Vector-based diagrams are treated as images
5. **Encrypted PDFs**: Password-protected PDFs require decryption first

### Not Supported

- **Scanned PDFs**: Automatically fallback to traditional OCR processing
- **Image-Only PDFs**: Treated as scanned documents
- **PDFs with Minimal Text**: Below threshold triggers OCR processing

## Performance Characteristics

### Text Extraction Speed

- **Direct Text Extraction**: ~1-2 seconds per page
- **Traditional OCR**: ~5-10 seconds per page
- **Speedup**: 3-5x faster for text-native PDFs

### Memory Usage

- **Text Extraction**: Low memory footprint (text-only processing)
- **Image Filtering**: Minimal overhead (quick heuristics)
- **OCR Processing**: Only for content-relevant images

### Scalability

The text extraction system scales linearly with document size and complexity:
- Large text-native PDFs: Excellent performance
- Mixed-content PDFs: Moderate performance improvement
- Image-heavy PDFs: Less benefit (more images to process)

## Future Enhancements

Planned improvements:

1. **ML-Based Filtering**: Train classifier to identify decorative images
2. **Duplicate Detection**: Filter repeated images across pages
3. **Image Hash Comparison**: Detect identical logos/watermarks
4. **Content Analysis**: Use image classification to identify image types
5. **Layout Analysis**: Better reading order for complex layouts
6. **Table Extraction**: Enhanced table structure preservation

## See Also

- [Configuration Guide](./configuration.md) - General system configuration
- [Extraction Guide](./extraction.md) - Information extraction from documents
- [OCR Image Sizing Guide](./ocr-image-sizing-guide.md) - Image optimization for OCR
- [Troubleshooting Guide](./troubleshooting.md) - Common issues and solutions
