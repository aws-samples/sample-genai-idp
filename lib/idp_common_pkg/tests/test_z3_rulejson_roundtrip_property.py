# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for RuleJSON serialization round-trip.

Feature: z3-dual-engine-rule-validation, Property 6: RuleJSON Serialization Round-Trip

For any valid RuleJSON instance (with valid parameter types from {Int, Real, Bool, String},
non-empty constraints, and consistent path mappings), serializing to dict via `to_dict()`
and deserializing back via `from_dict()` SHALL produce an equivalent RuleJSON instance.

**Validates: Requirements 5.5**
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from idp_common.rule_validation.z3.models import Parameter, PathMapping, RuleJSON

# --- Strategies ---

# Valid parameter types
VALID_PARAM_TYPES = ["Int", "Real", "Bool", "String"]

# Valid parameter names: alphanumeric + underscores, starting with a letter
valid_param_names = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,19}", fullmatch=True)

# Valid dot-notation data paths (no consecutive dots, no leading/trailing dots)
path_segments = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,9}", fullmatch=True)
valid_data_paths = st.lists(path_segments, min_size=1, max_size=4).map(
    lambda parts: ".".join(parts)
)

# Valid parameter types
valid_param_types = st.sampled_from(VALID_PARAM_TYPES)

# Non-empty strings for rule fields
non_empty_strings = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\x00"),
    min_size=1,
    max_size=100,
)

# Version strings
version_strings = st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True)


# Simple SMT-LIB constraint strings (valid expressions using parameter names)
# We generate constraints that reference parameter names to pass validation
def make_constraint(param_names):
    """Generate a simple valid SMT-LIB constraint referencing given parameter names."""
    if not param_names:
        return st.just("(> x 0)")

    def build_constraint(param_name, op, value):
        return f"({op} {param_name} {value})"

    return st.tuples(
        st.sampled_from(param_names),
        st.sampled_from([">", "<", ">=", "<=", "="]),
        st.integers(min_value=0, max_value=1000).map(str),
    ).map(lambda t: build_constraint(*t))


# Metadata: simple JSON-serializable dictionaries
simple_metadata_values = st.one_of(
    st.text(min_size=0, max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)

metadata_strategy = st.dictionaries(
    keys=st.from_regex(r"[a-z][a-z0-9_]{0,9}", fullmatch=True),
    values=simple_metadata_values,
    min_size=0,
    max_size=5,
)


@st.composite
def valid_parameter(draw):
    """Generate a valid Parameter instance."""
    name = draw(valid_param_names)
    param_type = draw(valid_param_types)
    required = draw(st.booleans())
    description = draw(st.one_of(st.none(), non_empty_strings))
    return Parameter(
        name=name, type=param_type, required=required, description=description
    )


@st.composite
def valid_rulejson_without_path_mappings(draw):
    """Generate a valid RuleJSON instance without path mappings (Workflow B)."""
    # Generate 1-5 unique parameters
    num_params = draw(st.integers(min_value=1, max_value=5))
    param_names_set = set()
    parameters = []
    for _ in range(num_params):
        name = draw(valid_param_names)
        assume(name not in param_names_set)
        param_names_set.add(name)
        param_type = draw(valid_param_types)
        required = draw(st.booleans())
        description = draw(st.one_of(st.none(), non_empty_strings))
        parameters.append(
            Parameter(
                name=name, type=param_type, required=required, description=description
            )
        )

    # Generate 1-3 constraints referencing the parameter names
    param_name_list = list(param_names_set)
    num_constraints = draw(st.integers(min_value=1, max_value=3))
    constraints = []
    for _ in range(num_constraints):
        constraint = draw(make_constraint(param_name_list))
        constraints.append(constraint)

    rule_id = draw(non_empty_strings)
    version = draw(version_strings)
    description = draw(non_empty_strings)
    natural_language_rule = draw(non_empty_strings)
    metadata = draw(metadata_strategy)

    return RuleJSON(
        rule_id=rule_id,
        version=version,
        description=description,
        natural_language_rule=natural_language_rule,
        parameters=parameters,
        constraints=constraints,
        path_mappings=[],
        metadata=metadata,
    )


@st.composite
def valid_rulejson_with_path_mappings(draw):
    """Generate a valid RuleJSON instance with path mappings (Workflow A)."""
    # Generate 1-5 unique parameters (all required for path mapping consistency)
    num_params = draw(st.integers(min_value=1, max_value=5))
    param_names_set = set()
    parameters = []
    for _ in range(num_params):
        name = draw(valid_param_names)
        assume(name not in param_names_set)
        param_names_set.add(name)
        param_type = draw(valid_param_types)
        description = draw(st.one_of(st.none(), non_empty_strings))
        # All parameters are required when path mappings exist (bijection requirement)
        parameters.append(
            Parameter(
                name=name, type=param_type, required=True, description=description
            )
        )

    # Generate path mappings for each required parameter (bijection)
    path_mappings = []
    for param in parameters:
        data_path = draw(valid_data_paths)
        path_mappings.append(
            PathMapping(parameter_name=param.name, data_path=data_path)
        )

    # Generate 1-3 constraints referencing the parameter names
    param_name_list = list(param_names_set)
    num_constraints = draw(st.integers(min_value=1, max_value=3))
    constraints = []
    for _ in range(num_constraints):
        constraint = draw(make_constraint(param_name_list))
        constraints.append(constraint)

    rule_id = draw(non_empty_strings)
    version = draw(version_strings)
    description = draw(non_empty_strings)
    natural_language_rule = draw(non_empty_strings)
    metadata = draw(metadata_strategy)

    return RuleJSON(
        rule_id=rule_id,
        version=version,
        description=description,
        natural_language_rule=natural_language_rule,
        parameters=parameters,
        constraints=constraints,
        path_mappings=path_mappings,
        metadata=metadata,
    )


# Combined strategy: either with or without path mappings
valid_rulejson = st.one_of(
    valid_rulejson_without_path_mappings(),
    valid_rulejson_with_path_mappings(),
)


# --- Property Tests ---


class TestRuleJSONRoundTrip:
    """Property tests for RuleJSON serialization round-trip."""

    @given(rule_json=valid_rulejson)
    @settings(max_examples=100)
    def test_rulejson_roundtrip_produces_equivalent_instance(self, rule_json: RuleJSON):
        """For any valid RuleJSON, to_dict() -> from_dict() produces an equivalent instance.

        **Validates: Requirements 5.5**
        """
        # Serialize to dict
        serialized = rule_json.to_dict()

        # Deserialize back
        deserialized = RuleJSON.from_dict(serialized)

        # Verify equivalence of all fields
        assert deserialized.rule_id == rule_json.rule_id
        assert deserialized.version == rule_json.version
        assert deserialized.description == rule_json.description
        assert deserialized.natural_language_rule == rule_json.natural_language_rule
        assert deserialized.metadata == rule_json.metadata
        assert deserialized.constraints == rule_json.constraints

        # Verify parameters equivalence
        assert len(deserialized.parameters) == len(rule_json.parameters)
        for orig, deser in zip(rule_json.parameters, deserialized.parameters):
            assert deser.name == orig.name
            assert deser.type == orig.type
            assert deser.required == orig.required
            assert deser.description == orig.description

        # Verify path_mappings equivalence
        assert len(deserialized.path_mappings) == len(rule_json.path_mappings)
        for orig, deser in zip(rule_json.path_mappings, deserialized.path_mappings):
            assert deser.parameter_name == orig.parameter_name
            assert deser.data_path == orig.data_path

    @given(rule_json=valid_rulejson)
    @settings(max_examples=100)
    def test_rulejson_roundtrip_dict_equality(self, rule_json: RuleJSON):
        """For any valid RuleJSON, to_dict() -> from_dict() -> to_dict() equals original to_dict().

        **Validates: Requirements 5.5**
        """
        # Serialize -> deserialize -> serialize again
        first_dict = rule_json.to_dict()
        reconstructed = RuleJSON.from_dict(first_dict)
        second_dict = reconstructed.to_dict()

        # The two dict representations should be identical
        assert first_dict == second_dict

    @given(rule_json=valid_rulejson_without_path_mappings())
    @settings(max_examples=100)
    def test_roundtrip_preserves_empty_path_mappings(self, rule_json: RuleJSON):
        """Round-trip preserves empty path_mappings list (Workflow B).

        **Validates: Requirements 5.5**
        """
        serialized = rule_json.to_dict()
        deserialized = RuleJSON.from_dict(serialized)

        assert deserialized.path_mappings == []
        assert deserialized.has_path_mappings() is False

    @given(rule_json=valid_rulejson_with_path_mappings())
    @settings(max_examples=100)
    def test_roundtrip_preserves_path_mappings(self, rule_json: RuleJSON):
        """Round-trip preserves non-empty path_mappings (Workflow A).

        **Validates: Requirements 5.5**
        """
        serialized = rule_json.to_dict()
        deserialized = RuleJSON.from_dict(serialized)

        assert len(deserialized.path_mappings) == len(rule_json.path_mappings)
        assert deserialized.has_path_mappings() is True

        for orig, deser in zip(rule_json.path_mappings, deserialized.path_mappings):
            assert deser.parameter_name == orig.parameter_name
            assert deser.data_path == orig.data_path

    @given(rule_json=valid_rulejson)
    @settings(max_examples=100)
    def test_roundtrip_preserves_parameter_types(self, rule_json: RuleJSON):
        """Round-trip preserves parameter types from {Int, Real, Bool, String}.

        **Validates: Requirements 5.5**
        """
        serialized = rule_json.to_dict()
        deserialized = RuleJSON.from_dict(serialized)

        for orig, deser in zip(rule_json.parameters, deserialized.parameters):
            assert deser.type == orig.type
            assert deser.type in {"Int", "Real", "Bool", "String"}
