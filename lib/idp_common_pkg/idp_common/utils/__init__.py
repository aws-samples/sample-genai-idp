# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import random
import time
import logging
from typing import Tuple, Dict, Any, Optional

# Import yaml with fallback for systems that don't have it installed
try:
    import yaml
except ImportError:
    yaml = None

# Import Lambda metering utility
from .lambda_metering import calculate_lambda_metering

logger = logging.getLogger(__name__)

# Common backoff constants
MAX_RETRIES = 7
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300    # 5 minutes

def calculate_backoff(attempt: int, initial_backoff: float = INITIAL_BACKOFF, 
                     max_backoff: float = MAX_BACKOFF) -> float:
    """
    Calculate exponential backoff with jitter
    
    Args:
        attempt: The current retry attempt number (0-based)
        initial_backoff: Starting backoff in seconds
        max_backoff: Maximum backoff cap in seconds
        
    Returns:
        Backoff time in seconds
    """
    backoff = min(max_backoff, initial_backoff * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * backoff)  # 10% jitter
    return backoff + jitter

def parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    """
    Parse an S3 URI into bucket and key
    
    Args:
        s3_uri: The S3 URI in format s3://bucket/key
        
    Returns:
        Tuple of (bucket, key)
    """
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI: {s3_uri}. Must start with s3://")
        
    parts = s3_uri.split('/', 3)
    if len(parts) < 4:
        raise ValueError(f"Invalid S3 URI: {s3_uri}. Format should be s3://bucket/key")
        
    bucket = parts[2]
    key = parts[3]
    return bucket, key

def build_s3_uri(bucket: str, key: str) -> str:
    """
    Build an S3 URI from bucket and key
    
    Args:
        bucket: The S3 bucket name
        key: The S3 object key
        
    Returns:
        S3 URI in format s3://bucket/key
    """
    return f"s3://{bucket}/{key}"

def merge_metering_data(existing_metering: Dict[str, Any], 
                       new_metering: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge metering data from multiple sources
    
    Args:
        existing_metering: Existing metering data to merge into
        new_metering: New metering data to add
        
    Returns:
        Merged metering data
    """
    merged = existing_metering.copy()
    
    for service_api, metrics in new_metering.items():
        if isinstance(metrics, dict):
            for unit, value in metrics.items():
                if service_api not in merged:
                    merged[service_api] = {}
                
                # Convert both values to numbers to handle string vs int mismatch
                try:
                    existing_value = merged[service_api].get(unit, 0)
                    # Handle both string and numeric values
                    if isinstance(existing_value, str):
                        existing_value = float(existing_value)
                    if isinstance(value, str):
                        value = float(value)
                    
                    merged[service_api][unit] = existing_value + value
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error converting metering values for {service_api}.{unit}: existing={merged[service_api].get(unit)}, new={value}, error={e}")
                    # Fallback to new value if conversion fails
                    merged[service_api][unit] = value
        else:
            logger.warning(f"Unexpected metering data format for {service_api}: {metrics}")
            
    return merged

def extract_json_from_text(text: str) -> str:
    """
    Extract JSON string from LLM response text with improved multi-line handling.
    
    This enhanced version handles JSON with literal newlines and provides
    multiple fallback strategies for robust JSON extraction.
    
    This function handles multiple common formats:
    - JSON wrapped in ```json code blocks
    - JSON wrapped in ``` code blocks
    - Raw JSON objects with proper brace matching
    - Multi-line JSON with literal newlines in string values
    
    Args:
        text: The text response from the model
        
    Returns:
        Extracted JSON string, or original text if no JSON found
    """
    import json
    import re
    
    if not text:
        logger.warning("Empty text provided to extract_json_from_text")
        return text

    # Strategy 1: Check for code block format with json tag
    if "```json" in text:
        start_idx = text.find("```json") + len("```json")
        end_idx = text.find("```", start_idx)
        if end_idx > start_idx:
            json_str = text[start_idx:end_idx].strip()
            try:
                # Test if it's valid JSON
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                logger.debug(
                    "Found code block but content is not valid JSON, trying other strategies"
                )
    
    # Strategy 2: Check for generic code block format
    elif "```" in text:
        start_idx = text.find("```") + len("```")
        end_idx = text.find("```", start_idx)
        if end_idx > start_idx:
            json_str = text[start_idx:end_idx].strip()
            try:
                # Test if it's valid JSON
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                logger.debug(
                    "Found code block but content is not valid JSON, trying other strategies"
                )
    
    # Strategy 3: Extract JSON between braces and try direct parsing
    if "{" in text and "}" in text:
        start_idx = text.find("{")
        # Find matching closing brace
        open_braces = 0
        in_string = False
        escape_next = False
        
        for i in range(start_idx, len(text)):
            char = text[i]
            
            if escape_next:
                escape_next = False
                continue
                
            if char == "\\":
                escape_next = True
                continue
                
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
                
            if not in_string:
                if char == "{":
                    open_braces += 1
                elif char == "}":
                    open_braces -= 1
                    if open_braces == 0:
                        json_str = text[start_idx : i + 1].strip()
                        try:
                            # Test if it's valid JSON as-is
                            json.loads(json_str)
                            return json_str
                        except json.JSONDecodeError:
                            # If direct parsing fails, continue to next strategy
                            logger.debug(
                                "Found JSON-like content but direct parsing failed, trying normalization"
                            )
                            break

    # Strategy 4: Try to extract JSON using more aggressive methods
    try:
        # Find the outermost braces
        if "{" in text and "}" in text:
            start_idx = text.find("{")
            end_idx = text.rfind("}")  # Use rfind to get the last closing brace
            if end_idx > start_idx:
                json_str = text[start_idx : end_idx + 1]

                # Try parsing as-is first
                try:
                    json.loads(json_str)
                    return json_str
                except json.JSONDecodeError:
                    pass

                # Try normalizing the JSON string
                try:
                    # Method 1: Handle literal newlines by replacing with spaces
                    normalized_json = " ".join(
                        line.strip() for line in json_str.splitlines()
                    )
                    json.loads(normalized_json)
                    return normalized_json
                except json.JSONDecodeError:
                    pass

                # Method 2: Try a more aggressive approach with regex
                try:
                    # Remove extra whitespace but preserve structure
                    normalized_json = re.sub(r"\s+", " ", json_str)
                    json.loads(normalized_json)
                    return normalized_json
                except json.JSONDecodeError:
                    logger.debug("All normalization attempts failed")
    except Exception as e:
        logger.warning(f"Error during JSON extraction: {str(e)}")

    # If all strategies fail, return the original text
    logger.warning("Could not extract valid JSON, returning original text")
    return text


def normalize_boolean_value(value: Any) -> bool:
    """
    Normalize a value to a boolean, handling string representations.

    This function is useful for configuration values that may come as strings
    (e.g., from JSON config files or environment variables) but need to be
    treated as booleans.

    Args:
        value: Value to normalize (can be bool, str, or other)

    Returns:
        Boolean value
    """
    if isinstance(value, bool):
        return value
    elif isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")
    else:
        return bool(value)


def extract_yaml_from_text(text: str) -> str:
    """
    Extract YAML string from LLM response text with robust multi-strategy handling.
    
    This function handles multiple common formats:
    - YAML wrapped in ```yaml code blocks
    - YAML wrapped in ``` code blocks
    - Raw YAML with document markers (---)
    - Raw YAML content with proper indentation detection
    
    Args:
        text: The text response from the model
        
    Returns:
        Extracted YAML string, or original text if no YAML found
    """
    import re
    
    if yaml is None:
        logger.error("YAML library not available. Please install PyYAML to use YAML parsing functionality.")
        return text
    
    if not text:
        logger.warning("Empty text provided to extract_yaml_from_text")
        return text

    # Strategy 1: Check for code block format with yaml tag
    if "```yaml" in text:
        start_idx = text.find("```yaml") + len("```yaml")
        end_idx = text.find("```", start_idx)
        if end_idx > start_idx:
            yaml_str = text[start_idx:end_idx].strip()
            try:
                # Test if it's valid YAML
                yaml.safe_load(yaml_str)
                return yaml_str
            except yaml.YAMLError:
                logger.debug(
                    "Found yaml code block but content is not valid YAML, falling back to original text"
                )
                return text
    
    # Strategy 2: Check for code block format with yml tag
    elif "```yml" in text:
        start_idx = text.find("```yml") + len("```yml")
        end_idx = text.find("```", start_idx)
        if end_idx > start_idx:
            yaml_str = text[start_idx:end_idx].strip()
            try:
                # Test if it's valid YAML
                yaml.safe_load(yaml_str)
                return yaml_str
            except yaml.YAMLError:
                logger.debug(
                    "Found yml code block but content is not valid YAML, trying other strategies"
                )
    
    # Strategy 3: Check for generic code block format and validate as YAML
    elif "```" in text:
        start_idx = text.find("```") + len("```")
        end_idx = text.find("```", start_idx)
        if end_idx > start_idx:
            yaml_str = text[start_idx:end_idx].strip()
            try:
                # Test if it's valid YAML
                yaml.safe_load(yaml_str)
                return yaml_str
            except yaml.YAMLError:
                logger.debug(
                    "Found code block but content is not valid YAML, trying other strategies"
                )
    
    # Strategy 4: Look for YAML document markers (---)
    if "---" in text:
        # Find YAML document start
        start_marker = text.find("---")
        if start_marker != -1:
            # Look for document end marker or end of text
            start_idx = start_marker
            end_marker = text.find("---", start_marker + 3)
            if end_marker != -1:
                # Found end marker
                yaml_str = text[start_idx:end_marker].strip()
            else:
                # No end marker, take rest of text
                yaml_str = text[start_idx:].strip()
            
            try:
                # Test if it's valid YAML
                yaml.safe_load(yaml_str)
                return yaml_str
            except yaml.YAMLError:
                logger.debug(
                    "Found YAML document markers but content is not valid YAML, trying other strategies"
                )
    
    # Strategy 5: Try to detect YAML by looking for key indicators
    # Look for patterns like "key:" at the start of lines
    yaml_indicators = [
        r'^\s*\w+\s*:',  # key: value patterns
        r'^\s*-\s+\w+',  # list item patterns
        r'^\s*-\s*$',    # empty list items
    ]
    
    lines = text.split('\n')
    yaml_like_lines = 0
    total_non_empty_lines = 0
    
    for line in lines:
        if line.strip():
            total_non_empty_lines += 1
            for pattern in yaml_indicators:
                if re.match(pattern, line):
                    yaml_like_lines += 1
                    break
    
    # If more than 50% of non-empty lines look like YAML and we have at least 2 lines, try to parse the whole text
    if total_non_empty_lines >= 2 and yaml_like_lines / total_non_empty_lines > 0.5:
        try:
            yaml.safe_load(text)
            return text
        except yaml.YAMLError:
            logger.debug("Text appears YAML-like but is not valid YAML")
    
    # Strategy 6: Try to extract YAML-like content by finding indented blocks
    try:
        # Look for blocks that start with a key: pattern and have consistent indentation
        yaml_block_pattern = r'(?:^|\n)(\w+\s*:(?:\s*\n(?:\s{2,}.*\n?)*|\s*.*(?:\n|$))(?:\w+\s*:(?:\s*\n(?:\s{2,}.*\n?)*|\s*.*(?:\n|$)))*)'
        matches = re.findall(yaml_block_pattern, text, re.MULTILINE)
        
        for match in matches:
            try:
                yaml.safe_load(match)
                return match.strip()
            except yaml.YAMLError:
                continue
                
    except Exception as e:
        logger.debug(f"Error during YAML block extraction: {str(e)}")
    
    # If all strategies fail, return the original text
    logger.warning("Could not extract valid YAML, returning original text")
    return text


def detect_format(text: str) -> str:
    """
    Detect whether text contains JSON or YAML format.
    
    Args:
        text: The text to analyze
        
    Returns:
        'json', 'yaml', or 'unknown'
    """
    import json
    import re
    
    if yaml is None:
        logger.warning("YAML library not available. Format detection will only work for JSON.")
    
    if not text or not text.strip():
        return 'unknown'
    
    text = text.strip()
    
    # Check for explicit format indicators in code blocks
    if "```json" in text.lower():
        return 'json'
    elif "```yaml" in text.lower() or "```yml" in text.lower():
        return 'yaml'
    
    # Check for YAML document markers
    if text.startswith('---'):
        return 'yaml'
    
    # Check for JSON structural indicators
    if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
        # Try to parse as JSON first
        try:
            json.loads(text)
            return 'json'
        except json.JSONDecodeError:
            pass
    
    # Check for YAML structural indicators (only if yaml is available)
    if yaml is not None:
        yaml_patterns = [
            r'^\s*\w+\s*:',  # key: value at start of line
            r'^\s*-\s+',     # list items
            r':\s*\n\s+',    # multiline values
        ]
        
        for pattern in yaml_patterns:
            if re.search(pattern, text, re.MULTILINE):
                # Try to parse as YAML
                try:
                    yaml.safe_load(text)
                    return 'yaml'
                except yaml.YAMLError:
                    pass
    
    # Try parsing both formats to determine which works
    json_works = False
    yaml_works = False
    
    try:
        json.loads(text)
        json_works = True
    except (json.JSONDecodeError, TypeError):
        pass
    
    if yaml is not None:
        try:
            parsed_yaml = yaml.safe_load(text)
            # Only consider it valid YAML if it's a dict or list (structured data)
            # Plain strings are not considered structured YAML
            if isinstance(parsed_yaml, (dict, list)):
                yaml_works = True
        except yaml.YAMLError:
            pass
    
    # Return the format that works, preferring JSON if both work
    if json_works and yaml_works:
        return 'json'  # Prefer JSON if both formats are valid
    elif json_works:
        return 'json'
    elif yaml_works:
        return 'yaml'
    else:
        return 'unknown'


def extract_structured_data_from_text(text: str, preferred_format: str = 'auto') -> Tuple[Any, str]:
    """
    Extract structured data from text, supporting both JSON and YAML formats.
    
    This function automatically detects the format and parses the content,
    returning the parsed data structure and the detected format.
    
    Args:
        text: The text response from the model
        preferred_format: 'json', 'yaml', or 'auto' for automatic detection
        
    Returns:
        Tuple of (parsed_data, detected_format)
        - parsed_data: The parsed data structure (dict, list, etc.) or original text if parsing fails
        - detected_format: 'json', 'yaml', or 'unknown'
    """
    import json
    
    if yaml is None:
        logger.warning("YAML library not available. Structured data extraction will only work for JSON.")
    
    if not text:
        logger.warning("Empty text provided to extract_structured_data_from_text")
        return text, 'unknown'
    
    # Determine format to use
    if preferred_format == 'auto':
        detected_format = detect_format(text)
    else:
        detected_format = preferred_format.lower()
    
    # Extract and parse based on detected/preferred format
    if detected_format == 'json':
        try:
            json_str = extract_json_from_text(text)
            parsed_data = json.loads(json_str)
            return parsed_data, 'json'
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse as JSON: {e}")
            # Fallback to YAML if JSON parsing fails
            try:
                yaml_str = extract_yaml_from_text(text)
                parsed_data = yaml.safe_load(yaml_str)
                return parsed_data, 'yaml'
            except yaml.YAMLError as yaml_e:
                logger.warning(f"Fallback YAML parsing also failed: {yaml_e}")
                return text, 'unknown'
                
    elif detected_format == 'yaml':
        try:
            yaml_str = extract_yaml_from_text(text)
            # Check if YAML extraction actually found structured content
            if yaml_str == text:
                # YAML extraction fell back to original text
                # Check if the original text was detected as JSON format initially
                original_format = detect_format(text)
                if original_format == 'json':
                    # This is actually JSON, not YAML
                    raise yaml.YAMLError("Text is actually JSON format, not YAML")
                # If it's unknown format, also fall back
                elif original_format == 'unknown':
                    raise yaml.YAMLError("No valid YAML structure found")
            
            parsed_data = yaml.safe_load(yaml_str)
            # Only consider it successful if we got structured data (dict or list)
            if isinstance(parsed_data, (dict, list)):
                return parsed_data, 'yaml'
            else:
                # Got a simple string, not structured data
                raise yaml.YAMLError("YAML parsing returned simple string, not structured data")
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse as YAML: {e}")
            # Fallback to JSON if YAML parsing fails
            try:
                json_str = extract_json_from_text(text)
                parsed_data = json.loads(json_str)
                return parsed_data, 'json'
            except (json.JSONDecodeError, TypeError) as json_e:
                logger.warning(f"Fallback JSON parsing also failed: {json_e}")
                return text, 'unknown'
    
    else:
        # Unknown format - try both
        logger.info("Unknown format detected, trying both JSON and YAML parsing")
        
        # Try JSON first
        try:
            json_str = extract_json_from_text(text)
            parsed_data = json.loads(json_str)
            return parsed_data, 'json'
        except (json.JSONDecodeError, TypeError):
            pass
        
        # Try YAML second
        try:
            yaml_str = extract_yaml_from_text(text)
            # Check if YAML extraction actually found structured content
            if yaml_str == text:
                # YAML extraction fell back to original text, check if it's actually structured
                parsed_data = yaml.safe_load(yaml_str)
                if not isinstance(parsed_data, (dict, list)):
                    # Got a simple string, not structured data
                    raise yaml.YAMLError("YAML parsing returned simple string, not structured data")
            else:
                parsed_data = yaml.safe_load(yaml_str)
            return parsed_data, 'yaml'
        except yaml.YAMLError:
            pass
        
        # If both fail, return original text
        logger.warning("Could not parse as either JSON or YAML, returning original text")
        return text, 'unknown'

def check_token_limit(document_text: str, extraction_results: Dict[str, Any], config: Dict[str, Any]) -> \
Optional[str]:
    """
    Create token limit warning message based on the configured value of max_tokens

    Args:
        document_text: The document text content
        extraction_results: Extraction results dictionary
        config: Configuration dictionary containing model and assessment settings

    Returns:
        Error message based on the configured_max_tokens, None otherwise
    """
    # Information for logging and troubleshooting
    assessment_config = config.get("assessment", {})
    logger.info(f"assessment_config: {assessment_config}")
    model_id = config.get("model_id") or assessment_config.get("model", "unknown")
    logger.info(f"model_id: {model_id}")
    configured_max_tokens = assessment_config.get("max_tokens")
    logger.info(f"configured_max_tokens: {configured_max_tokens}")
    estimated_tokens = (len(document_text) + len(str(extraction_results))) / 4
    logger.info(f"Estimated tokens: {estimated_tokens}")
    if configured_max_tokens and int(configured_max_tokens) < estimated_tokens:
        return (
            f"The max_tokens value of {configured_max_tokens} is too low for this document."
        )
    else:
        logger.info(f"This document is configured with {int(configured_max_tokens)} max_tokens, "
                    f" requires approximately {int(estimated_tokens)} tokens.")
    return None
