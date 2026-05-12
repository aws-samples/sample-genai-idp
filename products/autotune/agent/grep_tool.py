# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""Grep tool for searching the bundled IDP Accelerator source code."""

import os
import re

from strands import tool

IDP_SOURCE_ROOT = "/app/idp-source"

# Skip binary/generated files
SKIP_EXTENSIONS = {".pyc", ".pyo", ".so", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".zip", ".tar", ".gz", ".lock"}
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "cdk.out", ".venv", "dist", "build"}

MAX_RESULTS = 50


@tool
def grep_idp_source_code(pattern: str, path_filter: str = "", case_sensitive: bool = False) -> str:
    """Search the IDP Accelerator source code for a regex pattern.

    Use this to understand how the IDP pipeline works — e.g., how extraction
    prompts are assembled, how configs are validated, how evaluation scoring works.

    Args:
        pattern: Regex pattern to search for (e.g. "def run_extraction", "use_bda", "classification_prompt").
        path_filter: Optional substring to filter file paths (e.g. "lambda", "extraction", "config").
        case_sensitive: Whether the search is case-sensitive. Default: False.

    Returns:
        Matching lines with file paths and line numbers, truncated to 50 results.
    """
    if not os.path.isdir(IDP_SOURCE_ROOT):
        return f"ERROR: IDP source not found at {IDP_SOURCE_ROOT}"

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"ERROR: Invalid regex pattern: {e}"

    results = {}  # filepath -> [(lineno, line)]
    total_matches = 0
    for dirpath, dirnames, filenames in os.walk(IDP_SOURCE_ROOT):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in SKIP_EXTENSIONS:
                continue

            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, IDP_SOURCE_ROOT)

            if path_filter and path_filter not in rel_path:
                continue

            try:
                with open(filepath, "r", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            if filepath not in results:
                                results[filepath] = []
                            results[filepath].append((lineno, line.rstrip()))
                            total_matches += 1
                            if total_matches >= MAX_RESULTS:
                                return _format_results(results) + f"\n\n... truncated at {MAX_RESULTS} results. Narrow your search with path_filter or a more specific pattern."
            except (OSError, UnicodeDecodeError):
                continue

    if not results:
        return f"No matches found for pattern '{pattern}'" + (f" with path_filter '{path_filter}'" if path_filter else "")

    return _format_results(results)


def _format_results(results: dict) -> str:
    """Format results grouped by file to minimize token usage.

    Output format:
        ## /app/idp-source/lib/some/file.py
        :10: matching line content
        :25: another matching line

        ## /app/idp-source/src/lambda/other.py
        :3: matching line here

    Grouping avoids repeating the full file path on every line, saving tokens
    when the agent reads tool results. Absolute paths let the agent pass them
    directly to file_read without path manipulation.
    """
    parts = []
    for filepath, matches in results.items():
        lines = "\n".join(f":{lineno}: {line}" for lineno, line in matches)
        parts.append(f"## {filepath}\n{lines}")
    return "\n\n".join(parts)
