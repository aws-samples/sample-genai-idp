# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the HTTP API dispatcher's central schema-shape validation
(validation.py + the build-time generate_api_validation_spec.py).

The dispatcher and generator live outside the package, so we import them by path
following the pattern in test_http_api_ddb_direct.py.

Coverage (per PR B spec):
  * valid flat args pass; empty args pass for arg-less / all-optional fields.
  * missing non-null arg → ValueError; wrong scalar type → ValueError.
  * unknown arg → ValueError.
  * enum: valid value passes, invalid string / non-string rejected.
  * input-object arg: dict passes, non-dict rejected.
  * list arg: non-list rejected, bad element rejected, null element rejected.
  * handler-level: a bad request returns 400/BadRequest and never routes; a
    valid request routes.
  * validator-bug fail-open: a malformed spec entry does NOT raise/500.
  * spec drift: generator --check passes against the committed JSON.
  * acceptance corpus: every field accepts {} UNLESS it has a non-null arg, and
    that required-arg set is exactly the one derived from the schema.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "nested" / "api-resolvers").is_dir():
            return parent
    raise RuntimeError("Could not locate repo root containing nested/api-resolvers")


_REPO = _find_repo_root()
_DISPATCHER_DIR = (
    _REPO / "nested" / "api-resolvers" / "src" / "lambda" / "http_api_dispatcher"
)
_SPEC_PATH = _DISPATCHER_DIR / "api_validation_spec.json"
_GENERATOR = _REPO / "scripts" / "sdlc" / "generate_api_validation_spec.py"
_SCHEMA = _REPO / "nested" / "api-resolvers" / "src" / "api" / "schema.graphql"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_validation():
    # The dispatcher dir must be importable so `validation.py` can find its
    # sibling spec via __file__.
    if str(_DISPATCHER_DIR) not in sys.path:
        sys.path.insert(0, str(_DISPATCHER_DIR))
    return _load_module("validation", _DISPATCHER_DIR / "validation.py")


def _load_generator():
    # generate_api_validation_spec imports scan_api_rbac from its own dir.
    scripts_dir = _REPO / "scripts" / "sdlc"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return _load_module("generate_api_validation_spec", _GENERATOR)


@pytest.fixture(scope="module")
def validation():
    return _load_validation()


@pytest.fixture(scope="module")
def spec():
    return json.loads(_SPEC_PATH.read_text())


# ------------------------------- valid args -------------------------------- #
def test_valid_flat_scalar_passes(validation):
    validation.validate_arguments("getDocument", {"ObjectKey": "s3://bucket/key.pdf"})


def test_empty_args_for_all_optional_field_passes(validation):
    # listDocuments has only optional args.
    validation.validate_arguments("listDocuments", {})


def test_valid_optional_args_pass(validation):
    validation.validate_arguments("listDocuments", {"limit": 10, "nextToken": "abc"})


def test_valid_list_arg_passes(validation):
    validation.validate_arguments(
        "reprocessDocument", {"objectKeys": ["a", "b"], "version": "3"}
    )


def test_field_not_in_spec_is_noop(validation):
    # ddb_direct / alias / unknown field names are handled elsewhere.
    validation.validate_arguments("someUnknownOperation", {"whatever": 1})


# ----------------------------- non-null / type ----------------------------- #
def test_missing_non_null_raises(validation):
    with pytest.raises(ValueError, match="missing required argument 'ObjectKey'"):
        validation.validate_arguments("getDocument", {})


def test_explicit_null_non_null_raises(validation):
    with pytest.raises(ValueError, match="missing required argument 'ObjectKey'"):
        validation.validate_arguments("getDocument", {"ObjectKey": None})


def test_wrong_type_dict_for_id_raises(validation):
    with pytest.raises(ValueError, match="must be a string"):
        validation.validate_arguments("getDocument", {"ObjectKey": {"x": 1}})


def test_wrong_type_int_for_id_raises(validation):
    with pytest.raises(ValueError, match="must be a string"):
        validation.validate_arguments("getDocument", {"ObjectKey": 123})


def test_int_arg_rejects_bool(validation):
    # bool must not satisfy Int (bool is an int subclass in Python).
    with pytest.raises(ValueError, match="must be an integer"):
        validation.validate_arguments("listDocuments", {"limit": True})


def test_int_arg_accepts_int(validation):
    validation.validate_arguments(
        "listDocumentsDateHour", {"date": "2026-01-01", "hour": 5}
    )


def test_boolean_arg_rejects_non_bool(validation):
    with pytest.raises(ValueError, match="must be a boolean"):
        validation.validate_arguments(
            "sendAgentChatMessage",
            {"prompt": "hi", "enableCodeIntelligence": "yes"},
        )


# --------------------------------- unknown --------------------------------- #
def test_unknown_arg_raises(validation):
    with pytest.raises(ValueError, match="unknown argument 'bogus'"):
        validation.validate_arguments("getDocument", {"ObjectKey": "k", "bogus": 1})


# ---------------------------------- enums ---------------------------------- #
def test_enum_valid_value_passes(validation):
    validation.validate_arguments(
        "updateFinetuningJobStatus", {"jobId": "j1", "status": "TRAINING"}
    )


def test_enum_invalid_value_raises(validation):
    with pytest.raises(ValueError, match="not a valid value"):
        validation.validate_arguments(
            "updateFinetuningJobStatus", {"jobId": "j1", "status": "BOGUS"}
        )


def test_enum_non_string_raises(validation):
    with pytest.raises(ValueError, match="must be one of"):
        validation.validate_arguments(
            "updateFinetuningJobStatus", {"jobId": "j1", "status": 3}
        )


# ------------------------------ input objects ------------------------------ #
def test_input_object_dict_passes(validation):
    validation.validate_arguments("createDocument", {"input": {"ObjectKey": "k"}})


def test_input_object_non_dict_raises(validation):
    with pytest.raises(ValueError, match="must be an object"):
        validation.validate_arguments("createDocument", {"input": "not-an-object"})


def test_input_object_missing_non_null_raises(validation):
    with pytest.raises(ValueError, match="missing required argument 'input'"):
        validation.validate_arguments("createDocument", {})


# --------------------------------- lists ----------------------------------- #
def test_list_arg_non_list_raises(validation):
    with pytest.raises(ValueError, match="must be a list"):
        validation.validate_arguments("reprocessDocument", {"objectKeys": "a"})


def test_list_arg_bad_element_raises(validation):
    with pytest.raises(ValueError, match=r"objectKeys'\[1\] must be a string"):
        validation.validate_arguments("reprocessDocument", {"objectKeys": ["ok", 5]})


def test_list_arg_null_element_raises(validation):
    # objectKeys: [String!]! — elements are non-null.
    with pytest.raises(ValueError, match=r"objectKeys'\[0\] must not be null"):
        validation.validate_arguments("reprocessDocument", {"objectKeys": [None]})


# --------------------------------- AWSJSON --------------------------------- #
def test_awsjson_accepts_string(validation):
    validation.validate_arguments("updatePricing", {"pricingConfig": '{"a": 1}'})


def test_awsjson_accepts_object(validation):
    validation.validate_arguments("updatePricing", {"pricingConfig": {"a": 1}})


def test_awsjson_rejects_scalar(validation):
    with pytest.raises(ValueError, match="must be a JSON value"):
        validation.validate_arguments("updatePricing", {"pricingConfig": 5})


# ---------------------------- handler integration -------------------------- #
def _load_index(monkeypatch):
    """Load the dispatcher index.py with boto3 clients stubbed so import works
    without AWS. Returns the module."""
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())
    # index.py imports `ddb_direct` and `validation` as siblings.
    if str(_DISPATCHER_DIR) not in sys.path:
        sys.path.insert(0, str(_DISPATCHER_DIR))
    _load_module("ddb_direct", _DISPATCHER_DIR / "ddb_direct.py")
    _load_validation()
    return _load_module("index", _DISPATCHER_DIR / "index.py")


def _http_event(field, arguments):
    """A normalized HTTP API v2 event the dispatcher's adapter accepts."""
    return {
        "requestContext": {"http": {"method": "POST"}},
        "pathParameters": {"field": field},
        "body": json.dumps({"arguments": arguments}),
        "headers": {},
    }


def test_handler_rejects_bad_request_400_and_never_routes(monkeypatch):
    idx = _load_index(monkeypatch)
    routed = []
    monkeypatch.setattr(
        idx, "_invoke_resolver", lambda arn, ev: routed.append(ev) or {"ok": True}
    )
    idx.FIELD_FUNCTION_MAP["getDocument"] = "arn:aws:lambda:::function:x"

    # Missing required ObjectKey -> 400 BadRequest, resolver never invoked.
    resp = idx.handler(_http_event("getDocument", {}))
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert body["errors"][0]["errorType"] == "BadRequest"
    assert routed == []


def test_handler_valid_request_routes(monkeypatch):
    idx = _load_index(monkeypatch)
    routed = []
    monkeypatch.setattr(
        idx, "_invoke_resolver", lambda arn, ev: routed.append(ev) or {"ok": True}
    )
    idx.FIELD_FUNCTION_MAP["getDocument"] = "arn:aws:lambda:::function:x"

    resp = idx.handler(_http_event("getDocument", {"ObjectKey": "k"}))
    assert resp["statusCode"] == 200
    assert len(routed) == 1


# ------------------------------ fail-open ---------------------------------- #
def test_validator_internal_error_fails_open(validation, monkeypatch):
    """A malformed spec entry must NOT raise (fail-open on validator bugs)."""
    # Inject a field whose args record is malformed (missing 'name').
    bad_spec = {
        "fields": {"brokenField": {"args": [{"type": "String", "non_null": True}]}},
        "enums": {},
        "inputs": {},
    }
    monkeypatch.setattr(validation, "_SPEC", bad_spec)
    # Should log and allow through, not raise.
    validation.validate_arguments("brokenField", {"anything": 1})


def test_non_dict_arguments_raises(validation):
    with pytest.raises(ValueError, match="expected an object"):
        validation.validate_arguments("getDocument", ["not", "a", "dict"])


# ------------------------------ spec drift --------------------------------- #
def test_spec_matches_schema_no_drift():
    gen = _load_generator()
    schema_text = _SCHEMA.read_text()
    rebuilt = gen._dump(gen.build_spec(schema_text))
    committed = _SPEC_PATH.read_text()
    assert rebuilt == committed, (
        "api_validation_spec.json is out of date with schema.graphql; "
        "regenerate with scripts/sdlc/generate_api_validation_spec.py"
    )


# --------------------------- acceptance corpus ----------------------------- #
def test_empty_args_accepted_unless_non_null_required(validation, spec):
    """Every field accepts {} UNLESS it declares a non-null arg. The set of
    fields that REJECT {} must equal the set derived from the schema's non-null
    args (documents which ops require args)."""
    required = set()
    for field, fspec in spec["fields"].items():
        if any(a["non_null"] for a in fspec["args"]):
            required.add(field)

    rejected = set()
    for field, fspec in spec["fields"].items():
        try:
            validation.validate_arguments(field, {})
        except ValueError:
            rejected.add(field)

    assert rejected == required
    # Sanity: a well-known required field and a well-known optional field.
    assert "getDocument" in required
    assert "listDocuments" not in required


def test_required_arg_count_is_stable(spec):
    """Guardrail so a schema change that alters the required-arg surface is
    visible in the diff (89 fields require a non-null arg as of this spec)."""
    required = [
        f for f, v in spec["fields"].items() if any(a["non_null"] for a in v["args"])
    ]
    assert len(required) == 89
