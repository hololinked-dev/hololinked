import logging, unittest, time, os
import tempfile
import pydantic_core
from pydantic import BaseModel
from hololinked.client import ObjectProxy
from hololinked.core import action, Thing, Property
from hololinked.core.properties import Number, String, Selector, List, Integer
from hololinked.core.database import BaseDB
try:
    from .utils import TestCase, TestRunner
    from .things import start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    from things import start_thing_forked




class TestThing(Thing):

    number_prop = Number(doc="A fully editable number property")
    string_prop = String(default='hello', regex='^[a-z]+',
                        doc="A string property with a regex constraint to check value errors")
    int_prop = Integer(default=5, step=2, bounds=(0, 100),
                        doc="An integer property with step and bounds constraints to check RW")
    selector_prop = Selector(objects=['a', 'b', 'c', 1], default='a',
                        doc="A selector property to check RW")
    observable_list_prop = List(default=None, allow_None=True, observable=True,
                        doc="An observable list property to check observable events on write operations")
    observable_readonly_prop = Number(default=0, readonly=True, observable=True,
                        doc="An observable readonly property to check observable events on read operations")
    db_commit_number_prop = Number(default=0, db_commit=True,
                        doc="A fully editable number property to check commits to db on write operations")
    db_init_int_prop = Integer(default=1, db_init=True,
                        doc="An integer property to check initialization from db")
    db_persist_selector_prop = Selector(objects=['a', 'b', 'c', 1], default='a', db_persist=True,
                        doc="A selector property to check persistence to db on write operations")
    non_remote_number_prop = Number(default=5, remote=False,
                        doc="A non remote number property to check non-availability on client")
    

    class PydanticProp(BaseModel):
        foo : str
        bar : int
        foo_bar : float


    pydantic_prop = Property(default=None, allow_None=True, model=PydanticProp, 
                        doc="A property with a pydantic model to check RW")

    pydantic_simple_prop = Property(default=None, allow_None=True, model='int', 
                        doc="A property with a simple pydantic model to check RW")

    schema = {
        "type" : "string",
        "minLength" : 1,
        "maxLength" : 10,
        "pattern" : "^[a-z]+$"
    }

    json_schema_prop = Property(default=None, allow_None=True, model=schema, 
                        doc="A property with a json schema to check RW")


    @observable_readonly_prop.getter
    def get_observable_readonly_prop(self):
        if not hasattr(self, '_observable_readonly_prop'):
            self._observable_readonly_prop = 0
        self._observable_readonly_prop += 1
        return self._observable_readonly_prop


    @action()
    def print_props(self):
        print(f'number_prop: {self.number_prop}')
        print(f'string_prop: {self.string_prop}')
        print(f'int_prop: {self.int_prop}')
        print(f'selector_prop: {self.selector_prop}')
        print(f'observable_list_prop: {self.observable_list_prop}')
        print(f'observable_readonly_prop: {self.observable_readonly_prop}')
        print(f'db_commit_number_prop: {self.db_commit_number_prop}')
        print(f'db_init_int_prop: {self.db_init_int_prop}')
        print(f'db_persist_selctor_prop: {self.db_persist_selector_prop}')
        print(f'non_remote_number_prop: {self.non_remote_number_prop}')



class TestClassPropertyThing(Thing):
    # Simple class property with default value
    simple_class_prop = Number(class_member=True, default=42)
    
    # Class property with custom getter/setter
    managed_class_prop = Number(class_member=True)
    
    @managed_class_prop.getter
    def get_managed_class_prop(cls):
        return getattr(cls, '_managed_value', 0)
    
    @managed_class_prop.setter
    def set_managed_class_prop(cls, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        cls._managed_value = value
        
    # Read-only class property
    readonly_class_prop = String(class_member=True, readonly=True)
    
    @readonly_class_prop.getter
    def get_readonly_class_prop(cls):
        return "read-only-value"
    
    # Deletable class property
    deletable_class_prop = Number(class_member=True, default=100)
    
    @deletable_class_prop.getter
    def get_deletable_class_prop(cls):
        return getattr(cls, '_deletable_value', 100)
    
    @deletable_class_prop.setter
    def set_deletable_class_prop(cls, value):
        cls._deletable_value = value
        
    @deletable_class_prop.deleter
    def del_deletable_class_prop(cls):
        if hasattr(cls, '_deletable_value'):
            del cls._deletable_value

    not_a_class_prop = Number(class_member=False, default=43)

    @not_a_class_prop.getter
    def get_not_a_class_prop(self):
        return getattr(self, '_not_a_class_value', 43)
    
    @not_a_class_prop.setter
    def set_not_a_class_prop(self, value):
        self._not_a_class_value = value

    @not_a_class_prop.deleter
    def del_not_a_class_prop(self):
        if hasattr(self, '_not_a_class_value'):
            del self._not_a_class_value


class TestClassProperty(TestCase):
    
    def test_1_simple_class_property(self):
        """Test basic class property functionality"""
        # Test class-level access
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 42)
        TestClassPropertyThing.simple_class_prop = 100
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 100)
        
        # Test that instance-level access reflects class value
        instance1 = TestClassPropertyThing(id='test1', log_level=logging.WARN)
        instance2 = TestClassPropertyThing(id='test2', log_level=logging.WARN)
        self.assertEqual(instance1.simple_class_prop, 100)
        self.assertEqual(instance2.simple_class_prop, 100)
        
        # Test that instance-level changes affect class value
        instance1.simple_class_prop = 200
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 200)
        self.assertEqual(instance2.simple_class_prop, 200)

    def test_2_managed_class_property(self):
        """Test class property with custom getter/setter"""
        # Test initial value
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 0)
        
        # Test valid value assignment
        TestClassPropertyThing.managed_class_prop= 50
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 50)
        
        # Test validation in setter
        with self.assertRaises(ValueError):
            TestClassPropertyThing.managed_class_prop = -10
            
        # Verify value wasn't changed after failed assignment
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 50)
        
        # Test instance-level validation
        instance = TestClassPropertyThing(id='test3', log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.managed_class_prop = -20
        
        # Test that instance-level access reflects class value
        self.assertEqual(instance.managed_class_prop, 50)

        # Test that instance-level changes affects class value
        instance.managed_class_prop = 100
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 100)
        self.assertEqual(instance.managed_class_prop, 100)

    def test_3_readonly_class_property(self):
        """Test read-only class property behavior"""
        # Test reading the value
        self.assertEqual(TestClassPropertyThing.readonly_class_prop, "read-only-value")
        
        # Test that setting raises an error at class level
        with self.assertRaises(ValueError):
            TestClassPropertyThing.readonly_class_prop = "new-value"
            
        # Test that setting raises an error at instance level
        instance = TestClassPropertyThing(id='test4', log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.readonly_class_prop = "new-value"
            
        # Verify value remains unchanged
        self.assertEqual(TestClassPropertyThing.readonly_class_prop, "read-only-value")
        self.assertEqual(instance.readonly_class_prop, "read-only-value")

    def test_4_deletable_class_property(self):
        """Test class property deletion"""
        # Test initial value
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)
        
        # Test setting new value
        TestClassPropertyThing.deletable_class_prop = 150
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 150)
        
        # Test deletion
        instance = TestClassPropertyThing(id='test5', log_level=logging.WARN)
        del TestClassPropertyThing.deletable_class_prop
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)  # Should return to default
        self.assertEqual(instance.deletable_class_prop, 100)
        
        # Test instance-level deletion
        instance.deletable_class_prop = 200
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 200)
        del instance.deletable_class_prop
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)  # Should return to default

    def test_5_descriptor_access(self):
        """Test descriptor access for class properties"""
        # Test direct access through descriptor
        instance = TestClassPropertyThing(id='test6', log_level=logging.WARN)
        self.assertIsInstance(TestClassPropertyThing.not_a_class_prop, Number)
        self.assertEqual(instance.not_a_class_prop, 43)
        instance.not_a_class_prop = 50
        self.assertEqual(instance.not_a_class_prop, 50)

        del instance.not_a_class_prop
        # deleter deletes only an internal instance variable
        self.assertTrue(hasattr(TestClassPropertyThing, 'not_a_class_prop')) 
        self.assertEqual(instance.not_a_class_prop, 43)

        del TestClassPropertyThing.not_a_class_prop
        # descriptor itself is deleted
        self.assertFalse(hasattr(TestClassPropertyThing, 'not_a_class_prop'))
        self.assertFalse(hasattr(instance, 'not_a_class_prop'))
        with self.assertRaises(AttributeError):
            instance.not_a_class_prop
        


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
  