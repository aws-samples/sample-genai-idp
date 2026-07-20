# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Central argument-shape validation for the HTTP API dispatcher.

AppSync validated every operation's input arguments against ``schema.graphql``
before the resolver ran. The HTTP API that replaced it has no such gate, so a
malformed request flowed straight into a resolver (silently accepted, or a 500
deep in the code). This module restores a boundary input-shape gate: it loads a
build-time-generated JSON spec (``api_validation_spec.json``, bundled in this
Lambda's CodeUri) describing each Query/Mutation field's argument signature, and
rejects requests whose arguments don't match. Rejections raise ``ValueError`` so
the dispatcher's existing ``except (ValueError, KeyError)`` maps them to HTTP
400 / ``BadRequest``.

Relationship to AppSync's behavior — this validator is intentionally **stricter
than AppSync on input coercion**, not a byte-for-byte re-creation of it. AppSync
coerced some inputs before validating (a scalar passed for a list arg became a
one-element list; an integer passed for an ``ID`` was serialized to a string;
``AWSJSON`` accepted any JSON value including bare scalars). This validator does
NOT coerce — it rejects those shapes. That is safe for the current Web UI, which
already sends list args as arrays, IDs as strings, and ``AWSJSON`` as
``JSON.stringify`` objects (verified across all UI operations); but a non-UI API
client that relied on AppSync-style coercion would get a 400 where AppSync
accepted. Softening these to coerce (rather than reject) is a documented
follow-up; see the type-map notes below.

Design principles (see scripts/sdlc/generate_api_validation_spec.py for the
build side):

* **Stdlib only.** No graphql-core at runtime; the schema is precomputed to JSON.
* **Conservative.** Only reject UNAMBIGUOUS violations (unknown args, missing
  non-null args, wrong JSON type, bad enum value, list-vs-scalar). Type-only
  checks — no date/email FORMAT regex yet (a deliberate TODO; too risky for
  enforce-now). Input objects are validated shallowly (must be a dict); nested
  input fields are not deep-validated in v1 (TODO).
* **Fail-open on validator bugs, fail-closed on bad input.** Any INTERNAL error
  in the validator itself (e.g. a malformed spec entry) is caught and logged,
  then the request is ALLOWED through — a validator bug must never 500 the whole
  API. Genuine input violations still raise.
"""

import json
import logging
import os

logger = logging.getLogger()

_SPEC_PATH = os.path.join(os.path.dirname(__file__), "api_validation_spec.json")

# Custom AWS scalars + standard scalars, grouped by the Python type(s) accepted.
# AWSDateTime/AWSDate/AWSEmail/AWSURL are validated as strings only (no FORMAT
# regex in v1 — TODO: tighten once real UI payloads are confirmed).
# NOTE: `ID` is treated as string-only here. GraphQL/AppSync also accept an
# integer for ID (serializing it to a string); we require a string. Safe for the
# UI (it sends IDs as strings) but stricter than AppSync — TODO: coerce int→str
# for ID if a non-UI client needs it.
_STRING_TYPES = frozenset(
    {"String", "ID", "AWSDateTime", "AWSDate", "AWSEmail", "AWSURL"}
)
# AWSTimestamp is a Unix epoch integer in AppSync.
_INT_TYPES = frozenset({"Int", "AWSTimestamp"})
_FLOAT_TYPES = frozenset({"Float"})
_BOOL_TYPES = frozenset({"Boolean"})
# AWSJSON is a JSON-encoded STRING in AppSync, but the thin REST client / UI may
# pass the already-parsed object. Accept str OR dict OR list (the shapes the UI
# actually sends — verified). NOTE: AppSync's AWSJSON also accepts bare JSON
# scalars (a number/bool); we reject those. Stricter than AppSync but safe for
# the UI (every AWSJSON arg is sent as a JSON.stringify'd object) — TODO: accept
# any JSON value if a non-UI client needs it.
_JSON_TYPES = frozenset({"AWSJSON"})


def load_spec() -> dict:
    """Load the bundled validation spec once. On any failure return an empty
    spec so validation becomes a no-op (fail-open) rather than breaking cold
    start."""
    try:
        with open(_SPEC_PATH, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
        if not isinstance(spec, dict):
            raise ValueError("spec root is not an object")
        spec.setdefault("fields", {})
        spec.setdefault("enums", {})
        spec.setdefault("inputs", {})
        return spec
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to load api_validation_spec.json: %s", e)
        return {"fields": {}, "enums": {}, "inputs": {}}


_SPEC: dict = load_spec()


def _is_int(value: object) -> bool:
    # bool is a subclass of int in Python — reject it for Int/Float.
    return isinstance(value, int) and not isinstance(value, bool)


def _scalar_type_ok(value: object, type_name: str, enums: dict) -> str | None:
    """Return None if ``value`` is a valid instance of the (non-list) type,
    else a short reason string. ``value`` is assumed present and non-null."""
    if type_name in enums:
        if not isinstance(value, str):
            return f"must be one of {enums[type_name]} (got {type(value).__name__})"
        if value not in enums[type_name]:
            return (
                f"'{value}' is not a valid value (expected one of {enums[type_name]})"
            )
        return None
    if type_name in _STRING_TYPES:
        return None if isinstance(value, str) else "must be a string"
    if type_name in _INT_TYPES:
        return None if _is_int(value) else "must be an integer"
    if type_name in _FLOAT_TYPES:
        return (
            None if (_is_int(value) or isinstance(value, float)) else "must be a number"
        )
    if type_name in _BOOL_TYPES:
        return None if isinstance(value, bool) else "must be a boolean"
    if type_name in _JSON_TYPES:
        # AWSJSON: JSON-encoded string OR already-parsed object/array.
        return (
            None
            if isinstance(value, (str, dict, list))
            else "must be a JSON value (string, object, or array)"
        )
    # Input-object type (in the inputs map) OR an unknown/foreign named type.
    # Both are validated shallowly: must be an object. This deliberately does
    # NOT deep-validate nested input fields in v1 (TODO).
    return None if isinstance(value, dict) else "must be an object"


def _check_value(value: object, arg: dict, enums: dict) -> str | None:
    """Validate a present, non-null ``value`` against an arg record. Returns a
    reason string on violation, else None."""
    type_name = arg["type"]
    if arg.get("is_list"):
        if not isinstance(value, list):
            return f"'{arg['name']}' must be a list"
        elem_non_null = arg.get("elem_non_null")
        for idx, elem in enumerate(value):
            if elem is None:
                if elem_non_null:
                    return f"'{arg['name']}'[{idx}] must not be null"
                continue
            reason = _scalar_type_ok(elem, type_name, enums)
            if reason:
                return f"'{arg['name']}'[{idx}] {reason}"
        return None
    reason = _scalar_type_ok(value, type_name, enums)
    if reason:
        return f"'{arg['name']}' {reason}"
    return None


def validate_arguments(field: str, arguments: object) -> None:
    """Validate ``arguments`` for ``field`` against the schema-derived spec.

    Raises ``ValueError`` on an unambiguous violation. No-op when ``field`` is
    not in the spec (ddb_direct / alias / unknown ops are handled elsewhere).
    Fails OPEN on any internal validator error (logs and returns).
    """
    try:
        field_spec = _SPEC["fields"].get(field)
        if field_spec is None:
            return  # not a schema Query/Mutation field — nothing to validate
        enums = _SPEC.get("enums", {})

        if not isinstance(arguments, dict):
            raise ValueError(
                f"invalid arguments for {field}: expected an object, got "
                f"{type(arguments).__name__}"
            )

        args = field_spec.get("args", [])
        arg_by_name = {a["name"]: a for a in args}

        # Unknown args — safe to reject (AppSync did).
        for name in arguments:
            if name not in arg_by_name:
                raise ValueError(
                    f"invalid arguments for {field}: unknown argument '{name}'"
                )

        for arg in args:
            name = arg["name"]
            present = name in arguments
            value = arguments.get(name)
            if arg.get("non_null") and (not present or value is None):
                raise ValueError(
                    f"invalid arguments for {field}: missing required argument '{name}'"
                )
            if not present or value is None:
                continue  # optional + absent/null → nothing to type-check
            reason = _check_value(value, arg, enums)
            if reason:
                raise ValueError(f"invalid arguments for {field}: {reason}")
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        # Fail OPEN: a validator bug must never take down the API. Log and allow.
        logger.error("Validator internal error for %s (allowing through): %s", field, e)
        return
