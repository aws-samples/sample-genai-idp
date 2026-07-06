---
title: "Bounding Box Integration in Assessment Service"
---

# Bounding Box Integration in Assessment Service

> **This guide has moved.** Extraction, confidence, and geometry documentation
> is now consolidated in **[Extraction & Confidence](extraction-and-confidence.md)**.

As of config v0.6, field geometry is an **output of extraction**, configured
under `extraction.geometry.*`. What moved:

- **The four geometry modes** — `ocr_only` (default), `llm_grounded`, `llm`, and `off`.
- **OCR grounding via `pageData.json`** — matching extracted values to real OCR lines, format-aware matching, repeated-value disambiguation, and `geometry_source` / `ocr_confidence` provenance.
- **LLM-estimated boxes** — coordinate conversion (0–1000 → 0–1) and the UI-compatible `geometry` output format.

See the [Geometry / Bounding Boxes](extraction-and-confidence.md#4-geometry--bounding-boxes)
section of **[Extraction & Confidence](extraction-and-confidence.md)**.
