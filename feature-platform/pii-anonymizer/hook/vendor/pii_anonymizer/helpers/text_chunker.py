# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Token estimation and text chunking at line boundaries."""

import logging

logger = logging.getLogger(__name__)


def estimate_tokens(text, chars_per_token):
    """Estimate token count: len(text) // chars_per_token."""
    return len(text) // chars_per_token if text else 0


def chunk_text_by_lines(text, max_chunk_tokens, chars_per_token):
    """Split text into chunks at line boundaries, each under max_chunk_tokens.

    Returns list of text chunks. Single chunk if text fits.
    """
    if not text or not text.strip():
        return []

    if estimate_tokens(text, chars_per_token) <= max_chunk_tokens:
        return [text]

    max_chars = max_chunk_tokens * chars_per_token
    lines = text.split("\n")
    chunks = []
    current_lines = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_chars and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    logger.info(f"Split text ({len(text)} chars) into {len(chunks)} chunks")
    return chunks
