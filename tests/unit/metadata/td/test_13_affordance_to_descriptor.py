import jsonschema
import pytest

from pydantic import BaseModel

from hololinked import SchemaValidators
from hololinked.core import Action, Property, Thing
from hololinked.metadata.td.forms import Form
from hololinked.metadata.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
    input_signature_mismatches,
    schema_for_validator,
)
from hololinked.schema_validators.json_schema import JSONSchemaValidator
from hololinked.schema_validators.pydantic_model import PydanticSchemaValidator
from hololinked.utils import issubklass, uuid_hex


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
def test_01_from_metadata_keeps_schema_keywords(schema):
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
def test_02_from_metadata_drops_undeclared_keywords(affordance_cls, kind):
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
    "schema_validator, expected",
    [("pydantic", PydanticSchemaValidator), ("json_schema", JSONSchemaValidator)],
)
def test_03_schema_for_validator(schema_validator, expected):
    schema = {"type": "number", "minimum": 0}
    converted, preset = schema_for_validator(schema, "value", schema_validator)
    if expected is PydanticSchemaValidator:
        assert issubklass(converted, BaseModel)
        assert preset is None
    else:
        assert converted is schema
        assert type(preset) is expected


def property_affordance(schema: dict) -> PropertyAffordance:
    td = {"id": "thing", "properties": {"value": schema}}
    return PropertyAffordance.from_metadata("value", td)


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
    assert affordance.to_descriptor(schema_validator="json_schema").model == value
    assert property_affordance(interaction).to_descriptor(fget=lambda self: 1).model is None


def probe(descriptor: Property | Action, name: str = "value") -> Thing:
    return type("Probe", (Thing,), {name: descriptor})(id=f"probe-{uuid_hex()}")


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
def test_05_property_validates_writes(schema_validator, schema, valid, invalid):
    thing = probe(property_affordance(schema).to_descriptor(schema_validator=schema_validator))
    for value in valid:
        thing.value = value
    for value in invalid:
        with pytest.raises((ValueError, jsonschema.ValidationError)):
            thing.value = value


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_06_property_flags(schema_validator):
    affordance = property_affordance(
        {
            "type": "integer",
            "minimum": 0,
            "title": "Value",
            "description": "a value",
            "readOnly": True,
            "observable": True,
            "unit": "V",
            "default": 3,
        }
    )
    property = affordance.to_descriptor(schema_validator=schema_validator)
    assert property.readonly
    assert property.observable
    assert property.metadata == {"unit": "V"}
    assert (property.label, property.doc) == ("Value", "a value")
    thing = probe(property)
    assert thing.value == 3
    with pytest.raises(ValueError, match="Read-only"):
        thing.value = 4


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
@pytest.mark.parametrize(
    "schema, data_schema, valid, invalid",
    [
        (
            {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}], "default": 1},
            {"type": "integer", "minimum": 0, "default": 1},
            [None, 2],
            [-1],
        ),
        (
            {"oneOf": [{"type": "null"}, {"type": "integer"}, {"type": "string"}]},
            {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            [None, 2, "x"],
            [1.5],
        ),
        # written by hololinked for a typed property such as Number(allow_None=True)
        ({"type": "number", "oneOf": [{"type": "null"}]}, {"type": "number"}, [None, 2.5], ["x"]),
    ],
)
def test_07_property_null_option(schema_validator, schema, data_schema, valid, invalid):
    affordance = property_affordance(schema)
    assert affordance.to_descriptor(schema_validator="json_schema").model == data_schema
    property = affordance.to_descriptor(schema_validator=schema_validator)
    assert property.allow_None
    thing = probe(property)
    for value in valid:
        thing.value = value
        assert thing.value == value
    for value in invalid:
        with pytest.raises((ValueError, jsonschema.ValidationError)):
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
def test_08_property_const(schema_validator, schema, value):
    property = property_affordance(schema).to_descriptor(schema_validator=schema_validator)
    assert property.constant
    thing = probe(property)
    assert thing.value == value
    with pytest.raises(ValueError, match="Constant"):
        thing.value = value


def test_09_property_write_only_warns():
    with pytest.warns(UserWarning, match="writeOnly"):
        property_affordance({"type": "integer", "writeOnly": True, "default": 0}).to_descriptor()


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_10_property_handlers(schema_validator):
    """fget serves reads, fset receives the validated plain value."""
    written = []
    property = property_affordance({"type": "integer", "minimum": 0}).to_descriptor(
        fget=lambda self: 7,
        fset=lambda self, value: written.append(value),
        schema_validator=schema_validator,
    )
    thing = probe(property)
    assert thing.value == 7
    thing.value = 5
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        thing.value = -1
    assert written == [5]
    assert type(written[0]) is int


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_11_property_mutable_default_per_instance(schema_validator):
    property = property_affordance({"type": "array", "items": {"type": "integer"}, "default": [1]}).to_descriptor(
        schema_validator=schema_validator
    )
    assert property.deepcopy_default
    probe_cls = type("Probe", (Thing,), {"value": property})
    first, second = probe_cls(id=f"probe-{uuid_hex()}"), probe_cls(id=f"probe-{uuid_hex()}")
    first.value.append(2)
    assert second.value == [1]


def test_12_stored_property_needs_a_starting_value():
    affordance = property_affordance({"type": "integer"})
    with pytest.raises(ValueError, match="needs a default or a null option"):
        affordance.to_descriptor()
    probe(affordance.to_descriptor(fget=lambda self: 1))


def action_affordance(affordance: dict) -> ActionAffordance:
    return ActionAffordance.from_metadata("act", {"id": "thing", "actions": {"act": affordance}})


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
def test_13_action_input(schema_validator, schema, handler, valid, invalid):
    """an object input is called with keyword arguments, any other input with one positional argument."""
    thing = probe(action_affordance({"input": schema}).to_descriptor(handler, schema_validator=schema_validator), "act")

    def call(payload):
        return thing.act.external_call(**payload) if isinstance(payload, dict) else thing.act.external_call(payload)

    for payload, expected in valid:
        assert call(payload) == expected
    for payload in invalid:
        with pytest.raises((ValueError, jsonschema.ValidationError)):
            call(payload)


def test_14_action_metadata():
    def act(self, value: int) -> int:
        """Acts on a value."""
        return value

    described = action_affordance(
        {
            "title": "Act",
            "description": "acts on a value",
            "safe": True,
            "idempotent": True,
            "synchronous": False,
            "input": {"type": "integer"},
            "output": {"type": "integer"},
        }
    ).to_descriptor(act, schema_validator="json_schema")
    assert described.doc == "Act\n\nacts on a value"
    assert (described.safe, described.idempotent, described.synchronous) == (True, True, False)
    assert described.return_value_schema == {"type": "integer"}
    assert isinstance(described.schema_validator, JSONSchemaValidator)

    plain = action_affordance({}).to_descriptor(act)
    assert plain.doc == act.__doc__
    assert (plain.safe, plain.idempotent, plain.synchronous) == (False, False, True)
    assert plain.argument_schema is not None  # inferred from the signature, as for code-first actions


@pytest.mark.parametrize(
    "schema, handler, mismatches",
    [
        (
            {"type": "object", "properties": {"channel": {"type": "integer"}}, "required": ["channel"]},
            lambda self, samples: samples,
            ["required parameter 'samples' is not an input property", "input property 'channel' is not a parameter"],
        ),
        (
            {"type": "object", "properties": {"channel": {}}, "additionalProperties": True},
            lambda self, channel: channel,
            ["the handler takes **kwargs"],
        ),
        (
            {"type": "object", "properties": {"channel": {}}},
            lambda self, channel, /: channel,
            ["parameter 'channel' is positional-only"],
        ),
        ({"type": "number"}, lambda self, low, high: low, ["exactly one positional parameter"]),
    ],
)
def test_15_action_signature_mismatches(schema, handler, mismatches):
    affordance = action_affordance({"input": schema})
    with pytest.raises(TypeError) as error:
        affordance.to_descriptor(handler)
    for mismatch in mismatches:
        assert mismatch in str(error.value)


@pytest.mark.parametrize(
    "schema, handler",
    [
        ({"type": "object", "properties": {"channel": {}}, "additionalProperties": True}, lambda self, channel, **kw: kw),
        ({"type": "object", "properties": {"low": {}, "high": {}}}, lambda self, **kwargs: kwargs),
        ({"type": "object", "properties": {"channel": {}}}, lambda self, channel, samples=1, *, request=None: channel),
        ({"type": "number"}, lambda self, value, *, request=None: value),
    ],
)
def test_16_action_signature_matches(schema, handler):
    assert input_signature_mismatches(handler, schema) == []


def event_affordance(affordance: dict) -> EventAffordance:
    return EventAffordance.from_metadata("data_ready", {"id": "thing", "events": {"data_ready": affordance}})


@pytest.mark.parametrize("schema_validator", ["pydantic", "json_schema"])
def test_17_event(schema_validator):
    affordance = event_affordance(
        {
            "title": "Data ready",
            "description": "pushed after an acquisition",
            "data": {"type": "array", "items": {"type": "number"}},
        }
    )
    event = affordance.to_descriptor(schema_validator=schema_validator)
    assert (event.label, event.doc) == ("Data ready", "pushed after an acquisition")
    validator = SchemaValidators.for_schema(event.schema)(event.schema)
    validator.validate([1.0, 2.5])
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        validator.validate(["x"])
    assert event_affordance({}).to_descriptor(schema_validator=schema_validator).schema is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
