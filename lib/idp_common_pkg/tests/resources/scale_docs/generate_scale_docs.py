#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Reproducible generator for large multi-page tabular test PDFs.

These PDFs stress agentic sharded extraction at scale. Every table row carries a
**sequential row-index column** (``RowID``, 1..N over the whole document) so a
post-extraction check can prove NO rows were dropped, duplicated, or reordered
after the sharded merge — the expected row count is known exactly.

Usage:
    python3 generate_scale_docs.py [OUTPUT_DIR]

OUTPUT_DIR defaults to the directory containing this script. The large generated
PDFs are intentionally NOT committed (they regenerate deterministically); point
OUTPUT_DIR at a scratch/ working dir for E2E runs.

Produces:
    big_single_table_100p.pdf    ~100 pages, ONE continuous holdings table
    big_many_tables_100p.pdf     ~100 pages, MANY distinct tables per page
    huge_single_table_200p.pdf   ~200 pages, one massive holdings table

A sidecar ``<name>.expected.json`` records expected_rows + schema hints for each
doc so the E2E checker is self-describing.
"""

from __future__ import annotations

import json
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = getSampleStyleSheet()

# Deterministic, self-checking synthetic data. No randomness -> identical output
# every run, and a sequential RowID makes loss/dup/reorder detectable exactly.
SYMBOLS = ["AAPL", "MSFT", "AMZN", "GOOGL", "TSLA", "NVDA", "META", "JPM"]
ACCOUNTS = ["ACME-001", "ACME-002", "GLOBEX-7", "INITECH-3"]


def _holding_row(row_id: int) -> list[str]:
    """One deterministic holdings row keyed by the global sequential RowID."""
    sym = SYMBOLS[row_id % len(SYMBOLS)]
    qty = 100 + (row_id * 7) % 5000
    price = round(10.0 + (row_id * 1.37) % 990.0, 2)
    value = round(qty * price, 2)
    return [
        str(row_id),
        sym,
        ACCOUNTS[row_id % len(ACCOUNTS)],
        f"2024-{(row_id % 12) + 1:02d}-{(row_id % 28) + 1:02d}",
        str(qty),
        f"${price:,.2f}",
        f"${value:,.2f}",
    ]


HOLDINGS_HEADER = [
    "RowID",
    "Symbol",
    "Account",
    "TradeDate",
    "Quantity",
    "Price",
    "MarketValue",
]


def _make_table(rows: list[list[str]], header: list[str]) -> Table:
    data = [header] + rows
    t = Table(data, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#22304a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#eef2f7")],
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    return t


def _doc(path: str):
    frame = Frame(
        0.5 * inch, 0.5 * inch, 7.5 * inch, 10 * inch, id="main", showBoundary=0
    )
    tmpl = PageTemplate(id="all", frames=[frame])
    d = BaseDocTemplate(path, pagesize=letter, pageTemplates=[tmpl])
    return d


def gen_single_table(path: str, pages: int, rows_per_page: int, title: str) -> int:
    """One continuous holdings table spanning many pages. Returns total rows."""
    story = []
    story.append(Paragraph(title, STYLES["Title"]))
    story.append(
        Paragraph(
            "Continuous holdings ledger. RowID is a global sequential index "
            "(1..N) used to verify completeness.",
            STYLES["Normal"],
        )
    )
    story.append(Spacer(1, 8))
    total = pages * rows_per_page
    # Build the whole table once; repeatRows=1 reprints the header on each page,
    # and platypus splits the long table across pages automatically.
    rows = [_holding_row(i) for i in range(1, total + 1)]
    story.append(_make_table(rows, HOLDINGS_HEADER))
    _doc(path).build(story)
    return total


def gen_many_tables(
    path: str, pages: int, tables_per_page: int, rows_per_table: int, title: str
) -> int:
    """Many distinct small tables (multiple per page). Returns total rows.

    RowID is still globally sequential across every table so the merged
    extraction can be checked as one contiguous 1..N sequence even though the
    rows are spread over many separate tables.
    """
    story = []
    story.append(Paragraph(title, STYLES["Title"]))
    story.append(
        Paragraph(
            "Multiple transaction tables per section. RowID is a global "
            "sequential index (1..N) across ALL tables.",
            STYLES["Normal"],
        )
    )
    story.append(Spacer(1, 8))
    row_id = 0
    n_tables = pages * tables_per_page
    for t in range(n_tables):
        story.append(Paragraph(f"Statement Table {t + 1}", STYLES["Heading3"]))
        rows = []
        for _ in range(rows_per_table):
            row_id += 1
            rows.append(_holding_row(row_id))
        story.append(_make_table(rows, HOLDINGS_HEADER))
        story.append(Spacer(1, 10))
    _doc(path).build(story)
    return row_id


def _write_expected(pdf_path: str, expected_rows: int, kind: str) -> None:
    meta = {
        "pdf": os.path.basename(pdf_path),
        "expected_rows": expected_rows,
        "kind": kind,
        "row_index_column": "RowID",
        "row_index_range": [1, expected_rows],
        "columns": HOLDINGS_HEADER,
    }
    with open(pdf_path.replace(".pdf", ".expected.json"), "w") as fh:
        json.dump(meta, fh, indent=2)


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else HERE
    os.makedirs(out_dir, exist_ok=True)
    targets = []

    # NOTE: row counts below are calibrated empirically to the platypus layout
    # (~46 rows/page at font 7) so the rendered PDF lands near the target page
    # count (~101 / ~102 / ~201 pages); the exact page count is reported on build.
    p = os.path.join(out_dir, "big_single_table_100p.pdf")
    n = gen_single_table(
        p, pages=1, rows_per_page=4600, title="Big Single Table (100p)"
    )
    _write_expected(p, n, "single_table")
    targets.append((p, n))

    p = os.path.join(out_dir, "big_many_tables_100p.pdf")
    # ~14 rows/table; ~2.55 tables/page -> ~260 tables for ~100 pages.
    n = gen_many_tables(
        p,
        pages=1,
        tables_per_page=260,
        rows_per_table=14,
        title="Big Many Tables (100p)",
    )
    _write_expected(p, n, "many_tables")
    targets.append((p, n))

    p = os.path.join(out_dir, "huge_single_table_200p.pdf")
    n = gen_single_table(
        p, pages=1, rows_per_page=9200, title="Huge Single Table (200p)"
    )
    _write_expected(p, n, "single_table")
    targets.append((p, n))

    for path, rows in targets:
        size = os.path.getsize(path)
        print(f"{os.path.basename(path):32s} rows={rows:6d} size={size / 1024:.0f}KB")


if __name__ == "__main__":
    main()
