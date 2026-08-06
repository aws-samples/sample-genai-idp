# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""ConfBench noise-variant catalog and size tiers — the single source of truth.

Shared by the feature API (GET /variants), the ingest state machine (sharding),
and the UI (which fetches it rather than hardcoding a copy).

Why a static table instead of measuring at request time: producing these numbers
requires walking the HuggingFace tree API over 1,346 files across ~14 paginated
requests (several seconds). The admin needs them BEFORE committing to an ingest,
so the picker must render instantly. The dataset is a published, versioned
research artifact — it does not change under us — and `verify_against_hub()`
below re-derives the table from the live repo so drift is a test failure rather
than a silent lie in the cost estimate.

Figures measured 2026-08-05 against amazon/ConfBench @ main via the HuggingFace
tree API (exact `size` per object, not estimates).

NOTE ON VARIANT COUNT: the dataset has 21 distinct noise variants, not the 18
quoted in the source dataset card and in PR #583. `archetype2`, `archetype9`,
`custom22`, `custom23` and `default` are partial (they cover 20-46 of the 75
source documents rather than all 75), which is why a per-document count
undercounts the distinct pipelines. Totals here are per-FILE and exact.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

# Upstream dataset coordinates.
HF_REPO_ID = "amazon/ConfBench"
HF_PARQUET_PATH = "data/test-00000-of-00001.parquet"
# PDFs live at pdfs/{id} where id is "{doc_hash}__{noise_variant}.pdf".
HF_PDF_DIR = "pdfs"

# Total across all variants — asserted against the sum of VARIANTS below.
TOTAL_FILES = 1346
TOTAL_BYTES = 32713674359

# variant -> (file_count, total_bytes). Ordered smallest-first so a UI that
# renders insertion order naturally leads with the cheap options.
VARIANTS: Dict[str, Tuple[int, int]] = {
    "archetype9": (28, 15025850),
    "original": (75, 21973866),
    "custom23": (24, 104538536),
    "archetype4": (75, 116299196),
    "custom22": (29, 128231799),
    "archetype10": (75, 154637553),
    "archetype2": (20, 320619023),
    "custom21": (75, 375328384),
    "custom16": (75, 402415967),
    "custom19": (75, 406722672),
    "archetype7": (75, 499573438),
    "custom18": (75, 647258402),
    "custom13": (75, 977613206),
    "custom14": (75, 1067150904),
    "default": (46, 1174282048),
    "custom12": (75, 1197643087),
    "custom20": (75, 2044981512),
    "archetype11": (75, 4999306502),
    "archetype3": (75, 5001063593),
    "custom17": (75, 5940690287),
    "custom15": (74, 7118318534),
}

# Human-readable notes shown next to each variant in the picker. `original` is
# the clean source document; everything else is an Augraphy pipeline applied to
# it. We deliberately do NOT invent per-variant descriptions of the specific
# degradations — the upstream dataset card does not document them per variant,
# and guessing would put fiction in the UI. Size is the honest differentiator.
VARIANT_NOTES: Dict[str, str] = {
    "original": "Clean source document — no augmentation",
    "default": "Default Augraphy pipeline (partial: 46 of 75 documents)",
    "archetype2": "Archetype pipeline (partial: 20 of 75 documents)",
    "archetype9": "Archetype pipeline (partial: 28 of 75 documents)",
    "custom22": "Custom pipeline (partial: 29 of 75 documents)",
    "custom23": "Custom pipeline (partial: 24 of 75 documents)",
    "custom15": "Custom pipeline (partial: 74 of 75 documents)",
}


def variant_note(variant: str) -> str:
    """Per-variant note, defaulting to a generic label by family."""
    if variant in VARIANT_NOTES:
        return VARIANT_NOTES[variant]
    if variant.startswith("archetype"):
        return "Named archetype degradation pipeline"
    if variant.startswith("custom"):
        return "Custom noise configuration"
    return "Noise-augmented variant"


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
# Named subsets, so an admin does not have to reason about 21 checkboxes to get
# a sensible starting point. Each tier registers its own test-set id, so several
# can coexist in Test Studio.
#
# `representative` samples across the whole severity range (0.3 MB/doc up to
# 96 MB/doc average) rather than taking the cheapest N — the point of ConfBench
# is measuring accuracy DECAY, which needs spread, not just clean documents.
TIERS: Dict[str, Dict[str, object]] = {
    "clean": {
        "testSetId": "confbench-clean",
        "label": "Clean baseline",
        "summary": "The 75 source invoices with no degradation. Equivalent to "
        "RealKIE-FCC-Verified; useful as the control arm.",
        "variants": ["original"],
    },
    "light": {
        "testSetId": "confbench-light",
        "label": "Light noise",
        "summary": "Clean plus the three lightest degradation pipelines. Enough "
        "to see whether noise moves your numbers at all.",
        "variants": ["original", "archetype9", "archetype4", "archetype10"],
    },
    "representative": {
        "testSetId": "confbench-representative",
        "label": "Representative spread",
        "summary": "One pipeline sampled from each severity band, clean through "
        "heavy. The recommended default for calibration work.",
        "variants": [
            "original",
            "archetype4",
            "archetype10",
            "custom16",
            "archetype7",
            "custom13",
            "custom20",
        ],
    },
    "full": {
        "testSetId": "confbench",
        "label": "Full dataset",
        "summary": "All 21 noise variants — the complete published benchmark.",
        "variants": list(VARIANTS),
    },
}

# Test-set id used when the admin hand-picks variants rather than taking a tier.
CUSTOM_TEST_SET_ID = "confbench-custom"


def tier_variants(tier: str) -> List[str]:
    """Variant list for a named tier. Raises KeyError for an unknown tier."""
    return list(TIERS[tier]["variants"])  # type: ignore[arg-type]


def totals(variants: Iterable[str]) -> Tuple[int, int]:
    """(file_count, byte_count) for a variant selection.

    Unknown variant names raise — the API validates against this so a typo in a
    request body cannot silently ingest less than the caller asked for.
    """
    files = 0
    total = 0
    for v in variants:
        if v not in VARIANTS:
            raise KeyError(
                f"Unknown ConfBench noise variant {v!r}. "
                f"Known variants: {', '.join(sorted(VARIANTS))}"
            )
        f, b = VARIANTS[v]
        files += f
        total += b
    return files, total


def resolve_selection(
    tier: str | None, variants: Iterable[str] | None
) -> Tuple[str, List[str]]:
    """Map an ingest request to (test_set_id, variant_list).

    Exactly one of `tier` / `variants` is honoured, tier taking precedence.
    A hand-picked list that happens to match a tier exactly is treated as that
    tier, so re-selecting the same set twice targets one test set rather than
    accumulating near-duplicates.
    """
    if tier:
        return str(TIERS[tier]["testSetId"]), tier_variants(tier)
    selected = sorted(set(variants or []))
    if not selected:
        raise ValueError("Provide either a tier or a non-empty variants list")
    totals(selected)  # validate names before we accept the request
    for name, spec in TIERS.items():
        if sorted(set(spec["variants"])) == selected:  # type: ignore[arg-type]
            return str(spec["testSetId"]), selected
    return CUSTOM_TEST_SET_ID, selected


def catalog() -> Dict[str, object]:
    """Payload for GET /variants — what the picker renders."""
    return {
        "source": f"huggingface:{HF_REPO_ID}",
        "totalFiles": TOTAL_FILES,
        "totalBytes": TOTAL_BYTES,
        "variants": [
            {
                "name": name,
                "files": files,
                "bytes": nbytes,
                "note": variant_note(name),
            }
            for name, (files, nbytes) in VARIANTS.items()
        ],
        "tiers": [
            {
                "id": tier_id,
                "label": spec["label"],
                "summary": spec["summary"],
                "testSetId": spec["testSetId"],
                "variants": spec["variants"],
                "files": totals(spec["variants"])[0],  # type: ignore[arg-type]
                "bytes": totals(spec["variants"])[1],  # type: ignore[arg-type]
            }
            for tier_id, spec in TIERS.items()
        ],
    }


def verify_against_hub() -> Dict[str, object]:
    """Re-derive the table from the live HuggingFace repo and diff it.

    Used by the unit tests (network-gated) so upstream re-publishing the dataset
    surfaces as a test failure instead of a wrong cost estimate in the UI.
    Returns {"matches": bool, "differences": [...]}.
    """
    import collections
    import json
    import urllib.request

    sizes: Dict[str, int] = {}
    url: str | None = (
        f"https://huggingface.co/api/datasets/{HF_REPO_ID}/tree/main/{HF_PDF_DIR}"
    )
    pages = 0
    while url:
        # Fixed https://huggingface.co API host built from module constants;
        # pagination follows only the Link header that host returns. Test-only
        # helper — never called from Lambda request handling.
        with urllib.request.urlopen(url) as resp:  # nosec B310  # noqa: S310
            link = resp.headers.get("Link", "")
            for entry in json.load(resp):
                if entry.get("type") == "file":
                    sizes[entry["path"].split("/")[-1]] = entry["size"]
        url = link.split("<")[1].split(">")[0] if 'rel="next"' in link else None
        pages += 1
        if pages > 60:  # pagination guard
            break

    observed: Dict[str, List[int]] = collections.defaultdict(lambda: [0, 0])
    for name, size in sizes.items():
        variant = name[:-4].split("__")[-1] if name.endswith(".pdf") else name
        observed[variant][0] += 1
        observed[variant][1] += size

    differences: List[str] = []
    for variant, (files, nbytes) in sorted(VARIANTS.items()):
        if variant not in observed:
            differences.append(f"{variant}: present locally, absent upstream")
            continue
        obs_files, obs_bytes = observed[variant]
        if obs_files != files or obs_bytes != nbytes:
            differences.append(
                f"{variant}: local {files}f/{nbytes}b != upstream {obs_files}f/{obs_bytes}b"
            )
    for variant in sorted(set(observed) - set(VARIANTS)):
        differences.append(f"{variant}: new variant upstream, missing locally")

    return {
        "matches": not differences,
        "differences": differences,
        "observedFiles": len(sizes),
        "observedBytes": sum(sizes.values()),
    }
