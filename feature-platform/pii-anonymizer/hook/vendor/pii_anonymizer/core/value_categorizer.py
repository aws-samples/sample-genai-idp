# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Value Categorizer Module

Infers PII category from value content + LLM type hint,
provides category-specific normalization and clustering.
Type hint mapping is configurable via config.yaml clustering.type_hint_map.
"""

import re
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================================
# Categories
# ============================================================================


class ValueCategory:
    PERSON_NAME = "person_name"
    ORG_NAME = "org_name"
    ADDRESS = "address"
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    DATE = "date"
    FINANCIAL = "financial"
    ID_GENERIC = "id_generic"
    UNKNOWN = "unknown"


# ============================================================================
# Constants for value-based inference (not configurable — structural patterns)
# ============================================================================

_STREET_SUFFIXES = {
    "st",
    "street",
    "ave",
    "avenue",
    "rd",
    "road",
    "blvd",
    "boulevard",
    "ln",
    "lane",
    "dr",
    "drive",
    "ct",
    "court",
    "pl",
    "place",
    "pkwy",
    "parkway",
    "way",
    "cir",
    "circle",
    "trl",
    "trail",
    "ter",
    "terrace",
}

_ORG_TOKENS = {
    "llc",
    "inc",
    "corp",
    "corporation",
    "ltd",
    "bank",
    "insurance",
    "university",
    "hospital",
    "clinic",
    "medical",
    "center",
    "foundation",
    "associates",
    "group",
    "services",
    "company",
}

_NAME_TITLES = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "md",
    "lcsw",
    "rn",
    "np",
    "do",
    "phd",
    "jr",
    "sr",
    "ii",
    "iii",
}

_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.I)
_PHONE_RE = re.compile(r"^[\+\d\s\(\)\-\.\/]{10,}$")
_SSN_RE = re.compile(r"^\d{3}[-\s]?\d{2}[-\s]?\d{4}$")
_SSN_MASKED_RE = re.compile(r"\*{2,}.*\d{4}")
_DATE_PATTERNS = [
    re.compile(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$"),
    re.compile(r"^\d{4}[/\-]\d{1,2}[/\-]\d{1,2}$"),
    re.compile(r"^[A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4}$", re.I),
    re.compile(r"^\d{1,2}[/\-][A-Z][a-z]{2}[/\-]\d{2,4}$", re.I),
    re.compile(r"^[A-Z][a-z]{2,8}\s+\d{1,2}\s+\d{4}$", re.I),
    re.compile(r"^\d{1,2}\s+[A-Z][a-z]{2,8},?\s+\d{4}$", re.I),
]
_FINANCIAL_RE = re.compile(r"^\$[\d,]+\.?\d*$|^\$[\d,]+$|^[\d,]+\.\d{2}$")
_PO_BOX_RE = re.compile(r"\bP\.?O\.?\s*Box\b", re.I)

_MONTH_MAP = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


# ============================================================================
# Config helpers
# ============================================================================


def _build_type_hint_map(config):
    """Build type hint map from config.yaml clustering.type_hint_map."""
    cfg = (config or {}).get("clustering", {}).get("type_hint_map")
    if not cfg:
        return {}
    result = {}
    for cat, keywords in cfg.items():
        result[cat] = set(keywords) if isinstance(keywords, list) else {keywords}
    return result


def _get_max_cluster_size(config):
    return (config or {}).get("clustering", {}).get("max_cluster_size", 10)


# ============================================================================
# Category Inference — value-based checks
# ============================================================================


def _digits(s):
    return re.sub(r"\D", "", s or "")


def _looks_like_phone(s):
    d = _digits(s)
    return 10 <= len(d) <= 15 and bool(_PHONE_RE.match(s.strip()))


def _looks_like_ssn(s):
    s = s.strip()
    return bool(_SSN_RE.match(s)) or bool(_SSN_MASKED_RE.match(s))


def _looks_like_date(s):
    return any(p.match(s.strip()) for p in _DATE_PATTERNS)


def _looks_like_financial(s):
    return bool(_FINANCIAL_RE.match(s.strip()))


def _looks_like_address(s):
    s = s.strip()
    if _PO_BOX_RE.search(s):
        return True
    words = s.lower().split()
    if words and re.match(r"^\d+$", words[0]):
        return any(w.rstrip(".,") in _STREET_SUFFIXES for w in words[1:])
    return False


def _looks_like_org(s):
    words = set(re.findall(r"[a-zA-Z]+", s.lower()))
    return bool(words & _ORG_TOKENS)


def _looks_like_person_name(s):
    words = s.strip().split()
    if len(words) < 2 or len(words) > 5:
        return False
    alpha_words = [w for w in words if re.match(r"^[A-Za-z.\-']+$", w)]
    if len(alpha_words) < len(words) * 0.8:
        return False
    return all(w[0].isupper() or w.lower() in _NAME_TITLES for w in words if w)


def _category_from_type_hint(llm_type, type_hint_map):
    """Map LLM type hint string to a category using keyword matching."""
    if not llm_type:
        return None
    t = llm_type.lower().strip()
    for cat, keywords in type_hint_map.items():
        if t in keywords:
            return cat
        for kw in keywords:
            if kw in t or t in kw:
                return cat
    return None


def infer_category(value, llm_type_hint="", config=None):
    """
    Infer PII category from value content first, LLM type hint second.

    Args:
        value: The PII text value
        llm_type_hint: The type label from the LLM
        config: Config dict with clustering.type_hint_map from config.yaml

    Returns:
        str: One of ValueCategory constants
    """
    s = (value or "").strip()
    if not s:
        return ValueCategory.UNKNOWN

    # High-precision structural checks first
    if _EMAIL_RE.match(s):
        return ValueCategory.EMAIL
    if _looks_like_ssn(s):
        return ValueCategory.SSN
    if _looks_like_financial(s):
        return ValueCategory.FINANCIAL
    if _looks_like_date(s):
        return ValueCategory.DATE
    if _looks_like_phone(s):
        return ValueCategory.PHONE
    if _looks_like_address(s):
        return ValueCategory.ADDRESS

    # Softer checks
    if _looks_like_org(s):
        return ValueCategory.ORG_NAME
    if _looks_like_person_name(s):
        return ValueCategory.PERSON_NAME

    # Fall back to LLM type hint via config mapping
    type_hint_map = _build_type_hint_map(config)
    hint_cat = _category_from_type_hint(llm_type_hint, type_hint_map)
    if hint_cat:
        return hint_cat

    return ValueCategory.UNKNOWN


# ============================================================================
# Normalization Functions
# ============================================================================


def normalize_phone(value):
    """Strip to last 10 digits."""
    d = _digits(value)
    return d[-10:] if len(d) >= 10 else d


def normalize_ssn(value):
    """Strip to 9 digits. Return None for masked forms."""
    if "*" in value:
        return None
    d = _digits(value)
    return d if len(d) == 9 else None


def normalize_date(value):
    """Parse to ISO YYYY-MM-DD. Return None if unparsable."""
    s = value.strip()

    m = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})$", s)
    if m:
        yr = int(m.group(3))
        yr = yr + 2000 if yr < 50 else yr + 1900
        return f"{yr}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"

    m = re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mon = _MONTH_MAP.get(m.group(1).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"

    m = re.match(r"^(\d{1,2})[/\-]([A-Za-z]{3})[/\-](\d{2,4})$", s)
    if m:
        mon = _MONTH_MAP.get(m.group(2).lower())
        if mon:
            yr = m.group(3)
            if len(yr) == 2:
                yr = int(yr)
                yr = yr + 2000 if yr < 50 else yr + 1900
            return f"{yr}-{mon}-{int(m.group(1)):02d}"

    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$", s)
    if m:
        mon = _MONTH_MAP.get(m.group(1).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"

    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$", s)
    if m:
        mon = _MONTH_MAP.get(m.group(2).lower())
        if mon:
            return f"{m.group(3)}-{mon}-{int(m.group(1)):02d}"

    return None


def normalize_email(value):
    return value.strip().lower()


def normalize_financial(value):
    """Strip to digits + decimal, normalize trailing decimal zeros.
    '$45,230.00' and '$45,230' both → '45230'
    '$0.50' → '0.5'
    """
    s = re.sub(r"[^\d.]", "", value)
    if not s:
        return None
    # Only strip trailing zeros after a decimal point
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else None


def normalize_id(value):
    """Strip non-alphanumeric, lowercase."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


# ============================================================================
# Clustering Functions
# ============================================================================


def _representative(group):
    """Return the longest item's original text as the group representative."""
    return max(group, key=lambda x: len(x["original"]))["original"]


def cluster_by_exact_key(items, key_fn):
    """Group items where key_fn returns the same non-None value."""
    groups = defaultdict(list)
    orphans = []
    for item in items:
        key = key_fn(item["original"])
        if key:
            groups[key].append(item)
        else:
            orphans.append(item)
    result = list(groups.values())
    result.extend([[o] for o in orphans])
    return result


def _name_tokens(text):
    """Extract meaningful name tokens, stripping titles/suffixes."""
    cleaned = re.sub(
        r"\b(" + "|".join(_NAME_TITLES) + r")\b\.?", "", text, flags=re.IGNORECASE
    )
    return set(re.findall(r"[a-zA-Z]{2,}", cleaned.lower()))


def cluster_names(items, max_size):
    """Cluster names: 2+ shared tokens for multi-word, substring match for single-word."""
    groups = []

    multi = [it for it in items if len(it["original"].split()) >= 2]
    single = [it for it in items if len(it["original"].split()) < 2]

    for item in multi:
        tokens = _name_tokens(item["original"])
        if not tokens:
            groups.append([item])
            continue
        merged = False
        for g in groups:
            if len(g) >= max_size:
                continue
            if len(tokens & _name_tokens(_representative(g))) >= 2:
                g.append(item)
                merged = True
                break
        if not merged:
            groups.append([item])

    for item in single:
        word = re.sub(r"[^a-z]", "", item["original"].strip().lower())
        if not word or word in _NAME_TITLES:
            groups.append([item])
            continue
        merged = False
        for g in groups:
            if len(g) >= max_size:
                continue
            if word in _representative(g).lower():
                g.append(item)
                merged = True
                break
        if not merged:
            groups.append([item])

    return groups


def _address_street_tokens(value):
    """Extract street number + street name tokens for comparison."""
    street_part = value.split(",")[0].strip()
    return [
        w.rstrip(".,").lower()
        for w in street_part.split()
        if w.rstrip(".,").lower() not in _STREET_SUFFIXES
    ]


def cluster_addresses(items, max_size):
    """Cluster addresses by street components. Short fragments use substring match."""
    groups = []

    full = [it for it in items if _looks_like_address(it["original"])]
    fragments = [it for it in items if not _looks_like_address(it["original"])]

    for item in full:
        tokens = _address_street_tokens(item["original"])
        merged = False
        for g in groups:
            if len(g) >= max_size:
                continue
            rep_tokens = _address_street_tokens(_representative(g))
            if not tokens or not rep_tokens:
                continue
            # Street number must match
            if tokens[0] != rep_tokens[0]:
                continue
            # Street name similarity
            name_a = set(tokens[1:])
            name_b = set(rep_tokens[1:])
            if not name_a and not name_b:
                g.append(item)
                merged = True
                break
            union = name_a | name_b
            if union and len(name_a & name_b) / len(union) >= 0.5:
                g.append(item)
                merged = True
                break
        if not merged:
            groups.append([item])

    # Fragments: substring match against representative, first match wins
    for item in fragments:
        text = item["original"].strip().lower()
        merged = False
        for g in groups:
            if len(g) >= max_size:
                continue
            rep = _representative(g).lower()
            if text in rep or any(w in rep for w in text.split() if len(w) >= 3):
                g.append(item)
                merged = True
                break
        if not merged:
            groups.append([item])

    return groups


def cluster_orgs(items, max_size):
    """Cluster org names by token set similarity >= 0.9."""

    def _org_tokens(text):
        cleaned = re.sub(r"\b(llc|inc|ltd|corp|corporation)\b\.?", "", text.lower())
        return set(re.findall(r"[a-z]{2,}", cleaned))

    groups = []
    for item in items:
        tokens = _org_tokens(item["original"])
        if not tokens:
            groups.append([item])
            continue
        merged = False
        for g in groups:
            if len(g) >= max_size:
                continue
            rep_tokens = _org_tokens(_representative(g))
            if not rep_tokens:
                continue
            union = tokens | rep_tokens
            if union and len(tokens & rep_tokens) / len(union) >= 0.9:
                g.append(item)
                merged = True
                break
            # Substring for short org names
            if len(tokens) <= 2 or len(rep_tokens) <= 2:
                il = item["original"].strip().lower()
                rl = _representative(g).lower()
                if il in rl or rl in il:
                    g.append(item)
                    merged = True
                    break
        if not merged:
            groups.append([item])

    return groups


def cluster_items_by_category(items, config=None):
    """
    Main entry point: infer category per item, bucket by category,
    cluster within each bucket using category-specific logic.

    Args:
        items: list of dicts with 'original' (value) and '_pii_type' (LLM label)
        config: Config dict from config.yaml

    Returns:
        list of (category, group) tuples where group is a list of items
    """
    max_size = _get_max_cluster_size(config)

    buckets = defaultdict(list)
    for item in items:
        cat = infer_category(item["original"], item.get("_pii_type", ""), config)
        item["_category"] = cat
        buckets[cat].append(item)

    result = []
    for cat, cat_items in buckets.items():
        if cat == ValueCategory.UNKNOWN:
            result.extend((cat, [item]) for item in cat_items)
            continue

        if cat == ValueCategory.PERSON_NAME:
            groups = cluster_names(cat_items, max_size)
        elif cat == ValueCategory.ADDRESS:
            groups = cluster_addresses(cat_items, max_size)
        elif cat == ValueCategory.ORG_NAME:
            groups = cluster_orgs(cat_items, max_size)
        elif cat == ValueCategory.PHONE:
            groups = cluster_by_exact_key(cat_items, normalize_phone)
        elif cat == ValueCategory.SSN:
            groups = cluster_by_exact_key(cat_items, normalize_ssn)
        elif cat == ValueCategory.DATE:
            groups = cluster_by_exact_key(cat_items, normalize_date)
        elif cat == ValueCategory.EMAIL:
            groups = cluster_by_exact_key(cat_items, normalize_email)
        elif cat == ValueCategory.FINANCIAL:
            groups = cluster_by_exact_key(cat_items, normalize_financial)
        elif cat == ValueCategory.ID_GENERIC:
            groups = cluster_by_exact_key(cat_items, normalize_id)
        else:
            groups = [[x] for x in cat_items]

        for g in groups:
            result.append((cat, g))

    return result
