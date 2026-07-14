#!/usr/bin/env python3
"""Synthetic flat key/value FORM generator with exact ground truth.

A non-list document type (breadth): N labeled scalar fields, exact known values.
build(fields, out) -> <out>.pdf + <out>.truth.json ({fields: {label: value}})
"""

import json

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

LABELS = [
    "Full Name",
    "Date of Birth",
    "Policy Number",
    "Effective Date",
    "Premium",
    "Deductible",
    "Coverage Limit",
    "Agent Name",
    "Agent ID",
    "Phone",
    "Email",
    "Street Address",
    "City",
    "State",
    "ZIP Code",
    "Country",
    "Account Number",
    "Routing Number",
    "Balance",
    "Interest Rate",
    "Employer",
    "Occupation",
    "Annual Income",
    "Tax ID",
    "Reference Number",
]


def _value(label, i):
    v = {
        "Full Name": "Jane Q Public",
        "Date of Birth": "05/14/1985",
        "Policy Number": f"POL-{100000 + i}",
        "Effective Date": "01/01/2024",
        "Premium": f"${(i + 1) * 137}.50",
        "Deductible": f"${(i + 1) * 100}",
        "Coverage Limit": f"${(i + 1) * 10000}",
        "Agent Name": "John A Broker",
        "Agent ID": f"AG{2000 + i}",
        "Phone": f"555-0{100 + i}",
        "Email": "jane.public@example.com",
        "Street Address": f"{100 + i} Main Street",
        "City": "Anytown",
        "State": "CA",
        "ZIP Code": f"9021{i % 10}",
        "Country": "USA",
        "Account Number": f"{500000000 + i}",
        "Routing Number": "021000021",
        "Balance": f"${(i + 1) * 2500}.00",
        "Interest Rate": f"{2 + i * 0.1:.2f}%",
        "Employer": "AnyCompany Inc",
        "Occupation": "Engineer",
        "Annual Income": f"${80000 + i * 1000}",
        "Tax ID": f"12-345{6000 + i}",
        "Reference Number": f"REF{9000 + i}",
    }
    return v.get(label, f"value-{i}")


def build(fields=25, out="kv.pdf"):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(out, pagesize=letter)
    story = [
        Paragraph("<b>Policy Application Form</b>", styles["Title"]),
        Spacer(1, 0.2 * inch),
    ]
    gt = {}
    for i in range(min(fields, len(LABELS))):
        label = LABELS[i]
        val = _value(label, i)
        gt[label] = val
        story.append(Paragraph(f"<b>{label}:</b> {val}", styles["Normal"]))
        story.append(Spacer(1, 0.08 * inch))
    doc.build(story)
    truth = {
        "gen": "kv_form",
        "fields": gt,
        "seq_ids": [],
        "per_list": None,
        "list_key": None,
    }
    json.dump(truth, open(out + ".truth.json", "w"))
    return {"out": out, "fields": len(gt)}
