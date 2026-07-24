# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Synthetic PII Generator Module

This module handles the generation of synthetic PII data to replace detected PII.
It provides functions to:
1. Generate synthetic PII using an LLM
2. Create mappings between original and synthetic PII
3. Maintain consistency for related entities (e.g., institution names)
"""

import re
import logging
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import defusedxml.ElementTree as ET  # nosec B405 - safe XML parser

from faker import Faker

# Import functions from pii_detector module
from core.pii_detector import invoke_model_for_text, parse_text_response

# Configure logging
logger = logging.getLogger(__name__)

# Import prompts from centralized prompts module
from core.prompts import (
    SYNTHETIC_GENERATION_SYSTEM_PROMPT,
    SYNTHETIC_GENERATION_TASK_PROMPT,
    BATCH_SYNTHETIC_SYSTEM_PROMPT,
    BATCH_SYNTHETIC_TASK_PROMPT_TEMPLATE,
    BATCH_REPAIR_SYSTEM_PROMPT,
    BATCH_REPAIR_PROMPT_TEMPLATE,
    CATEGORY_INSTRUCTIONS,
)
from helpers.model_config_helper import (
    get_creative_config_from_yaml,
    get_concurrency_config,
)
from validation.model_schemas import validate_synthetic_input, validate_synthetic_output
from helpers.text_chunker import estimate_tokens

# Initialize Faker for fallback synthetic data generation
fake = Faker()

SUPER_GROUPS = {
    "person": ["name", "first_name", "last_name", "middle_name", "email"],
    "address": ["address", "city", "state", "zip"],
}
# Reverse lookup: type → group name
TYPE_TO_GROUP = {}
for _group, _types in SUPER_GROUPS.items():
    for _t in _types:
        TYPE_TO_GROUP[_t] = _group


def generate_synthetic_pii_with_llm(
    pii_type, original_value, model_id, model_provider, bedrock_runtime
):
    """
    Generate synthetic PII data using an LLM.

    Args:
        pii_type: Type of PII to generate
        original_value: Original PII value
        model_id: ID of the model to use
        model_provider: Provider of the model
        bedrock_runtime: Bedrock runtime client

    Returns:
        Synthetic PII value
    """
    # Use centralized prompts
    system_prompt = SYNTHETIC_GENERATION_SYSTEM_PROMPT

    # Format the task prompt with the specific PII type and original value
    task_prompt = SYNTHETIC_GENERATION_TASK_PROMPT.format(
        pii_type=pii_type, original_value=original_value
    )

    try:
        # Configure inference parameters for synthetic generation
        # Higher temperature and top_p for more creative synthetic data
        creative_params = get_creative_config_from_yaml({})

        # Invoke the model with creative parameters
        response = invoke_model_for_text(
            task_prompt,
            system_prompt,
            model_id,
            model_provider,
            bedrock_runtime,
            inference_params=creative_params,
        )

        # Parse the response
        synthetic_value = parse_text_response(response)

        # If the response is empty or too long, fall back to Faker
        if not synthetic_value or len(synthetic_value) > len(original_value) * 2:
            return generate_synthetic_pii_fallback(pii_type, original_value)

        return synthetic_value

    except Exception as e:
        logger.error(f"Error generating synthetic PII with LLM: {str(e)}")
        traceback.print_exc()

        # Fall back to Faker
        return generate_synthetic_pii_fallback(pii_type, original_value)


def generate_synthetic_pii_fallback(pii_type, original_value=None):
    """
    Generate synthetic PII data using Faker (fallback method).

    Args:
        pii_type: Type of PII to generate
        original_value: Original PII value (used for format matching)

    Returns:
        Synthetic PII value
    """
    import random

    pii_type = pii_type.lower()

    # Check for age patterns (e.g., "35 yo M", "42 y/o F", "28 year old male")
    if original_value:
        # Pattern for "XX yo M/F" or "XX y/o M/F" format
        age_pattern1 = re.match(
            r"(\d+)\s+(?:yo|y/o|year[s]?\s+old)\s+([MmFf])", original_value
        )
        age_pattern2 = re.match(r"(\d+)\s+(?:yo|y/o|year[s]?\s+old)", original_value)

        if age_pattern1:
            # Extract age and gender
            age = int(age_pattern1.group(1))
            gender = age_pattern1.group(2).upper()

            # Generate a new random age (within a reasonable range)
            new_age = random.randint(max(1, age - 15), min(99, age + 15))

            # Preserve the exact format of the original
            if "yo" in original_value:
                return original_value.replace(str(age), str(new_age))
            elif "y/o" in original_value:
                return original_value.replace(str(age), str(new_age))
            elif "year old" in original_value:
                return original_value.replace(str(age), str(new_age))
            else:
                return f"{new_age} yo {gender}"

        elif age_pattern2:
            # Extract just the age
            age = int(age_pattern2.group(1))

            # Generate a new random age (within a reasonable range)
            new_age = random.randint(max(1, age - 15), min(99, age + 15))

            # Preserve the exact format of the original
            if "yo" in original_value:
                return original_value.replace(str(age), str(new_age))
            elif "y/o" in original_value:
                return original_value.replace(str(age), str(new_age))
            elif "year old" in original_value:
                return original_value.replace(str(age), str(new_age))
            else:
                return f"{new_age} yo"

    # Generate based on PII type
    if "institution" in pii_type:
        # Generate a fake institution name
        institution_types = [
            "Hospital",
            "Medical Center",
            "Clinic",
            "Health Center",
            "Care Center",
        ]
        institution_prefixes = [
            "Community",
            "Regional",
            "County",
            "City",
            "Memorial",
            "General",
            "University",
        ]

        # If original has a specific pattern, try to maintain it
        if original_value:
            if "hospital" in original_value.lower():
                return f"{fake.city()} Hospital"
            elif "medical center" in original_value.lower():
                return f"{fake.city()} Medical Center"
            elif "clinic" in original_value.lower():
                return f"{fake.last_name()} Clinic"
            elif "health" in original_value.lower():
                return f"{fake.city()} Health Center"

        # Default institution name
        import random

        prefix = random.choice(institution_prefixes)
        type_name = random.choice(institution_types)
        return f"{prefix} {fake.city()} {type_name}"

    elif "name" in pii_type and "institution" not in pii_type:
        if original_value:
            word_count = len(original_value.split())
            # Preserve gender: detect from common female/male indicators
            is_female = any(
                w.lower() in ("ms", "ms.", "mrs", "mrs.", "she", "her")
                for w in original_value.split()
            )
            if not is_female:
                # Check if first real name word is common female
                name_words = [
                    w
                    for w in original_value.split()
                    if w.lower()
                    not in ("dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.")
                ]
                if name_words:
                    is_female = name_words[0] in (
                        "Sarah",
                        "Carol",
                        "Patricia",
                        "Emily",
                        "Lisa",
                        "Jane",
                        "Janet",
                        "Sandra",
                        "Amanda",
                        "Lily",
                    )
            if word_count == 1:
                return fake.first_name_female() if is_female else fake.first_name_male()
            elif word_count == 2:
                fn = fake.first_name_female() if is_female else fake.first_name_male()
                return f"{fn} {fake.last_name()}"
            else:
                fn = fake.first_name_female() if is_female else fake.first_name_male()
                mn = fake.first_name_female() if is_female else fake.first_name_male()
                return f"{fn} {mn} {fake.last_name()}"
        return fake.name()

    elif "ssn" in pii_type or "social" in pii_type:
        new_ssn = fake.ssn()  # generates XXX-XX-XXXX
        if not original_value:
            return new_ssn
        ov = original_value.strip()
        # Masked: ***-**-4321 or last four digits (4321) or ending in 4321
        if "***" in ov or "ending in" in ov.lower() or "last four" in ov.lower():
            last4 = new_ssn.replace("-", "")[-4:]
            if "***" in ov:
                return f"***-**-{last4}"
            elif "ending in" in ov.lower():
                return f"ending in {last4}"
            elif "last four" in ov.lower():
                return f"last four digits ({last4})"
            return f"***-**-{last4}"
        elif "-" in ov:
            return new_ssn
        else:
            return new_ssn.replace("-", "")

    elif "dob" in pii_type or "birth" in pii_type or "date" in pii_type:
        # Check format of original
        if original_value:
            if "-" in original_value:
                return fake.date(pattern="%d-%b-%Y")
            elif "/" in original_value:
                return fake.date(pattern="%m/%d/%Y")
            elif re.search(r"[A-Za-z]+\s+\d{1,2},\s+\d{4}", original_value):
                # Format like "January 15, 2023"
                month = fake.month_name()
                day = random.randint(1, 28)
                year = random.randint(2020, 2025)
                return f"{month} {day}, {year}"
        return fake.date(pattern="%d-%b-%Y")

    elif "address" in pii_type:
        # Generate a clean single-line address matching original word count roughly
        street = f"{fake.building_number()} {fake.street_name()}"
        city = fake.city()
        state = fake.state_abbr()
        zipcode = fake.zipcode()
        if original_value:
            # If original has city/state/zip, include them
            if re.search(r"[A-Z]{2}\s+\d{5}", original_value):
                return f"{street}, {city}, {state} {zipcode}"
            elif "," in original_value:
                return f"{street}, {city}, {state} {zipcode}"
            else:
                return street
        return f"{street}, {city}, {state} {zipcode}"

    elif "phone" in pii_type:
        import random as _rnd

        # Generate 10 random digits and format to match original
        digits = "".join(
            [
                str(_rnd.randint(2, 9)) if i < 3 else str(_rnd.randint(0, 9))
                for i in range(10)
            ]
        )
        area, prefix, line = digits[:3], digits[3:6], digits[6:]
        if not original_value:
            return f"({area}) {prefix}-{line}"
        ov = original_value.strip()
        # Match exact format of original
        if ov.startswith("+1 (") or ov.startswith("+1("):
            return f"+1 ({area}) {prefix}-{line}"
        elif ov.startswith("+1-"):
            return f"+1-{area}-{prefix}-{line}"
        elif ov.startswith("+1"):
            return f"+1{digits}"
        elif "(" in ov and ")" in ov:
            # Check for ext
            ext_match = re.search(r"ext\.?\s*(\d+)", ov, re.IGNORECASE)
            base = f"({area}) {prefix}-{line}"
            if ext_match:
                return f"{base} ext. {_rnd.randint(100, 999)}"
            return base
        elif "/" in ov:
            return f"{area}/{prefix}-{line}"
        elif "." in ov:
            return f"{area}.{prefix}.{line}"
        elif "-" in ov:
            return f"{area}-{prefix}-{line}"
        else:
            return digits

    elif "email" in pii_type:
        return fake.email()

    elif "credit_card" in pii_type or "creditcard" in pii_type:
        # Generate fake credit card with same format
        if original_value:
            # Check if it's a masked format like "xxxx-xxxx-xxxx-1234"
            if "x" in original_value.lower():
                # Keep the same format but replace the visible digits
                visible_digits = re.findall(r"\d+", original_value)
                if visible_digits:
                    for digit in visible_digits:
                        new_digits = "".join(
                            [str(random.randint(0, 9)) for _ in range(len(digit))]
                        )
                        original_value = original_value.replace(digit, new_digits)
                    return original_value

            # Otherwise generate a new number with the same format
            return re.sub(
                r"\d{4}",
                lambda _: "".join([str(random.randint(0, 9)) for _ in range(4)]),
                original_value,
            )

        # Default credit card format
        return fake.credit_card_number()

    elif "credit_score" in pii_type or "creditscore" in pii_type:
        # Generate realistic credit score
        if original_value:
            # Try to extract the score range
            match = re.search(r"(\d{3})[^\d]*(\d{3})", original_value)
            if match:
                return original_value.replace(
                    match.group(0),
                    f"{random.randint(300, 579)}-{random.randint(580, 850)}",
                )

            # Try to extract a single score
            score_match = re.search(r"(\d{3})", original_value)
            if score_match:
                score = int(score_match.group(1))
                # Generate a score in the same range
                if score < 580:
                    new_score = random.randint(300, 579)
                elif score < 670:
                    new_score = random.randint(580, 669)
                elif score < 740:
                    new_score = random.randint(670, 739)
                elif score < 800:
                    new_score = random.randint(740, 799)
                else:
                    new_score = random.randint(800, 850)

                return original_value.replace(score_match.group(0), str(new_score))

        # Default credit score
        return str(random.randint(300, 850))

    elif "account" in pii_type:
        # Generate account number with same format
        if original_value:
            # Preserve format with dashes, spaces, etc.
            pattern = ""
            for char in original_value:
                if char.isdigit():
                    pattern += "D"
                elif char.isalpha():
                    pattern += "A"
                else:
                    pattern += char

            result = ""
            for char in pattern:
                if char == "D":
                    result += str(random.randint(0, 9))
                elif char == "A":
                    result += random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")  # nosec
                else:
                    result += char

            return result

        # Default account number
        return "".join([str(random.randint(0, 9)) for _ in range(10)])

    elif (
        "patient" in pii_type
        or "id" in pii_type
        or "reference" in pii_type
        or "case" in pii_type
    ):
        # Generate format similar to original if available
        if original_value:
            # Extract prefix (alphabetic characters)
            prefix = "".join([c for c in original_value if c.isalpha()])

            # Extract numeric parts
            num_parts = re.findall(r"\d+", original_value)

            # Extract separators
            separators = re.findall(r"[^\w\s]", original_value)

            if prefix and num_parts:
                # Reconstruct with same format but different numbers
                result = prefix
                for i, num in enumerate(num_parts):
                    if i < len(separators):
                        result += separators[i] + "".join(
                            [str(random.randint(0, 9)) for _ in range(len(num))]
                        )
                    else:
                        result += "".join(
                            [str(random.randint(0, 9)) for _ in range(len(num))]
                        )
                return result

            # Simpler case: just replace digits
            return re.sub(
                r"\d+",
                lambda m: "".join(
                    [str(random.randint(0, 9)) for _ in range(len(m.group(0)))]
                ),
                original_value,
            )

        return f"PT-{fake.random_number(digits=5)}"

    elif "inquiry" in pii_type or "tradeline" in pii_type:
        # For inquiry information, often includes dates and company names
        if original_value:
            # Replace dates
            date_pattern = r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
            result = re.sub(
                date_pattern, lambda _: fake.date(pattern="%m/%d/%Y"), original_value
            )

            # Replace company names if present
            company_pattern = (
                r"[A-Z][A-Za-z\s&]+(?:Inc|LLC|Corp|Co|Bank|Finance|Credit)"
            )
            result = re.sub(company_pattern, lambda _: fake.company(), result)

            return result

        # Default inquiry format
        return f"{fake.date(pattern='%m/%d/%Y')} - {fake.company()}"

    elif "tracking" in pii_type or "barcode" in pii_type:
        # Generate tracking number with similar format
        if original_value:
            # Preserve format with dashes, slashes, etc.
            return re.sub(
                r"\d+",
                lambda m: "".join(
                    [str(random.randint(0, 9)) for _ in range(len(m.group(0)))]
                ),
                original_value,
            )
        return f"TK{fake.random_number(digits=8)}"

    elif "medical_record" in pii_type or "record_number" in pii_type:
        # Generate medical record number with similar format
        if original_value:
            return re.sub(
                r"\d+",
                lambda m: "".join(
                    [str(random.randint(0, 9)) for _ in range(len(m.group(0)))]
                ),
                original_value,
            )
        return f"MR{fake.random_number(digits=6)}"

    elif "accession" in pii_type:
        # Generate accession number with similar format
        if original_value:
            return re.sub(
                r"\d+",
                lambda m: "".join(
                    [str(random.randint(0, 9)) for _ in range(len(m.group(0)))]
                ),
                original_value,
            )
        return f"AC{fake.random_number(digits=6)}"

    else:
        # Generic replacement - generate similar format to original
        if original_value:
            # Try to preserve the format of the original value
            return re.sub(
                r"\d+",
                lambda m: "".join(
                    [str(random.randint(0, 9)) for _ in range(len(m.group(0)))]
                ),
                original_value,
            )

        # Last resort: generate a generic ID
        return f"ID{fake.random_number(digits=6)}"


def _post_process_consistency(pii_mapping):
    """Ensure consistency across entity variants in the mapping.
    Anchor = longest variant. All others derive from anchor's synthetic.
    Also normalizes punctuation variants to same synthetic."""
    import re as _re

    def _entity_tokens_pp(text):
        cleaned = _re.sub(
            r"\b(Mr|Mrs|Ms|Dr|MD|LCSW|RN|NP|DO|PhD|Jr|Sr|II|III)\b\.?",
            "",
            text,
            flags=_re.IGNORECASE,
        )
        return set(w.lower() for w in _re.findall(r"[a-zA-Z]{2,}|\d{3,}", cleaned))

    def _should_link(tokens_a, tokens_b):
        shared = tokens_a & tokens_b
        # Also count near-matches (one is prefix of other, >=3 chars)
        for a in tokens_a:
            for b in tokens_b:
                if a != b and len(a) >= 3 and len(b) >= 3:
                    if a.startswith(b) or b.startswith(a):
                        shared = shared | {a}
        if len(shared) >= 2:
            return True
        if len(shared) == 1 and (len(tokens_a) == 1 or len(tokens_b) == 1):
            return True
        return False

    all_items = list(pii_mapping.keys())
    groups = []
    for item in all_items:
        tokens = _entity_tokens_pp(item)
        merged = False
        if not tokens:
            # Handle initials like S.E.J. — match to group by first letters
            if _re.match(r"^[A-Z]\.([A-Z]\.)+[A-Z]?\.?$", item):
                initials = [c.lower() for c in item if c.isalpha()]
                for i, (gt, gitems) in enumerate(groups):
                    if (
                        len(initials) >= 2
                        and sum(
                            1 for ini in initials if any(t.startswith(ini) for t in gt)
                        )
                        >= 2
                    ):
                        groups[i] = (gt, gitems + [item])
                        merged = True
                        break
                if not merged:
                    groups.append((set(), [item]))
            continue
        for i, (gt, gitems) in enumerate(groups):
            if _should_link(gt, tokens):
                groups[i] = (gt | tokens, gitems + [item])
                merged = True
                break
        if not merged:
            groups.append((tokens, [item]))

    changed = True
    while changed:
        changed = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if _should_link(groups[i][0], groups[j][0]):
                    groups[i] = (
                        groups[i][0] | groups[j][0],
                        groups[i][1] + groups[j][1],
                    )
                    groups.pop(j)
                    changed = True
                    break
            if changed:
                break

    fixes = 0
    for tokens, items in groups:
        if len(items) < 2:
            continue
        sorted_items = sorted(items, key=lambda x: len(x.split()), reverse=True)
        anchor_orig = sorted_items[0]
        anchor_synth = pii_mapping[anchor_orig]

        anchor_orig_words = _re.findall(r"[a-zA-Z]+|\d+", anchor_orig)
        anchor_synth_words = _re.findall(r"[a-zA-Z]+|\d+", anchor_synth)
        part_map = {}
        for i, ow in enumerate(anchor_orig_words):
            if i < len(anchor_synth_words) and len(ow) > 1:
                part_map[ow.lower()] = anchor_synth_words[i]

        for ow_lower, sw in list(part_map.items()):
            if ow_lower == sw.lower():
                for item in sorted_items[1:]:
                    if (
                        item.lower() == ow_lower
                        and pii_mapping.get(item, "").lower() != ow_lower
                    ):
                        part_map[ow_lower] = pii_mapping[item]
                        break
                else:
                    for item in sorted_items[1:]:
                        item_clean = _re.sub(
                            r"^(Ms\.|Mr\.|Dr\.|Mrs\.)\s*", "", item
                        ).strip()
                        if (
                            item_clean.lower() == ow_lower
                            and pii_mapping.get(item, "").lower() != ow_lower
                        ):
                            part_map[ow_lower] = _re.sub(
                                r"^(Ms\.|Mr\.|Dr\.|Mrs\.)\s*", "", pii_mapping[item]
                            ).strip()
                            break

        # Fix ALL items including anchor (for case preservation)
        for item in sorted_items:
            new_val = item
            for orig_word in _re.findall(r"[a-zA-Z]+", item):
                key = orig_word.lower()
                replacement = part_map.get(key)
                # Fuzzy: try prefix match if exact not found
                if not replacement:
                    for pk, pv in part_map.items():
                        if len(key) >= 3 and (key.startswith(pk) or pk.startswith(key)):
                            replacement = pv
                            break
                if replacement:
                    if orig_word.isupper():
                        replacement = replacement.upper()
                    elif orig_word[0].isupper():
                        replacement = replacement.capitalize()
                    else:
                        replacement = replacement.lower()
                    new_val = new_val.replace(orig_word, replacement, 1)

            if _re.match(r"^[A-Z]\.[A-Z]\.[A-Z]\.?$", item):
                initials = [c for c in item if c.isalpha()]
                new_initials = []
                for ini in initials:
                    mapped = part_map.get(ini.lower())
                    if not mapped:
                        for ok, sv in part_map.items():
                            if ok.startswith(ini.lower()):
                                mapped = sv
                                break
                    new_initials.append(mapped[0].upper() if mapped else ini)
                new_val = ".".join(new_initials) + "."

            if new_val != item and new_val != pii_mapping.get(item):
                old_synth = pii_mapping.get(item)
                pii_mapping[item] = new_val
                fixes += 1
                logger.debug(
                    f"  Post-process fix: '{item}' | LLM: '{old_synth}' → Fixed: '{new_val}'"
                )

    if fixes:
        logger.info(f"Post-processing: fixed {fixes} inconsistent synthetic values")

    # Phone consistency: group by digits, derive all formats from one synthetic
    def _digits(s):
        d = _re.sub(r"\D", "", s)
        # Strip leading 1 for +1 prefix
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        return d

    phone_groups = {}  # digits → [(orig, synth)]
    for orig, synth in list(pii_mapping.items()):
        od = _digits(orig)
        if len(od) == 10 and od.isdigit():
            phone_groups.setdefault(od, []).append((orig, synth))

    for od, items in phone_groups.items():
        if len(items) < 2:
            continue
        # Pick the (xxx) xxx-xxxx format as anchor if available, else first
        anchor_orig, anchor_synth = items[0]
        for o, s in items:
            if "(" in o and ")" in o and "ext" not in o.lower() and "+" not in o:
                anchor_orig, anchor_synth = o, s
                break
        sd = _digits(anchor_synth)
        if len(sd) < 10:
            continue
        sd = sd[:10]
        a, p, line = sd[:3], sd[3:6], sd[6:]
        for orig, synth in items:
            ov = orig.strip()
            if ov.startswith("+1 (") or ov.startswith("+1("):
                new = f"+1 ({a}) {p}-{line}"
            elif ov.startswith("+1-"):
                new = f"+1-{a}-{p}-{line}"
            elif ov.startswith("+1"):
                new = f"+1{sd}"
            elif "(" in ov and ")" in ov:
                ext_m = _re.search(r"(ext\.?\s*)(\d+)", ov, _re.IGNORECASE)
                pager_m = _re.search(r"(Pager:\s*)", ov, _re.IGNORECASE)
                base = f"({a}) {p}-{line}"
                if pager_m:
                    base = f"{pager_m.group(1)}{base}"
                if ext_m:
                    base = f"{base} {ext_m.group(1)}{ext_m.group(2)}"
                if "(pager)" in ov:
                    base = f"{base} (pager)"
                new = base
            elif "/" in ov:
                new = f"{a}/{p}-{line}"
            elif "." in ov:
                new = f"{a}.{p}.{line}"
            elif "-" in ov:
                new = f"{a}-{p}-{line}"
            else:
                new = sd
            if new != pii_mapping.get(orig):
                pii_mapping[orig] = new

    # SSN partial consistency: ***-**-XXXX, ending in XXXX, last four digits
    ssn_groups = {}  # last4 → [(orig, synth)]
    for orig, synth in list(pii_mapping.items()):
        m = _re.search(r"(\d{3})-(\d{2})-(\d{4})$", orig.strip())
        if m:
            last4 = m.group(3)
            ssn_groups.setdefault(last4, []).append((orig, synth))
        elif _re.match(r"\*\*\*-\*\*-(\d{4})", orig.strip()):
            last4 = _re.match(r"\*\*\*-\*\*-(\d{4})", orig.strip()).group(1)
            ssn_groups.setdefault(last4, []).append((orig, synth))
        elif _re.search(r"ending in (\d{4})", orig, _re.IGNORECASE):
            last4 = _re.search(r"ending in (\d{4})", orig, _re.IGNORECASE).group(1)
            ssn_groups.setdefault(last4, []).append((orig, synth))
        elif _re.search(r"last four digits \((\d{4})\)", orig, _re.IGNORECASE):
            last4 = _re.search(
                r"last four digits \((\d{4})\)", orig, _re.IGNORECASE
            ).group(1)
            ssn_groups.setdefault(last4, []).append((orig, synth))
        elif _re.search(r"XX-(\d{4})", orig):
            last4 = _re.search(r"XX-(\d{4})", orig).group(1)
            ssn_groups.setdefault(last4, []).append((orig, synth))

    for last4, items in ssn_groups.items():
        if len(items) < 2:
            continue
        # Find the full SSN synthetic as anchor
        anchor_synth = None
        for o, s in items:
            if _re.match(r"\d{3}-\d{2}-\d{4}$", o.strip()):
                anchor_synth = s
                break
        if not anchor_synth:
            continue
        am = _re.search(r"(\d{3})-(\d{2})-(\d{4})", anchor_synth)
        if not am:
            continue
        new_last4 = am.group(3)
        for orig, synth in items:
            ov = orig.strip()
            if _re.match(r"\*\*\*-\*\*-\d{4}", ov):
                pii_mapping[orig] = f"***-**-{new_last4}"
            elif "ending in" in ov.lower():
                pii_mapping[orig] = f"ending in {new_last4}"
            elif "last four digits" in ov.lower():
                pii_mapping[orig] = f"last four digits ({new_last4})"
            elif _re.match(r"Issuer SSN ref:", ov):
                pii_mapping[orig] = f"Issuer SSN ref: XXX,XX-{new_last4}"

    def _norm(s):
        return _re.sub(r"[,.\s]+", " ", s).strip().lower()

    norm_map = {}
    for orig, synth in list(pii_mapping.items()):
        nk = _norm(orig)
        if nk not in norm_map:
            norm_map[nk] = (orig, synth)
        else:
            # Only normalize if the originals differ by more than just case
            prev_orig, prev_synth = norm_map[nk]
            if orig.lower() == prev_orig.lower():
                # Same text, different case — keep each item's own synthetic (case-corrected)
                pass
            else:
                pii_mapping[orig] = prev_synth


def create_pii_mapping(
    pii_detections, model_id, model_provider, bedrock_runtime, use_llm=True
):
    """
    Create a mapping between original PII values and synthetic replacements.
    Ensures consistency across multiple instances of the same PII and related entities.

    Args:
        pii_detections: List of PII detections
        model_id: ID of the model to use
        model_provider: Provider of the model
        bedrock_runtime: Bedrock runtime client
        use_llm: Whether to use the LLM for synthetic PII generation

    Returns:
        Dictionary mapping original PII values to synthetic replacements
    """
    pii_mapping = {}

    # Identify related entities (particularly for institution names)
    entity_mapping, entity_groups = identify_related_entities(pii_detections)

    # Dictionary to store synthetic values for base entities
    base_entity_synthetics = {}

    # First pass: generate synthetic values for base entities
    for base_entity, related_entities in entity_groups.items():
        # Generate a synthetic value for the base entity
        if use_llm:
            synthetic = generate_synthetic_pii_with_llm(
                "institution_name",
                base_entity,
                model_id,
                model_provider,
                bedrock_runtime,
            )
        else:
            synthetic = generate_synthetic_pii_fallback("institution_name", base_entity)

        base_entity_synthetics[base_entity] = synthetic

    # Process each detection
    for detection in pii_detections:
        if "content" in detection and "type" in detection:
            original = detection["content"]
            pii_type = detection["type"]

            # Check if this is an institution name that belongs to a group
            if pii_type.lower() == "institution_name" and original in entity_mapping:
                base_entity = entity_mapping[original]

                if base_entity in base_entity_synthetics:
                    # Use the base entity's synthetic value as a starting point
                    base_synthetic = base_entity_synthetics[base_entity]

                    if original == base_entity:
                        # If this is the base entity itself, use its synthetic value directly
                        pii_mapping[original] = base_synthetic
                    else:
                        # For related entities, replace the base part with the synthetic base
                        # while preserving the structure (e.g., department information)

                        # Handle "of" constructs
                        of_match = re.match(
                            r"^(.*?)\s+of\s+(.*?)$", original, re.IGNORECASE
                        )
                        if of_match:
                            # Replace the base part while keeping the location part
                            location_part = of_match.group(2)
                            synthetic_of_match = re.match(
                                r"^(.*?)(?:\s+of\s+(.*?))?$",
                                base_synthetic,
                                re.IGNORECASE,
                            )

                            if synthetic_of_match:
                                synthetic_base = synthetic_of_match.group(1)
                                pii_mapping[original] = (
                                    f"{synthetic_base} of {location_part}"
                                )
                            else:
                                pii_mapping[original] = (
                                    f"{base_synthetic} of {location_part}"
                                )

                        # Handle department information (after comma)
                        elif "," in original:
                            base_part = original.split(",")[0].strip()
                            dept_part = original[
                                len(base_part) :
                            ].strip()  # Get everything after the base part

                            # If the synthetic base also has a comma, use only the part before it
                            if "," in base_synthetic:
                                synthetic_base = base_synthetic.split(",")[0].strip()
                            else:
                                synthetic_base = base_synthetic

                            pii_mapping[original] = f"{synthetic_base}{dept_part}"

                        else:
                            # Default case: just use the synthetic base
                            pii_mapping[original] = base_synthetic

                continue  # Skip the standard processing below

            # Standard processing for non-grouped entities
            if original not in pii_mapping:
                if use_llm:
                    synthetic = generate_synthetic_pii_with_llm(
                        pii_type, original, model_id, model_provider, bedrock_runtime
                    )
                else:
                    synthetic = generate_synthetic_pii_fallback(pii_type, original)

                pii_mapping[original] = synthetic

    # Verify that no synthetic values match their original values
    verification_result = verify_synthetic_values(pii_mapping)

    # If there are issues, fix them
    if not verification_result["verified"]:
        logger.warning(
            f"Verification: fixed {len(verification_result['issues'])} values that matched original (LLM failure)"
        )

        for issue in verification_result["issues"]:
            original = issue["original"]
            pii_type = None

            # Find the PII type for this original value
            for detection in pii_detections:
                if "content" in detection and detection["content"] == original:
                    pii_type = detection["type"]
                    break

            if pii_type:
                # Generate a new synthetic value using the fallback method
                # to avoid calling the LLM again
                pii_mapping[original] = generate_synthetic_pii_fallback(
                    pii_type, original
                )

                # Ensure the new value is different
                attempts = 0
                while pii_mapping[original] == original and attempts < 5:
                    pii_mapping[original] = generate_synthetic_pii_fallback(
                        pii_type, original
                    )
                    attempts += 1

    # Post-processing disabled — it was mixing original+synthetic data
    # Pre-LLM clustering (value_categorizer.py) handles consistency correctly
    # _post_process_consistency(pii_mapping)

    return pii_mapping


def identify_related_entities(pii_detections):
    """

    Identify and group related entities in PII detections, particularly for institution names.

    Args:
        pii_detections: List of PII detections

    Returns:
        Dictionary mapping original values to their base entity identifiers
    """
    # Dictionary to store entity groups
    entity_groups = {}

    # Dictionary to map original values to their base entity
    entity_mapping = {}

    # First, extract all institution names
    institution_names = []
    for detection in pii_detections:
        if "content" in detection and "type" in detection:
            if detection["type"].lower() == "institution_name":
                institution_names.append(detection["content"])

    # Process each institution name to identify base entities
    for name in institution_names:
        # Extract the base entity name (typically before commas, "of", or department references)
        base_entity = name

        # Remove department information
        if "," in base_entity:
            base_entity = base_entity.split(",")[0].strip()

        # Handle "of" constructs (e.g., "Hospital of Washington")
        of_match = re.match(r"^(.*?)\s+of\s+", base_entity, re.IGNORECASE)
        if of_match:
            base_entity = of_match.group(1).strip()

        # Store the mapping
        entity_mapping[name] = base_entity

        # Group by base entity
        if base_entity not in entity_groups:
            entity_groups[base_entity] = []
        entity_groups[base_entity].append(name)

    return entity_mapping, entity_groups


def verify_synthetic_values(pii_mapping):
    """
    Verify that synthetic values don't match their original values.

    Args:
        pii_mapping: Dictionary mapping original PII values to synthetic replacements

    Returns:
        Dictionary with verification results and any issues found
    """
    issues = []

    for original, synthetic in pii_mapping.items():
        # Check for exact matches
        if original == synthetic:
            issues.append(
                {"original": original, "synthetic": synthetic, "issue": "exact_match"}
            )

        # Check for number-only values (e.g., dates, IDs) where only format changed
        elif re.sub(r"[^\d]", "", original) == re.sub(r"[^\d]", "", synthetic):
            # If both are purely numeric after stripping non-digits
            if (
                re.sub(r"[^\d]", "", original) == original
                and re.sub(r"[^\d]", "", synthetic) == synthetic
            ):
                issues.append(
                    {
                        "original": original,
                        "synthetic": synthetic,
                        "issue": "same_digits",
                    }
                )

    return {"verified": len(issues) == 0, "issues": issues}


def parse_synthetic_data(xml_string):
    """
    Parse the XML output from Claude and create a dictionary mapping
    original values to their synthetic replacements.

    Args:
        xml_string: String containing the XML output from Claude

    Returns:
        dict: A dictionary mapping original values to synthetic values

    Raises:
        Exception: If XML parsing fails
    """
    # Create a dictionary to store the mappings
    mappings = {}

    try:
        # Validate that the string looks like XML before parsing
        # Handle markdown-wrapped XML (```xml ... ```) anywhere in response
        xml_content = xml_string.strip()
        if "```xml" in xml_content:
            start_idx = xml_content.index("```xml")
            block = xml_content[start_idx:]
            lines = block.split("\n")
            xml_lines = []
            in_xml = False
            for line in lines:
                if line.strip() == "```xml":
                    in_xml = True
                    continue
                elif line.strip() == "```" and in_xml:
                    break
                elif in_xml:
                    xml_lines.append(line)
            xml_content = "\n".join(xml_lines).strip()
            logger.debug("Extracted XML from markdown code block")
        elif "<synthetic_data>" in xml_content:
            start = xml_content.index("<synthetic_data>")
            end = (
                xml_content.index("</synthetic_data>") + len("</synthetic_data>")
                if "</synthetic_data>" in xml_content
                else len(xml_content)
            )
            xml_content = xml_content[start:end].strip()
            logger.debug("Extracted XML by locating <synthetic_data> tag")

        if not xml_content or not xml_content.startswith("<"):
            logger.error("LLM Response Format Issue - Expected XML but got:")
            logger.error(
                f"Response length: {len(xml_string) if xml_string else 0} characters"
            )
            raise ValueError("Response does not appear to be XML")

        # Use the cleaned XML content for further processing
        xml_string = xml_content

        # Check if XML is complete (has closing root tag per the prompt format)
        if "</synthetic_data>" not in xml_string:
            logger.warning(
                "XML response appears to be truncated (missing </synthetic_data> closing tag)"
            )
            logger.error("Incomplete XML Response:")
            logger.error(f"Response length: {len(xml_string)} characters")
            raise ValueError("Incomplete XML response - likely hit token limit")

        # Escape XML-special characters in text content (& is common in institution names)
        xml_string = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;)", "&amp;", xml_string)

        # Parse the XML
        root = ET.fromstring(xml_string)

        # Process each section (institution_names, dates_dob, dates_other, ids, names, etc.)
        for section in root:
            for item in section:
                original_elem = item.find("original")
                synthetic_elem = item.find("synthetic")

                if original_elem is not None and synthetic_elem is not None:
                    original = original_elem.text
                    synthetic = synthetic_elem.text
                    if original and synthetic:
                        mappings[original] = synthetic

        logger.debug(f"Successfully parsed {len(mappings)} synthetic values from XML")
        return mappings

    except ET.ParseError as e:
        logger.error(f"XML parsing failed: {str(e)}")
        logger.error(f"Response length: {len(xml_string) if xml_string else 0} chars")
        raise
    except Exception as e:
        logger.error(f"Error processing synthetic data: {str(e)}")
        logger.error(f"Response length: {len(xml_string) if xml_string else 0} chars")
        raise


def _build_batch_prompt(pii_by_type, config=None):
    """
    Build the batch synthetic generation prompt using category-aware clustering.

    Uses value_categorizer to infer categories from value content + LLM type hints,
    then clusters within each category using category-specific logic.
    All prompt text comes from prompts.py — this function only builds entity data.

    Args:
        pii_by_type: dict {pii_type: [{"original": str, "index": int, ...}, ...]}
        config: Optional config dict from config.yaml

    Returns:
        str: Complete task prompt ready to send to the LLM
    """
    from core.value_categorizer import cluster_items_by_category

    # Collect ALL items with their LLM type label
    all_items = []
    for pii_type, items in pii_by_type.items():
        for item in items:
            item["_pii_type"] = item.get("_original_type", pii_type)
            all_items.append(item)

    if not all_items:
        return BATCH_SYNTHETIC_TASK_PROMPT_TEMPLATE.format(
            values_section="", replacements_section=""
        )

    # Cluster using category-aware logic
    entity_groups = cluster_items_by_category(all_items, config)

    # Build values section (only data, no instruction text)
    values = ""
    for idx, (cat, group) in enumerate(entity_groups):
        cat_label = cat.upper().replace("_", " ")
        instruction = CATEGORY_INSTRUCTIONS.get(cat, "")
        multi = len(group) > 1

        values += f"\n  Entity {idx + 1} [{cat_label}]"
        if multi:
            values += " (SAME entity):\n"
            if instruction:
                values += f"    >> {instruction}\n"
        else:
            values += ":\n"
            if cat == "address" and instruction:
                values += f"    >> {instruction}\n"

        for item in group:
            values += (
                f"    {item['index'] + 1}. [{item['_pii_type']}] {item['original']}\n"
            )

    # Build replacements section (only data)
    replacements = ""
    for idx, (cat, group) in enumerate(entity_groups):
        cat_label = cat.upper().replace("_", " ")
        replacements += f"\n  Entity {idx + 1} [{cat_label}]"
        if len(group) > 1:
            replacements += " (SAME synthetic base for all):\n"
        else:
            replacements += ":\n"
        for item in group:
            replacements += (
                f"    {item['index'] + 1}. [{item['_pii_type']}] '{item['original']}'\n"
            )

    return BATCH_SYNTHETIC_TASK_PROMPT_TEMPLATE.format(
        values_section=values, replacements_section=replacements
    )


def _split_into_batches(pii_by_type, max_batch_tokens, chars_per_token, config=None):
    """
    Split pii_by_type into batches that fit under max_batch_tokens.

    Preserves type group boundaries — all items of a given PII type stay together
    in the same batch. This ensures the LLM sees full context for each type
    (e.g., all dates together for chronological consistency).

    If all type groups fit under max_batch_tokens, returns a single-element list
    (same as no batching — one LLM call).

    Measures the actual built prompt size (instructions + items + formatting)
    rather than estimating from raw values alone. Also accounts for output tokens
    since the LLM response repeats each value in XML format.

    Args:
        pii_by_type: dict {pii_type: [{"original": str, "index": int, ...}, ...]}
        max_batch_tokens: from config concurrency.max_synthetic_batch_tokens
        chars_per_token: from config concurrency.chars_per_token

    Returns:
        list[dict]: List of pii_by_type dicts, one per batch.
                    Single-element list when everything fits in one batch.
    """
    # Check if everything fits in one batch
    # Use 3x: prompt has each value twice (values + replacements sections)
    # plus LLM output repeats all values again in XML with tags
    full_prompt = _build_batch_prompt(pii_by_type, config)
    prompt_tokens = estimate_tokens(full_prompt, chars_per_token)

    if prompt_tokens * 3 <= max_batch_tokens:
        logger.info(
            f"Step 2 - Synthetic Generation: All {len(pii_by_type)} PII categories fit in 1 LLM call ({prompt_tokens} tokens)"
        )
        return [pii_by_type]

    # Need to split — add groups until batch exceeds limit
    batches = []
    current_batch = {}

    for pii_type, items in pii_by_type.items():
        trial_batch = {**current_batch, pii_type: items}
        trial_prompt = _build_batch_prompt(trial_batch, config)
        trial_tokens = estimate_tokens(trial_prompt, chars_per_token) * 3

        if trial_tokens > max_batch_tokens and current_batch:
            batches.append(current_batch)
            current_batch = {pii_type: items}
        else:
            current_batch = trial_batch

    if current_batch:
        batches.append(current_batch)

    logger.info(
        f"Step 2 - Synthetic Generation: {len(pii_by_type)} PII categories split into {len(batches)} LLM calls (exceeds single-call token limit)"
    )
    return batches


def _process_single_batch(
    batch,
    system_prompt,
    model_id,
    model_provider,
    bedrock_runtime,
    creative_params,
    token_tracker=None,
    config=None,
):
    """
    Process a single batch: build prompt, call LLM, parse XML response.

    Used by batch_generate_synthetic_pii as the unit of work submitted to
    ThreadPoolExecutor. When max_workers=1, batches run sequentially.
    When max_workers>1, batches run in parallel.

    Args:
        batch: dict {pii_type: [{"original": str, "index": int, ...}, ...]}
        system_prompt: System prompt for synthetic generation
        model_id: Bedrock model ID
        model_provider: "amazon" or "anthropic"
        bedrock_runtime: Bedrock runtime client
        creative_params: Inference params from get_creative_config_from_yaml
        config: Optional config dict from config.yaml

    Returns:
        dict: Mapping {original: synthetic} for items in this batch.
              Empty dict if LLM call or XML parsing fails.
    """
    task_prompt = _build_batch_prompt(batch, config)
    response = invoke_model_for_text(
        task_prompt,
        system_prompt,
        model_id,
        model_provider,
        bedrock_runtime,
        inference_params=creative_params,
        token_tracker=token_tracker,
        config=config,
        step="synthetic",
    )
    response_text = parse_text_response(response)
    return parse_synthetic_data(response_text)


def _repair_with_llm(
    pii_mapping,
    items_to_fix,
    type_lookup,
    model_id,
    model_provider,
    bedrock_runtime,
    creative_params,
    token_tracker=None,
    config=None,
):
    """LLM calls to fix missed + inconsistent + collision items, grouped by super-group."""
    if not items_to_fix:
        return {}

    # Validate input: each item must have original + type
    valid_items = [i for i in items_to_fix if i.get("original") and i.get("type")]
    if len(valid_items) != len(items_to_fix):
        logger.warning(
            f"Repair input validation: {len(items_to_fix) - len(valid_items)} items skipped (missing original or type)"
        )
    if not valid_items:
        return {}

    # Group items to fix by super-group
    groups = {}
    for item in valid_items:
        group = TYPE_TO_GROUP.get(item["type"], item["type"])
        groups.setdefault(group, []).append(item)

    # Build reverse: which types belong to each group
    group_types = {}
    for group_name, member_types in SUPER_GROUPS.items():
        group_types[group_name] = set(member_types)

    all_repairs = {}
    existing_synthetics = set(pii_mapping.values())

    for group, fix_items in groups.items():
        # Filter existing mappings to only this group's types
        relevant_types = group_types.get(group, {group})
        existing_lines = []
        for orig, synth in sorted(pii_mapping.items()):
            if type_lookup.get(orig) in relevant_types:
                existing_lines.append(f"  [{orig}] → [{synth}]")

        fix_lines = []
        template_lines = []
        for i, item in enumerate(fix_items, 1):
            fix_lines.append(f'  {i}. [{item["type"]}] "{item["original"]}"')
            template_lines.append(
                f"  <item>\n    <original>{item['original']}</original>\n    <synthetic>REPLACE_ME</synthetic>\n  </item>"
            )

        task_prompt = BATCH_REPAIR_PROMPT_TEMPLATE.format(
            existing_mappings="\n".join(existing_lines) or "  (none)",
            items_to_fix="\n".join(fix_lines),
            response_template="\n".join(template_lines),
        )

        response = invoke_model_for_text(
            task_prompt,
            BATCH_REPAIR_SYSTEM_PROMPT,
            model_id,
            model_provider,
            bedrock_runtime,
            inference_params=creative_params,
            token_tracker=token_tracker,
            config=config,
            step="synthetic",
        )
        try:
            repair_mapping = parse_synthetic_data(parse_text_response(response))
        except Exception as e:
            logger.warning(f"Repair [{group}]: parse failed ({e}), Faker will fill")
            repair_mapping = {}

        # Validate output: unique, not original, not reusing existing synthetics
        valid_count = 0
        for item in fix_items:
            orig = item["original"]
            synth = repair_mapping.get(orig)
            if not synth:
                logger.warning(f"Repair [{group}]: 1 item not in LLM response")
            elif synth == orig:
                logger.warning(f"Repair [{group}]: 1 item returned original back")
            elif synth in existing_synthetics:
                logger.warning(f"Repair [{group}]: 1 item reused existing synthetic")
            else:
                all_repairs[orig] = synth
                existing_synthetics.add(synth)
                valid_count += 1

        logger.info(
            f"Repair [{group}]: {len(fix_items)} items, {len(repair_mapping)} returned, {valid_count} valid"
        )

    return all_repairs


def batch_generate_synthetic_pii(
    pii_detections,
    model_id,
    model_provider,
    bedrock_runtime,
    config=None,
    token_tracker=None,
):
    """
    Generate synthetic PII for a batch of detections using LLM calls with
    dynamic chunking to prevent XML truncation.

    When all PII fits under max_synthetic_batch_tokens, makes a single LLM call
    (same behavior as before). When PII exceeds the limit, splits into multiple
    batches preserving type group boundaries, calls LLM per batch, and merges
    results into a unified mapping.

    Batches run concurrently via ThreadPoolExecutor using max_workers from config.
    Setting max_workers=1 in config.yaml runs batches sequentially (no parallelism).

    Ensures consistency across related entities (especially institution names)
    and maintains logical relationships between PII types (dates, IDs, etc.).

    Input validation filters out detections missing content or type.
    Output validation logs any originals that didn't get a synthetic mapping.
    Faker fallback fills in any items the LLM missed or failed to generate.

    Args:
        pii_detections: List of dicts with {content, type, confidence} from Step 1 detection
        model_id: ID of the Bedrock model to use
        model_provider: Provider of the model ("amazon" or "anthropic")
        bedrock_runtime: Bedrock runtime client
        config: Full config dict (optional). Used to read concurrency and creative params.
                When None, uses defaults from get_concurrency_config({}) and
                get_creative_config_from_yaml({}).

    Returns:
        dict: Mapping of {original_value: synthetic_value} for all detected PII
    """
    if config is None:
        config = {}

    # Blackout mode: skip LLM, return [REDACTED] for all items
    redaction_mode = config.get("redaction", {}).get("mode", "synthetic")
    if redaction_mode == "blackout":
        logger.info("Blackout mode — skipping synthetic generation")
        return {
            d.get("content", ""): "[REDACTED]"
            for d in pii_detections
            if d.get("content")
        }

    # Validate input — filter out detections missing content or type
    pii_detections = validate_synthetic_input(pii_detections)
    if not pii_detections:
        return {}

    system_prompt = BATCH_SYNTHETIC_SYSTEM_PROMPT
    cc = get_concurrency_config(config)
    creative_params = get_creative_config_from_yaml(config)

    # Identify related entities (particularly for institution names)
    entity_mapping, entity_groups = identify_related_entities(pii_detections)

    # Group PII by type, handling related entities specially and deduplicating
    pii_by_type = {}
    processed_entities = set()

    for detection in pii_detections:
        pii_type = detection["type"]
        original = detection["content"]

        # Special handling for institution names — only include base entity
        if pii_type.lower() == "institution_name" and original in entity_mapping:
            base_entity = entity_mapping[original]

            if base_entity not in processed_entities:
                processed_entities.add(base_entity)

                if pii_type not in pii_by_type:
                    pii_by_type[pii_type] = []

                pii_by_type[pii_type].append(
                    {
                        "original": base_entity,
                        "index": len(pii_by_type[pii_type]),
                        "is_base_entity": True,
                        "related_entities": entity_groups.get(base_entity, []),
                    }
                )

            # Skip adding individually — handled through base entity
            continue

        # Standard handling for other PII types — deduplicate within type
        if pii_type not in pii_by_type:
            pii_by_type[pii_type] = []

        if original not in [item["original"] for item in pii_by_type[pii_type]]:
            pii_by_type[pii_type].append(
                {
                    "original": original,
                    "index": len(pii_by_type[pii_type]),
                    "is_base_entity": False,
                }
            )

    # Log duplicate statistics
    unique_values = {d["content"] for d in pii_detections}
    duplicates = len(pii_detections) - len(unique_values)

    logger.info(
        f"Dedup: {len(pii_detections)} detections, {len(unique_values)} unique, {duplicates} duplicates"
    )

    # Merge related types into super-groups for cross-type consistency
    # Items keep their original type labels — super-group just ensures they're in the same batch
    merged_pii_by_type = {}
    merged_types = set()
    for group_name, member_types in SUPER_GROUPS.items():
        group_items = []
        for mt in member_types:
            if mt in pii_by_type:
                # Keep original type label on each item
                for item in pii_by_type[mt]:
                    item["_original_type"] = mt
                group_items.extend(pii_by_type[mt])
                merged_types.add(mt)
        if group_items:
            for i, item in enumerate(group_items):
                item["index"] = i
            merged_pii_by_type[group_name] = group_items
            logger.debug(
                f"Super-group '{group_name}': {len(group_items)} items merged from {[mt for mt in member_types if mt in pii_by_type]}"
            )

    # Add remaining types that weren't merged
    for pii_type, items in pii_by_type.items():
        if pii_type not in merged_types:
            merged_pii_by_type[pii_type] = items

    pii_by_type = merged_pii_by_type

    # Split into batches — category-aware clustering is handled inside _build_batch_prompt
    batches = _split_into_batches(
        pii_by_type, cc["max_synthetic_batch_tokens"], cc["chars_per_token"], config
    )

    # Process batches concurrently using max_workers from config
    # max_workers=1 runs sequentially, max_workers>1 runs in parallel
    pii_mapping = {}
    llm_count = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=cc["max_workers"]) as executor:
        futures = {}
        for batch_idx, batch in enumerate(batches):
            items = sum(len(v) for v in batch.values())
            logger.info(
                f"Batch {batch_idx + 1}/{len(batches)}: submitting {len(batch)} type groups, {items} items"
            )
            future = executor.submit(
                _process_single_batch,
                batch,
                system_prompt,
                model_id,
                model_provider,
                bedrock_runtime,
                creative_params,
                token_tracker,
                config,
            )
            futures[future] = batch_idx

        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_mapping = future.result()
                with lock:
                    pii_mapping.update(batch_mapping)
                    llm_count += len(batch_mapping)
                logger.info(
                    f"Batch {batch_idx + 1}/{len(batches)} complete: {len(batch_mapping)} mappings generated"
                )
            except Exception as e:
                logger.warning(
                    f"Batch {batch_idx + 1}/{len(batches)} failed: {e}. "
                    "Faker fallback will fill missing mappings."
                )

    # Collect items needing repair: missed + inconsistent (synthetic==original) + collisions
    items_to_fix = []
    type_lookup = {d["content"]: d["type"] for d in pii_detections}

    # Missed: LLM didn't return a mapping
    for detection in pii_detections:
        original = detection["content"]
        if original not in pii_mapping:
            items_to_fix.append(
                {"original": original, "type": detection["type"], "reason": "missed"}
            )

    # Inconsistent: synthetic == original
    for orig, synth in list(pii_mapping.items()):
        if orig == synth and orig in type_lookup:
            items_to_fix.append(
                {"original": orig, "type": type_lookup[orig], "reason": "inconsistent"}
            )
            del pii_mapping[orig]

    # Collisions: multiple originals → same synthetic
    from collections import Counter

    synth_counts = Counter(pii_mapping.values())
    for synth_val, count in synth_counts.items():
        if count > 1:
            colliders = [k for k, v in pii_mapping.items() if v == synth_val]
            for orig in colliders[1:]:  # keep first, fix rest
                if orig in type_lookup:
                    items_to_fix.append(
                        {
                            "original": orig,
                            "type": type_lookup[orig],
                            "reason": "collision",
                        }
                    )
                    del pii_mapping[orig]

    faker_count = 0

    if items_to_fix:
        missed = sum(1 for i in items_to_fix if i["reason"] == "missed")
        inconsistent = sum(1 for i in items_to_fix if i["reason"] == "inconsistent")
        collisions = sum(1 for i in items_to_fix if i["reason"] == "collision")
        logger.info(
            f"Repair needed: {missed} missed, {inconsistent} inconsistent, {collisions} collisions"
        )

        pre_repair = (
            (
                token_tracker.input_tokens,
                token_tracker.output_tokens,
                token_tracker.requests,
            )
            if token_tracker
            else (0, 0, 0)
        )
        repair_mapping = _repair_with_llm(
            pii_mapping,
            items_to_fix,
            type_lookup,
            model_id,
            model_provider,
            bedrock_runtime,
            creative_params,
            token_tracker,
            config,
        )
        if token_tracker:
            r_in = token_tracker.input_tokens - pre_repair[0]
            r_out = token_tracker.output_tokens - pre_repair[1]
            r_req = token_tracker.requests - pre_repair[2]
            logger.info(f"Repair tokens: input={r_in} output={r_out} requests={r_req}")
        for item in items_to_fix:
            orig = item["original"]
            if orig in repair_mapping:
                pii_mapping[orig] = repair_mapping[orig]
            else:
                existing_synthetics = set(pii_mapping.values())
                for _ in range(10):
                    candidate = generate_synthetic_pii_fallback(item["type"], orig)
                    if candidate != orig and candidate not in existing_synthetics:
                        break
                pii_mapping[orig] = candidate
                faker_count += 1

    logger.info(
        f"Synthetic generation complete: {llm_count} LLM, {len(items_to_fix)} repaired ({faker_count} Faker fallback), {len(pii_mapping)} total"
    )

    # Validate output — log any originals that didn't get a synthetic mapping
    validate_synthetic_output(pii_mapping, pii_detections)

    # Remove any LLM-hallucinated keys not in detections
    valid_originals = {d["content"] for d in pii_detections}
    extra = set(pii_mapping) - valid_originals
    if extra:
        logger.info(
            f"Removed {len(extra)} extra LLM-generated keys not in detection list"
        )
        for k in extra:
            del pii_mapping[k]

    # Final count check: every unique PII must have a mapping
    missing = valid_originals - set(pii_mapping)
    if missing:
        logger.error(
            f"Final validation FAILED: {len(missing)} unique PII values have no mapping"
        )
    else:
        logger.info(
            f"Final validation OK: {len(pii_mapping)} mappings == {len(valid_originals)} unique PII values"
        )

    return pii_mapping
