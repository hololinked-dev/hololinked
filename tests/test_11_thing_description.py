import logging
import unittest
from pydantic import BaseModel
from hololinked.td.data_schema import (DataSchema, NumberSchema, StringSchema, BooleanSchema, ObjectSchema, 
                                ArraySchema, EnumSchema)
from hololinked.td.interaction_affordance import PropertyAffordance
from hololinked.core.properties import Property, Number, String, Boolean

try:
    from .things import OceanOpticsSpectrometer
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer
    from utils import TestCase, TestRunner


class TestDataSchema(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing = OceanOpticsSpectrometer(id='test-thing', log_level=logging.ERROR)
        print(f"Test Data Schema with {cls.__name__}")

    def test_1_data_schema(self):
        OceanOpticsSpectrometer.trigger_mode # selector 
        OceanOpticsSpectrometer.integration_time # number
        OceanOpticsSpectrometer.serial_number # string
        OceanOpticsSpectrometer.nonlinearity_correction # boolean
        OceanOpticsSpectrometer.custom_background_intensity # typed list float, int
        OceanOpticsSpectrometer.wavelengths # list float int

    def test_2_number_schema(self):
        
        integration_time = Number(bounds=(1, 1000), default=100, crop_to_bounds=True, 
                                doc="integration time in milliseconds", metadata=dict(unit="ms"))
        integration_time.__set_name__(OceanOpticsSpectrometer, 'integration_time')
        # req. 1. Schema can be created 
        schema = integration_time.to_affordance(owner_inst=self.thing) # type: NumberSchema
        # print(schema.json(indent=4))
        self.assertIsInstance(schema, BaseModel)
        self.assertIsInstance(schema, DataSchema)
        self.assertIsInstance(schema, PropertyAffordance)
        self.assertEqual(schema.type, 'number') 
        # req. 2. Test number schema specific attributes
        self.assertEqual(schema.minimum, integration_time.bounds[0])
        # test some standard data schema values
        self.assertEqual(schema.default, integration_time.default)
       

    # def test_3_string_schema(self):

    #     # req. 1. Schema can be created from the string property and is a string schema based property affordance
    #     schema = OceanOpticsSpectrometer.status.to_affordance(owner_inst=self.thing)
    #     self.assertIsInstance(schema, BaseModel)
    #     self.assertIsInstance(schema, DataSchema)
    #     self.assertIsInstance(schema, PropertyAffordance)
    #     self.assertEqual(schema.type, 'string')
    #     # print(schema.json(indent=4))
    #     # req. 2. Test string schema specific attributes
    #     # self.assertEqual(schema.pattern, OceanOpticsSpectrometer.status)
    #     # req. 3. Test some standard data schema values
    #     self.assertEqual(schema.default, OceanOpticsSpectrometer.status.default)


    # def test_4_boolean_schema(self):
        
    #     # req. 1. Schema can be created from the boolean property and is a boolean schema based property affordance
    #     schema = OceanOpticsSpectrometer.nonlinearity_correction.to_affordance(owner_inst=self.thing)
    #     self.assertIsInstance(schema, BaseModel)
    #     self.assertIsInstance(schema, DataSchema)
    #     self.assertIsInstance(schema, PropertyAffordance)
    #     self.assertEqual(schema.type, 'boolean')
    #     # print(schema.json(indent=4))
    #     # req. 2. Test boolean schema specific attributes
    #     # None exists for boolean schema
    #     # req. 3. Test some standard data schema values
    #     self.assertEqual(schema.default, OceanOpticsSpectrometer.nonlinearity_correction.default)
        
    
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