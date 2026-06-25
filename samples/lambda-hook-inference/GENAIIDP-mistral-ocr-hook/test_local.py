#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Local test script for the Mistral OCR Lambda Hook.

This script tests the Mistral OCR integration by:
1. Converting PDF pages (or a single image) to JPEG images
2. Submitting each page to the hosted Mistral OCR API
3. Translating the response into Amazon Textract block format
4. Displaying the markdown, per-line/word confidence, and geometry

It exercises the same translation code (index.py) that runs in the deployed
Lambda, so you can validate end-to-end behavior — including the per-word
confidence and bounding-box capture — before deploying.

Prerequisites:
  pip install pdf2image Pillow

  # pdf2image requires poppler:
  # macOS: brew install poppler
  # Ubuntu: sudo apt-get install poppler-utils
  # Amazon Linux: sudo yum install poppler-utils

Usage:
  export MISTRAL_API_KEY="your-api-key-here"

  # OCR a PDF file
  python test_local.py ../../insurance_package.pdf

  # OCR specific pages only
  python test_local.py ../../insurance_package.pdf --pages 1,2

  # OCR a single image
  python test_local.py page.jpg
"""

import argparse
import io
import json
import os
import sys

# Import the deployed Lambda's translation helpers so we test the real code.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index  # noqa: E402, I001


def pdf_to_images(pdf_path: str, pages: list[int] | None = None) -> list[bytes]:
    """Convert PDF pages to JPEG image bytes."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        print("ERROR: pdf2image is required. Install with: pip install pdf2image")
        print("       Also install poppler: brew install poppler (macOS)")
        sys.exit(1)

    print(f"Converting PDF to images: {pdf_path}")
    pil_images = convert_from_path(pdf_path, dpi=150)

    if pages:
        pil_images = [pil_images[p - 1] for p in pages if p <= len(pil_images)]

    image_bytes_list = []
    for i, img in enumerate(pil_images):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_bytes_list.append(buf.getvalue())
        print(
            f"  Page {i + 1}: {img.width}x{img.height} -> {len(buf.getvalue())} bytes"
        )

    return image_bytes_list


def load_image(path: str) -> tuple[bytes, str]:
    """Load a single image file and infer its format."""
    with open(path, "rb") as f:
        data = f.read()
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpeg"
    return data, ext


def summarize_blocks(textract_response: dict) -> None:
    """Print a short summary of the Textract-format blocks."""
    blocks = textract_response.get("Blocks", [])
    by_type: dict[str, int] = {}
    for b in blocks:
        by_type[b["BlockType"]] = by_type.get(b["BlockType"], 0) + 1
    print(f"  Block counts: {by_type}")

    # Show the confidence table that the IDP pipeline would generate.
    line_blocks = [b for b in blocks if b["BlockType"] == "LINE" and b.get("Text")][:10]
    if line_blocks:
        print("  Sample LINE blocks (text | confidence | has-geometry):")
        for b in line_blocks:
            geom = "yes" if "Geometry" in b else "no"
            conf = b.get("Confidence", "N/A")
            text = b["Text"][:60]
            print(f"    | {text} | {conf} | {geom}")

    word_blocks = [b for b in blocks if b["BlockType"] == "WORD"]
    if word_blocks:
        print(f"  WORD blocks with per-word confidence: {len(word_blocks)}")
        for b in word_blocks[:5]:
            print(f"    {b.get('Text')!r}: {b.get('Confidence', 'N/A')}")


def main():
    parser = argparse.ArgumentParser(
        description="Test Mistral OCR on a PDF or image document",
        epilog="Set MISTRAL_API_KEY environment variable before running.",
    )
    parser.add_argument("path", help="Path to PDF or image file to OCR")
    parser.add_argument(
        "--pages", help="Comma-separated page numbers (PDF only)", default=None
    )
    parser.add_argument("--output", help="Write full JSON to this file", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"ERROR: File not found: {args.path}")
        sys.exit(1)

    if not index.MISTRAL_API_KEY:
        print("ERROR: Set MISTRAL_API_KEY environment variable.")
        print("       Get your API key from https://console.mistral.ai")
        sys.exit(1)

    if args.path.lower().endswith(".pdf"):
        pages = None
        if args.pages:
            pages = [int(p.strip()) for p in args.pages.split(",")]
        images = [
            {"bytes": b, "format": "jpeg"} for b in pdf_to_images(args.path, pages)
        ]
    else:
        data, fmt = load_image(args.path)
        images = [{"bytes": data, "format": fmt}]

    print(f"\nProcessing {len(images)} image(s) with Mistral OCR")
    print(f"API: {index.MISTRAL_API_URL}")
    print(f"Model: {index.MISTRAL_OCR_MODEL}")
    print(
        f"include_blocks={index.INCLUDE_BLOCKS}, confidence={index.CONFIDENCE_GRANULARITY}"
    )
    print("=" * 70)

    full_results = []
    for i, img in enumerate(images):
        print(f"\n--- Image {i + 1} ---")
        ocr_response = index.call_mistral_ocr(img["bytes"], img["format"])
        text, textract_response, pages_processed = index.build_textract_response(
            ocr_response
        )
        print(f"  pages_processed: {pages_processed}")
        summarize_blocks(textract_response)
        print("\n  --- Markdown ---")
        print(text[:2000])
        full_results.append(
            {"raw": ocr_response, "textract": textract_response, "text": text}
        )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(full_results, f, indent=2)
        print(f"\nFull results written to {args.output}")


if __name__ == "__main__":
    main()
