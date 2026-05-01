# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Stickler Configuration Mapper.

This module provides mapping between IDP evaluation configuration
(using x-aws-idp-evaluation-* extensions) and Stickler configuration format.

The mapper acts as an abstraction layer, allowing the IDP system to use
neutral evaluation configuration that can be translated to Stickler's format.
"""

import copy
import logging
from typing import Any, Dict, List, Optional, Set

from idp_common.config.schema_constants import (
    EVALUATION_METHOD_EXACT,
    EVALUATION_METHOD_FUZZY,
    EVALUATION_METHOD_HUNGARIAN,
    EVALUATION_METHOD_LEVENSHTEIN,
    EVALUATION_METHOD_LLM,
    EVALUATION_METHOD_NUMERIC_EXACT,
    EVALUATION_METHOD_SEMANTIC,
    SCHEMA_DESCRIPTION,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_BOOLEAN,
    TYPE_INTEGER,
    TYPE_NUMBER,
    TYPE_OBJECT,
    TYPE_STRING,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_EVALUATION_MATCH_THRESHOLD,
    X_AWS_IDP_EVALUATION_METHOD,
    X_AWS_IDP_EVALUATION_MODEL_NAME,
    X_AWS_IDP_EVALUATION_THRESHOLD,
    X_AWS_IDP_EVALUATION_WEIGHT,
)

logger = logging.getLogger(__name__)


class SticklerConfigMapper:
    """
    Maps IDP evaluation configuration to Stickler configuration.

    This mapper provides a backend-agnostic abstraction layer that translates
    neutral IDP evaluation extensions into Stickler-specific format.

    Note: LLM comparator configuration is handled via global config in
    llm_comparator.py, not through schema extensions.
    """

    # Mapping from IDP evaluation methods to Stickler comparator class names
    METHOD_TO_COMPARATOR = {
        EVALUATION_METHOD_EXACT: "ExactComparator",
        EVALUATION_METHOD_NUMERIC_EXACT: "NumericComparator",
        EVALUATION_METHOD_FUZZY: "FuzzyComparator",
        EVALUATION_METHOD_LEVENSHTEIN: "LevenshteinComparator",
        EVALUATION_METHOD_SEMANTIC: "SemanticComparator",
        EVALUATION_METHOD_LLM: "LLMComparator",  # Uses global config from llm_comparator.py
        EVALUATION_METHOD_HUNGARIAN: None,  # Built-in for arrays
    }

    # Mapping from JSON Schema types to Stickler types
    JSON_SCHEMA_TO_STICKLER_TYPE = {
        TYPE_STRING: "str",
        TYPE_NUMBER: "float",
        TYPE_INTEGER: "int",
        TYPE_BOOLEAN: "bool",
        TYPE_OBJECT: "structured_model",
        TYPE_ARRAY: "list",
    }

    @classmethod
    def map_field_config(
        cls,
        field_name: str,
        field_schema: Dict[str, Any],
        parent_path: str = "",
        is_required: bool = True,
    ) -> Dict[str, Any]:
        """
        Map a single field's IDP evaluation config to Stickler format.

        This method only translates explicitly configured values - it does not
        inject defaults, allowing Stickler to use its own default values.

        Args:
            field_name: Name of the field
            field_schema: JSON Schema for the field with IDP extensions
            parent_path: Parent path for nested fields (for logging)
            is_required: Whether this field is required (affects optional flag)

        Returns:
            Stickler field configuration dict
        """
        stickler_config: Dict[str, Any] = {}
        full_path = f"{parent_path}.{field_name}" if parent_path else field_name

        # Handle $ref (reference to $defs)
        if "$ref" in field_schema:
            # This is a reference to a nested object definition
            stickler_config["type"] = "structured_model"
            stickler_config["fields"] = {}
            # Note: $ref resolution would need the full schema context
            # For now, we'll mark it as structured_model and let Stickler handle it
            logger.debug(
                f"Field '{full_path}': Detected $ref, will be structured_model"
            )
        else:
            # Field type (required)
            field_type = field_schema.get(SCHEMA_TYPE, TYPE_STRING)
            stickler_type = cls._map_type(field_type)
            stickler_config["type"] = stickler_type

        # Evaluation method -> Comparator
        eval_method = field_schema.get(X_AWS_IDP_EVALUATION_METHOD)
        if eval_method:
            comparator = cls.METHOD_TO_COMPARATOR.get(eval_method)
            if comparator:
                stickler_config["comparator"] = comparator
                logger.debug(
                    f"Field '{full_path}': Mapped method {eval_method} to {comparator}"
                )

                # Special case: NumericComparator uses 'tolerance' instead of 'threshold'
                if eval_method == EVALUATION_METHOD_NUMERIC_EXACT:
                    threshold = field_schema.get(X_AWS_IDP_EVALUATION_THRESHOLD)
                    if threshold is not None:
                        stickler_config["comparator_config"] = {"tolerance": threshold}
                        logger.debug(
                            f"Field '{full_path}': Set numeric tolerance to {threshold}"
                        )
            elif eval_method == EVALUATION_METHOD_HUNGARIAN:
                # Hungarian is handled automatically for arrays by Stickler
                logger.debug(
                    f"Field '{full_path}': Hungarian method - will be handled by Stickler for arrays"
                )
        else:
            logger.debug(
                f"Field '{full_path}': No evaluation method specified, will use Stickler default"
            )

        # Threshold (only for non-numeric comparators)
        if eval_method != EVALUATION_METHOD_NUMERIC_EXACT:
            threshold = field_schema.get(X_AWS_IDP_EVALUATION_THRESHOLD)
            if threshold is not None:
                stickler_config["threshold"] = threshold
                logger.debug(f"Field '{full_path}': Set threshold to {threshold}")

        # Weight (field importance)
        weight = field_schema.get(X_AWS_IDP_EVALUATION_WEIGHT)
        if weight is not None:
            stickler_config["weight"] = weight
            logger.debug(f"Field '{full_path}': Set weight to {weight}")

        # Description (always include if present)
        if SCHEMA_DESCRIPTION in field_schema:
            stickler_config["description"] = field_schema[SCHEMA_DESCRIPTION]

        # Handle nested objects (group attributes)
        if field_type == TYPE_OBJECT and SCHEMA_PROPERTIES in field_schema:
            stickler_config["type"] = "structured_model"
            stickler_config["fields"] = {}
            for prop_name, prop_schema in field_schema[SCHEMA_PROPERTIES].items():
                stickler_config["fields"][prop_name] = cls.map_field_config(
                    prop_name, prop_schema, full_path
                )
            logger.debug(
                f"Field '{full_path}': Mapped nested object with {len(stickler_config['fields'])} properties"
            )

        # Handle arrays (list attributes)
        if field_type == TYPE_ARRAY and SCHEMA_ITEMS in field_schema:
            items_schema = field_schema[SCHEMA_ITEMS]
            items_type = items_schema.get(SCHEMA_TYPE)

            if items_type == TYPE_OBJECT and SCHEMA_PROPERTIES in items_schema:
                # Structured list - Hungarian matching
                stickler_config["type"] = "list_structured_model"
                stickler_config["fields"] = {}
                for prop_name, prop_schema in items_schema[SCHEMA_PROPERTIES].items():
                    stickler_config["fields"][prop_name] = cls.map_field_config(
                        prop_name, prop_schema, f"{full_path}[]"
                    )
                logger.debug(
                    f"Field '{full_path}': Mapped list of structured objects with {len(stickler_config['fields'])} item properties"
                )
            else:
                # Simple list (list of primitives)
                stickler_config["type"] = "list"
                logger.debug(f"Field '{full_path}': Mapped simple list")

        return stickler_config

    @classmethod
    def _resolve_ref(
        cls, ref_path: str, document_class_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Resolve a $ref path to its definition in $defs.

        Args:
            ref_path: The $ref path (e.g., "#/$defs/Address")
            document_class_schema: Full document schema containing $defs

        Returns:
            The resolved schema definition
        """
        # Parse ref path like "#/$defs/Address"
        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.replace("#/$defs/", "")
            defs = document_class_schema.get("$defs", {})
            if def_name in defs:
                return defs[def_name]
            else:
                logger.warning(f"Could not resolve $ref: {ref_path}")
                return {}
        return {}

    @classmethod
    def _is_unevaluable_object(cls, schema: Dict[str, Any]) -> bool:
        """
        Check if an object schema cannot be evaluated by Stickler.

        Stickler requires object types to have a 'properties' key with at least
        one field. Objects that are free-form (using additionalProperties without
        defined properties) or have empty properties cannot be evaluated.

        Args:
            schema: JSON Schema dict to check

        Returns:
            True if the object schema cannot be evaluated by Stickler
        """
        if not isinstance(schema, dict):
            return False
        if schema.get(SCHEMA_TYPE) != TYPE_OBJECT:
            return False

        prop_properties = schema.get(SCHEMA_PROPERTIES)

        # Case 1: No 'properties' key at all (free-form object, e.g. additionalProperties: true)
        if prop_properties is None:
            return True

        # Case 2: Empty properties dict
        if isinstance(prop_properties, dict) and len(prop_properties) == 0:
            return True

        return False

    @classmethod
    def _remove_empty_object_properties(
        cls, schema: Dict[str, Any], field_path: str = ""
    ) -> List[str]:
        """
        Recursively remove properties that are objects without evaluable properties.

        Stickler's ModelFactory requires at least one field to create a Pydantic model.
        This method removes:
        - Object properties with empty properties (e.g., {"type": "object", "properties": {}})
        - Object properties with NO properties key (free-form objects, e.g.,
          {"type": "object", "additionalProperties": true})
        - Array properties whose items are unevaluable objects (e.g.,
          {"type": "array", "items": {"type": "object", "additionalProperties": true}})

        These cause validation errors in Stickler and provide no evaluation value.

        Args:
            schema: Schema to process (modified in-place)
            field_path: Current path for logging

        Returns:
            List of removed property paths for logging
        """
        removed: List[str] = []

        if not isinstance(schema, dict):
            return removed

        if SCHEMA_PROPERTIES in schema:
            props_to_remove = []

            for prop_name, prop_schema in schema[SCHEMA_PROPERTIES].items():
                prop_path = f"{field_path}.{prop_name}" if field_path else prop_name

                if not isinstance(prop_schema, dict):
                    continue

                prop_type = prop_schema.get(SCHEMA_TYPE)
                prop_properties = prop_schema.get(SCHEMA_PROPERTIES)

                if prop_type == TYPE_OBJECT:
                    if cls._is_unevaluable_object(prop_schema):
                        # Object with no properties or empty properties - remove it
                        props_to_remove.append(prop_name)
                        removed.append(prop_path)
                        has_additional = "additionalProperties" in prop_schema
                        logger.info(
                            f"Removing unevaluable object property '{prop_path}' - "
                            f"Stickler requires at least one field in nested objects"
                            f"{' (has additionalProperties but no defined properties)' if has_additional else ''}"
                        )
                    elif prop_properties is not None:
                        # Recurse into non-empty objects
                        removed.extend(
                            cls._remove_empty_object_properties(prop_schema, prop_path)
                        )

                # Check arrays - remove if items are unevaluable objects
                elif prop_type == TYPE_ARRAY and SCHEMA_ITEMS in prop_schema:
                    items_schema = prop_schema[SCHEMA_ITEMS]
                    if cls._is_unevaluable_object(items_schema):
                        # Array of free-form objects - can't be evaluated
                        props_to_remove.append(prop_name)
                        removed.append(prop_path)
                        logger.info(
                            f"Removing array property '{prop_path}' - "
                            f"array items are free-form objects without defined properties, "
                            f"which Stickler cannot evaluate"
                        )
                    else:
                        removed.extend(
                            cls._remove_empty_object_properties(
                                items_schema, f"{prop_path}[]"
                            )
                        )

            # Remove unevaluable properties
            for prop_name in props_to_remove:
                del schema[SCHEMA_PROPERTIES][prop_name]

        # Check array items at this level too
        if SCHEMA_ITEMS in schema:
            removed.extend(
                cls._remove_empty_object_properties(
                    schema[SCHEMA_ITEMS], f"{field_path}[]"
                )
            )

        # Process $defs as well
        if "$defs" in schema:
            for def_name, def_schema in list(schema["$defs"].items()):
                # Check if the definition itself is an unevaluable object
                if isinstance(def_schema, dict) and cls._is_unevaluable_object(
                    def_schema
                ):
                    has_additional = "additionalProperties" in def_schema
                    logger.info(
                        f"Removing unevaluable $defs entry '{def_name}' - "
                        f"Stickler requires at least one field in nested objects"
                        f"{' (has additionalProperties but no defined properties)' if has_additional else ''}"
                    )
                    del schema["$defs"][def_name]
                    removed.append(f"$defs.{def_name}")
                else:
                    removed.extend(
                        cls._remove_empty_object_properties(
                            def_schema, f"$defs.{def_name}"
                        )
                    )

        return removed

    @classmethod
    def _inline_refs(
        cls,
        schema: Dict[str, Any],
        defs: Dict[str, Any],
        visited: Optional[Set[str]] = None,
        field_path: str = "",
    ) -> Dict[str, Any]:
        """
        Recursively inline all $ref references in the schema.

        This replaces all #/$defs/XXX references with the actual definition content,
        allowing Stickler's JsonSchemaFieldConverter to process nested schemas
        without losing $defs context.

        Handles circular references by tracking visited definitions.

        Args:
            schema: Schema or sub-schema to process
            defs: The $defs dictionary from the root schema
            visited: Set of definition names already being processed (for circular ref detection)
            field_path: Current path for logging

        Returns:
            Schema with all $ref references inlined
        """
        if visited is None:
            visited = set()

        if not isinstance(schema, dict):
            return schema

        # Handle $ref - inline the referenced definition
        if "$ref" in schema:
            ref_path = schema["$ref"]
            if ref_path.startswith("#/$defs/"):
                def_name = ref_path[8:]  # Remove "#/$defs/"
                if def_name in defs:
                    if def_name in visited:
                        # Circular reference detected - keep $ref to avoid infinite loop
                        logger.warning(
                            f"Circular $ref detected at '{field_path}': {ref_path}. Keeping reference."
                        )
                        return schema

                    # Mark as being processed
                    visited.add(def_name)

                    # Deep copy and recursively inline the definition
                    inlined = copy.deepcopy(defs[def_name])
                    inlined = cls._inline_refs(
                        inlined, defs, visited.copy(), f"{field_path}({def_name})"
                    )

                    # Merge any other properties from the original schema (like description)
                    # onto the inlined definition (original props take precedence)
                    for key, value in schema.items():
                        if key != "$ref" and key not in inlined:
                            inlined[key] = value

                    logger.debug(f"Inlined $ref '{ref_path}' at '{field_path}'")
                    return inlined
                else:
                    logger.warning(
                        f"Cannot inline $ref '{ref_path}' at '{field_path}': "
                        f"definition not found in $defs. Available: {list(defs.keys())}"
                    )

        # Recursively process properties
        if SCHEMA_PROPERTIES in schema:
            schema[SCHEMA_PROPERTIES] = {
                k: cls._inline_refs(v, defs, visited.copy(), f"{field_path}.{k}")
                for k, v in schema[SCHEMA_PROPERTIES].items()
            }

        # Recursively process array items
        if SCHEMA_ITEMS in schema:
            schema[SCHEMA_ITEMS] = cls._inline_refs(
                schema[SCHEMA_ITEMS], defs, visited.copy(), f"{field_path}[]"
            )

        # Process allOf, anyOf, oneOf
        for keyword in ["allOf", "anyOf", "oneOf"]:
            if keyword in schema:
                schema[keyword] = [
                    cls._inline_refs(
                        item, defs, visited.copy(), f"{field_path}.{keyword}[{i}]"
                    )
                    for i, item in enumerate(schema[keyword])
                ]

        # Process additionalProperties if it's a schema
        if "additionalProperties" in schema and isinstance(
            schema["additionalProperties"], dict
        ):
            schema["additionalProperties"] = cls._inline_refs(
                schema["additionalProperties"],
                defs,
                visited.copy(),
                f"{field_path}.additionalProperties",
            )

        return schema

    @classmethod
    def _validate_method_for_field(
        cls, schema: Dict[str, Any], method: str, field_path: str = ""
    ) -> None:
        """
        Validate that evaluation method is appropriate for the field type.

        Raises:
            ValueError: If method is incompatible with field type
        """
        field_type = schema.get(SCHEMA_TYPE)
        is_array = field_type == TYPE_ARRAY

        # Check if this is a structured array (array of objects)
        is_structured_array = False
        if is_array and SCHEMA_ITEMS in schema:
            items = schema[SCHEMA_ITEMS]
            if isinstance(items, dict):
                is_structured_array = (
                    items.get(SCHEMA_TYPE) == TYPE_OBJECT or "$ref" in items
                )

        # Validate HUNGARIAN - only for structured arrays
        if method == EVALUATION_METHOD_HUNGARIAN:
            if not is_structured_array:
                raise ValueError(
                    f"Field '{field_path}': HUNGARIAN method requires List[Object] (structured array). "
                    f"Field has type '{field_type}' with items type '{schema.get(SCHEMA_ITEMS, {}).get(SCHEMA_TYPE, 'N/A')}'"
                )

        # Validate other methods - should NOT be used on structured arrays
        elif method in [
            EVALUATION_METHOD_EXACT,
            EVALUATION_METHOD_FUZZY,
            EVALUATION_METHOD_LEVENSHTEIN,
            EVALUATION_METHOD_SEMANTIC,
            EVALUATION_METHOD_NUMERIC_EXACT,
        ]:
            if is_structured_array:
                raise ValueError(
                    f"Field '{field_path}': {method} cannot be used on List[Object]. "
                    f"Use HUNGARIAN for structured array matching."
                )

    @classmethod
    def _coerce_to_float(cls, value: Any, field_name: str = "") -> float:
        """
        Coerce value to float, handling strings and ints.

        Args:
            value: Value to coerce
            field_name: Field name for error messages

        Returns:
            Float value

        Raises:
            ValueError: If value cannot be converted to float
        """
        if isinstance(value, float):
            return value
        if isinstance(value, (str, int)):
            try:
                return float(value)
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"Field '{field_name}': Cannot convert '{value}' to float: {e}"
                )
        raise ValueError(
            f"Field '{field_name}': Expected numeric value, got {type(value).__name__}"
        )

    @classmethod
    def _coerce_json_schema_types(
        cls, schema: Dict[str, Any], field_path: str = ""
    ) -> None:
        """
        Coerce string values to proper JSON Schema types.

        This fixes common issues where numeric constraints are provided as strings
        instead of numbers (e.g., maxItems: '7' should be maxItems: 7).

        Args:
            schema: Schema to coerce (modified in-place)
            field_path: Current path for error messages
        """
        if not isinstance(schema, dict):
            return

        # Numeric constraints that must be integers
        INTEGER_CONSTRAINTS = [
            "maxItems",
            "minItems",
            "maxLength",
            "minLength",
            "maxProperties",
            "minProperties",
            "multipleOf",
        ]

        # Numeric constraints that must be numbers (int or float)
        NUMBER_CONSTRAINTS = [
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
        ]

        for key, value in list(schema.items()):
            # Coerce integer constraints
            if key in INTEGER_CONSTRAINTS and isinstance(value, str):
                try:
                    schema[key] = int(value)
                    logger.info(
                        f"Field '{field_path}': Coerced {key} from string '{value}' to integer {schema[key]}"
                    )
                except ValueError:
                    logger.error(
                        f"Field '{field_path}': Cannot coerce {key}='{value}' to integer. "
                        f"This will cause validation errors."
                    )

            # Coerce number constraints
            elif key in NUMBER_CONSTRAINTS and isinstance(value, str):
                try:
                    schema[key] = float(value)
                    logger.info(
                        f"Field '{field_path}': Coerced {key} from string '{value}' to float {schema[key]}"
                    )
                except ValueError:
                    logger.error(
                        f"Field '{field_path}': Cannot coerce {key}='{value}' to number. "
                        f"This will cause validation errors."
                    )

        # Recursively process nested schemas
        if SCHEMA_PROPERTIES in schema:
            for prop_name, prop_schema in schema[SCHEMA_PROPERTIES].items():
                prop_path = f"{field_path}.{prop_name}" if field_path else prop_name
                cls._coerce_json_schema_types(prop_schema, prop_path)

        if SCHEMA_ITEMS in schema:
            items_path = f"{field_path}[]" if field_path else "items"
            cls._coerce_json_schema_types(schema[SCHEMA_ITEMS], items_path)

        if "$defs" in schema:
            for def_name, def_schema in schema["$defs"].items():
                cls._coerce_json_schema_types(def_schema, f"$defs.{def_name}")

    @classmethod
    def _translate_extensions_in_schema(
        cls, schema: Dict[str, Any], field_path: str = ""
    ) -> Dict[str, Any]:
        """
        Recursively translate IDP evaluation extensions to Stickler extensions.

        This modifies the schema in-place to replace:
        - x-aws-idp-evaluation-method → x-aws-stickler-comparator (except for structured arrays)
        - x-aws-idp-evaluation-threshold → x-aws-stickler-threshold (for non-arrays)
        - x-aws-idp-evaluation-match-threshold → x-aws-stickler-match-threshold (for array items)
        - x-aws-idp-evaluation-weight → x-aws-stickler-weight

        Also adds empty "required" arrays to objects that don't have one,
        making all fields optional by default.

        Note: LLM comparator configuration is handled via global config in
        llm_comparator.py, not through schema extensions.

        Args:
            schema: Schema (or sub-schema) to translate
            field_path: Path for error messages (e.g., "Transaction.items.amount")

        Returns:
            Translated schema (same object, modified in-place)
        """
        if not isinstance(schema, dict):
            return schema

        # Coerce types FIRST, before any other processing
        cls._coerce_json_schema_types(schema, field_path)

        # If this is an object with properties but no required array, add empty one
        # This makes all fields optional, allowing None values
        if schema.get(SCHEMA_TYPE) == TYPE_OBJECT and SCHEMA_PROPERTIES in schema:
            if "required" not in schema:
                schema["required"] = []

        # Check if this is an array with structured items
        is_structured_array = False
        if schema.get(SCHEMA_TYPE) == TYPE_ARRAY and SCHEMA_ITEMS in schema:
            items = schema[SCHEMA_ITEMS]
            # Check if items is an object or has $ref (both indicate structured list)
            if isinstance(items, dict):
                is_structured_array = (
                    items.get(SCHEMA_TYPE) == TYPE_OBJECT or "$ref" in items
                )

        # Validate evaluation method if present
        if X_AWS_IDP_EVALUATION_METHOD in schema:
            method = schema[X_AWS_IDP_EVALUATION_METHOD]
            try:
                cls._validate_method_for_field(schema, method, field_path)
            except ValueError as e:
                logger.error(str(e))
                # Remove invalid method to prevent downstream errors
                del schema[X_AWS_IDP_EVALUATION_METHOD]
                return schema

        # Translate evaluation method to comparator
        # BUT skip for structured arrays - they use item field comparators
        if X_AWS_IDP_EVALUATION_METHOD in schema and not is_structured_array:
            method = schema[X_AWS_IDP_EVALUATION_METHOD]
            comparator = cls.METHOD_TO_COMPARATOR.get(method)
            if comparator:
                schema["x-aws-stickler-comparator"] = comparator

        # Handle thresholds based on field type
        # For structured arrays (Hungarian): use match_threshold at field level
        if is_structured_array:
            # Validate: structured arrays should use match-threshold, not threshold
            if X_AWS_IDP_EVALUATION_THRESHOLD in schema:
                raise ValueError(
                    f"Field '{field_path}': Cannot use 'evaluation-threshold' on List[Object]. "
                    f"Use 'evaluation-match-threshold' for HUNGARIAN matching instead."
                )

            # Set match_threshold at field level (array itself)
            if X_AWS_IDP_EVALUATION_MATCH_THRESHOLD in schema:
                match_threshold = cls._coerce_to_float(
                    schema[X_AWS_IDP_EVALUATION_MATCH_THRESHOLD],
                    f"{field_path}.match_threshold",
                )
                # Set on the field itself - this is where backend looks for it
                schema["x-aws-stickler-match-threshold"] = match_threshold
                logger.debug(
                    f"Field '{field_path}': Set match_threshold={match_threshold} at field level for Hungarian matching"
                )

        # For non-array fields: use threshold
        elif X_AWS_IDP_EVALUATION_THRESHOLD in schema:
            threshold = cls._coerce_to_float(
                schema[X_AWS_IDP_EVALUATION_THRESHOLD], f"{field_path}.threshold"
            )
            schema["x-aws-stickler-threshold"] = threshold

        # Translate weight (valid for non-array fields)
        # Note: Stickler doesn't support weight on array fields themselves
        if not is_structured_array and X_AWS_IDP_EVALUATION_WEIGHT in schema:
            weight = cls._coerce_to_float(
                schema[X_AWS_IDP_EVALUATION_WEIGHT], f"{field_path}.weight"
            )
            schema["x-aws-stickler-weight"] = weight

        # Recursively process nested schemas with path tracking
        if SCHEMA_PROPERTIES in schema:
            for prop_name, prop_schema in schema[SCHEMA_PROPERTIES].items():
                prop_path = f"{field_path}.{prop_name}" if field_path else prop_name
                cls._translate_extensions_in_schema(prop_schema, prop_path)

        if SCHEMA_ITEMS in schema:
            items_path = f"{field_path}[]" if field_path else "items"
            cls._translate_extensions_in_schema(schema[SCHEMA_ITEMS], items_path)

        if "$defs" in schema:
            for def_name, def_schema in schema["$defs"].items():
                cls._translate_extensions_in_schema(def_schema, f"$defs.{def_name}")

        if "definitions" in schema:
            for def_name, def_schema in schema["definitions"].items():
                cls._translate_extensions_in_schema(
                    def_schema, f"definitions.{def_name}"
                )

        return schema

    @classmethod
    def build_stickler_model_config(
        cls, document_class_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build complete Stickler model configuration from IDP document class schema.

        Translates IDP evaluation extensions to Stickler extensions throughout
        the schema. Stickler's JsonSchemaFieldConverter will handle $ref resolution,
        required vs optional fields, and nested structures.

        Args:
            document_class_schema: JSON Schema for document class with IDP extensions

        Returns:
            Configuration dict with translated schema for JsonSchemaFieldConverter
        """
        import copy

        # Make a deep copy to avoid modifying the original
        schema = copy.deepcopy(document_class_schema)

        # Extract model name
        model_name = (
            schema.get(X_AWS_IDP_EVALUATION_MODEL_NAME)
            or schema.get(X_AWS_IDP_DOCUMENT_TYPE)
            or "Document"
        )

        # Sanitize model name to be valid Python identifier
        model_name = cls._sanitize_model_name(model_name)

        # Extract match threshold (document-level)
        match_threshold = schema.get(X_AWS_IDP_EVALUATION_MATCH_THRESHOLD, 0.8)

        logger.info(
            f"Building Stickler config for model '{model_name}' with match_threshold={match_threshold}"
        )

        # Inline all $ref references BEFORE translating extensions
        # This is necessary because Stickler's JsonSchemaFieldConverter creates new
        # converter instances for nested schemas without propagating root $defs,
        # causing nested $ref resolution to fail
        defs = schema.get("$defs", {}) or schema.get("definitions", {})
        if defs:
            num_defs = len(defs)
            schema = cls._inline_refs(schema, defs, field_path=model_name)
            logger.info(f"Inlined {num_defs} $defs references for model '{model_name}'")

        # Remove empty object properties AFTER inlining refs but BEFORE translating extensions
        # This prevents Stickler's ModelFactory from failing on nested objects with no fields
        # (e.g., "AccidentInformation": {"type": "object", "properties": {}})
        removed_properties = cls._remove_empty_object_properties(
            schema, field_path=model_name
        )
        if removed_properties:
            logger.info(
                f"Removed {len(removed_properties)} empty object properties for model '{model_name}': "
                f"{removed_properties}"
            )

        # Translate IDP extensions to Stickler extensions throughout the schema
        cls._translate_extensions_in_schema(schema)

        # Return the full schema - JsonSchemaFieldConverter will handle everything else
        stickler_config = {
            "model_name": model_name,
            "match_threshold": match_threshold,
            "schema": schema,  # Full JSON Schema with translated extensions
        }

        logger.info(
            f"Built Stickler config for model '{model_name}' using native JSON Schema with JsonSchemaFieldConverter"
        )

        return stickler_config

    @classmethod
    def build_all_stickler_configs(
        cls, idp_config: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build Stickler configurations for all document classes in IDP config.

        Args:
            idp_config: Complete IDP configuration with 'classes' array

        Returns:
            Dictionary mapping document class names to Stickler configs
        """
        stickler_configs = {}
        classes = idp_config.get("classes", [])

        logger.info(f"Building Stickler configs for {len(classes)} document classes")

        for class_schema in classes:
            try:
                doc_type = class_schema.get(X_AWS_IDP_DOCUMENT_TYPE)
                if not doc_type:
                    logger.warning("Document class missing x-aws-idp-document-type")
                    continue

                # Build Stickler config for this document class
                stickler_config = cls.build_stickler_model_config(class_schema)

                # Use lowercase document type as key
                stickler_configs[doc_type.lower()] = stickler_config

                logger.info(f"Built Stickler config for document type: {doc_type}")

            except Exception as e:
                logger.error(
                    f"Error building Stickler config for class: {str(e)}", exc_info=True
                )
                # Continue with other classes
                continue

        logger.info(
            f"Successfully built {len(stickler_configs)} Stickler configurations"
        )
        return stickler_configs

    @staticmethod
    def _sanitize_model_name(name: str) -> str:
        """
        Sanitize model name to be a valid Python identifier.

        Stickler requires model names to be valid Python identifiers,
        which means they cannot contain hyphens or start with numbers.

        Args:
            name: Original model name (may contain hyphens)

        Returns:
            Sanitized name that is a valid Python identifier
        """
        # Replace hyphens with underscores
        sanitized = name.replace("-", "_")

        # Replace spaces with underscores
        sanitized = sanitized.replace(" ", "_")

        # Remove any other non-alphanumeric characters except underscores
        sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)

        # Ensure it doesn't start with a number
        if sanitized and sanitized[0].isdigit():
            sanitized = f"_{sanitized}"

        logger.debug(f"Sanitized model name: '{name}' -> '{sanitized}'")
        return sanitized

    @staticmethod
    def _map_type(json_schema_type: str) -> str:
        """
        Map JSON Schema type to Stickler type.

        Args:
            json_schema_type: JSON Schema type (string, number, object, etc.)

        Returns:
            Stickler type (str, float, structured_model, etc.)
        """
        mapped = SticklerConfigMapper.JSON_SCHEMA_TO_STICKLER_TYPE.get(
            json_schema_type, "str"
        )
        if mapped == "str" and json_schema_type not in ["string", "str"]:
            logger.warning(
                f"Unknown JSON Schema type '{json_schema_type}', defaulting to 'str'"
            )
        return mapped
