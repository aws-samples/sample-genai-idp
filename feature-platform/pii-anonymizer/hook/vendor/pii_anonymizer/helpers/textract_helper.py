# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
AWS Textract Helper for Accurate Bounding Box Detection

This module uses AWS Textract to get accurate bounding boxes for text in images,
then matches them with PII detected by the LLM.
"""

import io
import logging
import time
from typing import List, Dict, Tuple
from PIL import Image
import boto3

logger = logging.getLogger(__name__)


def get_textract_bounding_boxes(image: Image.Image, bedrock_runtime) -> List[Dict]:
    """
    Use AWS Textract to extract text with accurate bounding boxes.

    Args:
        image: PIL Image
        bedrock_runtime: Boto3 client (we'll create textract client from same session)

    Returns:
        List of dicts with 'text' and 'bbox' (left, top, width, height in pixels)
    """
    response = _call_textract(image, bedrock_runtime)
    if not response:
        return []
    return _parse_textract_words(response, image.size)


def get_textract_ocr_text(image: Image.Image, bedrock_runtime) -> str:
    """
    Extract OCR text lines from image using Textract.

    Args:
        image: PIL Image
        bedrock_runtime: Boto3 client

    Returns:
        OCR text as newline-separated string of LINE blocks
    """
    response = _call_textract(image, bedrock_runtime)
    if not response:
        return ""
    return "\n".join(
        b["Text"] for b in response.get("Blocks", []) if b["BlockType"] == "LINE"
    )


def get_textract_full(image: Image.Image, bedrock_runtime):
    """
    Single Textract call returning both word bboxes and OCR text lines.

    Args:
        image: PIL Image
        bedrock_runtime: Boto3 client

    Returns:
        Tuple of (words_list, ocr_text_string, raw_response)
    """
    response = _call_textract(image, bedrock_runtime)
    if not response:
        return [], "", {}
    words = _parse_textract_words(response, image.size)
    ocr_text = "\n".join(
        b["Text"] for b in response.get("Blocks", []) if b["BlockType"] == "LINE"
    )
    return words, ocr_text, response


def _call_textract(image: Image.Image, bedrock_runtime):
    """Call Textract detect_document_text with retry and exponential backoff."""
    textract = boto3.client("textract", region_name=bedrock_runtime.meta.region_name)
    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    doc_bytes = img_bytes.getvalue()

    max_retries = 5
    for attempt in range(max_retries):
        try:
            return textract.detect_document_text(Document={"Bytes": doc_bytes})
        except (
            textract.exceptions.ThrottlingException,
            textract.exceptions.ProvisionedThroughputExceededException,
        ) as e:
            if attempt < max_retries - 1:
                wait = 2**attempt
                logger.warning(
                    f"Textract throttled, retry {attempt + 1}/{max_retries} in {wait}s"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"Textract throttled after {max_retries} retries: {str(e)}"
                )
                return None
        except Exception as e:
            logger.error(f"Error using Textract: {str(e)}")
            return None


def _parse_textract_words(response, image_size):
    """Parse WORD blocks from Textract response into pixel-coordinate dicts."""
    img_width, img_height = image_size
    words = []
    for block in response.get("Blocks", []):
        if block["BlockType"] == "WORD":
            text = block.get("Text", "")
            bbox = block.get("Geometry", {}).get("BoundingBox", {})
            left = int(bbox.get("Left", 0) * img_width)
            top = int(bbox.get("Top", 0) * img_height)
            width = int(bbox.get("Width", 0) * img_width)
            height = int(bbox.get("Height", 0) * img_height)
            words.append(
                {
                    "text": text,
                    "bbox": {
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                    },
                }
            )
    logger.debug(f"Textract extracted {len(words)} words from image")
    return words


def find_text_bbox(
    pii_text: str, textract_words: List[Dict], used_indices: set = None
) -> Tuple[Dict, List[int], str]:
    """
    Find bounding box for PII text by matching with Textract words.

    Args:
        pii_text: The PII text to find (e.g., "John Doe")
        textract_words: List of words from Textract with bounding boxes
        used_indices: Set of word indices already used (to handle duplicates)

    Returns:
        Tuple of (bounding_box dict or None, list of used word indices,
        match_type: str or None)
    """
    if used_indices is None:
        used_indices = set()

    pii_text = pii_text.strip()

    # Handle empty string
    if not pii_text:
        return None, [], None

    pii_words = pii_text.split()

    # Try exact match first
    for i in range(len(textract_words)):
        # Skip if this word index is already used
        if i in used_indices:
            continue

        # Check if we have enough words
        if i + len(pii_words) > len(textract_words):
            continue

        # Check if any of the words in this sequence are already used
        sequence_used = any((i + j) in used_indices for j in range(len(pii_words)))
        if sequence_used:
            continue

        # Check if words match
        match = True
        for j, pii_word in enumerate(pii_words):
            textract_word = textract_words[i + j]["text"]
            if not words_match(pii_word, textract_word):
                match = False
                break

        if match:
            # Found match - combine bounding boxes
            matched_bboxes = [
                textract_words[i + j]["bbox"] for j in range(len(pii_words))
            ]
            left = min(b["left"] for b in matched_bboxes)
            top = min(b["top"] for b in matched_bboxes)
            right = max(b["left"] + b["width"] for b in matched_bboxes)
            bottom = max(b["top"] + b["height"] for b in matched_bboxes)

            # Return bbox and the indices we used
            used_word_indices = list(range(i, i + len(pii_words)))
            return (
                {
                    "left": left,
                    "top": top,
                    "width": right - left,
                    "height": bottom - top,
                },
                used_word_indices,
                "exact",
            )

    # Try fuzzy match for single words
    if len(pii_words) == 1:
        for idx, word_data in enumerate(textract_words):
            if idx not in used_indices and words_match(pii_text, word_data["text"]):
                return word_data["bbox"], [idx], "exact"

    # Try matching with punctuation removed (phone numbers, codes, IDs, dates)
    import re

    pii_normalized = re.sub(r"[^\w]", "", pii_text)  # Remove all non-alphanumeric
    if pii_normalized != pii_text and len(pii_normalized) > 0:
        # Try single word match
        for idx, word_data in enumerate(textract_words):
            if idx not in used_indices:
                word_normalized = re.sub(r"[^\w]", "", word_data["text"])
                if pii_normalized.lower() == word_normalized.lower():
                    return word_data["bbox"], [idx], "exact"

        # Try multi-word sequence with normalization
        for i in range(len(textract_words)):
            if i in used_indices:
                continue
            for seq_len in range(2, min(10, len(textract_words) - i + 1)):
                sequence_used = any((i + j) in used_indices for j in range(seq_len))
                if sequence_used:
                    continue

                # Combine and normalize Textract sequence
                textract_phrase = " ".join(
                    textract_words[i + j]["text"] for j in range(seq_len)
                )
                textract_normalized = re.sub(r"[^\w]", "", textract_phrase)

                if pii_normalized.lower() == textract_normalized.lower():
                    indices = list(range(i, i + seq_len))
                    matched_bboxes = [
                        textract_words[i + j]["bbox"] for j in range(seq_len)
                    ]

                    combined_bbox = {
                        "left": min(b["left"] for b in matched_bboxes),
                        "top": min(b["top"] for b in matched_bboxes),
                        "width": max(b["left"] + b["width"] for b in matched_bboxes)
                        - min(b["left"] for b in matched_bboxes),
                        "height": max(b["top"] + b["height"] for b in matched_bboxes)
                        - min(b["top"] for b in matched_bboxes),
                    }
                    return combined_bbox, indices, "exact"

    # Fuzzy match with similarity threshold
    from difflib import SequenceMatcher

    best_match = None
    best_score = 0.0
    best_idx = None

    for idx, word_data in enumerate(textract_words):
        if idx not in used_indices:
            score = SequenceMatcher(
                None, pii_text.lower(), word_data["text"].lower()
            ).ratio()
            if score > best_score and score >= 0.8:
                best_score = score
                best_match = word_data["bbox"]
                best_idx = idx

    if best_match:
        return best_match, [best_idx], "fuzzy"

    # Multi-word fuzzy: try matching phrase against sliding window of Textract words
    if len(pii_words) >= 2:
        from difflib import SequenceMatcher as SM2

        for win_len in range(len(pii_words), max(1, len(pii_words) - 1), -1):
            for i in range(len(textract_words) - win_len + 1):
                if any((i + j) in used_indices for j in range(win_len)):
                    continue
                window_text = " ".join(
                    textract_words[i + j]["text"] for j in range(win_len)
                )
                score = SM2(None, pii_text.lower(), window_text.lower()).ratio()
                if score >= 0.8:
                    indices = list(range(i, i + win_len))
                    matched_bboxes = [
                        textract_words[i + j]["bbox"] for j in range(win_len)
                    ]
                    combined_bbox = {
                        "left": min(b["left"] for b in matched_bboxes),
                        "top": min(b["top"] for b in matched_bboxes),
                        "width": max(b["left"] + b["width"] for b in matched_bboxes)
                        - min(b["left"] for b in matched_bboxes),
                        "height": max(b["top"] + b["height"] for b in matched_bboxes)
                        - min(b["top"] for b in matched_bboxes),
                    }
                    return combined_bbox, indices, "fuzzy"

    # Order-independent word matching - check if most PII words exist in Textract (any order)
    # This handles multi-column layouts and multi-line text
    # where words are out of sequence
    import re

    pii_words = [
        re.sub(r"[^\w]", "", w).lower()
        for w in pii_text.split()
        if re.sub(r"[^\w]", "", w)
    ]

    if len(pii_words) >= 3:  # Only for 3+ word phrases
        # Find ALL Textract words that match ANY PII word (may have duplicates on page)
        all_matching_words = []
        for idx, word_data in enumerate(textract_words):
            if idx in used_indices:
                continue
            word_normalized = re.sub(r"[^\w]", "", word_data["text"]).lower()
            if word_normalized in pii_words:
                all_matching_words.append((idx, word_data))

        # Allow 1 missing word for phrases with 4+ words
        required_matches = len(pii_words) - 1 if len(pii_words) > 3 else len(pii_words)

        if len(all_matching_words) >= required_matches:
            # ANCHOR-BASED DEDUP: pick rarest word as anchor, select nearest candidates
            from collections import Counter

            word_counts = Counter(
                re.sub(r"[^\w]", "", w[1]["text"]).lower() for w in all_matching_words
            )
            # Anchor = numeric token with fewest occurrences, else rarest word
            numeric_words = [
                (w, word_counts[w])
                for w in set(pii_words)
                if w.isdigit() or any(c.isdigit() for c in w)
            ]
            if numeric_words:
                anchor_word = min(numeric_words, key=lambda x: x[1])[0]
            else:
                anchor_word = min(set(pii_words), key=lambda w: word_counts.get(w, 999))

            # Find anchor position (pick first occurrence)
            anchor_candidates = [
                (idx, wd)
                for idx, wd in all_matching_words
                if re.sub(r"[^\w]", "", wd["text"]).lower() == anchor_word
            ]
            if anchor_candidates:
                anchor_idx, anchor_wd = anchor_candidates[0]
                anchor_y = anchor_wd["bbox"]["top"]
                anchor_x = anchor_wd["bbox"]["left"]

                # For each PII word, pick the candidate closest to anchor
                selected = []
                used_pii = []
                for pii_w in pii_words:
                    if pii_w in used_pii:
                        continue
                    candidates = [
                        (idx, wd)
                        for idx, wd in all_matching_words
                        if re.sub(r"[^\w]", "", wd["text"]).lower() == pii_w
                        and idx not in [s[0] for s in selected]
                    ]
                    if candidates:
                        best = min(
                            candidates,
                            key=lambda x: 3 * abs(x[1]["bbox"]["top"] - anchor_y)
                            + abs(x[1]["bbox"]["left"] - anchor_x),
                        )
                        selected.append(best)
                    used_pii.append(pii_w)

                # Check cohesion: max y spread <= 2 line heights
                if len(selected) >= required_matches:
                    avg_h = sum(w[1]["bbox"]["height"] for w in selected) / len(
                        selected
                    )
                    y_vals = [w[1]["bbox"]["top"] for w in selected]
                    y_span = max(y_vals) - min(y_vals)
                    if y_span <= avg_h * 3:  # Allow ~2-3 lines
                        all_matching_words = selected
                    # else: fall through to original cluster logic

        if len(all_matching_words) >= required_matches:
            # Verify enough unique PII words are covered
            matched_unique = set(
                re.sub(r"[^\w]", "", wd["text"]).lower() for _, wd in all_matching_words
            )
            if len(matched_unique & set(pii_words)) < required_matches:
                return None, [], None

            # LINE-CONTIGUOUS MATCHING - find the best cluster of words
            # that form consecutive lines
            # This handles multi-line text like "Group Insurance of\nAmerica" properly

            # DOCUMENT-AGNOSTIC: Calculate thresholds from actual word heights
            # This adapts to any document
            # (high-res ID cards, low-res scans, any font size)
            avg_word_height = sum(
                w[1]["bbox"]["height"] for w in all_matching_words
            ) / len(all_matching_words)

            LINE_THRESHOLD = avg_word_height * 0.5  # 50% of word height = same line
            MAX_LINE_GAP = avg_word_height * 2.0  # 200% of word height = next line

            # Dynamic: also compute actual line spacing from ALL Textract words on page
            # to adapt to the document's real spacing
            all_tops = sorted(set(w["bbox"]["top"] for w in textract_words))
            if len(all_tops) > 1:
                line_gaps = [
                    all_tops[i + 1] - all_tops[i]
                    for i in range(len(all_tops) - 1)
                    if all_tops[i + 1] - all_tops[i] > avg_word_height * 0.3
                ]  # skip same-line words
                if line_gaps:
                    median_gap = sorted(line_gaps)[len(line_gaps) // 2]
                    MAX_LINE_GAP = max(MAX_LINE_GAP, median_gap * 1.5)

            def group_words_by_line(words_with_idx):
                """Group words into lines based on vertical position."""
                if not words_with_idx:
                    return []

                # Sort by top position
                sorted_words = sorted(words_with_idx, key=lambda x: x[1]["bbox"]["top"])

                lines = []
                current_line = [sorted_words[0]]
                current_line_top = sorted_words[0][1]["bbox"]["top"]

                for idx_word in sorted_words[1:]:
                    word_top = idx_word[1]["bbox"]["top"]
                    # If word is within LINE_THRESHOLD of current line, add to same line
                    if abs(word_top - current_line_top) <= LINE_THRESHOLD:
                        current_line.append(idx_word)
                    else:
                        # Start a new line
                        lines.append(current_line)
                        current_line = [idx_word]
                        current_line_top = word_top

                lines.append(current_line)
                return lines

            def find_contiguous_cluster(words_with_idx):
                """Find the largest cluster of words on consecutive lines."""
                lines = group_words_by_line(words_with_idx)
                if not lines:
                    return []

                if len(lines) == 1:
                    return lines[0]  # Single line - return all words

                # Find consecutive line groups
                # Calculate line centers (average top of words in line)
                line_centers = []
                for line in lines:
                    avg_top = sum(w[1]["bbox"]["top"] for w in line) / len(line)
                    line_centers.append(avg_top)

                # Find best contiguous sequence of lines
                best_cluster = []
                current_cluster_lines = [0]  # Start with first line

                for i in range(1, len(lines)):
                    gap = line_centers[i] - line_centers[i - 1]
                    if gap <= MAX_LINE_GAP:
                        current_cluster_lines.append(i)
                    else:
                        # Gap too large - check if current cluster is best
                        cluster_words = []
                        for line_idx in current_cluster_lines:
                            cluster_words.extend(lines[line_idx])
                        if len(cluster_words) > len(best_cluster):
                            best_cluster = cluster_words
                        # Start new cluster
                        current_cluster_lines = [i]

                # Check final cluster
                cluster_words = []
                for line_idx in current_cluster_lines:
                    cluster_words.extend(lines[line_idx])
                if len(cluster_words) > len(best_cluster):
                    best_cluster = cluster_words

                return best_cluster

            # Find best contiguous cluster
            best_cluster = find_contiguous_cluster(all_matching_words)

            if len(best_cluster) >= required_matches:
                matching_words = [w[1] for w in best_cluster]
                matching_indices = [w[0] for w in best_cluster]

                # Additional validation: area ratio check
                individual_areas_sum = sum(
                    w["bbox"]["width"] * w["bbox"]["height"] for w in matching_words
                )

                combined_left = min(w["bbox"]["left"] for w in matching_words)
                combined_top = min(w["bbox"]["top"] for w in matching_words)
                combined_right = max(
                    w["bbox"]["left"] + w["bbox"]["width"] for w in matching_words
                )
                combined_bottom = max(
                    w["bbox"]["top"] + w["bbox"]["height"] for w in matching_words
                )
                combined_area = (combined_right - combined_left) * (
                    combined_bottom - combined_top
                )

                area_ratio = combined_area / max(individual_areas_sum, 1)
                max_area_ratio = 2.5  # Tighter ratio to prevent oversized boxes

                if area_ratio > max_area_ratio:
                    pass  # Log removed to prevent PII exposure
                else:
                    # PASSED validation - create combined bbox
                    combined_bbox = {
                        "left": combined_left,
                        "top": combined_top,
                        "width": combined_right - combined_left,
                        "height": combined_bottom - combined_top,
                    }
                    # Log removed to prevent PII exposure
                    return combined_bbox, matching_indices, "spatial"

    # No match found
    return None, [], None


def words_match(word1: str, word2: str) -> bool:
    """Check if two words match (case-insensitive, ignoring punctuation and spaces)."""
    w1 = word1.lower().strip(".,;:!?()[]{}\"'-")
    w2 = word2.lower().strip(".,;:!?()[]{}\"'-")

    # Direct match
    if w1 == w2:
        return True

    # Match without spaces (for phone numbers like "(920) 555-0101" vs "(920)555-0101")
    w1_no_space = w1.replace(" ", "")
    w2_no_space = w2.replace(" ", "")
    if w1_no_space == w2_no_space and len(w1_no_space) > 0:
        return True

    # Match without any non-alphanumeric (for IDs with different formatting)
    w1_clean = "".join(c for c in w1 if c.isalnum())
    w2_clean = "".join(c for c in w2 if c.isalnum())

    return w1_clean == w2_clean and len(w1_clean) > 0


def enhance_pii_detections_with_textract(
    image: Image.Image,
    pii_detections: List[Dict],
    bedrock_runtime,
    textract_words=None,
) -> List[Dict]:
    """
    Replace LLM bounding boxes with accurate Textract bounding boxes.

    Args:
        image: PIL Image
        pii_detections: List of PII detections from LLM
        bedrock_runtime: Boto3 client
        textract_words: Optional pre-fetched Textract words (avoids duplicate API call)

    Returns:
        Updated PII detections with accurate bounding boxes
    """
    if not pii_detections:
        return []

    # Use pre-fetched words or call Textract
    if textract_words is None:
        textract_words = get_textract_bounding_boxes(image, bedrock_runtime)

    if not textract_words:
        # If LLM detected PII but Textract found nothing, try zoom-in
        # If LLM also found nothing, page is truly blank
        if pii_detections:
            logger.warning(
                "Textract returned no words from full image, will try zoom-in for each detection"
            )
            textract_words = []  # Empty list to skip full-image matching
        else:
            logger.warning("Textract returned no words - page appears blank")
            return []

    logger.debug(
        f"Textract extracted {len(textract_words)} words, matching against {len(pii_detections)} PII detections"
    )

    # Track which word indices have been used to handle duplicates
    used_word_indices = set()

    # Match each PII with Textract words (reusing the same Textract results)
    enhanced_detections = []
    textract_count = 0
    fuzzy_count = 0
    spatial_count = 0
    skipped_count = 0
    llm_vision_count = 0

    # Process longest detections first so they claim the right Textract words
    # before shorter overlapping detections (standard "longest match first" strategy)
    pii_detections = sorted(
        pii_detections, key=lambda d: len(d.get("content", "").split()), reverse=True
    )

    for detection in pii_detections:
        pii_text = detection.get("content", "").strip()
        if not pii_text:
            continue

        # Use LLM bbox as spatial gate to match correct instance
        llm_bbox = detection.get("bounding_box")
        accurate_bbox = None
        used_indices = []
        match_type = None

        if llm_bbox and all(k in llm_bbox for k in ("left", "top", "width", "height")):
            left = float(llm_bbox["left"])
            top_val = float(llm_bbox["top"])
            width = float(llm_bbox["width"])
            height = float(llm_bbox["height"])
            pad_x = max(0.01, 0.25 * width)
            pad_y = max(0.01, 0.25 * height)
            lx0 = max(0.0, left - pad_x)
            ly0 = max(0.0, top_val - pad_y)
            lx1 = min(1.0, left + width + pad_x)
            ly1 = min(1.0, top_val + height + pad_y)

            gated_words = []
            gated_index_map = {}
            for idx, w in enumerate(textract_words):
                wb = w["bbox"]
                wx = float(wb["left"]) + float(wb["width"]) / 2
                wy = float(wb["top"]) + float(wb["height"]) / 2
                if lx0 <= wx <= lx1 and ly0 <= wy <= ly1:
                    gated_index_map[len(gated_words)] = idx
                    gated_words.append(w)

            if gated_words and len(gated_words) <= 250:
                rev = {v: k for k, v in gated_index_map.items()}
                gated_used = {rev[i] for i in used_word_indices if i in rev}
                accurate_bbox, gi, match_type = find_text_bbox(
                    pii_text, gated_words, gated_used
                )
                if accurate_bbox:
                    used_indices = [
                        gated_index_map[i] for i in gi if i in gated_index_map
                    ]

        # Fallback to global search
        if not accurate_bbox:
            accurate_bbox, used_indices, match_type = find_text_bbox(
                pii_text, textract_words, used_word_indices
            )

        if accurate_bbox:
            # Mark these words as used
            used_word_indices.update(used_indices)

            # Replace with accurate bbox
            detection["bounding_box"] = accurate_bbox
            detection["bbox_source"] = (
                f"textract_{match_type}" if match_type != "exact" else "textract"
            )

            # Store segment bboxes when large gaps exist (form columns)
            if len(used_indices) > 1:
                wbs = [textract_words[idx]["bbox"] for idx in used_indices]
                avg_w = sum(float(b["width"]) for b in wbs) / len(wbs)
                segs = [[wbs[0]]]
                for k in range(1, len(wbs)):
                    pr = float(wbs[k - 1]["left"]) + float(wbs[k - 1]["width"])
                    gap = float(wbs[k]["left"]) - pr
                    if gap > avg_w * 3:
                        segs.append([])
                    segs[-1].append(wbs[k])
                if len(segs) > 1:
                    detection["bbox_segments"] = []
                    for s in segs:
                        sl = min(b["left"] for b in s)
                        st = min(b["top"] for b in s)
                        sr = max(b["left"] + b["width"] for b in s)
                        sb = max(b["top"] + b["height"] for b in s)
                        detection["bbox_segments"].append(
                            {"left": sl, "top": st, "width": sr - sl, "height": sb - st}
                        )
            else:
                logger.debug(
                    f"  Found bbox: type={detection.get('type')}, match={match_type}"
                )

            enhanced_detections.append(detection)

            if match_type == "spatial":
                spatial_count += 1
            elif match_type == "fuzzy":
                fuzzy_count += 1
            else:
                textract_count += 1
        else:
            # Last resort: use LLM vision bbox if available
            if llm_bbox and all(
                k in llm_bbox for k in ("left", "top", "width", "height")
            ):
                detection["bounding_box"] = llm_bbox
                detection["bbox_source"] = "llm_vision"
                enhanced_detections.append(detection)
                llm_vision_count += 1
                logger.info(
                    f"LLM vision bbox fallback: type={detection.get('type')}, len={len(pii_text)}"
                )
            else:
                detection["bbox_source"] = "skipped"
                detection["bounding_box"] = None
                enhanced_detections.append(detection)
                skipped_count += 1
                logger.debug(
                    f"Skipped PII (no bbox match): type={detection.get('type')}, words={len(pii_text.split())}"
                )

    logger.debug(
        f"Bounding box extraction completed: {textract_count} exact, {fuzzy_count} fuzzy, {spatial_count} spatial, {llm_vision_count} llm_vision, {skipped_count} skipped"
    )

    return enhanced_detections
