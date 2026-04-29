# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Constants for AWS IDP-specific JSON Schema extensions.

These custom fields extend standard JSON Schema to support IDP-specific features
like document types, attribute types, and evaluation methods.
"""

# ============================================================================
# JSON Schema Standard Fields
# ============================================================================
SCHEMA_FIELD = "$schema"
ID_FIELD = "$id"
DEFS_FIELD = "$defs"
REF_FIELD = "$ref"

# ============================================================================
# AWS IDP Document Type Extensions
# ============================================================================
# Marks a schema as a document type (top-level class)
X_AWS_IDP_DOCUMENT_TYPE = "x-aws-idp-document-type"

# Classification metadata for document type
X_AWS_IDP_CLASSIFICATION = "x-aws-idp-classification"

# Regex patterns for classification optimization
X_AWS_IDP_DOCUMENT_NAME_REGEX = "x-aws-idp-document-name-regex"
X_AWS_IDP_PAGE_CONTENT_REGEX = "x-aws-idp-document-page-content-regex"

# Classes whose pages contain only static content (instructions, legal
# boilerplate, cover pages, etc.) can be marked with this extension. When
# true, downstream services (extraction, assessment, summarization,
# rule_validation, evaluation) will skip sections classified as this class.
X_AWS_IDP_EXCLUDE_FROM_PROCESSING = "x-aws-idp-exclude-from-processing"

# Optional short reason/category for why a class is excluded
# (e.g., "instructions", "legal", "cover-page"). Used for UI badges and
# evaluation report annotations.
X_AWS_IDP_EXCLUSION_REASON = "x-aws-idp-exclusion-reason"

# ============================================================================
# AWS IDP Extraction Extensions
# ============================================================================
# Per-class model override for extraction (overrides extraction.model)
X_AWS_IDP_EXTRACTION_MODEL = "x-aws-idp-extraction-model"

# ============================================================================
# Legacy Attribute Type Values (for migration only)
# ============================================================================
# These map to standard JSON Schema types:
# - "simple" → type: "string"
# - "group" → type: "object" with properties
# - "list" → type: "array" with items
ATTRIBUTE_TYPE_SIMPLE = "simple"
ATTRIBUTE_TYPE_GROUP = "group"
ATTRIBUTE_TYPE_LIST = "list"

# ============================================================================
# AWS IDP List-Specific Extensions
# ============================================================================
# Description for list items
X_AWS_IDP_LIST_ITEM_DESCRIPTION = "x-aws-idp-list-item-description"

# Original attribute name (preserved from legacy format)
X_AWS_IDP_ORIGINAL_NAME = "x-aws-idp-original-name"


# ============================================================================
# AWS IDP Evaluation Extensions
# ============================================================================
# Evaluation method for attribute comparison (maps to Stickler comparators)
X_AWS_IDP_EVALUATION_METHOD = "x-aws-idp-evaluation-method"

# Evaluation threshold for comparison (0.0 to 1.0)
X_AWS_IDP_EVALUATION_THRESHOLD = "x-aws-idp-evaluation-threshold"

# Evaluation weight for field importance (business criticality)
X_AWS_IDP_EVALUATION_WEIGHT = "x-aws-idp-evaluation-weight"

# Model name for evaluation (document-level configuration)
X_AWS_IDP_EVALUATION_MODEL_NAME = "x-aws-idp-evaluation-model-name"

# Match threshold for overall document evaluation (0.0 to 1.0)
X_AWS_IDP_EVALUATION_MATCH_THRESHOLD = "x-aws-idp-evaluation-match-threshold"

X_AWS_IDP_EXAMPLES = "x-aws-idp-examples"

# Valid evaluation methods
EVALUATION_METHOD_EXACT = "EXACT"
EVALUATION_METHOD_NUMERIC_EXACT = "NUMERIC_EXACT"
EVALUATION_METHOD_FUZZY = "FUZZY"
EVALUATION_METHOD_LEVENSHTEIN = "LEVENSHTEIN"
EVALUATION_METHOD_SEMANTIC = "SEMANTIC"
EVALUATION_METHOD_LLM = "LLM"
EVALUATION_METHOD_HUNGARIAN = "HUNGARIAN"

VALID_EVALUATION_METHODS = frozenset(
    [
        EVALUATION_METHOD_EXACT,
        EVALUATION_METHOD_NUMERIC_EXACT,
        EVALUATION_METHOD_FUZZY,
        EVALUATION_METHOD_LEVENSHTEIN,
        EVALUATION_METHOD_SEMANTIC,
        EVALUATION_METHOD_LLM,
        EVALUATION_METHOD_HUNGARIAN,
    ]
)

# Legacy: Confidence threshold for evaluation (0.0 to 1.0)
# Note: This is now superseded by X_AWS_IDP_EVALUATION_THRESHOLD
X_AWS_IDP_CONFIDENCE_THRESHOLD = "x-aws-idp-confidence-threshold"

# ============================================================================
# AWS IDP Prompt Extensions
# ============================================================================
# Custom prompt override for attribute extraction
X_AWS_IDP_PROMPT_OVERRIDE = "x-aws-idp-prompt-override"

# Maximum length for prompt overrides
MAX_PROMPT_OVERRIDE_LENGTH = 10000

# ============================================================================
# AWS IDP Example Extensions
# ============================================================================
# Extensions for few-shot example support
X_AWS_IDP_CLASS_PROMPT = "x-aws-idp-class-prompt"
X_AWS_IDP_ATTRIBUTES_PROMPT = "x-aws-idp-attributes-prompt"
X_AWS_IDP_IMAGE_PATH = "x-aws-idp-image-path"

# ============================================================================
# Legacy Format Field Names
# ============================================================================
# These are the field names used in the legacy format
LEGACY_ATTRIBUTES = "attributes"
LEGACY_NAME = "name"
LEGACY_DESCRIPTION = "description"
LEGACY_ATTRIBUTE_TYPE = "attributeType"
LEGACY_GROUP_ATTRIBUTES = "groupAttributes"
LEGACY_LIST_ITEM_TEMPLATE = "listItemTemplate"
LEGACY_ITEM_ATTRIBUTES = "itemAttributes"
LEGACY_ITEM_DESCRIPTION = "itemDescription"
LEGACY_EVALUATION_METHOD = "evaluation_method"
LEGACY_CONFIDENCE_THRESHOLD = "confidence_threshold"
LEGACY_PROMPT_OVERRIDE = "prompt_override"

# Legacy example fields
LEGACY_EXAMPLES = "examples"
LEGACY_CLASS_PROMPT = "classPrompt"
LEGACY_ATTRIBUTES_PROMPT = "attributesPrompt"
LEGACY_IMAGE_PATH = "imagePath"

# Legacy regex fields (same name in both legacy and new format)
LEGACY_DOCUMENT_NAME_REGEX = "document_name_regex"
LEGACY_DOCUMENT_PAGE_CONTENT_REGEX = "document_page_content_regex"

# ============================================================================
# JSON Schema Standard Property Names
# ============================================================================
SCHEMA_TYPE = "type"
SCHEMA_PROPERTIES = "properties"
SCHEMA_ITEMS = "items"
SCHEMA_REQUIRED = "required"
SCHEMA_DESCRIPTION = "description"

# JSON Schema type values
TYPE_OBJECT = "object"
TYPE_ARRAY = "array"
TYPE_STRING = "string"
TYPE_NUMBER = "number"
TYPE_INTEGER = "integer"
TYPE_BOOLEAN = "boolean"
TYPE_NULL = "null"
