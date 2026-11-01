from typing import Any, Callable

import pytest

from pydantic import BaseModel

from hololinked import SchemaValidators
from hololinked.core import Action, Property, Thing
from hololinked.core.exceptions import ValidationError
from hololinked.core.interfaces.schema_validators import BaseSchemaValidator
from hololinked.metadata.td.forms import Form
from hololinked.metadata.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from hololinked.metadata.td.interaction_affordance import schema_validator as schema_validator_factory
from hololinked.schema_validators.json_schema import JSONSchemaValidator
from hololinked.schema_validators.pydantic_model import PydanticSchemaValidator
from hololinked.utils import InputSignatureError, SignatureMismatchKind, check_input_signature, issubklass, uuid_hex


def property_affordance(schema: dict) -> PropertyAffordance:
    td = {"id": "thing", "properties": {"value": schema}}
    return PropertyAffordance.from_metadata("value", td)


def action_affordance(affordance: dict) -> ActionAffordance:
    return ActionAffordance.from_metadata("act", {"id": "thing", "actions": {"act": affordance}})


def event_affordance(affordance: dict) -> EventAffordance:
    return EventAffordance.from_metadata("data_ready", {"id": "thing", "events": {"data_ready": affordance}})


def test_thing(descriptor: Property | Action, name: str = "value") -> Thing:
    return type("TestThing", (Thing,), {name: descriptor})(id=f"test-thing-{uuid_hex()}")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "number", "minimum": 0, "maximum": 10, "readOnly": True},
        {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        {"type": "string", "enum": ["a", "b"]},
        {"type": "integer", "const": 5},
        {"type": "object", "additionalProperties": {"type": "integer"}, "@type": "saref:Temperature"},
        {"type": "string", "contentEncoding": "base64", "contentMediaType": "image/png"},
        {"type": "string", "uriVariables": {"id": {"type": "string"}}},
    ],
)
def test_01_metadata_dataclass_retains_known_definitions_from_api(schema: dict):
    """
    InteractionAffordance.from_metadata() keeps supported schema keywords intact, although many keywords
    belong to DataSchema rather than the affordance itself.
    """
    form = {
        "href": "http://localhost:8080/thing/value",
        "op": "readproperty",
    }
    td = {
        "id": "thing",
        "properties": {
            "value": {
                **schema,
                "forms": [form],
            },
        },
    }
    affordance = PropertyAffordance.from_metadata("value", td)
    assert {key: value for key, value in affordance.json().items() if key != "forms"} == schema
    assert affordance.forms is not None
    assert all(isinstance(form, Form) for form in affordance.forms)


@pytest.mark.parametrize(
    "affordance_cls, kind",
    [
        (PropertyAffordance, "properties"),
        (ActionAffordance, "actions"),
        (EventAffordance, "events"),
    ],
)
def test_02_metadata_dataclass_drops_unknown_definitions_from_api(
    affordance_cls: type[InteractionAffordance],
    kind: str,
):
    declared = {
        "@type": "saref:Command",
        "uriVariables": {
            "id": {"type": "string"},
        },
    }
    td = {
        "id": "thing",
        kind: {
            "value": {
                **declared,
                "minimum": 0,
                "x-custom": 1,
            },
        },
    }
    loaded = affordance_cls.from_metadata("value", td).json()
    expected = {**declared, "minimum": 0} if affordance_cls is PropertyAffordance else declared
    assert loaded == expected  # minimum is a data schema keyword, valid only on a property


@pytest.mark.parametrize(
    "schema_validator_type, expected",
    [("pydantic", PydanticSchemaValidator), ("json_schema", JSONSchemaValidator)],
)
def test_03_validator_kind_can_be_specified(schema_validator_type: str, expected: type[BaseSchemaValidator]):
    schema = {"type": "number", "minimum": 0}
    converted, preset = schema_validator_factory(schema=schema, name="value", typ=schema_validator_type)
    if expected is PydanticSchemaValidator:
        assert issubklass(converted, BaseModel)
    else:
        assert converted is schema
    assert type(preset) is expected


def test_04_property_data_schema():
    """the DataSchema keywords make up the schema of the value, except a property-level const."""
    value = {
        "type": "object",
        "properties": {"x": {"type": "integer", "title": "X", "default": 0}},
        "@type": "saref:Temperature",
        "title": "Value",
        "description": "a value",
        "readOnly": True,
        "unit": "V",
        "default": {"x": 1},
    }
    interaction = {
        "forms": [{"href": "http://localhost:8080/thing/value", "op": "readproperty"}],
        "observable": True,
        "uriVariables": {"id": {"type": "string"}},
    }
    affordance = property_affordance({**value, **interaction, "const": True})
    assert affordance.to_descriptor(validator="json_schema").model == value
    assert property_affordance(interaction).to_descriptor(fget=lambda self: 1).model is None


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "number", "minimum": 0, "default": 0}, [0, 2.5], [-1, "x", None]),
        ({"oneOf": [{"type": "integer"}, {"type": "string"}], "default": 1}, [1, "x"], [1.5, [1], None]),
        (
            {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"], "default": {"x": 0}},
            [{"x": 1}],
            [{"x": "a"}, 1, None],
        ),
        ({"title": "Value", "default": 0}, [1, "x", {"x": 1}], [None]),
    ],
)
def test_05_property_validates_writes(schema_validator: str, schema: dict, valid: list[Any], invalid: list[Any]):
    thing = test_thing(property_affordance(schema).to_descriptor(validator=schema_validator))
    for value in valid:
        thing.value = value
    for value in invalid:
        # None is refused by the property itself, not the validator
        with pytest.raises(ValueError if value is None else ValidationError):
            thing.value = value


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize("read_only", [True, False, None])
@pytest.mark.parametrize("observable", [True, False, None])
@pytest.mark.parametrize(
    "title, description, unit",
    [("Value", "a value", "V"), (None, None, None)],
)
def test_06_property_flags(
    schema_validator: str,
    read_only: bool | None,
    observable: bool | None,
    title: str | None,
    description: str | None,
    unit: str | None,
):
    """an absent flag or text field is left to the default of Property, None stands for absent."""
    fields = {"readOnly": read_only, "observable": observable, "title": title, "description": description, "unit": unit}
    affordance = property_affordance(
        {
            "type": "integer",
            "default": 3,
            **{key: value for key, value in fields.items() if value is not None},
        }
    )
    property = affordance.to_descriptor(validator=schema_validator)
    assert property.readonly is bool(read_only)
    assert property.observable is bool(observable)
    assert property.metadata == ({"unit": unit} if unit else None)
    assert (property.label, property.doc) == (title, description)
    thing = test_thing(property)
    assert thing.value == 3
    if read_only:
        with pytest.raises(ValueError, match="Read-only"):
            thing.value = 4
    else:
        thing.value = 4
        assert thing.value == 4


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, data_schema, valid, invalid",
    [
        (
            {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}], "default": 1},
            {"type": "integer", "minimum": 0, "default": 1},  # should match the non-null part of the oneOf schema
            [None, 2],
            [-1],
        ),
        (
            {"oneOf": [{"type": "null"}, {"type": "integer"}, {"type": "string"}]},
            {"oneOf": [{"type": "integer"}, {"type": "string"}]},  # should match the non-null part of the oneOf schema
            [None, 2, "x"],
            [1.5],
        ),
        # written by hololinked for a typed property such as Number(allow_None=True)
        (
            {"type": "number", "oneOf": [{"type": "null"}]},
            {"type": "number"},  # should match the non-null part of the oneOf schema
            [None, 2.5],
            ["x"],
        ),
    ],
)
def test_07_property_null_option(
    schema_validator: str,
    schema: dict,
    data_schema: dict,
    valid: list[Any],
    invalid: list[Any],
):
    affordance = property_affordance(schema)
    # can check the model only in json_schema mode
    assert affordance.to_descriptor(validator="json_schema").model == data_schema
    # check with the actual validator
    property = affordance.to_descriptor(validator=schema_validator)
    assert property.allow_None
    thing = test_thing(property)
    for value in valid:
        thing.value = value
        assert thing.value == value
    for value in invalid:
        with pytest.raises(ValidationError):
            thing.value = value


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, value",
    [
        # written by hololinked for Property(constant=True), the value is the default
        ({"const": True, "oneOf": [{"type": "null"}, {"type": "integer"}], "default": 5}, 5),
        ({"type": "integer", "const": 7}, 7),
    ],
)
def test_08_property_const(schema_validator: str, schema: dict, value: Any):
    property = property_affordance(schema).to_descriptor(validator=schema_validator)
    assert property.constant
    thing = test_thing(property)
    assert thing.value == value
    with pytest.raises(ValueError, match="Constant"):
        thing.value = value


def test_09_property_write_only_warns_as_its_a_noop():
    with pytest.warns(UserWarning, match="writeOnly"):
        property_affordance({"type": "integer", "writeOnly": True, "default": 0}).to_descriptor()


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_10_property_handlers(schema_validator):
    """fget serves reads, fset receives the validated plain value."""
    written = []
    property = property_affordance({"type": "integer", "minimum": 0}).to_descriptor(
        fget=lambda self: 7,
        fset=lambda self, value: written.append(value),
        validator=schema_validator,
    )
    thing = test_thing(property)
    assert thing.value == 7
    thing.value = 5
    with pytest.raises(ValidationError):
        thing.value = -1
    assert written == [5]
    assert type(written[0]) is int


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, default, mutate, mutated",
    [
        ({"type": "array", "items": {"type": "integer"}}, [1], lambda value: value.append(2), [1, 2]),
        (
            {"type": "object", "additionalProperties": {"type": "integer"}},
            {"a": 1},
            lambda value: value.update(b=2),
            {"a": 1, "b": 2},
        ),
        # a shallow copy would share the inner list
        (
            {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "integer"}}},
            {"a": [1]},
            lambda value: value["a"].append(2),
            {"a": [1, 2]},
        ),
    ],
    ids=["array", "object", "nested"],
)
def test_11_property_mutable_default_per_instance(
    schema_validator: str,
    schema: dict,
    default: Any,
    mutate: Callable,
    mutated: Any,
):
    property = property_affordance({**schema, "default": default}).to_descriptor(validator=schema_validator)
    assert property.deepcopy_default
    test_thing_cls = type("TestThing", (Thing,), {"value": property})
    first, second = test_thing_cls(id=f"test-thing-{uuid_hex()}"), test_thing_cls(id=f"test-thing-{uuid_hex()}")
    assert first.value is not second.value
    mutate(first.value)
    assert first.value == mutated
    assert second.value == default
    assert first.value != second.value


def test_11_property_scalar_default_is_not_copied():
    assert not property_affordance({"type": "integer", "default": 1}).to_descriptor().deepcopy_default


def test_12_attribute_like_property_needs_a_starting_value():
    affordance = property_affordance({"type": "integer"})
    with pytest.raises(ValueError, match="needs a default or a null option"):
        affordance.to_descriptor()
    test_thing(affordance.to_descriptor(fget=lambda self: 1))


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, handler, valid, invalid",
    [
        (
            {
                "type": "object",
                "properties": {"channel": {"type": "integer"}, "samples": {"type": "integer", "minimum": 1}},
                "required": ["channel"],
            },
            lambda self, channel, samples=10: channel * samples,
            [({"channel": 2}, 20), ({"channel": 2, "samples": 3}, 6)],
            [{"channel": "x"}, {"samples": 3}, {"channel": 2, "samples": 0}],
        ),
        (
            {"type": "number", "minimum": 0},
            lambda self, value: value * 2,
            [(2.5, 5.0)],
            [-1, "x"],
        ),
        (
            {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            lambda self, value: value,
            [(1, 1), ("x", "x")],
            [1.5],
        ),
    ],
)
def test_13_action_input(schema_validator: str, schema: dict, handler: Callable, valid: list[Any], invalid: list[Any]):
    """an object input is called with keyword arguments, any other input with one positional argument."""
    thing = test_thing(action_affordance({"input": schema}).to_descriptor(handler, validator=schema_validator), "act")
    for payload, expected in valid:
        # normally we need the eventloop object which does the splitting of args and kwargs
        # for this test we do this manually for now.
        args, kwargs = ((), payload) if isinstance(payload, dict) else ((payload,), {})
        assert thing.act.external_call(*args, **kwargs) == expected

    for payload in invalid:
        args, kwargs = ((), payload) if isinstance(payload, dict) else ((payload,), {})
        with pytest.raises(ValidationError):
            thing.act.external_call(*args, **kwargs)


@pytest.mark.parametrize(
    "schema_validator, expected_validator",
    [("pydantic", PydanticSchemaValidator), ("json_schema", JSONSchemaValidator)],
)
@pytest.mark.parametrize("safe", [True, False, None])
@pytest.mark.parametrize("idempotent", [True, False, None])
@pytest.mark.parametrize("synchronous", [True, False, None])
@pytest.mark.parametrize(
    "title, description, doc",
    [
        ("Act", "acts on a value", "Act\n\nacts on a value"),
        ("Act", None, "Act"),
        (None, "acts on a value", "acts on a value"),
        (
            None,
            None,
            "Acts on a value.",
        ),  # the docstring of the handler, as for code-first actions, keep in sync with the definition inside the test
    ],
)
def test_14_action_metadata(
    schema_validator: str,
    expected_validator: type,
    safe: bool | None,
    idempotent: bool | None,
    synchronous: bool | None,
    title: str | None,
    description: str | None,
    doc: str,
):
    """an absent flag is left to the default of action(), None stands for absent."""

    def act(self, value: int) -> int:
        """Acts on a value."""
        return value

    fields = {
        "safe": safe,
        "idempotent": idempotent,
        "synchronous": synchronous,
        "title": title,
        "description": description,
    }
    described = action_affordance(
        {
            "input": {"type": "integer"},
            "output": {"type": "integer"},
            **{key: value for key, value in fields.items() if value is not None},
        }
    ).to_descriptor(act, validator=schema_validator)
    assert described.safe is (safe is True)
    assert described.idempotent is (idempotent is True)
    assert described.synchronous is (synchronous is not False)
    assert described.doc == doc
    assert isinstance(described.schema_validator, expected_validator)
    if schema_validator == "json_schema":
        assert described.return_value_schema == {"type": "integer"}
    else:
        assert issubklass(described.return_value_schema, BaseModel)


def test_14_action_schemas_inferred_from_signature():
    """without an input or output in the TD, the schemas are inferred from the signature, as for code-first actions."""

    def annotated(self, value: int) -> int:
        return value

    def unannotated(self, value):
        return value

    inferred = action_affordance({}).to_descriptor(annotated)
    assert issubklass(inferred.argument_schema, BaseModel)
    assert inferred.return_value_schema is not None
    inferred.schema_validator.validate_method_call((1,), {})
    with pytest.raises(ValidationError):
        inferred.schema_validator.validate_method_call(("x",), {})

    # nothing to infer from a signature without annotations
    not_inferred = action_affordance({}).to_descriptor(unannotated)
    assert not_inferred.argument_schema is None
    assert not_inferred.return_value_schema is None
    assert not_inferred.schema_validator is None

    # the TD takes precedence over the signature
    declared = action_affordance({"input": {"type": "string"}, "output": {"type": "string"}}).to_descriptor(
        annotated, validator="json_schema"
    )
    assert declared.argument_schema == {"type": "string"}
    assert declared.return_value_schema == {"type": "string"}
    declared.schema_validator.validate_method_call(("x",), {})
    with pytest.raises(ValidationError):
        declared.schema_validator.validate_method_call((1,), {})


@pytest.mark.parametrize(
    "schema, handler, mismatches",
    [
        (
            {"type": "object", "properties": {"channel": {"type": "integer"}}, "required": ["channel"]},
            lambda self, samples: samples,
            {
                (SignatureMismatchKind.REQUIRED_NOT_IN_INPUT, "samples"),
                (SignatureMismatchKind.PROPERTY_NOT_A_PARAMETER, "channel"),
            },
        ),
        (
            {"type": "object", "properties": {"channel": {}}, "additionalProperties": True},
            lambda self, channel: channel,
            {(SignatureMismatchKind.ADDITIONAL_NEEDS_KWARGS, None)},
        ),
        (
            {"type": "object", "properties": {"channel": {}}},
            lambda self, channel, /: channel,
            {
                (SignatureMismatchKind.POSITIONAL_ONLY, "channel"),
                (SignatureMismatchKind.PROPERTY_NOT_A_PARAMETER, "channel"),
            },
        ),
        ({"type": "number"}, lambda self, low, high: low, {(SignatureMismatchKind.SINGLE_VALUE_ARITY, None)}),
    ],
)
def test_15_action_signature_mismatches(
    schema: dict,
    handler: Callable,
    mismatches: set[tuple[SignatureMismatchKind, str | None]],
):
    affordance = action_affordance({"input": schema})
    with pytest.raises(InputSignatureError) as error:
        affordance.to_descriptor(handler)
    assert {(mismatch.kind, mismatch.name) for mismatch in error.value.mismatches} == mismatches


@pytest.mark.parametrize(
    "schema, handler",
    [
        (
            {"type": "object", "properties": {"channel": {}}, "additionalProperties": True},
            lambda self, channel, **kw: kw,
        ),
        ({"type": "object", "properties": {"low": {}, "high": {}}}, lambda self, **kwargs: kwargs),
        ({"type": "object", "properties": {"channel": {}}}, lambda self, channel, samples=1, *, request=None: channel),
        ({"type": "number"}, lambda self, value, *, request=None: value),
    ],
)
def test_16_action_signature_matches(schema, handler):
    check_input_signature(handler, schema)


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_17_event(schema_validator):
    affordance = event_affordance(
        {
            "title": "Data ready",
            "description": "pushed after an acquisition",
            "data": {"type": "array", "items": {"type": "number"}},
        }
    )
    event = affordance.to_descriptor(validator=schema_validator)
    assert (event.label, event.doc) == ("Data ready", "pushed after an acquisition")
    validator = SchemaValidators.for_schema(event.schema)(event.schema)
    validator.validate([1.0, 2.5])
    with pytest.raises(ValidationError):
        validator.validate(["x"])
    assert event_affordance({}).to_descriptor(validator=schema_validator).schema is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
