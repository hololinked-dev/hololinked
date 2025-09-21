import logging
import unittest
from pydantic import BaseModel
from hololinked.constants import ResourceTypes
from hololinked.schema_validators.json_schema import JSONSchema
from hololinked.td.data_schema import DataSchema
from hololinked.td.interaction_affordance import (
    PropertyAffordance,
    InteractionAffordance,
    ActionAffordance,
    EventAffordance,
)
from hololinked.core.properties import (
    Property,
    Number,
    String,
    Boolean,
    List,
    Selector,
    ClassSelector,
)
from hololinked.utils import issubklass

try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import TestCase, TestRunner
    from .things.spectrometer import Intensity
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from utils import TestCase, TestRunner
    from things.spectrometer import Intensity


class TestInteractionAffordance(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing = OceanOpticsSpectrometer(id="test-thing", log_level=logging.ERROR)
        print(f"Test Interaction Affordance with {cls.__name__}")

    def test_1_associated_objects(self):
        affordance = PropertyAffordance()
        affordance.objekt = OceanOpticsSpectrometer.integration_time
        affordance.owner = self.thing
        # req. 1. internal test for multiple inheritance of pydantic models as there are many classes to track
        self.assertIsInstance(affordance, BaseModel)
        self.assertIsInstance(affordance, DataSchema)
        self.assertIsInstance(affordance, InteractionAffordance)
        self.assertTrue(affordance.what, ResourceTypes.PROPERTY)
        # req. 2. owner must be a Thing
        self.assertEqual(affordance.owner, self.thing)
        # req. 3. when owner is set, thing id & thing class is also set
        self.assertEqual(affordance.thing_id, self.thing.id)
        self.assertEqual(affordance.thing_cls, self.thing.__class__)
        # req. 4. objekt must be a Property, since we use a property affordance here
        self.assertIsInstance(affordance.objekt, Property)
        # req. 5. objekt must be a property of the owner thing
        # --- not enforced yet
        # req. 6. when objekt is set, property name is also set
        self.assertEqual(affordance.name, OceanOpticsSpectrometer.integration_time.name)

        # test the opposite
        affordance = PropertyAffordance()
        # req. 7. accessing any of unset objects should raise an error
        self.assertTrue(affordance.owner is None)
        self.assertTrue(affordance.objekt is None)
        self.assertTrue(affordance.name is None)
        self.assertTrue(affordance.thing_id is None)
        self.assertTrue(affordance.thing_cls is None)

        # req. 8. Only the corresponding object can be set for each affordance type
        # i.e. ActionAffordance accepts only an Action as its Objekt, same for property and same for event
        affordance = ActionAffordance()
        with self.assertRaises(ValueError) as ex:
            affordance.objekt = OceanOpticsSpectrometer.integration_time
        with self.assertRaises(TypeError) as ex:
            affordance.objekt = 5
        self.assertIn(
            "objekt must be instance of Property, Action or Event, given type",
            str(ex.exception),
        )
        affordance.objekt = OceanOpticsSpectrometer.connect
        self.assertTrue(affordance.what, ResourceTypes.ACTION)

        affordance = EventAffordance()
        with self.assertRaises(ValueError) as ex:
            affordance.objekt = OceanOpticsSpectrometer.integration_time
        with self.assertRaises(TypeError) as ex:
            affordance.objekt = 5
        self.assertIn(
            "objekt must be instance of Property, Action or Event, given type",
            str(ex.exception),
        )
        affordance.objekt = OceanOpticsSpectrometer.intensity_measurement_event
        self.assertTrue(affordance.what, ResourceTypes.EVENT)

        affordance = PropertyAffordance()
        with self.assertRaises(ValueError) as ex:
            affordance.objekt = OceanOpticsSpectrometer.connect
        with self.assertRaises(TypeError) as ex:
            affordance.objekt = 5
        self.assertIn(
            "objekt must be instance of Property, Action or Event, given type",
            str(ex.exception),
        )
        affordance.objekt = OceanOpticsSpectrometer.integration_time


class TestDataSchema(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing = OceanOpticsSpectrometer(id="test-thing", log_level=logging.ERROR)
        print(f"Test Data Schema with {cls.__name__}")

    """
    OceanOpticsSpectrometer.trigger_mode # selector 
    OceanOpticsSpectrometer.integration_time # number
    OceanOpticsSpectrometer.serial_number # string
    OceanOpticsSpectrometer.nonlinearity_correction # boolean
    OceanOpticsSpectrometer.custom_background_intensity # typed list float, int
    OceanOpticsSpectrometer.wavelengths # list float int
    """

    def test_2_number_schema(self):
        # test implicit generation before actual testing
        schema = OceanOpticsSpectrometer.integration_time.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "number")
        # this is because we will use a Property directly so that we can generate dataschema
        # based on different parameters of the property. See below

        integration_time = Number(
            bounds=(1, 1000),
            default=100,
            crop_to_bounds=True,
            step=1,
            doc="integration time in milliseconds",
            metadata=dict(unit="ms"),
        )
        integration_time.__set_name__(OceanOpticsSpectrometer, "integration_time")
        # req. 1. Schema can be created
        schema = integration_time.to_affordance(owner_inst=self.thing)
        # print(schema.json())
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "number")
        # req. 2. Test number schema specific attributes
        # minimum, maximum, multipleOf
        self.assertEqual(schema.minimum, integration_time.bounds[0])
        self.assertEqual(schema.maximum, integration_time.bounds[1])
        self.assertEqual(schema.multipleOf, integration_time.step)
        self.assertRaises(AttributeError, lambda: schema.exclusiveMinimum)
        self.assertRaises(AttributeError, lambda: schema.exclusiveMaximum)
        # exclusiveMinimum, exclusiveMaximum
        integration_time.inclusive_bounds = (False, False)
        integration_time.step = None
        schema = integration_time.to_affordance(owner_inst=self.thing)
        self.assertEqual(schema.exclusiveMinimum, integration_time.bounds[0])
        self.assertEqual(schema.exclusiveMaximum, integration_time.bounds[1])
        self.assertRaises(AttributeError, lambda: schema.minimum)
        self.assertRaises(AttributeError, lambda: schema.maximum)
        self.assertRaises(AttributeError, lambda: schema.multipleOf)
        # req. 3. oneOf for allow_None to be True
        integration_time.allow_None = True
        schema = integration_time.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == "null" for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == "number" for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # when oneOf was used, make sure the entire dataschema is found within the number subtype
        number_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "number")
        self.assertEqual(number_schema["exclusiveMinimum"], integration_time.bounds[0])
        self.assertEqual(number_schema["exclusiveMaximum"], integration_time.bounds[1])
        self.assertRaises(KeyError, lambda: number_schema["minimum"])
        self.assertRaises(KeyError, lambda: number_schema["maximum"])
        self.assertRaises(KeyError, lambda: number_schema["multipleOf"])
        # print(schema.json())
        # Test some standard data schema values
        self.assertEqual(schema.default, integration_time.default)
        self.assertEqual(schema.unit, integration_time.metadata["unit"])

    def test_3_string_schema(self):
        # test implicit generation before actual testing
        schema = OceanOpticsSpectrometer.status.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)

        status = String(
            regex=r"^[a-zA-Z0-9]{1,10}$",
            default="IDLE",
            doc="status of the spectrometer",
        )
        status.__set_name__(OceanOpticsSpectrometer, "status")
        # req. 1. Schema can be created from the string property
        schema = status.to_affordance(owner_inst=self.thing)
        # print(schema.json())
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "string")
        # req. 2. Test string schema specific attributes
        self.assertEqual(schema.pattern, status.regex)
        # req. 3. oneOf for allow_None to be True
        status.allow_None = True
        schema = status.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == "null" for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == "string" for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # when oneOf was used, make sure the entire dataschema is found within the string subtype
        string_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "string")
        self.assertEqual(string_schema["pattern"], status.regex)
        # print(schema.json())
        # Test some standard data schema values
        self.assertEqual(schema.default, status.default)

    def test_4_boolean_schema(self):
        # req. 1. Schema can be created from the boolean property and is a boolean schema based property affordance
        schema = OceanOpticsSpectrometer.nonlinearity_correction.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)

        nonlinearity_correction = Boolean(default=True, doc="nonlinearity correction enabled")
        nonlinearity_correction.__set_name__(OceanOpticsSpectrometer, "nonlinearity_correction")
        schema = nonlinearity_correction.to_affordance(owner_inst=self.thing)
        # print(schema.json())
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "boolean")
        # req. 2. Test boolean schema specific attributes
        # None exists for boolean schema
        # req. 3. oneOf for allow_None to be True
        nonlinearity_correction.allow_None = True
        schema = nonlinearity_correction.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == "null" for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == "boolean" for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # print(schema.json())
        # Test some standard data schema values
        self.assertEqual(schema.default, nonlinearity_correction.default)

    def test_5_array_schema(self):
        schema = OceanOpticsSpectrometer.wavelengths.to_affordance(owner_inst=self.thing)
        assert isinstance(schema, PropertyAffordance)

        wavelengths = List(
            default=[],
            item_type=(float, int),
            readonly=True,
            allow_None=False,
            doc="wavelength bins of measurement",
        )
        wavelengths.__set_name__(OceanOpticsSpectrometer, "wavelengths")
        schema = wavelengths.to_affordance(owner_inst=self.thing)
        # req. 1. Schema can be created from the array property and is a array schema based property affordance
        self.assertIsInstance(schema, BaseModel)
        self.assertIsInstance(schema, DataSchema)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "array")
        # req. 2. Test array schema specific attributes
        for types in schema.items["oneOf"]:
            self.assertTrue(types["type"] == "number" or types["type"] == "integer")
        # req. 3. Test some standard data schema values
        if OceanOpticsSpectrometer.wavelengths.default is not None:
            self.assertEqual(schema.default, OceanOpticsSpectrometer.wavelengths.default)
        # req. 4. oneOf for allow_None to be True
        OceanOpticsSpectrometer.wavelengths.allow_None = True
        schema = OceanOpticsSpectrometer.wavelengths.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == "null" for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == "array" for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # when oneOf was used, make sure the entire dataschema is found within the array subtype
        array_schema = next(subtype for subtype in schema.oneOf if subtype["type"] == "array")
        for types in array_schema["items"]["oneOf"]:  # we know that there are two item types in this array
            self.assertTrue(types["type"] == "number" or types["type"] == "integer")
        # req. 5 check for length constraints
        for bounds in [(5, 1000), (None, 100), (50, None), (51, 101)]:
            wavelengths.bounds = bounds
            wavelengths.allow_None = False
            schema = wavelengths.to_affordance(owner_inst=self.thing)
            if bounds[0] is not None:
                self.assertEqual(schema.minItems, bounds[0])
            else:
                self.assertTrue(not hasattr(schema, "minItems") or schema.minItems is None)
            if bounds[1] is not None:
                self.assertEqual(schema.maxItems, bounds[1])
            else:
                self.assertTrue(not hasattr(schema, "maxItems") or schema.maxItems is None)
            # check if min & max items within allow_None and oneOf
            wavelengths.bounds = bounds
            wavelengths.allow_None = True
            schema = wavelengths.to_affordance(owner_inst=self.thing)
            subtype = next(subtype for subtype in schema.oneOf if subtype["type"] == "array")
            if bounds[0] is not None:
                self.assertEqual(subtype["minItems"], bounds[0])
            else:
                self.assertRaises(KeyError, lambda: subtype["minItems"])
            if bounds[1] is not None:
                self.assertEqual(subtype["maxItems"], bounds[1])
            else:
                self.assertRaises(KeyError, lambda: subtype["maxItems"])

    def test_6_enum_schema(self):
        schema = OceanOpticsSpectrometer.trigger_mode.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)

        trigger_mode = Selector(
            objects=[0, 1, 2, 3, 4],
            default=0,
            observable=True,
            doc="""0 = normal/free running, 1 = Software trigger, 2 = Ext. Trigger Level,
                        3 = Ext. Trigger Synchro/ Shutter mode, 4 = Ext. Trigger Edge""",
        )
        trigger_mode.__set_name__(OceanOpticsSpectrometer, "trigger_mode")
        schema = trigger_mode.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "integer")
        self.assertEqual(schema.default, 0)
        # check if enum is equal to objects
        self.assertEqual(schema.enum, trigger_mode.objects)

        # check if allow_None is handled
        trigger_mode.allow_None = True
        trigger_mode.default = 3
        trigger_mode.objects = [0, 1, 2, 3, 4, "0", "1", "2", "3", "4"]
        schema = trigger_mode.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        self.assertEqual(schema.default, 3)
        enum_subschema = next(
            subtype
            for subtype in schema.oneOf
            if (subtype.get("type", None) != "null" or len(subtype.get("oneOf", [])) > 1)
        )
        self.assertIsInstance(enum_subschema, dict)
        self.assertEqual(enum_subschema["enum"], trigger_mode.objects)

    def test_7_class_selector_custom_schema(self):
        last_intensity = ClassSelector(
            default=Intensity([], []),
            allow_None=False,
            class_=Intensity,
            doc="last measurement intensity (in arbitrary units)",
        )
        last_intensity.__set_name__(OceanOpticsSpectrometer, "last_intensity")
        schema = last_intensity.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        # Intensity contains an object schema
        self.assertEqual(schema.type, "object")
        self.assertEqual(schema.properties, Intensity.schema["properties"])

        last_intensity.allow_None = True
        schema = last_intensity.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
        self.assertIsInstance(subschema, dict)
        self.assertTrue(subschema["type"], "object")
        self.assertEqual(subschema["properties"], Intensity.schema["properties"])

    def test_8_json_schema_properties(self):
        # req. 1. test if all values of a model are found in the property affordance schema
        json_schema_prop = TestThing.json_schema_prop  # type: Property
        json_schema_prop.allow_None = False
        schema = json_schema_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        for key in json_schema_prop.model:
            self.assertEqual(getattr(schema, key, NotImplemented), json_schema_prop.model[key])

        # req. 2. test the schema even if allow None is True
        json_schema_prop.allow_None = True
        schema = json_schema_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        subschema = next(
            subtype
            for subtype in schema.oneOf
            if (subtype.get("type", None) != "null" or len(subtype.get("oneOf", [])) > 1)
        )
        self.assertIsInstance(subschema, dict)
        for key in json_schema_prop.model:
            self.assertEqual(subschema.get(key, NotImplemented), json_schema_prop.model[key])

    def test_9_pydantic_properties(self):
        # req. 1. test if all values of a model are found in the property affordance schema for a BaseModel
        pydantic_prop = TestThing.pydantic_prop  # type: Property
        pydantic_prop.allow_None = False
        schema = pydantic_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        # TODO, this is an inherently harder test case
        if issubklass(pydantic_prop.model, BaseModel):
            self.assertEqual(schema.type, "object")
            for field in pydantic_prop.model.model_fields:
                self.assertIn(field, schema.properties)

        # req. 2 test if all values of a model are found in the property affordance for a BaseModel when allow_None = True
        pydantic_prop.allow_None = True
        schema = pydantic_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "object")
        self.assertIsInstance(subschema, dict)
        for key in pydantic_prop.model.model_fields:
            self.assertIn(key, subschema.get("properties", {}))

        # req. 3. test if base python types can be used in pydantic property
        pydantic_simple_prop = TestThing.pydantic_simple_prop  # type: Property # its an integer
        pydantic_simple_prop.allow_None = False
        schema = pydantic_simple_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, "integer")

        pydantic_simple_prop.allow_None = True
        schema = pydantic_simple_prop.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "integer")
        self.assertEqual(subschema["type"], "integer")
        subschema = next(subtype for subtype in schema.oneOf if subtype.get("type", None) == "null")
        self.assertEqual(subschema["type"], "null")


class TestThingDescription(TestCase):
    def test_1_thing_model_generation(self):
        thing = TestThing(id="test-thing-model", log_level=logging.ERROR + 10)
        self.assertIsInstance(thing.get_thing_model(skip_names=["base_property"]).json(), dict)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestInteractionAffordance))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestDataSchema))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestThingDescription))
    return suite


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
