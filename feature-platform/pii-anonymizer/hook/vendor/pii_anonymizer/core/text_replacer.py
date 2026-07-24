# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared matching utilities for PII replacement across all text-based formats."""

import re
import logging

logger = logging.getLogger(__name__)


def normalize_text(text):
    """Normalize text for comparison: canonicalize colons, collapse whitespace, strip."""
    text = re.sub(r"\s*:\s*", ": ", text)
    return re.sub(r"\s+", " ", text).strip()


def replace_pii_in_text(text, pii_mapping):
    """Replace PII in text using exact match, then normalized match.

    Replaces longest matches first. Uses placeholders to prevent synthetic values
    from being corrupted by later replacements.

    Args:
        text: The text to perform replacements in
        pii_mapping: dict {original: synthetic}

    Returns:
        tuple: (replaced_text, found_originals set, replacement_count, match_types dict)
    """
    found_originals = set()
    match_types = {}
    count = 0
    placeholders = {}

    sorted_mapping = sorted(pii_mapping.items(), key=lambda x: len(x[0]), reverse=True)

    def _make_ph():
        """Generate placeholder using Unicode PUA chars — unmatchable by any PII, XML-safe."""
        nonlocal count
        n = count
        count += 1
        return "\ue000" + "\ue001" * (n + 1) + "\ue000"

    # Pass 1: Exact match — replace with placeholder
    occurrence_counts = {}
    for orig, syn in sorted_mapping:
        if orig in text:
            ph = _make_ph()
            placeholders[ph] = syn
            # For short PII (<=3 chars), use word-boundary to avoid replacing inside longer words
            if len(orig) <= 3:
                pattern = r"\b" + re.escape(orig) + r"\b"
                occurrence_counts[orig] = len(re.findall(pattern, text))
                new_text = re.sub(pattern, ph, text)
                if new_text == text:
                    continue
                text = new_text
            else:
                occurrence_counts[orig] = text.count(orig)
                text = text.replace(orig, ph)
            found_originals.add(orig)
            match_types[orig] = "exact"

    # Pass 2: Normalized match for remaining
    unmatched = [(k, v) for k, v in sorted_mapping if k not in found_originals]
    for orig, syn in unmatched:
        norm_orig = normalize_text(orig)
        if norm_orig and norm_orig in normalize_text(text):
            pattern = re.escape(norm_orig).replace(r"\ ", r"\s+")
            ph = _make_ph()
            placeholders[ph] = syn
            text = re.sub(pattern, ph, text)
            found_originals.add(orig)
            match_types[orig] = "normalized"

    # Final: swap placeholders with actual synthetic values
    for ph, syn in placeholders.items():
        text = text.replace(ph, syn)

    return text, found_originals, count, match_types, occurrence_counts
