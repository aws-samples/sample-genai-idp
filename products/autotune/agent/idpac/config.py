# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""IDPConfig - Manipulate IDP Accelerator config.yaml files.

CONFIG BEST PRACTICES
=====================

OCR Configuration
-----------------
OCR extracts text from document images before classification/extraction.

Why OCR in Pattern-2 (Multimodal)?
  Pattern-2 prompts use BOTH {DOCUMENT_TEXT} (OCR) and {DOCUMENT_IMAGE}:
  - OCR text: Clean, searchable text for finding values/keywords
  - Image: Visual context - layout, logos, signatures, spatial relationships
  - Together: Better accuracy than either alone (hybrid approach)

Backends (ocr.backend):
  - "textract": AWS Textract - fast, cheap, limited language support
  - "bedrock": LLM-based OCR - slower, costlier, supports all languages
  - "none": Skip OCR, image-only mode (for multimodal LLM extraction)

When to disable OCR (backend: "none"):
  - Simple documents where visual-only is sufficient
  - Highly capable multimodal model reading images directly
  - Reducing pipeline complexity/cost (accept potential accuracy tradeoff)

Textract Features (ocr.features[].name):
  - LAYOUT: Preserves document structure (recommended default)
  - TABLES: Extracts table structures
  - FORMS: Extracts key-value pairs from forms
  - SIGNATURES: Detects signatures

Textract Language Support (printed text only):
  English, Spanish, German, French, Italian, Portuguese
  For other languages (Chinese, Japanese, Korean, Arabic, etc.) use Bedrock.

Bedrock OCR Settings (when backend="bedrock"):
  - ocr.model_id: Bedrock model (e.g., "us.amazon.nova-2-lite-v1:0")
  - ocr.system_prompt: System prompt for OCR
  - ocr.task_prompt: Task prompt for OCR

Image Settings (ocr.image.*):
  - target_width/target_height: Resize limits (default: 951x1268)
  - dpi: PDF conversion DPI (default: 150)
  - preprocessing: Enable image preprocessing for low-quality scans

Schema Requirements (classes[].*)
---------------------------------
Each document class schema MUST have:
  - $id: Unique identifier for the class (e.g., "Invoice")
  - x-aws-idp-document-type: REQUIRED - Maps LLM classification output to schema.
    Without this, classification returns "undefined" and extraction is skipped (0% accuracy).
  - $schema: JSON Schema declaration (https://json-schema.org/draft/2020-12/schema)
  - type: object

Per-Field Evaluation Extensions (properties.*):
  - x-aws-idp-evaluation-method: How to compare extracted vs ground truth values
      * EXACT: Exact string match
      * NUMERIC_EXACT: Numeric comparison (use for amounts, quantities)
      * FUZZY: Fuzzy string matching
      * LEVENSHTEIN: Edit distance comparison
      * SEMANTIC: Semantic similarity (uses embeddings)
      * LLM: LLM-based comparison (most flexible, highest cost)
      * HUNGARIAN: For arrays of objects - optimal matching algorithm
  - x-aws-idp-evaluation-threshold: Match threshold 0.0-1.0 (e.g., 0.7 for 70% similarity)
  - x-aws-idp-evaluation-weight: Field importance multiplier (e.g., 2.0 for critical fields)
  - x-aws-idp-confidence-threshold: Minimum confidence for HITL routing (used by assessment)

Array Fields (LineItems, etc.):
  - Use $defs to define reusable item schemas
  - Reference with $ref: '#/$defs/LineItem'
  - Set evaluation methods on individual item properties, not the array itself

Assessment vs Evaluation
------------------------
These are TWO DIFFERENT FEATURES that both use the config:

ASSESSMENT (runtime, every document):
  - Runs DURING document processing in the Step Functions workflow
  - LLM analyzes extraction results against source document
  - Generates CONFIDENCE SCORES (0.0-1.0) for each field
  - Purpose: "How confident are we in this extraction?"
  - Used for Human-in-the-Loop (HITL) routing
  - ADDS LATENCY AND COST TO EVERY DOCUMENT
  - Granular mode processes each list item separately → can timeout on large arrays
  - Config: assessment.enabled, assessment.granular.enabled

EVALUATION (test-time only):
  - Runs AFTER extraction to compare against ground truth baselines
  - Uses comparison methods (EXACT, FUZZY, LEVENSHTEIN, etc.)
  - Generates ACCURACY SCORES by comparing to known-correct values
  - Purpose: "How accurate is extraction compared to ground truth?"
  - ONLY runs during Test Studio evaluations (when baselines exist)
  - Config: evaluation.enabled, x-aws-idp-evaluation-* schema extensions

Summarization
-------------
  - summarization.enabled: Generate document summaries (adds latency/cost per document)
  - Disable for initial testing: summarization.enabled: false

Recommended Starting Config
---------------------------
For initial optimization, start with a minimal config:
  - assessment.enabled: false (enable after extraction works, if HITL needed)
  - summarization.enabled: false (enable if summaries needed)
  - Focus on getting extraction accuracy right first
  - The verified config in config_library uses assessment.enabled: false
"""

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML

# Valid patterns for system defaults
VALID_PATTERNS = ["pattern-1", "pattern-2"]

# OCR constants
VALID_OCR_BACKENDS = frozenset(["textract", "bedrock", "none"])
VALID_TEXTRACT_FEATURES = frozenset(["LAYOUT", "TABLES", "FORMS", "SIGNATURES"])
TEXTRACT_SUPPORTED_LANGUAGES = frozenset(["English", "Spanish", "German", "French", "Italian", "Portuguese"])

# Schema constants
X_AWS_IDP_DOCUMENT_TYPE = "x-aws-idp-document-type"
X_AWS_IDP_EVALUATION_METHOD = "x-aws-idp-evaluation-method"
JSON_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"

# Valid evaluation methods
VALID_EVALUATION_METHODS = frozenset([
    "EXACT", "NUMERIC_EXACT", "FUZZY", "LEVENSHTEIN", "SEMANTIC", "LLM", "HUNGARIAN"
])


@dataclass
class ValidationResult:
    """Result of config validation."""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = []
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            lines.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            lines.extend(f"  - {w}" for w in self.warnings)
        if self.is_valid and not self.warnings:
            lines.append("Config is valid.")
        return "\n".join(lines)


class IDPConfig:
    """Manipulate IDP Accelerator config.yaml files."""

    def __init__(self, config_path: str):
        """Load config from YAML file.

        Args:
            config_path: Path to config.yaml file
        """
        self.config_path = Path(config_path)
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096  # Prevent line wrapping

        with open(self.config_path) as f:
            self.data = self._yaml.load(f)

    def save(self, output_path: Optional[str] = None) -> str:
        """Save config to YAML file.

        Args:
            output_path: Path to save to (defaults to original path)

        Returns:
            Path where config was saved
        """
        path = Path(output_path) if output_path else self.config_path
        with open(path, "w") as f:
            self._yaml.dump(self.data, f)
        return str(path)

    def print(self, fields: Optional[list[str]] = None) -> None:
        """Pretty-print config or specific fields.

        Args:
            fields: List of dot-notation paths to print (e.g., ["extraction.model", "classes"])
                   If None, prints entire config
        """
        import sys

        if fields is None:
            self._yaml.dump(self.data, sys.stdout)
        else:
            for field in fields:
                value = self.get(field)
                print(f"{field}:")
                if isinstance(value, (dict, list)):
                    self._yaml.dump(value, sys.stdout)
                else:
                    print(f"  {value}")
                print()

    def get(self, field: str) -> Any:
        """Get a field value using dot notation with array index support.

        Args:
            field: Dot-notation path (e.g., "extraction.model", "classes.0.$schema")

        Returns:
            Field value, or None if not found
        """
        keys = field.split(".")
        value = self.data
        for key in keys:
            if isinstance(value, (list, tuple)) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(value):
                    value = value[idx]
                else:
                    return None
            elif isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def set(self, field: str, value: Any) -> None:
        """Set a field value using dot notation with array index support.

        Args:
            field: Dot-notation path (e.g., "extraction.task_prompt", "classes.0.properties.Field.x-aws-idp-evaluation-method")
            value: New value to set
        """
        keys = field.split(".")
        target = self.data
        for key in keys[:-1]:
            if isinstance(target, (list, tuple)) and key.isdigit():
                target = target[int(key)]
            elif isinstance(target, dict):
                if key not in target:
                    target[key] = {}
                target = target[key]
            else:
                raise ValueError(f"Cannot traverse path at '{key}': target is {type(target)}")
        
        final_key = keys[-1]
        if isinstance(target, (list, tuple)) and final_key.isdigit():
            target[int(final_key)] = value
        else:
            target[final_key] = value

    # --- Multi-Class Support ---

    def get_class_names(self) -> list[str]:
        """Return list of class $id values from config."""
        classes = self.get("classes") or []
        return [c.get("$id") for c in classes if c.get("$id")]

    def get_class_by_name(self, class_name: str) -> dict | None:
        """Get class schema by $id."""
        classes = self.get("classes") or []
        for c in classes:
            if c.get("$id") == class_name:
                return c
        return None

    def add_class(self, schema: dict) -> None:
        """Add a new document class schema to config.classes[].
        
        Args:
            schema: JSON schema dict with $id, x-aws-idp-document-type, properties, etc.
        """
        if "classes" not in self.data or self.data["classes"] is None:
            self.data["classes"] = []
        self.data["classes"].append(schema)

    # NOTE: Classification config fields (classification.enabled is NOT valid):
    # - classificationMethod: 'multimodalPageLevelClassification' or 'textbasedHolisticClassification'
    # - sectionSplitting: 'disabled' (single section), 'page' (one per page), 'llm_determined' (default, LLM boundaries)
    # - model: Bedrock model ID (default: us.amazon.nova-2-lite-v1:0)
    # - system_prompt, task_prompt, temperature, top_p, top_k, max_tokens
    # Classification is always enabled when multiple classes are defined.

    def _get_all_paths(self, data: Optional[dict] = None, prefix: str = "") -> list[str]:
        """Get all dot-notation paths in the config."""
        if data is None:
            data = self.data
        paths = []
        for key, value in data.items():
            current_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                paths.extend(self._get_all_paths(value, current_path))
            else:
                paths.append(current_path)
        return paths

    @staticmethod
    def _compare(config1: "IDPConfig", config2: "IDPConfig", name1: str, name2: str) -> list[dict]:
        """Compare two configs and return differences."""
        all_paths = set(config1._get_all_paths()) | set(config2._get_all_paths())
        
        differences = []
        for path in sorted(all_paths):
            val1 = config1.get(path)
            val2 = config2.get(path)
            
            str1 = str(val1).strip() if val1 is not None else None
            str2 = str(val2).strip() if val2 is not None else None
            
            if str1 != str2:
                differences.append({
                    "setting": path,
                    "values": {name1: str1, name2: str2}
                })
        
        return differences

    @staticmethod
    def print_comparison(path1: str, path2: str, name1: str = None, name2: str = None) -> None:
        """Load two configs and print their differences.

        Args:
            path1: Path to first config file
            path2: Path to second config file
            name1: Label for first config (defaults to filename)
            name2: Label for second config (defaults to filename)
        """
        config1 = IDPConfig(path1)
        config2 = IDPConfig(path2)
        
        name1 = name1 or Path(path1).name
        name2 = name2 or Path(path2).name
        
        differences = IDPConfig._compare(config1, config2, name1, name2)
        
        if not differences:
            print("No differences found.")
            return
        
        print(f"Found {len(differences)} differences:\n")
        for diff in differences:
            print(f"{diff['setting']}:")
            for name, value in diff["values"].items():
                display_val = value if value and len(value) < 80 else (value[:77] + "..." if value else "None")
                print(f"  {name}: {display_val}")
            print()

    # --- System Defaults Support (v0.4.12+) ---

    def merge_with_defaults(self, pattern: str = "pattern-2") -> "IDPConfig":
        """Merge this config with system defaults.

        User values take precedence. Missing fields are populated from defaults.

        Args:
            pattern: Pattern name (pattern-1, pattern-2)

        Returns:
            New IDPConfig with merged data (original unchanged)
        """
        from idp_common.config.merge_utils import merge_config_with_defaults

        merged_data = merge_config_with_defaults(self.data, pattern)
        return IDPConfig._from_data(merged_data, apply_idpac_defaults=False)

    def to_minimal(self, pattern: str = "pattern-2") -> "IDPConfig":
        """Extract only non-default values (minimal config format).

        Returns a config containing only fields that differ from system defaults.
        Useful for converting verbose configs to the new minimal format.

        Args:
            pattern: Pattern to compare against

        Returns:
            New IDPConfig with only customized values
        """
        from idp_common.config.merge_utils import get_diff_dict, load_system_defaults

        defaults = load_system_defaults(pattern)
        diff = get_diff_dict(defaults, self.data)
        return IDPConfig._from_data(diff, apply_idpac_defaults=False)

    def diff_from_defaults(self, pattern: str = "pattern-2") -> list[dict]:
        """Show differences between this config and system defaults.

        Args:
            pattern: Pattern to compare against

        Returns:
            List of differences (same format as _compare)
        """
        from idp_common.config.merge_utils import load_system_defaults

        defaults = load_system_defaults(pattern)
        defaults_config = IDPConfig._from_data(defaults, apply_idpac_defaults=False)
        return IDPConfig._compare(defaults_config, self, "default", "custom")

    @classmethod
    def _from_data(cls, data: dict, apply_idpac_defaults: bool = True) -> "IDPConfig":
        """Create IDPConfig from dict without loading from file.
        
        Args:
            data: Config data dictionary
            apply_idpac_defaults: If True, apply IDPAC-recommended defaults
                (evaluation.enabled: true, summarization.enabled: false,
                 assessment.enabled: false)
        """
        instance = object.__new__(cls)
        instance.config_path = None
        instance._yaml = YAML()
        instance._yaml.preserve_quotes = True
        instance._yaml.width = 4096
        instance.data = deepcopy(data)
        
        if apply_idpac_defaults:
            # Ensure evaluation is enabled (needed for Test Studio accuracy measurement)
            if "evaluation" not in instance.data:
                instance.data["evaluation"] = {}
            if "enabled" not in instance.data["evaluation"]:
                instance.data["evaluation"]["enabled"] = True
            
            # Disable summarization by default (adds latency/cost, not needed for most use cases)
            if "summarization" not in instance.data:
                instance.data["summarization"] = {}
            instance.data["summarization"]["enabled"] = False

            # Disable assessment by default (adds cost/latency without improving extraction
            # accuracy — only useful for HITL confidence routing in production)
            if "assessment" not in instance.data:
                instance.data["assessment"] = {}
            instance.data["assessment"]["enabled"] = False
        
        return instance

    @classmethod
    def from_defaults(cls, pattern: str = "pattern-2") -> "IDPConfig":
        """Create IDPConfig from system defaults with IDPAC-recommended settings.

        IDPAC automatically sets:
          - evaluation.enabled: true (required for Test Studio accuracy measurement)

        Args:
            pattern: Pattern name (pattern-1, pattern-2)

        Returns:
            IDPConfig with system default values + IDPAC defaults
        """
        from idp_common.config.merge_utils import load_system_defaults

        if pattern not in VALID_PATTERNS:
            raise ValueError(f"Invalid pattern '{pattern}'. Valid: {VALID_PATTERNS}")
        return cls._from_data(load_system_defaults(pattern), apply_idpac_defaults=True)

    # --- Schema Validation (IDPAC Enhancement) ---

    def validate(self) -> ValidationResult:
        """Validate schema classes for evaluation compatibility.

        Checks for required x-aws-idp-* attributes that cause 0% accuracy if missing.
        Also warns about assessment/summarization settings that may cause issues.

        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult()
        classes = self.data.get("classes", [])

        if not classes:
            result.warnings.append("No document classes defined")
            return result

        # Check assessment settings
        assessment_enabled = self.data.get("assessment", {}).get("enabled", True)
        granular_enabled = self.data.get("assessment", {}).get("granular", {}).get("enabled", True)
        
        has_arrays = False
        has_evaluation_methods = False
        leaf_fields_missing_data_type = 0
        leaf_fields_total = 0

        for i, cls_def in enumerate(classes):
            prefix = f"classes[{i}]"
            cls_id = cls_def.get("$id", f"<unnamed-{i}>")

            # ERROR: Missing x-aws-idp-document-type (required for evaluation)
            if not cls_def.get(X_AWS_IDP_DOCUMENT_TYPE):
                result.is_valid = False
                result.errors.append(
                    f"{prefix} ({cls_id}): Missing '{X_AWS_IDP_DOCUMENT_TYPE}' - "
                    "evaluation will skip this class (0% accuracy)"
                )

            # WARNING: Missing type: object
            if cls_def.get("type") != "object":
                result.warnings.append(f"{prefix} ({cls_id}): Missing 'type: object'")

            # WARNING: Missing $schema
            if not cls_def.get("$schema"):
                result.warnings.append(f"{prefix} ({cls_id}): Missing '$schema' declaration")

            # Check properties (recursively)
            def _check_properties(props, path_prefix):
                nonlocal has_arrays, has_evaluation_methods
                nonlocal leaf_fields_missing_data_type, leaf_fields_total
                for prop_name, prop_def in props.items():
                    if not isinstance(prop_def, dict):
                        continue
                    prop_path = f"{path_prefix}.{prop_name}"
                    prop_type = prop_def.get("type")

                    # ERROR: Nullable type list (e.g. type: ["string", "null"])
                    # The evaluator cannot hash list types, causing "unhashable type: 'list'" errors
                    if isinstance(prop_type, list):
                        result.is_valid = False
                        result.errors.append(
                            f"{prop_path}: 'type' is a list {prop_type} — "
                            "the evaluator cannot handle this (unhashable type: 'list'). "
                            "Use a single type string instead (e.g. 'string'). "
                            "Run auto_fix(['fix_nullable_types']) to fix automatically."
                        )

                    if prop_type == "array":
                        has_arrays = True
                        if "items" not in prop_def:
                            result.is_valid = False
                            result.errors.append(f"{prop_path}: Array type missing 'items' definition")
                        else:
                            items = prop_def["items"]
                            if isinstance(items, dict) and items.get("type") == "object":
                                _check_properties(items.get("properties", {}), f"{prop_path}[]")

                    if prop_type == "object" and "properties" in prop_def:
                        _check_properties(prop_def["properties"], prop_path)

                    if prop_def.get(X_AWS_IDP_EVALUATION_METHOD):
                        has_evaluation_methods = True

                    # Track leaf fields missing data_type
                    if prop_type in ("string", "number", "integer", "boolean"):
                        leaf_fields_total += 1
                        if not prop_def.get("data_type"):
                            leaf_fields_missing_data_type += 1

            props = cls_def.get("properties", {})
            _check_properties(props, prefix + ".properties")
            # Also check $defs
            for def_name, def_val in cls_def.get("$defs", {}).items():
                if isinstance(def_val, dict) and "properties" in def_val:
                    _check_properties(def_val["properties"], f"{prefix}.$defs.{def_name}")

        # WARNINGS about assessment
        if assessment_enabled:
            result.warnings.append(
                "assessment.enabled=true: Assessment adds an extra LLM call per document, "
                "increasing cost and latency without affecting extraction accuracy. "
                "It is only needed for HITL confidence routing in production. "
                "Consider setting assessment.enabled: false during config optimization."
            )
            if granular_enabled and has_arrays:
                result.warnings.append(
                    "assessment.granular.enabled=true with array fields: "
                    "May cause timeouts on documents with many line items. "
                    "Consider setting assessment.enabled: false for initial testing."
                )

        # INFO: No evaluation methods configured
        if not has_evaluation_methods:
            result.warnings.append(
                "No x-aws-idp-evaluation-method configured on any field. "
                "Evaluation will use default comparison methods. "
                "For better accuracy measurement, configure per-field evaluation methods."
            )

        # INFO: Missing data_type on leaf fields
        if leaf_fields_missing_data_type > 0:
            result.warnings.append(
                f"{leaf_fields_missing_data_type}/{leaf_fields_total} leaf fields missing 'data_type'. "
                "Adding data_type (string, number, boolean) improves extraction accuracy. "
                "Run auto_fix(['add_data_type']) to add automatically."
            )

        # Multi-class validation
        if len(classes) > 1:
            # Check classification is configured (has model or prompts)
            # Note: classification.enabled is NOT a valid field - classification is always
            # enabled when multiple classes are defined. Use classificationMethod to control behavior.
            classification = self.data.get("classification", {})
            has_classification_config = classification.get("model") or classification.get("task_prompt")
            
            if not has_classification_config:
                result.warnings.append(
                    f"Multiple classes ({len(classes)}) defined but no classification config found. "
                    "System defaults will be used. Configure classification.model and classification.task_prompt for custom behavior."
                )
            
            # Check for duplicate $id or x-aws-idp-document-type
            ids = [c.get("$id") for c in classes]
            doc_types = [c.get(X_AWS_IDP_DOCUMENT_TYPE) for c in classes]
            
            if len(ids) != len(set(filter(None, ids))):
                result.is_valid = False
                result.errors.append("Duplicate class $id values found - each class must have unique $id")
            
            if len(doc_types) != len(set(filter(None, doc_types))):
                result.is_valid = False
                result.errors.append("Duplicate x-aws-idp-document-type values found - each class must have unique document type")

        return result

    def auto_fix(self, fixes: Optional[list[str]] = None) -> "IDPConfig":
        """Apply automatic fixes to common schema issues.

        Args:
            fixes: List of fixes to apply. If None, applies all safe fixes.
                   Options:
                     - 'add_document_type': Copy $id to x-aws-idp-document-type
                     - 'add_schema': Add $schema declaration
                     - 'add_type_object': Add type: object
                     - 'fix_nullable_types': Replace type: ["string", "null"] with type: "string"
                     - 'add_data_type': Add data_type annotation to leaf fields based on type
                     - 'disable_assessment': Set assessment.enabled: false
                     - 'disable_summarization': Set summarization.enabled: false

        Returns:
            New IDPConfig with fixes applied (original unchanged)
        """
        # Default safe fixes (schema-only, doesn't change behavior)
        default_fixes = {"add_document_type", "add_schema", "add_type_object", "fix_nullable_types", "add_data_type"}
        all_fixes = default_fixes | {"disable_assessment", "disable_summarization"}
        fixes_to_apply = set(fixes) if fixes else default_fixes

        invalid = fixes_to_apply - all_fixes
        if invalid:
            raise ValueError(f"Unknown fixes: {invalid}. Valid: {all_fixes}")

        # Don't apply IDPAC defaults - we're modifying an existing config, not creating new
        new_config = IDPConfig._from_data(self.data, apply_idpac_defaults=False)
        classes = new_config.data.get("classes", [])

        for cls_def in classes:
            cls_id = cls_def.get("$id")

            if "add_document_type" in fixes_to_apply:
                if not cls_def.get(X_AWS_IDP_DOCUMENT_TYPE) and cls_id:
                    cls_def[X_AWS_IDP_DOCUMENT_TYPE] = cls_id

            if "add_schema" in fixes_to_apply:
                if not cls_def.get("$schema"):
                    cls_def["$schema"] = JSON_SCHEMA_URL

            if "add_type_object" in fixes_to_apply:
                if cls_def.get("type") != "object":
                    cls_def["type"] = "object"

            if "fix_nullable_types" in fixes_to_apply:
                def _fix_nullable(schema):
                    for prop_name, prop_def in schema.get("properties", {}).items():
                        if not isinstance(prop_def, dict):
                            continue
                        t = prop_def.get("type")
                        if isinstance(t, list):
                            non_null = [x for x in t if x != "null"]
                            prop_def["type"] = non_null[0] if non_null else "string"
                        if prop_def.get("type") == "object":
                            _fix_nullable(prop_def)
                        if prop_def.get("type") == "array":
                            items = prop_def.get("items", {})
                            if isinstance(items, dict) and items.get("type") == "object":
                                _fix_nullable(items)
                    for def_val in schema.get("$defs", {}).values():
                        if isinstance(def_val, dict):
                            _fix_nullable(def_val)
                _fix_nullable(cls_def)

            if "add_data_type" in fixes_to_apply:
                _type_map = {"string": "string", "number": "number", "integer": "number", "boolean": "boolean"}
                def _add_data_type(schema):
                    for prop_def in schema.get("properties", {}).values():
                        if not isinstance(prop_def, dict):
                            continue
                        t = prop_def.get("type")
                        if t in _type_map and "data_type" not in prop_def:
                            prop_def["data_type"] = _type_map[t]
                        if t == "object":
                            _add_data_type(prop_def)
                        if t == "array":
                            items = prop_def.get("items", {})
                            if isinstance(items, dict) and items.get("type") == "object":
                                _add_data_type(items)
                    for def_val in schema.get("$defs", {}).values():
                        if isinstance(def_val, dict):
                            _add_data_type(def_val)
                _add_data_type(cls_def)

        # Behavior-changing fixes
        if "disable_assessment" in fixes_to_apply:
            if "assessment" not in new_config.data:
                new_config.data["assessment"] = {}
            new_config.data["assessment"]["enabled"] = False

        if "disable_summarization" in fixes_to_apply:
            if "summarization" not in new_config.data:
                new_config.data["summarization"] = {}
            new_config.data["summarization"]["enabled"] = False

        return new_config
