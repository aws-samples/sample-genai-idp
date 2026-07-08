# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Deterministic string-matching helpers for evaluation and OCR grounding.

The primary structured-object evaluation runs entirely through the Stickler
library (see ``service.py``). These small, dependency-free helpers remain in the
codebase because OCR bounding-box grounding
(``idp_common.assessment.ocr_grounding``) needs a normalized Levenshtein-based
fuzzy score to match extracted values against OCR lines.
"""

import re


def strip_punctuation_space(text: str) -> str:
    """
    Strip punctuation and standardize whitespace in text.

    Args:
        text: Input text to process

    Returns:
        Processed text with punctuation removed and whitespace standardized
    """
    if not isinstance(text, str):
        text = str(text)
    # Replace punctuation and extra whitespace
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def fuzz_score(s1: str, s2: str) -> float:
    """
    Calculate a normalized fuzzy match score between two strings.

    Uses Levenshtein edit distance normalized by the longer string length,
    after stripping punctuation and standardizing whitespace/case.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity score between 0.0 and 1.0
    """
    # Normalize inputs
    s1 = strip_punctuation_space(s1)
    s2 = strip_punctuation_space(s2)

    # Perfect match
    if s1 == s2:
        return 1.0

    # Edge cases
    if not s1 or not s2:
        return 0.0

    # Calculate Levenshtein distance (simplified implementation)
    len_s1, len_s2 = len(s1), len(s2)
    d = [[0 for _ in range(len_s2 + 1)] for _ in range(len_s1 + 1)]

    for i in range(len_s1 + 1):
        d[i][0] = i
    for j in range(len_s2 + 1):
        d[0][j] = j

    for i in range(1, len_s1 + 1):
        for j in range(1, len_s2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,  # deletion
                d[i][j - 1] + 1,  # insertion
                d[i - 1][j - 1] + cost,  # substitution
            )

    # Convert to similarity score (1.0 for identical, approaching 0.0 for very different)
    max_len = max(len_s1, len_s2)
    return 1.0 - (d[len_s1][len_s2] / max_len if max_len > 0 else 0.0)
