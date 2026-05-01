# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Comparator module for document evaluation.

⚠️ DEPRECATED: This module is deprecated and will be removed in a future release.
The evaluation system now uses the Stickler library for comparison logic.

This module is kept for backward compatibility only. New code should use
the Stickler-based EvaluationService directly.

Legacy functions (compare_exact, compare_fuzzy, etc.) are still used internally
by the LLMComparator wrapper but should not be called directly in new code.

Migration Path:
- Use EvaluationService (now Stickler-based) for all evaluation needs
- Configure evaluation using x-aws-idp-evaluation-* extensions in JSON Schema
- Stickler provides more sophisticated comparators and better list matching

This module provides methods to compare expected and actual values using various comparison strategies.
"""

import ast
import json
import logging
import math
import re
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple

from munkres import Munkres, make_cost_matrix

from idp_common import bedrock
from idp_common.evaluation.models import EvaluationMethod

logger = logging.getLogger(__name__)


class Comparator(ABC):
    """Base class for value comparators."""

    @abstractmethod
    def compare(self, value1: Any, value2: Any) -> float:
        """
        Compare two values and return a similarity score between 0.0 and 1.0.

        Args:
            value1: First value to compare
            value2: Second value to compare

        Returns:
            float: Similarity score between 0.0 (no match) and 1.0 (perfect match)
        """
        pass


class ExactComparator(Comparator):
    """Exact string match comparator."""

    def compare(self, value1: Any, value2: Any) -> float:
        """Compare values for exact string match after normalization."""
        value1_norm = strip_punctuation_space(str(value1))
        value2_norm = strip_punctuation_space(str(value2))
        return 1.0 if value1_norm == value2_norm else 0.0


class NumericComparator(Comparator):
    """Numeric exact match comparator."""

    def compare(self, value1: Any, value2: Any) -> float:
        """Compare values for exact numeric match."""
        try:
            num1 = normalize_numeric(value1)
            num2 = normalize_numeric(value2)
            return 1.0 if num1 == num2 else 0.0
        except ValueError:
            # Fall back to string comparison if numeric conversion fails
            return ExactComparator().compare(value1, value2)


class FuzzyComparator(Comparator):
    """Fuzzy string match comparator."""

    def __init__(self, threshold: float = 0.8):
        """
        Initialize the fuzzy comparator.

        Args:
            threshold: Minimum similarity score to consider a match (0.0 to 1.0)
        """
        self.threshold = threshold

    def compare(self, value1: Any, value2: Any) -> float:
        """Compare values using fuzzy string matching."""
        score = fuzz_score(str(value1), str(value2))
        return score


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


def normalize_numeric(value: Any) -> float:
    """
    Normalize a numeric value by removing currency symbols and commas.

    Args:
        value: Input value to normalize

    Returns:
        Normalized float value
    """
    if isinstance(value, (int, float)):
        return float(value)

    if not isinstance(value, str):
        value = str(value)

    # Remove currency symbols, commas, parentheses
    value = value.replace("$", "").replace(",", "").replace("(", "").replace(")", "")

    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Cannot convert {value} to numeric value")


def compare_exact(expected: Any, actual: Any) -> Tuple[bool, float]:
    """
    Compare values for exact string match.

    Args:
        expected: Expected value
        actual: Actual value

    Returns:
        Tuple of (matched, score)
    """
    if expected is None and actual is None:
        return True, 1.0

    if expected is None or actual is None:
        return False, 0.0

    # Check if both values are empty strings
    if (
        isinstance(expected, str)
        and not expected.strip()
        and isinstance(actual, str)
        and not actual.strip()
    ):
        return True, 1.0

    expected_str = strip_punctuation_space(str(expected))
    actual_str = strip_punctuation_space(str(actual))

    return expected_str == actual_str, 1.0 if expected_str == actual_str else 0.0


def compare_numeric(expected: Any, actual: Any) -> Tuple[bool, float]:
    """
    Compare values for exact numeric match.

    Args:
        expected: Expected value
        actual: Actual value

    Returns:
        Tuple of (matched, score)
    """
    if expected is None and actual is None:
        return True, 1.0

    # Check if both values are empty strings
    if (
        isinstance(expected, str)
        and not expected.strip()
        and isinstance(actual, str)
        and not actual.strip()
    ):
        return True, 1.0

    if expected is None or actual is None:
        return False, 0.0

    try:
        expected_num = normalize_numeric(expected)
        actual_num = normalize_numeric(actual)
        return expected_num == actual_num, 1.0 if expected_num == actual_num else 0.0
    except ValueError:
        # Fall back to exact string comparison if numeric conversion fails
        return compare_exact(expected, actual)


def convert_to_list(value: Any) -> List[str]:
    """
    Convert a value to a list.

    Args:
        value: Input value to convert (string, list, or other)

    Returns:
        List of strings
    """
    if value is None:
        return []

    # If already a list, return as is
    if isinstance(value, list):
        return [str(item) for item in value]

    # Try to convert a string representation of a list to a list
    if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
        try:
            parsed_list = ast.literal_eval(value)
            if isinstance(parsed_list, list):
                return [str(item) for item in parsed_list]
        except (ValueError, SyntaxError):
            pass

    # Default: treat as a single value
    return [str(value)]


def compare_hungarian(
    expected: Any,
    actual: Any,
    comparator: Optional[Comparator] = None,
    threshold: float = 0.8,
) -> Tuple[int, int, float]:
    """
    Compare lists using Hungarian algorithm for maximum bipartite matching.

    Args:
        expected: Expected list or value
        actual: Actual list or value
        comparator: Comparator to use for individual item comparison
        threshold: Minimum similarity threshold for considering a match

    Returns:
        Tuple of (true_positives, false_positives, average_score)
    """
    # Default to exact comparator if none provided
    if comparator is None:
        comparator = ExactComparator()

    expected_list = convert_to_list(expected)
    actual_list = convert_to_list(actual)

    # Handle simple case with single values
    if len(expected_list) == 1 and len(actual_list) == 1:
        score = comparator.compare(expected_list[0], actual_list[0])
        matched = score >= threshold
        return (1, 0, score) if matched else (0, 1, score)

    # Empty lists edge case
    if not expected_list and not actual_list:
        return 0, 0, 1.0
    if not expected_list:
        return 0, len(actual_list), 0.0
    if not actual_list:
        return 0, 0, 0.0

    # Create similarity matrix for Hungarian algorithm
    matrix: List[List[float]] = [
        [0.0 for _ in range(len(actual_list))] for _ in range(len(expected_list))
    ]

    # Fill matrix with comparison scores from the provided comparator
    for i, exp_val in enumerate(expected_list):
        for j, act_val in enumerate(actual_list):
            matrix[i][j] = comparator.compare(exp_val, act_val)

    # Convert to cost matrix (Hungarian algorithm minimizes cost)
    cost_matrix = make_cost_matrix(matrix, lambda x: 1 - x)  # type: ignore[arg-type]

    # Compute the optimal assignment
    m = Munkres()
    indexes = m.compute(cost_matrix)

    # Count matches and calculate average score
    matches = [(i, j, matrix[i][j]) for i, j in indexes]
    true_positives = sum(1 for _, _, score in matches if score >= threshold)
    false_positives = len(actual_list) - true_positives

    avg_score = sum(score for _, _, score in matches) / len(matches) if matches else 0.0

    return true_positives, false_positives, avg_score


def fuzz_score(s1: str, s2: str) -> float:
    """
    Calculate fuzzy match score between two strings.

    This is a simplified implementation. For a real implementation,
    you might want to use a dedicated library like python-Levenshtein or fuzzywuzzy.

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


def compare_fuzzy(
    expected: Any, actual: Any, threshold: float = 0.8
) -> Tuple[bool, float]:
    """
    Compare values using fuzzy string matching.

    Args:
        expected: Expected value
        actual: Actual value
        threshold: Minimum similarity score to consider a match (0.0 to 1.0)

    Returns:
        Tuple of (matched, score)
    """
    if expected is None and actual is None:
        return True, 1.0

    # Check if both values are empty strings
    if (
        isinstance(expected, str)
        and not expected.strip()
        and isinstance(actual, str)
        and not actual.strip()
    ):
        return True, 1.0

    if expected is None or actual is None:
        return False, 0.0

    score = fuzz_score(str(expected), str(actual))
    return score >= threshold, score


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        v1: First vector
        v2: Second vector

    Returns:
        Cosine similarity (0.0 to 1.0)
    """
    if not v1 or not v2:
        return 0.0

    # Ensure vectors are the same length
    if len(v1) != len(v2):
        logger.warning(f"Vector lengths don't match: {len(v1)} vs {len(v2)}")
        min_len = min(len(v1), len(v2))
        v1 = v1[:min_len]
        v2 = v2[:min_len]

    # Calculate dot product and magnitudes
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(b * b for b in v2))

    # Avoid division by zero
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    # Calculate cosine similarity
    return dot_product / (magnitude1 * magnitude2)


def compare_semantic(
    expected: Any,
    actual: Any,
    threshold: float = 0.8,
    model_id: str = "amazon.titan-embed-text-v1",
) -> Tuple[bool, float]:
    """
    Compare values using semantic embedding similarity.

    Args:
        expected: Expected value
        actual: Actual value
        threshold: Minimum similarity score to consider a match (0.0 to 1.0)
        model_id: The embedding model to use

    Returns:
        Tuple of (matched, score)
    """
    if expected is None and actual is None:
        return True, 1.0

    # Check if both values are empty strings
    if (
        isinstance(expected, str)
        and not expected.strip()
        and isinstance(actual, str)
        and not actual.strip()
    ):
        return True, 1.0

    if expected is None or actual is None:
        return False, 0.0

    try:
        # Generate embeddings for both values
        expected_str = str(expected)
        actual_str = str(actual)

        # Log embedding generation
        logger.info(
            f"Generating embeddings for semantic comparison using model: {model_id}"
        )
        logger.debug(
            f"Expected text: {expected_str[:100]}{'...' if len(expected_str) > 100 else ''}"
        )
        logger.debug(
            f"Actual text: {actual_str[:100]}{'...' if len(actual_str) > 100 else ''}"
        )

        # Generate embeddings
        expected_embedding = bedrock.generate_embedding(expected_str, model_id)
        actual_embedding = bedrock.generate_embedding(actual_str, model_id)

        # If either embedding is empty, fall back to fuzzy matching
        if not expected_embedding or not actual_embedding:
            logger.warning(
                "Failed to generate embeddings, falling back to fuzzy matching"
            )
            return compare_fuzzy(expected, actual, threshold)

        # Calculate cosine similarity
        similarity = cosine_similarity(expected_embedding, actual_embedding)
        logger.info(f"Semantic similarity score: {similarity:.4f}")

        return similarity >= threshold, similarity

    except Exception as e:
        logger.error(f"Error in semantic comparison: {str(e)}", exc_info=True)
        # Fall back to fuzzy matching on error
        logger.warning("Error in semantic comparison, falling back to fuzzy matching")
        return compare_fuzzy(expected, actual, threshold)


def compare_values(
    expected: Any,
    actual: Any,
    method: EvaluationMethod,
    threshold: float = 0.8,
    document_class: Optional[str] = None,
    attr_name: Optional[str] = None,
    attr_description: Optional[str] = None,
    llm_config: Optional[dict] = None,
    comparator_type: Optional[str] = None,  # New parameter for specifying comparator
) -> Tuple[bool, float, Optional[str]]:
    """
    Compare values using the specified method.

    Args:
        expected: Expected value
        actual: Actual value
        method: Comparison method to use
        threshold: Threshold for fuzzy/semantic methods
        document_class: Document class name (for LLM evaluation)
        attr_name: Attribute name (for LLM evaluation)
        attr_description: Attribute description (for LLM evaluation)
        llm_config: Configuration for LLM invocation
        comparator_type: Type of comparator to use (for Hungarian methods)

    Returns:
        Tuple of (matched, score, reason)
    """
    # Initialize reason as None for non-LLM methods
    reason = None

    # Check for both None/Empty case first - handle consistently across all methods
    is_expected_empty = expected is None or (
        isinstance(expected, str) and not expected.strip()
    )
    is_actual_empty = actual is None or (isinstance(actual, str) and not actual.strip())

    if is_expected_empty and is_actual_empty:
        return (
            True,
            1.0,
            "Both actual and expected values are missing, so they are matched.",
        )

    # Continue with method-specific logic
    if method == EvaluationMethod.EXACT:
        matched, score = compare_exact(expected, actual)

    elif method == EvaluationMethod.NUMERIC_EXACT:
        matched, score = compare_numeric(expected, actual)

    elif method == EvaluationMethod.FUZZY:
        matched, score = compare_fuzzy(expected, actual, threshold)

    # Handle all Hungarian methods
    elif method in [EvaluationMethod.HUNGARIAN]:
        # Select the appropriate comparator based on method or comparator_type
        if comparator_type == "EXACT":
            comparator = ExactComparator()
        elif comparator_type == "FUZZY":
            comparator = FuzzyComparator(threshold)
        elif comparator_type == "NUMERIC":
            comparator = NumericComparator()
        else:
            # Default to exact comparator
            comparator = ExactComparator()

        # Call the enhanced compare_hungarian function
        tp, fp, avg_score = compare_hungarian(
            expected=expected, actual=actual, comparator=comparator, threshold=threshold
        )

        # Convert Hungarian output to match/score format
        if tp + fp == 0:
            matched, score = True, 1.0  # Both lists empty
        else:
            matched = tp > 0 and fp == 0
            score = avg_score

    elif method == EvaluationMethod.SEMANTIC:
        # Use embedding-based semantic comparison with configurable threshold
        matched, score = compare_semantic(expected, actual, threshold)

    elif method == EvaluationMethod.LLM:
        # Use the compare_llm function directly
        matched, score, reason = compare_llm(
            expected=expected,
            actual=actual,
            document_class=document_class,
            attr_name=attr_name,
            attr_description=attr_description,
            llm_config=llm_config,
        )

    else:
        # Default to exact matching
        matched, score = compare_exact(expected, actual)

    return matched, score, reason


def compare_llm(
    expected: Any,
    actual: Any,
    document_class: Optional[str] = None,
    attr_name: Optional[str] = None,
    attr_description: Optional[str] = None,
    llm_config: Optional[dict] = None,
    bedrock_invoker=None,
) -> Tuple[bool, float, Optional[str]]:
    """
    Compare values using LLM to determine semantic equivalence.

    Args:
        expected: Expected value
        actual: Actual value
        document_class: Document class name
        attr_name: Attribute name
        attr_description: Attribute description
        llm_config: Configuration for LLM invocation
        bedrock_invoker: Function to invoke Bedrock models

    Returns:
        Tuple of (matched, score, reason)
    """
    if not bedrock_invoker:
        # Import here to avoid circular imports
        from idp_common import bedrock

        bedrock_invoker = bedrock.invoke_model

    try:
        # Format attribute description
        doc_class = document_class if document_class is not None else "unknown"
        name = attr_name if attr_name is not None else "attribute"
        desc = attr_description if attr_description is not None else ""

        # Default LLM configuration if not provided
        config = llm_config or {}
        model = config.get("model", "us.anthropic.claude-3-sonnet-20240229-v1:0")
        temperature = config.get("temperature", 0.0)
        top_k = config.get("top_k", 5)

        # Get system and task prompts from config or use defaults
        system_prompt = config.get(
            "system_prompt",
            """You are an evaluator that helps determine if the predicted and expected values match for document attribute extraction. You will consider the context and meaning rather than just exact string matching.""",
        )

        task_prompt_template = config.get(
            "task_prompt",
            """I need to evaluate attribute extraction for a document of class: {DOCUMENT_CLASS}.

For the attribute named "{ATTRIBUTE_NAME}" described as "{ATTRIBUTE_DESCRIPTION}":
- Expected value: {EXPECTED_VALUE}
- Actual value: {ACTUAL_VALUE}

Do these values match in meaning, taking into account formatting differences, word order, abbreviations, and semantic equivalence?
Provide your assessment as a JSON with three fields:
- "match": boolean (true if they match, false if not)
- "score": number between 0 and 1 representing the confidence/similarity score
- "reason": brief explanation of your decision

Respond ONLY with the JSON and nothing else.  Here's the exact format:
{
  "match": true or false,
  "score": 0.0 to 1.0,
  "reason": "Your explanation here"
}
""",
        )

        # Log for debugging
        logger.debug(f"LLM evaluation starting for attribute: {name}")
        logger.debug(f"Document class: {doc_class}")
        logger.debug(f"Attribute description: {desc}")

        # Handle None values
        expected_str = str(expected) if expected is not None else "None"
        actual_str = str(actual) if actual is not None else "None"

        logger.debug(f"Expected value: {expected_str}")
        logger.debug(f"Actual value: {actual_str}")

        # Create task_placeholders dictionary with all possible placeholders
        task_placeholders = {
            "DOCUMENT_CLASS": doc_class,
            "ATTRIBUTE_NAME": name,
            "ATTRIBUTE_DESCRIPTION": desc,
            "EXPECTED_VALUE": expected_str,
            "ACTUAL_VALUE": actual_str,
        }

        try:
            # Use the common format_prompt function from bedrock
            from idp_common.bedrock import format_prompt

            task_prompt = format_prompt(
                task_prompt_template,
                task_placeholders,
                required_placeholders=None,  # Don't validate specific placeholders as they may vary
            )
            logger.debug(
                f"Successfully formatted task prompt with {len(task_placeholders)} placeholders"
            )
        except Exception as e:
            error_msg = f"Task prompt formatting error: {str(e)}"
            logger.error(f"Prompt template: '{task_prompt_template}'")
            logger.error(f"Placeholders: '{task_placeholders}'")
            logger.error(error_msg)
            return False, 0.0, error_msg

        # Create content for LLM request
        content = [{"text": task_prompt}]

        # Log system prompt for debugging
        logger.debug(f"Calling Bedrock model: {model}")

        # Call Bedrock model
        response = bedrock_invoker(
            model_id=model,
            system_prompt=system_prompt,
            content=content,
            temperature=temperature,
            top_k=top_k,
        )

        # Extract and parse response
        from idp_common import bedrock

        result_text = bedrock.extract_text_from_response(response).strip()
        logger.debug(f"Raw LLM response: {result_text}")

        # Try to parse as JSON
        try:
            # First attempt to find JSON block within text using regex
            # This pattern looks for balanced braces to find JSON objects
            json_pattern = r"(\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\})"
            json_matches = re.findall(json_pattern, result_text)

            # Check for code blocks with ```json ... ``` pattern
            code_block_pattern = r"```json\s*([\s\S]*?)\s*```"
            code_blocks = re.findall(code_block_pattern, result_text)

            # Try to parse code blocks first if they exist
            for code_block in code_blocks:
                try:
                    result_json = json.loads(code_block)
                    # Check if the JSON has the expected fields
                    if "match" in result_json and "score" in result_json:
                        match_value = result_json.get("match", False)
                        score_value = result_json.get("score", 0.0)
                        reason = result_json.get("reason", "No reason provided")
                        logger.info(
                            f"LLM evaluation for {name} (from code block): match={match_value}, score={score_value}, reason={reason}"
                        )
                        return bool(match_value), float(score_value), reason
                except json.JSONDecodeError:
                    # This code block wasn't valid JSON, try next one
                    continue

            # If we found potential JSON blocks
            if json_matches:
                # Try each potential JSON block
                for json_block in json_matches:
                    try:
                        result_json = json.loads(json_block)
                        # Check if the JSON has the expected fields
                        if "match" in result_json and "score" in result_json:
                            match_value = result_json.get("match", False)
                            score_value = result_json.get("score", 0.0)
                            reason = result_json.get("reason", "No reason provided")
                            logger.info(
                                f"LLM evaluation for {name}: match={match_value}, score={score_value}, reason={reason}"
                            )
                            return bool(match_value), float(score_value), reason
                    except json.JSONDecodeError:
                        # This particular block wasn't valid JSON, try next one
                        continue

            # If we didn't find a valid JSON block, try the entire text
            result_json = json.loads(result_text)
            # Extract values from JSON
            match_value = result_json.get("match", False)
            score_value = result_json.get("score", 0.0)
            reason = result_json.get("reason", "No reason provided")
            logger.info(
                f"LLM evaluation for {name}: match={match_value}, score={score_value}, reason={reason}"
            )
            return bool(match_value), float(score_value), reason
        except json.JSONDecodeError as e:
            error_msg = f"Error parsing LLM response as JSON: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Raw response was: {result_text}")

            # Last-ditch effort: try a very flexible pattern to extract key information
            # Look for match/score/reason patterns directly
            try:
                match_pattern = r'"?match"?\s*[:=]\s*(true|false)'
                score_pattern = r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)'
                reason_pattern = r'"?reason"?\s*[:=]\s*"([^"]*)"'

                match_search = re.search(match_pattern, result_text.lower())
                score_search = re.search(score_pattern, result_text.lower())
                reason_search = re.search(reason_pattern, result_text)

                if match_search and score_search:
                    match_value = match_search.group(1).lower() == "true"
                    score_value = float(score_search.group(1))
                    reason = (
                        reason_search.group(1)
                        if reason_search
                        else "No reason extracted"
                    )

                    logger.info(
                        f"LLM evaluation for {name} (extracted from text): match={match_value}, score={score_value}"
                    )
                    return bool(match_value), float(score_value), reason
            except Exception as extract_error:
                logger.error(
                    f"Failed to extract values from malformed response: {str(extract_error)}"
                )

            logger.error(
                f'Response from LLM must be JSON like: {"match": boolean, "score": float, "reason": string}'
            )
            return False, 0.0, error_msg
        except Exception as e:
            error_msg = f"Unexpected error processing LLM response: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Raw response was: {result_text}")
            return False, 0.0, error_msg

    except Exception as e:
        error_msg = f"Error in LLM evaluation for {attr_name}: {str(e)}"
        logger.error(error_msg)
        return False, 0.0, error_msg
