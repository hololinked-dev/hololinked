import logging

import pytest

from pydantic import BaseModel

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
from hololinked.td.data_schema import DataSchema
from hololinked.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from hololinked.utils import issubklass, uuid_hex


try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .things.spectrometer import Intensity
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from things.spectrometer import Intensity


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

    affordance = PropertyAffordance()
    assert affordance.owner is None
    assert affordance.objekt is None
    assert affordance.name is None
    assert affordance.thing_id is None
    assert affordance.thing_cls is None

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
    schema = OceanOpticsSpectrometer.integration_time.to_affordance(owner_inst=thing)
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
    schema = integration_time.to_affordance(owner_inst=thing)
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
    schema = integration_time.to_affordance(owner_inst=thing)
    assert schema.exclusiveMinimum == integration_time.bounds[0]
    assert schema.exclusiveMaximum == integration_time.bounds[1]
    with pytest.raises(AttributeError):
        _ = schema.minimum
    with pytest.raises(AttributeError):
        _ = schema.maximum
    with pytest.raises(AttributeError):
        _ = schema.multipleOf
    integration_time.allow_None = True
    schema = integration_time.to_affordance(owner_inst=thing)
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
    schema = OceanOpticsSpectrometer.status.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    status = String(
        regex=r"^[a-zA-Z0-9]{1,10}$",
        default="IDLE",
        doc="status of the spectrometer",
    )
    status.__set_name__(OceanOpticsSpectrometer, "status")
    schema = status.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "string"
    assert schema.pattern == status.regex
    status.allow_None = True
    schema = status.to_affordance(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "string" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    string_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "string")
    assert string_schema["pattern"] == status.regex
    assert schema.default == status.default


def test_04_boolean_schema(thing):
    schema = OceanOpticsSpectrometer.nonlinearity_correction.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    nonlinearity_correction = Boolean(default=True, doc="nonlinearity correction enabled")
    nonlinearity_correction.__set_name__(OceanOpticsSpectrometer, "nonlinearity_correction")
    schema = nonlinearity_correction.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "boolean"
    nonlinearity_correction.allow_None = True
    schema = nonlinearity_correction.to_affordance(owner_inst=thing)
    assert any(subtype["type"] == "null" for subtype in schema.oneOf)
    assert any(subtype["type"] == "boolean" for subtype in schema.oneOf)
    assert len(schema.oneOf) == 2
    assert not hasattr(schema, "type") or schema.type is None
    assert schema.default == nonlinearity_correction.default


def test_05_array_schema(thing):
    schema = OceanOpticsSpectrometer.wavelengths.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    wavelengths = List(
        default=[],
        item_type=(float, int),
        readonly=True,
        allow_None=False,
        doc="wavelength bins of measurement",
    )
    wavelengths.__set_name__(OceanOpticsSpectrometer, "wavelengths")
    schema = wavelengths.to_affordance(owner_inst=thing)
    assert isinstance(schema, BaseModel)
    assert isinstance(schema, DataSchema)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "array"
    for types in schema.items["oneOf"]:
        assert types["type"] == "number" or types["type"] == "integer"
    if OceanOpticsSpectrometer.wavelengths.default is not None:
        assert schema.default == OceanOpticsSpectrometer.wavelengths.default
    OceanOpticsSpectrometer.wavelengths.allow_None = True
    schema = OceanOpticsSpectrometer.wavelengths.to_affordance(owner_inst=thing)
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
        schema = wavelengths.to_affordance(owner_inst=thing)
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
        schema = wavelengths.to_affordance(owner_inst=thing)
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
    schema = OceanOpticsSpectrometer.trigger_mode.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)

    trigger_mode = Selector(
        objects=[0, 1, 2, 3, 4],
        default=0,
        observable=True,
        doc="""0 = normal/free running, 1 = Software trigger, 2 = Ext. Trigger Level,
                    3 = Ext. Trigger Synchro/ Shutter mode, 4 = Ext. Trigger Edge""",
    )
    trigger_mode.__set_name__(OceanOpticsSpectrometer, "trigger_mode")
    schema = trigger_mode.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "integer"
    assert schema.default == 0
    assert schema.enum == trigger_mode.objects

    trigger_mode.allow_None = True
    trigger_mode.default = 3
    trigger_mode.objects = [0, 1, 2, 3, 4, "0", "1", "2", "3", "4"]
    schema = trigger_mode.to_affordance(owner_inst=thing)
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
    schema = last_intensity.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "object"
    assert schema.properties == Intensity.schema["properties"]

    last_intensity.allow_None = True
    schema = last_intensity.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert not hasattr(schema, "type") or schema.type is None
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
    assert isinstance(subschema, dict)
    assert subschema["type"] == "object"
    assert subschema["properties"] == Intensity.schema["properties"]


def test_08_json_schema_properties(thing):
    json_schema_prop = TestThing.json_schema_prop  # type: Property
    json_schema_prop.allow_None = False
    schema = json_schema_prop.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    for key in json_schema_prop.model:
        assert getattr(schema, key, NotImplemented) == json_schema_prop.model[key]

    json_schema_prop.allow_None = True
    schema = json_schema_prop.to_affordance(owner_inst=thing)
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
    schema = pydantic_prop.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    if issubklass(pydantic_prop.model, BaseModel):
        assert schema.type == "object"
        for field in pydantic_prop.model.model_fields:
            assert field in schema.properties

    pydantic_prop.allow_None = True
    schema = pydantic_prop.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
    assert isinstance(subschema, dict)
    for key in pydantic_prop.model.model_fields:
        assert key in subschema.get("properties", {})

    pydantic_simple_prop = TestThing.pydantic_simple_prop  # type: Property # its an integer
    pydantic_simple_prop.allow_None = False
    schema = pydantic_simple_prop.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    assert schema.type == "integer"

    pydantic_simple_prop.allow_None = True
    schema = pydantic_simple_prop.to_affordance(owner_inst=thing)
    assert isinstance(schema, PropertyAffordance)
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "integer")
    assert subschema["type"] == "integer"
    subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "null")
    assert subschema["type"] == "null"


def test_10_thing_model_generation():
    thing = TestThing(id="test-thing-model", log_level=logging.ERROR + 10)
    assert isinstance(thing.get_thing_model(skip_names=["base_property"]).json(), dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
