import unittest
import logging
import warnings

from hololinked.core import Thing, ThingMeta, Action, Event, Property
from hololinked.core.meta import PropertyRegistry, ActionsRegistry, EventsRegistry
from hololinked.core.state_machine import StateMachine
from hololinked.utils import get_default_logger 
from hololinked.core.logger import RemoteAccessHandler
from hololinked.client import ObjectProxy
try:
    from .things import OceanOpticsSpectrometer, start_thing_forked
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer, start_thing_forked
    from utils import TestCase, TestRunner




class TestThing(TestCase):
    """Test Thing class from hololinked.core.thing module."""
    
    @classmethod
    def setUpClass(self):
        super().setUpClass()
        print(f"test Thing __init__ with {self.__name__}")
        self.thing_cls = Thing


    def test_1_id(self):
        """Test id property of Thing class"""
        # instance name must be a string and cannot be changed after set
        thing = self.thing_cls(id="test_id", log_level=logging.WARN)
        self.assertEqual(thing.id, "test_id")
        with self.assertRaises(ValueError):
            thing.id = "new_instance"
        with self.assertRaises(NotImplementedError):
            del thing.id
        # regex is r'[A-Za-z]+[A-Za-z_0-9\-\/]*'
        valid_ids = ["test_id", "A123", "valid_id-123", "another/valid-id"]
        invalid_ids = ["123_invalid", "invalid id", "invalid@id", ""]
        for valid_id in valid_ids:
            thing.properties["id"].validate_and_adapt(valid_id)
        for invalid_id in invalid_ids:
            with self.assertRaises(ValueError):
                thing.properties["id"].validate_and_adapt(invalid_id)


    def test_2_logger(self):
        """Test logger of Thing class"""
        # logger must have remote access handler if remote_accessible_logger is True
        logger = get_default_logger("test_logger", log_level=logging.WARN)
        thing = self.thing_cls(id="test_remote_accessible_logger", logger=logger, remote_accessible_logger=True)
        self.assertEqual(thing.logger, logger)
        self.assertTrue(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))

        # Therefore also check the false condition
        logger = get_default_logger("test_logger_2", log_level=logging.WARN)
        thing = self.thing_cls(id="test_logger_without_remote_access", logger=logger, remote_accessible_logger=False)
        self.assertFalse(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        # NOTE - logger is modifiable after instantiation 
       
        
    def test_3_state(self):
        """Test state and state_machine of Thing class"""
        # state property must be None when no state machine is present
        thing1 = self.thing_cls(id="test_no_state_machine", log_level=logging.WARN)
        self.assertIsNone(thing1.state)
        self.assertIsNone(thing1.state_machine)
        # class level property state machine checked in the following test class 
        # detailed checks in another file
        

    def test_4_subthings(self):
        """Test composition"""
        thing = self.thing_cls(
                            id="test_subthings", log_level=logging.WARN, 
                            remote_accessible_logger=True
                        )
        # subthings must be a dictionary
        self.assertIsInstance(thing.sub_things, dict)
        self.assertEqual(len(thing.sub_things), 1)

        thing.another_thing = OceanOpticsSpectrometer(id="another_thing", log_level=logging.WARN)
        self.assertIsInstance(thing.sub_things, dict)
        self.assertEqual(len(thing.sub_things), 2)


    def test_7_servers_init(self):
        # rpc_server and event_publisher must be None when not run()
        thing = self.thing_cls(id="test_servers_init", log_level=logging.WARN)
        self.assertIsNone(thing.rpc_server)
        self.assertIsNone(thing.event_publisher)

    
    def _test_8_resource_generation(self):
        pass
        # basic test only to make sure nothing is fundamentally wrong
        # thing = self.thing_cls(id="test_servers_init", log_level=logging.WARN)
        # self.assertIsInstance(thing.get_thing_description(), dict)
        # self.assertIsInstance(thing.get_our_temp_thing_description(), dict)
     
        # start_thing_forked(self.thing_cls, id='test-gui-resource-generation', log_level=logging.WARN)
        # thing_client = ObjectProxy('test-gui-resource-generation')
        # self.assertIsInstance(thing_client.get_our_temp_thing_description(), dict)
        # thing_client.exit()



class TestOceanOpticsSpectrometer(TestThing):


    @classmethod
    def setUpClass(self):
        super().setUpClass()
        print(f"test Thing init with {self.__name__}")
        self.thing_cls = OceanOpticsSpectrometer


    def test_3_state(self):
        return
        thing1 = self.thing_cls(id="test_state_machine", log_level=logging.WARN)
        self.assertIsNotNone(thing1.state)
        self.assertIsInstance(thing1.state_machine, StateMachine)

        thing2 = self.thing_cls(id="test_state_machine_2", log_level=logging.WARN)
        self.assertIsNotNone(thing2.state)
        self.assertIsInstance(thing2.state_machine, StateMachine)

        self.assertEqual(thing1.state_machine, thing2.state_machine)
        self.assertEqual(thing1.state, thing2.state) # returns initial state
        
        thing1.state_machine.set_state(thing1.states.ALARM)
        self.assertNotEqual(thing1.state, thing2.state) # returns initial state
        self.assertEqual(thing1.state_machine, thing2.state_machine)



class TestMetaclass(TestCase):

    def test_1_metaclass(self):
        # metaclass must be ThingMeta
        self.assertEqual(Thing.__class__, ThingMeta)

    def test_2_registry_creation(self):
        """test registry creation and access"""
        # registry attributes must be instances of their respective classes
        self.assertIsInstance(Thing.properties, PropertyRegistry)
        self.assertIsInstance(Thing.actions, ActionsRegistry)
        self.assertIsInstance(Thing.events, EventsRegistry)

        # new registries are not created on the fly and are same between accesses 
        self.assertEqual(Thing.properties, Thing.properties)
        self.assertEqual(Thing.actions, Thing.actions)
        self.assertEqual(Thing.events, Thing.events)

        # different subclasses have different registries
        self.assertNotEqual(Thing.properties, OceanOpticsSpectrometer.properties)
        self.assertNotEqual(Thing.actions, OceanOpticsSpectrometer.actions)
        self.assertNotEqual(Thing.events, OceanOpticsSpectrometer.events)

        thing = Thing(id="test_registry_creation", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_registry_creation", log_level=logging.WARN)

        # registry attributes must be instances of their respective classes also for instances
        self.assertIsInstance(thing.properties, PropertyRegistry)
        self.assertIsInstance(thing.actions, ActionsRegistry)
        self.assertIsInstance(thing.events, EventsRegistry)

        # registries are not created on the fly and are same between accesses also for instances
        self.assertEqual(thing.properties, thing.properties)
        self.assertEqual(thing.actions, thing.actions)
        self.assertEqual(thing.events, thing.events)

        # registries are not shared between instances
        self.assertNotEqual(thing.properties, spectrometer.properties)
        self.assertNotEqual(thing.actions, spectrometer.actions)
        self.assertNotEqual(thing.events, spectrometer.events)

        # registries are not shared between instances and classes
        self.assertNotEqual(thing.properties, Thing.properties)
        self.assertNotEqual(thing.actions, Thing.actions)
        self.assertNotEqual(thing.events, Thing.events)
        self.assertNotEqual(spectrometer.properties, OceanOpticsSpectrometer.properties)
        self.assertNotEqual(spectrometer.actions, OceanOpticsSpectrometer.actions)
        self.assertNotEqual(spectrometer.events, OceanOpticsSpectrometer.events)



class TestActionRegistry(TestCase):


    def test_1_owner(self):
        # owner attribute must be the class itself
        self.assertEqual(Thing.actions.owner, Thing)
        self.assertEqual(OceanOpticsSpectrometer.actions.owner, OceanOpticsSpectrometer)
        self.assertIsNone(Thing.actions.owner_inst)
        self.assertIsNone(OceanOpticsSpectrometer.actions.owner_inst)

        # owner attribute must be the instance for instance registries
        thing = Thing(id="test_action_registry_owner", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_action_registry_owner", log_level=logging.WARN)
        self.assertEqual(thing.actions.owner, thing)
        self.assertEqual(spectrometer.actions.owner, spectrometer)
        self.assertEqual(thing.actions.owner_cls, Thing)
        self.assertEqual(spectrometer.actions.owner_cls, OceanOpticsSpectrometer)

        self.assertEqual(Thing.actions.descriptor_object, Action)
        self.assertEqual(OceanOpticsSpectrometer.actions.descriptor_object, Action)
        self.assertEqual(thing.actions.descriptor_object, Action)
        self.assertEqual(thing.actions.descriptor_object, Thing.actions.descriptor_object)
    

    def test_2_descriptors(self):
        thing = Thing(id="test_action_registry_owner", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_action_registry_owner", log_level=logging.WARN)

        for name, value in Thing.actions.descriptors.items():
            self.assertIsInstance(value, Action)
            self.assertIsInstance(name, str)
        for name, value in OceanOpticsSpectrometer.actions.descriptors.items():
            self.assertIsInstance(value, Action)
            self.assertIsInstance(name, str)
        for name, value in thing.actions.descriptors.items():
            self.assertIsInstance(value, Action)
            self.assertIsInstance(name, str)
        for name, value in spectrometer.actions.descriptors.items():
            self.assertIsInstance(value, Action)
            self.assertIsInstance(name, str)
        for (name, value), (name2, value2) in zip(Thing.actions.descriptors.items(), thing.actions.descriptors.items()):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)
        for (name, value), (name2, value2) in zip(OceanOpticsSpectrometer.actions.descriptors.items(), spectrometer.actions.descriptors.items()):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)

        self.assertTrue(hasattr(thing.actions, f'_{thing.actions._qualified_prefix}_{ActionsRegistry.__name__.lower()}'))
        thing.actions.clear()
        self.assertTrue(not hasattr(thing.actions, f'_{thing.actions._qualified_prefix}_{ActionsRegistry.__name__.lower()}'))
        thing.actions.clear()
        thing.actions.clear()
        self.assertTrue(not hasattr(thing.actions, f'_{thing.actions._qualified_prefix}_{ActionsRegistry.__name__.lower()}'))


    def test_3_dunders(self):
    
        # __getitem__ must return the descriptor object
        for name, value in Thing.actions.descriptors.items():
            self.assertEqual(Thing.actions[name], value)
            # __contains__ must return True if the descriptor is present
            self.assertIn(value, Thing.actions)
            self.assertIn(name, Thing.actions.descriptors.keys())
    
    

class TestEventRegistry(TestCase):

    def test_1_owner(self):
        # owner attribute must be the class itself
        self.assertEqual(Thing.events.owner, Thing)
        self.assertEqual(OceanOpticsSpectrometer.events.owner, OceanOpticsSpectrometer)
        self.assertIsNone(Thing.events.owner_inst)
        self.assertIsNone(OceanOpticsSpectrometer.events.owner_inst)

        # owner attribute must be the instance's class
        thing = Thing(id="test_event_registry_owner", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_event_registry_owner", log_level=logging.WARN)
        self.assertEqual(thing.events.owner, thing)
        self.assertEqual(spectrometer.events.owner, spectrometer)
        self.assertEqual(thing.events.owner_cls, Thing)
        self.assertEqual(spectrometer.events.owner_cls, OceanOpticsSpectrometer)

    def test_2_descriptors(self):

        thing = Thing(id="test_event_registry_owner", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_event_registry_owner", log_level=logging.WARN)

        for name, value in Thing.events.descriptors.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)
        for name, value in OceanOpticsSpectrometer.events.descriptors.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)
        for name, value in thing.events.descriptors.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)
        for name, value in spectrometer.events.descriptors.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)
        for (name, value), (name2, value2) in zip(Thing.events.descriptors.items(), thing.events.descriptors.items()):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)
        for (name, value), (name2, value2) in zip(OceanOpticsSpectrometer.events.descriptors.items(), spectrometer.events.descriptors.items()):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)
        for name, value in thing.events.observables.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
        for name, value in thing.events.change_events.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)

        self.assertTrue(hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}'))
        self.assertTrue(hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events'))
        self.assertTrue(hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables'))
        thing.events.clear()
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}'))
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events'))
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables'))
        thing.events.clear()
        thing.events.clear()
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}'))
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events'))
        self.assertTrue(not hasattr(thing.events, f'_{thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables'))

    def test_3_dunders(self):
    
        # __getitem__ must return the descriptor object
        for name, value in Thing.events.descriptors.items():
            self.assertEqual(Thing.events[name], value)
            # __contains__ must return True if the descriptor is present
            self.assertIn(value, Thing.events)
            self.assertIn(name, Thing.events.descriptors.keys())
       


if __name__ == '__main__':
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestThing))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestOceanOpticsSpectrometer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestMetaclass))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestActionRegistry))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestEventRegistry))
    runner = TestRunner()
    runner.run(suite)
   
