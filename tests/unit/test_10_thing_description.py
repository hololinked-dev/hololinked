import logging
import warnings

from enum import Enum
from typing import Any

import pytest

from pydantic import BaseModel, Field, RootModel, TypeAdapter, ValidationError
from testkit.things import OceanOpticsSpectrometer, TestThing
from testkit.things.spectrometer import Intensity

from hololinked.constants import ResourceTypes
from hololinked.core.properties import (
    Boolean,
    ClassSelector,
    List,
    Number,
    Property,
    Selector,
    String,
)
from hololinked.metadata.td.data_schema import DataSchema
from hololinked.metadata.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from hololinked.metadata.td.pydantic_extensions import (
    GenerateJsonSchemaWithoutDefaultTitles,
    dataschema_to_model,
    type_to_dataschema,
)
from hololinked.utils import issubklass, uuid_hex


@pytest.fixture(scope="module")
def thing():
    return OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", log_level=logging.ERROR)


@pytest.fixture(scope="module")
def test_thing():
    return TestThing(id=f"test-spectrometer-thing-{uuid_hex()}", log_level=logging.ERROR)


def test_01_associated_objects(thing):
    affordance = PropertyAffordance()
    affordance.objekt = OceanOpticsSpectrometer.integration_time
    affordance.owner = thing
    assert isinstance(affordance, BaseModel)
    assert isinstance(affordance, DataSchema)
    assert isinstance(affordance, InteractionAffordance)
    assert affordance.what == ResourceTypes.PROPERTY
    assert affordance.owner == thing
    assert affordance.thing_id == thing.id
    assert affordance.thing_cls == thing.__class__
    assert isinstance(affordance.objekt, Property)
    assert affordance.name == OceanOpticsSpectrometer.integration_time.name

    affordance = ActionAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.integration_time
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.connect
    assert affordance.what == ResourceTypes.ACTION

    affordance = EventAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.integration_time
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.intensity_measurement_event
    assert affordance.what == ResourceTypes.EVENT

    affordance = PropertyAffordance()
    with pytest.raises(ValueError) as ex:
        affordance.objekt = OceanOpticsSpectrometer.connect
    with pytest.raises(TypeError) as ex:
        affordance.objekt = 5
    assert "objekt must be instance of Property, Action or Event, given type" in str(ex.value)
    affordance.objekt = OceanOpticsSpectrometer.integration_time


def test_02_number_schema(thing):
    schema = OceanOpticsSpectrometer.integration_time.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "number"

    integration_time = Number(
        bounds=(1, 1000),
        default=100,
        crop_to_bounds=True,
        step=1,
        doc="integration time in milliseconds",
        metadata=dict(unit="ms"),
    )
    integration_time.__set_name__(OceanOpticsSpectrometer, "integration_time")
    schema = integration_time.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "number"
    assert schema.minimum == integration_time.bounds[0]
    assert schema.maximum == integration_time.bounds[1]
    assert schema.multipleOf == integration_time.step
    with pytest.raises(AttributeError):
        _ = schema.exclusiveMinimum
    with pytest.raises(AttributeError):
        _ = schema.exclusiveMaximum
    integration_time.inclusive_bounds = (False, False)
    integration_time.step = None
    schema = integration_time.to_metadata(owner_inst=thing)
    assert schema.exclusiveMinimum == integration_time.bounds[0]
    assert schema.exclusiveMaximum == integration_time.bounds[1]
    with pytest.raises(AttributeError):
        _ = schema.minimum
    with pytest.raises(AttributeError):
        _ = schema.maximum
    with pytest.raises(AttributeError):
        _ = schema.multipleOf
    integration_time.allow_None = True
    schema = integration_time.to_metadata(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "number" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    number_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "number")
    assert number_schema["exclusiveMinimum"] == integration_time.bounds[0]
    assert number_schema["exclusiveMaximum"] == integration_time.bounds[1]
    with pytest.raises(KeyError):
        _ = number_schema["minimum"]
    with pytest.raises(KeyError):
        _ = number_schema["maximum"]
    with pytest.raises(KeyError):
        _ = number_schema["multipleOf"]
    assert schema.default == integration_time.default
    assert schema.unit == integration_time.metadata["unit"]


def test_03_string_schema(thing):
    schema = OceanOpticsSpectrometer.status.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    status = String(
        regex=r"^[a-zA-Z0-9]{1,10}$",
        default="IDLE",
        doc="status of the spectrometer",
    )
    status.__set_name__(OceanOpticsSpectrometer, "status")
    schema = status.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "string"
    assert schema.pattern == status.regex
    status.allow_None = True
    schema = status.to_metadata(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "string" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    string_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "string")
    assert string_schema["pattern"] == status.regex
    assert schema.default == status.default


def test_04_boolean_schema(thing):
    schema = OceanOpticsSpectrometer.nonlinearity_correction.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    nonlinearity_correction = Boolean(default=True, doc="nonlinearity correction enabled")
    nonlinearity_correction.__set_name__(OceanOpticsSpectrometer, "nonlinearity_correction")
    schema = nonlinearity_correction.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "boolean"
    nonlinearity_correction.allow_None = True
    schema = nonlinearity_correction.to_metadata(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "boolean" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    assert schema.default == nonlinearity_correction.default


def test_05_array_schema(thing):
    schema = OceanOpticsSpectrometer.wavelengths.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    wavelengths = List(
        default=[],
        item_type=(float, int),
        readonly=True,
        allow_None=False,
        doc="wavelength bins of measurement",
    )
    wavelengths.__set_name__(OceanOpticsSpectrometer, "wavelengths")
    schema = wavelengths.to_metadata(owner_inst=thing)
    assert isinstance(schema, BaseModel)
    assert isinstance(schema, DataSchema)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "array"
    for types in schema.items["oneOf"]:
        assert types["type"] == "number" or types["type"] == "integer"
    if OceanOpticsSpectrometer.wavelengths.default is not None:
        assert schema.default == OceanOpticsSpectrometer.wavelengths.default
    OceanOpticsSpectrometer.wavelengths.allow_None = True
    schema = OceanOpticsSpectrometer.wavelengths.to_metadata(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "array" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    array_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "array")
    for types in array_schema["items"]["oneOf"]:
        assert types["type"] == "number" or types["type"] == "integer"

    for bounds in [(5, 1000), (None, 100), (50, None), (51, 101)]:
        wavelengths.bounds = bounds
        wavelengths.allow_None = False
        schema = wavelengths.to_metadata(owner_inst=thing)
        if bounds[0] is not None:
            assert schema.minItems == bounds[0]
        else:
            assert not hasattr(schema, "minItems") or schema.minItems is None
        if bounds[1] is not None:
            assert schema.maxItems == bounds[1]
        else:
            assert not hasattr(schema, "maxItems") or schema.maxItems is None
        wavelengths.bounds = bounds
        wavelengths.allow_None = True
        schema = wavelengths.to_metadata(owner_inst=thing)
        subtype = next(subtype for subtype in schema.oneOf if subtype["type"] == "array")
        if bounds[0] is not None:
            assert subtype["minItems"] == bounds[0]
        else:
            with pytest.raises(KeyError):
                _ = subtype["minItems"]
        if bounds[1] is not None:
            assert subtype["maxItems"] == bounds[1]
        else:
            with pytest.raises(KeyError):
                _ = subtype["maxItems"]


def test_06_enum_schema(thing):
    schema = OceanOpticsSpectrometer.trigger_mode.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    trigger_mode = Selector(
        objects=[0, 1, 2, 3, 4],
        default=0,
        observable=True,
        doc="""0 = normal/free running, 1 = Software trigger, 2 = Ext. Trigger Level,
                    3 = Ext. Trigger Synchro/ Shutter mode, 4 = Ext. Trigger Edge""",
    )
    trigger_mode.__set_name__(OceanOpticsSpectrometer, "trigger_mode")
    schema = trigger_mode.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "integer"
    assert schema.default == 0
    assert schema.enum == trigger_mode.objects

    trigger_mode.allow_None = True
    trigger_mode.default = 3
    trigger_mode.objects = [0, 1, 2, 3, 4, "0", "1", "2", "3", "4"]
    schema = trigger_mode.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert not hasattr(schema, "type") or schema.type is None
    assert schema.default == 3
    enum_subschema = next(
        subtype
        for subtype in schema.oneOf
        if (subtype.get("type", None) != "null" or len(subtype.get("oneOf", [])) > 1)
    )
    assert isinstance(enum_subschema, dict)
    assert enum_subschema["enum"] == trigger_mode.objects


def test_07_class_selector_custom_schema(thing):
    last_intensity = ClassSelector(
        default=Intensity([], []),
        allow_None=False,
        class_=Intensity,
        doc="last measurement intensity (in arbitrary units)",
    )
    last_intensity.__set_name__(OceanOpticsSpectrometer, "last_intensity")
    schema = last_intensity.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "object"
    assert schema.properties == Intensity.schema["properties"]

    last_intensity.allow_None = True
    schema = last_intensity.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert not hasattr(schema, "type") or schema.type is None
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
    assert isinstance(subschema, dict)
    assert subschema["type"] == "object"
    assert subschema["properties"] == Intensity.schema["properties"]


def test_08_json_schema_properties(thing):
    json_schema_prop = TestThing.json_schema_prop  # type: Property
    json_schema_prop.allow_None = False
    schema = json_schema_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    for key in json_schema_prop.model:
        assert getattr(schema, key, NotImplemented) == json_schema_prop.model[key]

    json_schema_prop.allow_None = True
    schema = json_schema_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    subschema = next(
        subtype
        for subtype in schema.oneOf
        if (subtype.get("type", None) != "null" or len(subtype.get("oneOf", [])) > 1)
    )
    assert isinstance(subschema, dict)
    for key in json_schema_prop.model:
        assert subschema.get(key, NotImplemented) == json_schema_prop.model[key]


def test_09_pydantic_properties(thing):
    pydantic_prop = TestThing.pydantic_prop  # type: Property
    pydantic_prop.allow_None = False
    schema = pydantic_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    if issubklass(pydantic_prop.model, BaseModel):
        assert schema.type == "object"
        for field in pydantic_prop.model.model_fields:
            assert field in schema.properties

    pydantic_prop.allow_None = True
    schema = pydantic_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
    assert isinstance(subschema, dict)
    for key in pydantic_prop.model.model_fields:
        assert key in subschema.get("properties", {})

    pydantic_simple_prop = TestThing.pydantic_simple_prop  # type: Property # its an integer
    pydantic_simple_prop.allow_None = False
    schema = pydantic_simple_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "integer"

    pydantic_simple_prop.allow_None = True
    schema = pydantic_simple_prop.to_metadata(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "integer")
    assert subschema["type"] == "integer"
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "null")
    assert subschema["type"] == "null"


def test_10_thing_model_generation():
    thing = TestThing(id="test-thing-model", log_level=logging.ERROR + 10)
    assert isinstance(thing.get_thing_model(skip_names=["base_property"]).json(), dict)


@pytest.mark.parametrize(
    "schema_type, valid, invalid",
    [
        ("null", None, 0),
        ("boolean", True, [True]),
        ("integer", 5, 5.5),
        ("number", 5.5, "five"),
        ("string", "five", 5),
    ],
)
def test_11_dataschema_to_model_primitive_types(schema_type, valid, invalid):
    model = dataschema_to_model({"type": schema_type}, "Model")
    assert type_to_dataschema(model.model_fields["root"].annotation) == {"type": schema_type}
    assert model.model_validate(valid).root == valid
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "array", "items": {}}, [1, "a", None], "abc"),
        ({"type": "array", "items": {"type": "integer"}}, [1, 2], [1, "a"]),
        ({"type": "array", "items": {"type": "array", "items": {"type": "string"}}}, [["a"], []], [["a", 1]]),
    ],
)
def test_12_dataschema_to_model_arrays(schema, valid, invalid):
    model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model.model_fields["root"].annotation) == schema
    assert model.model_validate(valid).root == valid
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "array", "items": [{"type": "integer"}, {"type": "string"}]}, (1, "a"), [1, 2]),
        ({"type": "array", "prefixItems": [{"type": "integer"}, {"type": "string"}]}, (1, "a"), [1, "a", 2]),
        ({"type": "array", "prefixItems": [{}, {"type": "boolean"}], "items": False}, (None, True), [None]),
    ],
)
def test_13_dataschema_to_model_tuples(schema, valid, invalid):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert model.model_validate(valid).root == valid
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_14_dataschema_to_model_tuple_round_trip():
    for python_type in (tuple[int, str], tuple[Any, tuple[float, bool]]):
        schema = type_to_dataschema(python_type)
        model = dataschema_to_model(schema, "Model")
        assert type_to_dataschema(model.model_fields["root"].annotation) == schema
    with pytest.warns(UserWarning, match="maxItems"):
        dataschema_to_model({"type": "array", "items": [{"type": "integer"}], "maxItems": 3}, "Model")


def test_15_dataschema_to_model_objects():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "position": {
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                "required": ["x", "y"],
            },
            "tags": {"type": "array", "items": {"type": "object", "properties": {"label": {"type": "string"}}}},
        },
        "required": ["position"],
    }
    model = dataschema_to_model(schema, "Model")
    assert not issubklass(model, RootModel)
    assert type_to_dataschema(model) == schema
    assert list(model.model_fields) == ["name", "position", "tags"]

    instance = model.model_validate({"position": {"x": 1, "y": 2.5}, "tags": [{"label": "a"}, {}]})
    assert instance.name is None and instance.position.y == 2.5 and instance.tags[1].label is None
    for invalid in (
        {},  # required field missing
        {"position": {"x": 1}},  # nested required field missing
        {"position": {"x": 1, "y": 2}, "name": None},  # optional is not nullable
        {"position": {"x": 1, "y": 2}, "speed": 3},  # additional properties are forbidden
        {"position": {"x": 1, "y": 2}, "tags": [{"label": 1}]},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(invalid)


def test_16_dataschema_to_model_object_edge_cases():
    class Point(BaseModel):
        x: int = Field(description="horizontal")
        y: list[float] = [0.0]

    schema = type_to_dataschema(Point)
    assert type_to_dataschema(dataschema_to_model(schema, "Point")) == schema

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            "Model",
        )
    assert model.model_validate({"a": 1, "b": [None]}).b == [None]
    with pytest.raises(ValidationError):
        model.model_validate({"a": 1})


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "object"}, {"a": 1, "b": [None]}, [("a", 1)]),
        ({"type": "object", "additionalProperties": True}, {"a": 1}, "a"),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, {"a": 1}, {"a": "b"}),
        (
            {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "number"}}},
            {"a": [1.5], "b": []},
            {"a": 1.5},
        ),
        ({"type": "object", "additionalProperties": False}, {}, {"a": 1}),
    ],
)
def test_17_dataschema_to_model_dictionaries(schema, valid, invalid):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert model.model_validate(valid).model_dump() == valid
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_18_dataschema_to_model_objects_with_additional_properties():
    # TD generation drops additionalProperties, so free-form dictionaries read back with any value type
    assert type_to_dataschema(dataschema_to_model(type_to_dataschema(dict[str, int]), "Model")) == {"type": "object"}

    properties = {"name": {"type": "string"}}
    model = dataschema_to_model(
        {"type": "object", "properties": properties, "additionalProperties": {"type": "integer"}}, "Model"
    )
    assert list(model.model_fields) == ["name"]
    assert model.model_validate({"name": "a", "count": 1}).model_extra == {"count": 1}
    with pytest.raises(ValidationError):
        model.model_validate({"name": "a", "count": "one"})

    model = dataschema_to_model({"type": "object", "properties": properties, "additionalProperties": True}, "Model")
    assert model.model_validate({"name": "a", "anything": [None]}).model_extra == {"anything": [None]}


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "string", "enum": ["fast", "slow"]}, ["fast", "slow"], ["medium", 1]),
        ({"enum": [1, "a", None]}, [1, "a", None], [2, "b"]),
        ({"type": "number", "enum": [1.5, 2.5]}, [1.5, 2.5], [2.0, "1.5"]),
        ({"const": "x", "type": "string"}, ["x"], ["y"]),
        ({"type": "array", "enum": [[1, 2], [3]]}, [[1, 2], [3]], [[1], [1, 2, 3]]),
        ({"enum": [{"a": 1}, {"a": 2}]}, [{"a": 1}], [{"a": 3}, {"a": 1, "b": 1}]),
    ],
)
def test_19_dataschema_to_model_enum_and_const(schema, valid, invalid):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model) == schema
    for value in valid:
        assert model.model_validate(value).root == value
    for value in invalid:
        with pytest.raises(ValidationError):
            model.model_validate(value)


def test_20_dataschema_to_model_enum_and_const_edge_cases():
    class Mode(str, Enum):
        FAST = "fast"
        SLOW = "slow"

    schema = type_to_dataschema(Mode)
    assert type_to_dataschema(dataschema_to_model(schema, "Mode")) == schema
    # a single valued enum is the same constraint as const, and pydantic writes it as such
    assert type_to_dataschema(dataschema_to_model({"type": "string", "enum": ["x"]}, "Model")) == {
        "const": "x",
        "type": "string",
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dataschema_to_model({"const": 1, "enum": [1, 2]}, "Model")
        # the listed values make items redundant, so the regenerated schema drops it
        model = dataschema_to_model({"type": "array", "items": {"type": "integer"}, "enum": [[1, 2]]}, "Model")
    assert type_to_dataschema(model) == {"type": "array", "const": [1, 2]}
    with pytest.warns(UserWarning, match="enum"):
        dataschema_to_model({"const": 3, "enum": [1, 2]}, "Model")

    model = dataschema_to_model(
        {"type": "object", "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}}, "required": ["mode"]},
        "Model",
    )
    assert model.model_validate({"mode": "fast"}).mode == "fast"
    with pytest.raises(ValidationError):
        model.model_validate({"mode": "medium"})


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"oneOf": [{"type": "integer"}, {"type": "null"}]}, [1, None], ["a", 1.5]),
        ({"oneOf": [{"type": "integer"}, {"const": "auto", "type": "string"}]}, [1, "auto"], ["manual"]),
        ({"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "number"}}]}, ["a", [1.5]], [["a"], 1]),
        (
            {
                "oneOf": [
                    {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
                    {"type": "null"},
                ]
            },
            [{"x": 1}, None],
            [{"y": 1}, 1],
        ),
    ],
)
def test_21_dataschema_to_model_unions(schema, valid, invalid):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model) == schema
    for value in valid:
        assert model.model_validate(value).model_dump() == value
    for value in invalid:
        with pytest.raises(ValidationError):
            model.model_validate(value)


def test_22_dataschema_to_model_union_edge_cases():
    # TD generation writes pydantic's anyOf as oneOf
    model = dataschema_to_model({"anyOf": [{"type": "integer"}, {"type": "string"}]}, "Model")
    assert type_to_dataschema(model) == {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert model.model_validate("1").root == "1"  # the exact type wins over coercion
    assert type_to_dataschema(dataschema_to_model({"oneOf": [{"type": "integer"}]}, "Model")) == {"type": "integer"}
    with pytest.raises(TypeError, match=r"#/oneOf/1"):
        dataschema_to_model({"oneOf": [{"type": "integer"}, {"type": "string", "not": {}}]}, "Model", strict=True)
    with pytest.warns(UserWarning, match="oneOf"):
        dataschema_to_model({"type": "integer", "oneOf": [{"const": 1}, {"const": 2}]}, "Model")


@pytest.mark.parametrize(
    "schema, valid, invalid",
    [
        ({"type": "integer", "minimum": 0, "maximum": 10, "multipleOf": 2}, [0, 4, 10], [-2, 3, 12]),
        ({"type": "number", "exclusiveMinimum": 0.5, "exclusiveMaximum": 1}, [0.75], [0.5, 1]),
        (
            {"type": "string", "minLength": 2, "maxLength": 4, "pattern": "^[a-z]+$"},
            ["ab", "abcd"],
            ["a", "abcde", "AB"],
        ),
        ({"type": "string", "pattern": "b"}, ["abc"], ["xyz"]),  # unanchored, like JSON schema
        ({"type": "string", "pattern": r"^(?!x)(a)\1"}, ["aa"], ["ab", "xaa"]),  # lookaround and backreference
        (
            {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 1, "maxItems": 2},
            [[0], [1, 2]],
            [[], [1, 2, 3], [-1]],
        ),
    ],
)
def test_23_dataschema_to_model_constraints(schema, valid, invalid):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model) == schema
    for value in valid:
        assert model.model_validate(value).root == value
    for value in invalid:
        with pytest.raises(ValidationError):
            model.model_validate(value)


def test_24_dataschema_to_model_constraint_edge_cases():
    schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "pattern": r"^(?=[A-Z])\w+$"},
            "gain": {"type": "number", "minimum": 0},
        },
        "required": ["code"],
    }
    model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model) == schema
    assert model.model_validate({"code": "A1", "gain": 0}).code == "A1"
    with pytest.raises(ValidationError):
        model.model_validate({"code": "a1"})

    # constraints next to enum or const filter the listed values, an equivalent schema
    model = dataschema_to_model({"type": "integer", "enum": [1, 2, 3], "minimum": 2}, "Model")
    assert type_to_dataschema(model) == {"type": "integer", "enum": [2, 3]}
    with pytest.raises(ValueError, match="enum"):
        dataschema_to_model({"type": "integer", "enum": [1, 2], "minimum": 3}, "Model")

    # a tuple has a fixed length, other length limits are not applied
    with pytest.warns(UserWarning, match="minItems"):
        dataschema_to_model({"type": "array", "items": [{"type": "integer"}], "minItems": 0}, "Model")
    # constraints of another type have no meaning
    with pytest.warns(UserWarning, match="minLength"):
        dataschema_to_model({"type": "integer", "minLength": 1}, "Model")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "number", "title": "Gain", "description": "amplifier gain", "default": 1.5, "minimum": 0},
        {
            "type": "string",
            "titles": {"de": "Modus"},
            "descriptions": {"de": "Betriebsart"},
            "enum": ["a", "b"],
            "default": "a",
        },
        {"type": "array", "items": {"type": "integer", "description": "a sample"}, "default": [1, 2]},
        {"oneOf": [{"type": "integer"}, {"type": "null"}], "default": None, "description": "optional count"},
        {
            "type": "object",
            "title": "Settings",
            "description": "acquisition settings",
            "properties": {
                "samples": {"type": "integer", "default": 1000, "description": "per channel"},
                "trigger": {
                    "type": "object",
                    "title": "Trigger",
                    "properties": {"level": {"type": "number", "default": 0.5}},
                    "default": {"level": 0.1},
                },
                "channel": {"type": "integer", "default": 1},
            },
            "required": ["channel"],
        },
    ],
)
def test_25_dataschema_to_model_annotations(schema):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Model")
    assert type_to_dataschema(model) == schema


def test_26_dataschema_to_model_field_defaults():
    schema = {
        "type": "object",
        "properties": {
            "samples": {"type": "integer", "default": 1000},
            "label": {"type": "string"},
            "channel": {"type": "integer", "default": 1},
            "trigger": {
                "type": "object",
                "properties": {"level": {"type": "number"}},
                "required": ["level"],
                "default": {"level": 0.1},
            },
        },
        "required": ["channel"],
    }
    model = dataschema_to_model(schema, "Model")
    instance = model.model_validate({"channel": 2})
    assert instance.samples == 1000
    assert instance.label is None
    assert instance.channel == 2
    assert isinstance(instance.trigger, BaseModel)  # defaults are validated
    assert instance.trigger.level == 0.1
    with pytest.raises(ValidationError):
        model.model_validate({})  # a default does not make a required field optional

    # an invalid default is reported when the TD is converted, not when a request leaves the field out
    for invalid, location in (
        ({"type": "integer", "default": "many"}, "#/default"),
        ({"type": "integer", "minimum": 0, "default": -1}, "#/default"),
        ({"type": "object", "properties": {"n": {"type": "string", "default": None}}}, "#/properties/n/default"),
        ({"type": "array", "items": {"type": "object", "properties": {}}, "default": [{"x": 1}]}, "#/default"),
    ):
        with pytest.raises(ValueError, match=location):
            dataschema_to_model(invalid, "Model")


def test_27_dataschema_to_model_references():
    class Point(BaseModel):
        x: float
        y: float

    class Path(BaseModel):
        start: Point
        points: list[Point]
        end: Point | None = None

    # pydantic's own JSON schema refers to nested models through $defs
    schema = TypeAdapter(Path).json_schema(schema_generator=GenerateJsonSchemaWithoutDefaultTitles)
    assert "$defs" in schema
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        model = dataschema_to_model(schema, "Path")
    assert type_to_dataschema(model) == type_to_dataschema(Path)
    instance = model.model_validate({"start": {"x": 0, "y": 0}, "points": [{"x": 1, "y": 2}]})
    assert instance.points[0].y == 2
    with pytest.raises(ValidationError):
        model.model_validate({"start": {"x": 0}, "points": []})

    # keywords next to $ref apply together with the referenced schema
    model = dataschema_to_model({"$defs": {"n": {"type": "integer"}}, "$ref": "#/$defs/n", "minimum": 0}, "Model")
    assert type_to_dataschema(model) == {"type": "integer", "minimum": 0}
    # references can resolve against an enclosing document, such as a TD
    td = {"schemaDefinitions": {"level": {"type": "number", "maximum": 1}}}
    model = dataschema_to_model({"$ref": "#/schemaDefinitions/level"}, "Model", root=td)
    assert type_to_dataschema(model) == {"type": "number", "maximum": 1}


def test_28_dataschema_to_model_reference_errors():
    node = {"type": "object", "properties": {"next": {"$ref": "#/$defs/node"}}}
    with pytest.raises(ValueError, match="circular"):
        dataschema_to_model({"$defs": {"node": node}, "$ref": "#/$defs/node"}, "Model")
    with pytest.raises(KeyError, match="missing"):
        dataschema_to_model({"$ref": "#/$defs/missing"}, "Model")
    with pytest.raises(NotImplementedError):
        dataschema_to_model({"$ref": "https://example.com/schema.json"}, "Model")
    with pytest.raises(TypeError, match=r"#/\$defs/n"):  # problems are located in the referenced schema
        dataschema_to_model({"$defs": {"n": {"type": "integer", "not": {}}}, "$ref": "#/$defs/n"}, "Model", strict=True)


def test_29_dataschema_to_model_unsupported_keywords():
    with pytest.warns(UserWarning, match="not"):
        dataschema_to_model({"type": "integer", "not": {"const": 0}}, "Model")
    with pytest.raises(TypeError, match="not"):
        dataschema_to_model({"type": "integer", "not": {"const": 0}}, "Model", strict=True)
    dataschema_to_model({"type": "number", "unit": "s", "readOnly": True}, "Model", strict=True)
    with pytest.raises(TypeError, match=r"#/items"):
        dataschema_to_model({"type": "array", "items": {"type": "integer", "not": {"const": 0}}}, "Model", strict=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
