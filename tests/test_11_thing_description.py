import logging
import unittest
from pydantic import BaseModel
from hololinked.constants import ResourceTypes
from hololinked.td.data_schema import (DataSchema, NumberSchema, StringSchema, BooleanSchema, ObjectSchema, 
                                ArraySchema, EnumSchema)
from hololinked.td.interaction_affordance import (PropertyAffordance, InteractionAffordance,
                                                ActionAffordance, EventAffordance)
from hololinked.core.properties import Property, Number, String, Boolean

try:
    from .things import OceanOpticsSpectrometer
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer
    from utils import TestCase, TestRunner



class TestInteractionAffordance(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing = OceanOpticsSpectrometer(id='test-thing', log_level=logging.ERROR)
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
        self.assertRaises(AttributeError, lambda: affordance.owner)
        self.assertRaises(AttributeError, lambda: affordance.objekt)
        self.assertRaises(AttributeError, lambda: affordance.name)
        self.assertRaises(AttributeError, lambda: affordance.thing_id)
        self.assertRaises(AttributeError, lambda: affordance.thing_cls)

        # req. 8. Only the corresponding object can be set for each affordance type
        affordance = ActionAffordance()
        with self.assertRaises(ValueError) as ex: 
            affordance.objekt = OceanOpticsSpectrometer.integration_time
        with self.assertRaises(TypeError) as ex: 
            affordance.objekt = 5
        self.assertIn("objekt must be instance of Property, Action or Event, given type", str(ex.exception))
        affordance.objekt = OceanOpticsSpectrometer.connect
        self.assertTrue(affordance.what, ResourceTypes.ACTION)

        affordance = EventAffordance()
        with self.assertRaises(ValueError) as ex:
            affordance.objekt = OceanOpticsSpectrometer.integration_time
        with self.assertRaises(TypeError) as ex:
            affordance.objekt = 5
        self.assertIn("objekt must be instance of Property, Action or Event, given type", str(ex.exception))
        affordance.objekt = OceanOpticsSpectrometer.intensity_measurement_event
        self.assertTrue(affordance.what, ResourceTypes.EVENT)

        affordance = PropertyAffordance()
        with self.assertRaises(ValueError) as ex:
            affordance.objekt = OceanOpticsSpectrometer.connect
        with self.assertRaises(TypeError) as ex:
            affordance.objekt = 5
        self.assertIn("objekt must be instance of Property, Action or Event, given type", str(ex.exception))
        affordance.objekt = OceanOpticsSpectrometer.integration_time


       
class TestDataSchema(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing = OceanOpticsSpectrometer(id='test-thing', log_level=logging.ERROR)
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
        self.assertEqual(schema.type, 'number') 
        
        integration_time = Number(bounds=(1, 1000), default=100, crop_to_bounds=True, step=1,
                                doc="integration time in milliseconds", metadata=dict(unit="ms"))
        integration_time.__set_name__(OceanOpticsSpectrometer, 'integration_time')
        # req. 1. Schema can be created 
        schema = integration_time.to_affordance(owner_inst=self.thing)
        # print(schema.json(indent=4))
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, 'number') 
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
        self.assertTrue(any(subtype["type"] == 'null' for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == 'number' for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # print(schema.json(indent=4))    
        # Test some standard data schema values
        self.assertEqual(schema.default, integration_time.default)
        self.assertEqual(schema.unit, integration_time.metadata['unit'])


    def test_3_string_schema(self):

        # test implicit generation before actual testing
        schema = OceanOpticsSpectrometer.status.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)
        
        status = String(regex=r'^[a-zA-Z0-9]{1,10}$', default='IDLE', doc="status of the spectrometer")
        status.__set_name__(OceanOpticsSpectrometer, 'status')
        # req. 1. Schema can be created from the string property
        schema = status.to_affordance(owner_inst=self.thing) 
        # print(schema.json(indent=4))
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, 'string')
        # req. 2. Test string schema specific attributes
        self.assertEqual(schema.pattern, status.regex)
        # req. 3. oneOf for allow_None to be True
        status.allow_None = True
        schema = status.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == 'null' for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == 'string' for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # print(schema.json(indent=4))
        # Test some standard data schema values
        self.assertEqual(schema.default, status.default)


    def test_4_boolean_schema(self):
        
        # req. 1. Schema can be created from the boolean property and is a boolean schema based property affordance
        schema = OceanOpticsSpectrometer.nonlinearity_correction.to_affordance(owner_inst=self.thing)
        self.assertIsInstance(schema, PropertyAffordance)

        nonlinearity_correction = Boolean(default=True, doc="nonlinearity correction enabled")
        nonlinearity_correction.__set_name__(OceanOpticsSpectrometer, 'nonlinearity_correction')
        schema = nonlinearity_correction.to_affordance(owner_inst=self.thing)
        # print(schema.json(indent=4))
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, 'boolean')
        # req. 2. Test boolean schema specific attributes
        # None exists for boolean schema
        # req. 3. oneOf for allow_None to be True
        nonlinearity_correction.allow_None = True
        schema = nonlinearity_correction.to_affordance(owner_inst=self.thing)
        self.assertTrue(any(subtype["type"] == 'null' for subtype in schema.oneOf))
        self.assertTrue(any(subtype["type"] == 'boolean' for subtype in schema.oneOf))
        self.assertTrue(len(schema.oneOf), 2)
        self.assertTrue(not hasattr(schema, "type") or schema.type is None)
        # print(schema.json(indent=4))
        # Test some standard data schema values
        self.assertEqual(schema.default, nonlinearity_correction.default)
        
    
    # def test_5_array_schema(self):

    #     # req. 1. Schema can be created from the array property and is a array schema based property affordance
    #     schema = OceanOpticsSpectrometer.wavelengths.to_affordance(owner_inst=self.thing)
    #     self.assertIsInstance(schema, BaseModel)
    #     self.assertIsInstance(schema, DataSchema)
    #     self.assertIsInstance(schema, PropertyAffordance)
    #     # print(schema.json(indent=4))
    #     self.assertEqual(schema.type, 'array')
    #     # req. 2. Test array schema specific attributes
    #     self.assertEqual(schema.items.type, 'number')
    #     # req. 3. Test some standard data schema values
    #     # self.assertEqual(schema.default, OceanOpticsSpectrometer.custom_background_intensity.default)


    # def test_6_enum_schema(self):
    #     pass 



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())