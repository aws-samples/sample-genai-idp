#!/usr/bin/env python3
"""Synthetic Bank Statement generator with EXACT ground truth.

Each transaction Description embeds a unique 'SEQnnnnn' tag for exact completeness
measurement. Deterministic given params (no RNG) so regeneration is byte-stable.

build(rows, cols, lists, desc_len, ocr_noise, out) -> writes <out>.pdf + <out>.truth.json
"""

import json

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MERCHANTS = [
    "AnyCompany Store",
    "Example Mart",
    "Sample Cafe",
    "Test Fuel Co",
    "Demo Pharmacy",
    "Placeholder Books",
    "Acme Utilities",
    "Widget Depot",
]
WIDE_COLS = [
    "Date",
    "Description",
    "Amount",
    "Balance",
    "Category",
    "Ref",
    "Type",
    "Location",
]

# Fixed top-level fields (exact GT for scalar accuracy)
FIELDS = {
    "Account Number": "000123456789",
    "Statement Period": "01/01/2024 - 12/31/2024",
}


def _noise(s, seq, level):
    """Deterministic OCR-like corruption: drop/merge chars based on seq, no RNG."""
    if level <= 0:
        return s
    out = []
    for i, ch in enumerate(s):
        # drop roughly `level` fraction of spaces/digits deterministically
        if ch == " " and ((seq * 7 + i) % max(1, int(1 / level))) == 0:
            continue  # merge tokens (removes a space)
        out.append(ch)
    return "".join(out)


def _row(seq, cols, desc_len, noise):
    date = f"{(seq % 12) + 1:02d}/{(seq % 28) + 1:02d}/2024"
    merch = MERCHANTS[seq % len(MERCHANTS)]
    if desc_len == "long":
        desc = (
            f"SEQ{seq:05d} Purchase at {merch} - authorization code "
            f"{seq * 7 % 999999:06d} - recurring monthly charge reference "
            f"invoice {seq} terminal {seq % 50}"
        )
    else:
        desc = f"SEQ{seq:05d} {merch} #{seq}"
    amount = f"{'-' if seq % 3 else ''}{(seq * 13.7) % 5000:.2f}"
    if noise:
        desc = _noise(desc, seq, noise)
    if cols == 3:
        return [date, desc, amount]
    return [
        date,
        desc,
        amount,
        f"{(seq * 31.1) % 99999:.2f}",
        ["Food", "Fuel", "Retail", "Bills"][seq % 4],
        f"R{seq:06d}",
        ["DEBIT", "CREDIT"][seq % 2],
        f"City{seq % 40}, ST",
    ]


def build(rows, cols=3, lists=1, desc_len="short", ocr_noise=0.0, out="doc.pdf"):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        out,
        pagesize=letter,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.4 * inch,
        rightMargin=0.4 * inch,
    )
    story = [
        Paragraph("<b>AnyBank Monthly Statement</b>", styles["Title"]),
        Paragraph(f"Account Number: {FIELDS['Account Number']}", styles["Normal"]),
        Paragraph(f"Statement Period: {FIELDS['Statement Period']}", styles["Normal"]),
        Paragraph(
            "Account Holder: Jane Q Public, 100 Main Street, Anytown, CA 90210",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
    ]
    header = WIDE_COLS[:cols] if cols > 3 else ["Date", "Description", "Amount"]
    fontsize = 7 if cols > 3 else 8
    colwidths = [0.9 * inch, 4.8 * inch, 1.0 * inch] if cols == 3 else None
    seq = 0
    seq_ids, per_list = [], {}
    rpl = rows // lists
    for li in range(lists):
        n = rpl if li < lists - 1 else (rows - seq)
        if lists > 1:
            story.append(
                Paragraph(f"<b>Transaction Ledger {li + 1}</b>", styles["Heading2"])
            )
        data = [header]
        ids = []
        for _ in range(n):
            data.append(_row(seq, cols, desc_len, ocr_noise))
            ids.append(f"SEQ{seq:05d}")
            seq_ids.append(f"SEQ{seq:05d}")
            seq += 1
        t = Table(data, repeatRows=1, colWidths=colwidths)
        t.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), fontsize),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 0.15 * inch))
        per_list[f"list{li + 1}"] = ids
    doc.build(story)
    truth = {
        "gen": "bank_statement",
        "rows": rows,
        "cols": cols,
        "lists": lists,
        "desc_len": desc_len,
        "ocr_noise": ocr_noise,
        "fields": dict(FIELDS),
        "seq_ids": seq_ids,
        "per_list": per_list if lists > 1 else None,
        "list_key": "Transactions",
    }
    json.dump(truth, open(out + ".truth.json", "w"))
    try:
        import pypdfium2 as p

        pages = len(p.PdfDocument(out))
    except Exception:
        pages = None
    return {"out": out, "rows": rows, "pages": pages}
