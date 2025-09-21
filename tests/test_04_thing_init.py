import typing
import unittest
import logging

from hololinked.core.actions import BoundAction
from hololinked.core.events import EventDispatcher
from hololinked.core.zmq.brokers import EventPublisher
from hololinked.core import Thing, ThingMeta, Action, Event, Property
from hololinked.core.meta import (
    DescriptorRegistry,
    PropertiesRegistry,
    ActionsRegistry,
    EventsRegistry,
)
from hololinked.core.zmq.rpc_server import RPCServer, prepare_rpc_server
from hololinked.core.properties import Parameter
from hololinked.core.state_machine import BoundFSM
from hololinked.utils import get_default_logger
from hololinked.core.logger import RemoteAccessHandler

try:
    from .things import OceanOpticsSpectrometer
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer
    from utils import TestCase, TestRunner


"""
The tests in this file are for the initialization of the Thing class and its subclasses.
1. Test Thing class 
2. Test Thing subclass
3. Test ThingMeta metaclass
4. Test ActionRegistry class
5. Test EventRegistry class
6. Test PropertiesRegistry class
"""


class TestThingInit(TestCase):
    """Test Thing class which is the bread and butter of this package."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print(f"test Thing instantiation with {cls.__name__}")
        cls.thing_cls = Thing
        # using a variable called thing_cls because same tests are repeated for different thing class

    """
    Test sequence is as follows:
    1. Test id requirements 
    2. Test logger setup
    3. Test state and state_machine setup
    4. Test composition of subthings
    5. Test servers init
    6. Test thing model generation
    """

    def test_1_id(self):
        """Test id property of Thing class"""
        # req. 1. instance name must be a string and cannot be changed after set
        thing = self.thing_cls(id="test_id", log_level=logging.WARN)
        self.assertEqual(thing.id, "test_id")
        with self.assertRaises(ValueError):
            thing.id = "new_instance"
        with self.assertRaises(NotImplementedError):
            del thing.id
        # req. 2. regex is r'[A-Za-z]+[A-Za-z_0-9\-\/]*', simple URI like
        valid_ids = ["test_id", "A123", "valid_id-123", "another/valid-id"]
        invalid_ids = ["123_invalid", "invalid id", "invalid@id", ""]
        for valid_id in valid_ids:
            thing.properties.descriptors["id"].validate_and_adapt(valid_id)
        for invalid_id in invalid_ids:
            with self.assertRaises(ValueError):
                thing.properties.descriptors["id"].validate_and_adapt(invalid_id)

    def test_2_logger(self):
        """Test logger setup"""
        # req. 1. logger must have remote access handler if remote_accessible_logger is True
        logger = get_default_logger("test_logger", log_level=logging.WARN)
        thing = self.thing_cls(
            id="test_remote_accessible_logger",
            logger=logger,
            remote_accessible_logger=True,
        )
        self.assertEqual(thing.logger, logger)
        self.assertTrue(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        # Therefore also check the false condition
        logger = get_default_logger("test_logger_2", log_level=logging.WARN)
        thing = self.thing_cls(
            id="test_logger_without_remote_access",
            logger=logger,
            remote_accessible_logger=False,
        )
        self.assertFalse(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        # NOTE - logger is modifiable after instantiation

        # req. 2. logger is created automatically if not provided
        thing = self.thing_cls(id="test_logger_auto_creation", log_level=logging.WARN)
        self.assertIsNotNone(thing.logger)
        self.assertFalse(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        self.assertNotEqual(thing.logger, logger)  # not the above logger that we used.
        # remote accessible only when we ask for it
        thing = self.thing_cls(
            id="test_logger_auto_creation_2",
            log_level=logging.WARN,
            remote_accessible_logger=True,
        )
        self.assertIsNotNone(thing.logger)
        self.assertTrue(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        self.assertNotEqual(thing.logger, logger)

    def test_3_state(self):
        """Test state and state_machine setup"""
        # req. 1. state property must be None when no state machine is present
        thing1 = self.thing_cls(id="test_no_state_machine", log_level=logging.WARN)
        self.assertIsNone(thing1.state)
        self.assertIsNone(thing1.state_machine)
        # detailed checks in another file

    def test_4_subthings(self):
        """Test composition"""
        thing = self.thing_cls(id="test_subthings", log_level=logging.WARN, remote_accessible_logger=True)
        # req. 1. subthings must be a dictionary
        self.assertIsInstance(thing.sub_things, dict)
        self.assertEqual(len(thing.sub_things), 1)  # logger
        # req. 2. subthings are always recomputed when accessed (at least thats the way it is right now),
        # so we can add new subthings anytime
        thing.another_thing = OceanOpticsSpectrometer(id="another_thing", log_level=logging.WARN)
        self.assertIsInstance(thing.sub_things, dict)
        self.assertEqual(len(thing.sub_things), 2)
        # req. 3. subthings must be instances of Thing and have the parent as owner
        for name, subthing in thing.sub_things.items():
            self.assertTrue(thing in subthing._owners)
            self.assertIsInstance(subthing, Thing)
            # req. 4. name of subthing must match name of the attribute
            self.assertTrue(hasattr(thing, name))

    def test_5_servers_init(self):
        """Test if servers can be initialized/instantiated"""
        # req. 1. rpc_server and event_publisher must be None when not run()
        thing = self.thing_cls(id="test_servers_init", log_level=logging.ERROR)
        self.assertIsNone(thing.rpc_server)
        self.assertIsNone(thing.event_publisher)
        # req. 2. rpc_server and event_publisher must be instances of their respective classes when run()
        prepare_rpc_server(thing, "IPC")
        self.assertIsInstance(thing.rpc_server, RPCServer)
        self.assertIsInstance(thing.event_publisher, EventPublisher)
        # exit to quit nicely
        thing.rpc_server.exit()
        thing.event_publisher.exit()


class TestOceanOpticsSpectrometer(TestThingInit):
    """test Thing subclass example"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing_cls = OceanOpticsSpectrometer

    # check docs of the parent class for the test sequence

    def test_3_state(self):
        """Test state and state_machine setup"""
        thing1 = self.thing_cls(id="test_state_machine", log_level=logging.WARN)
        # req. 1. state and state machine must be present because we create this subclass with a state machine
        self.assertIsNotNone(thing1.state)
        self.assertIsInstance(thing1.state_machine, BoundFSM)
        # req. 2. state and state machine must be different for different instances
        thing2 = self.thing_cls(id="test_state_machine_2", log_level=logging.WARN)
        # first check if state machine exists
        self.assertIsNotNone(thing2.state)
        self.assertIsInstance(thing2.state_machine, BoundFSM)
        # then check if they are different
        self.assertNotEqual(thing1.state_machine, thing2.state_machine)
        # until state is set, initial state is equal
        self.assertEqual(thing1.state, thing2.state)
        self.assertEqual(thing1.state_machine.initial_state, thing2.state_machine.initial_state)
        # after state is set, they are different
        thing1.state_machine.set_state(thing1.states.ALARM)
        self.assertNotEqual(thing1.state, thing2.state)
        self.assertNotEqual(thing1.state_machine, thing2.state_machine)
        # initial state is still same
        self.assertEqual(thing1.state_machine.initial_state, thing2.state_machine.initial_state)


class TestMetaclass(TestCase):
    """Test ThingMeta metaclass which instantiates a Thing (sub-)class"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print(f"test ThingMeta with {cls.__name__}")

    """
    Test sequence is as follows:
    1. Test metaclass of Thing class
    2. Test registry creation and access which is currently the main purpose of the metaclass
    """

    def test_1_metaclass(self):
        """test metaclass of Thing class"""
        # req. 1 metaclass must be ThingMeta of any Thing class
        self.assertEqual(Thing.__class__, ThingMeta)
        self.assertEqual(OceanOpticsSpectrometer.__class__, ThingMeta)
        self.assertEqual(Thing.__class__, OceanOpticsSpectrometer.__class__)

    def test_2_registry_creation(self):
        """test registry creation and access which is currently the main purpose of the metaclass"""
        # req. 1. registry attributes must be instances of their respective classes
        self.assertIsInstance(Thing.properties, PropertiesRegistry)
        self.assertIsInstance(Thing.actions, ActionsRegistry)
        self.assertIsInstance(Thing.events, EventsRegistry)

        # req. 2. new registries are not created on the fly and are same between accesses
        self.assertEqual(Thing.properties, Thing.properties)
        self.assertEqual(Thing.actions, Thing.actions)
        self.assertEqual(Thing.events, Thing.events)
        # This test is done as the implementation deviates from `param`

        # req. 3. different subclasses have different registries
        self.assertNotEqual(Thing.properties, OceanOpticsSpectrometer.properties)
        self.assertNotEqual(Thing.actions, OceanOpticsSpectrometer.actions)
        self.assertNotEqual(Thing.events, OceanOpticsSpectrometer.events)

        # create instances for further tests
        thing = Thing(id="test_registry_creation", log_level=logging.WARN)
        spectrometer = OceanOpticsSpectrometer(id="test_registry_creation_2", log_level=logging.WARN)

        # req. 4. registry attributes must be instances of their respective classes also for instances
        self.assertIsInstance(thing.properties, PropertiesRegistry)
        self.assertIsInstance(thing.actions, ActionsRegistry)
        self.assertIsInstance(thing.events, EventsRegistry)

        # req. 5. registries are not created on the fly and are same between accesses also for instances
        self.assertEqual(thing.properties, thing.properties)
        self.assertEqual(thing.actions, thing.actions)
        self.assertEqual(thing.events, thing.events)

        # req. 6. registries are not shared between instances
        self.assertNotEqual(thing.properties, spectrometer.properties)
        self.assertNotEqual(thing.actions, spectrometer.actions)
        self.assertNotEqual(thing.events, spectrometer.events)

        # req. 7. registries are not shared between instances and their classes
        self.assertNotEqual(thing.properties, Thing.properties)
        self.assertNotEqual(thing.actions, Thing.actions)
        self.assertNotEqual(thing.events, Thing.events)
        self.assertNotEqual(spectrometer.properties, OceanOpticsSpectrometer.properties)
        self.assertNotEqual(spectrometer.actions, OceanOpticsSpectrometer.actions)
        self.assertNotEqual(spectrometer.events, OceanOpticsSpectrometer.events)


# Uncomment the following for type hints while coding registry tests,
# comment it before testing, otherwise tests will fail due to overriding Thing object
# class Thing(Thing):
#     class_registry: PropertiesRegistry | ActionsRegistry | EventsRegistry
#     instance_registry: PropertiesRegistry  | ActionsRegistry | EventsRegistry  | None
#     descriptor_object: type[Property | Action | Event]

# class OceanOpticsSpectrometer(OceanOpticsSpectrometer):
#     class_registry: PropertiesRegistry | ActionsRegistry | EventsRegistry
#     instance_registry: PropertiesRegistry  | ActionsRegistry | EventsRegistry  | None
#     descriptor_object: type[Property | Action | Event]


class TestRegistry(TestCase):
    # Read the commented section above before proceeding to this test

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.setUpRegistryObjects()
        cls.setUpRegistryAttributes()
        if cls.is_abstract_test_class:
            return
        print(f"test {cls.registry_cls.__name__} with {cls.__name__}")

    @classmethod
    def setUpRegistryObjects(cls):
        cls.registry_cls = None  # type: DescriptorRegistry | None
        cls.registry_object = None  # type: type[Property | Action | Event]

    @property
    def is_abstract_test_class(self):
        # if self.registry_cls is None:
        #     print("registry_cls is None")
        # if self.registry_object is None:
        #     print("registry_object is None")
        return self.registry_cls is None or self.registry_object is None

    @classmethod
    def setUpRegistryAttributes(cls):
        if cls.registry_cls is None or cls.registry_object is None:
            return

        # create instances for further tests
        cls.thing = Thing(id=f"test_{cls.registry_object.__name__}_registry", log_level=logging.WARN)
        cls.spectrometer = OceanOpticsSpectrometer(
            id=f"test_{cls.registry_object.__name__}_registry", log_level=logging.WARN
        )
        if cls.registry_cls == ActionsRegistry:
            Thing.class_registry = Thing.actions
            OceanOpticsSpectrometer.class_registry = OceanOpticsSpectrometer.actions
            cls.thing.instance_registry = cls.thing.actions
            cls.spectrometer.instance_registry = cls.spectrometer.actions
            cls.bound_object = BoundAction
        elif cls.registry_cls == PropertiesRegistry:
            Thing.class_registry = Thing.properties
            OceanOpticsSpectrometer.class_registry = OceanOpticsSpectrometer.properties
            cls.thing.instance_registry = cls.thing.properties
            cls.spectrometer.instance_registry = cls.spectrometer.properties
            cls.bound_object = typing.Any
        elif cls.registry_cls == EventsRegistry:
            Thing.class_registry = Thing.events
            OceanOpticsSpectrometer.class_registry = OceanOpticsSpectrometer.events
            cls.thing.instance_registry = cls.thing.events
            cls.spectrometer.instance_registry = cls.spectrometer.events
            cls.bound_object = EventDispatcher
        else:
            raise NotImplementedError("This registry class is not implemented")

    """
    Test action registry first because actions are the easiest to test.
    1. Test owner attribute
    2. Test descriptors access 
    3. Test dunders
    """

    def test_1_owner(self):
        """Test owner attribute of DescriptorRegistry"""
        if self.is_abstract_test_class:
            return
        # See comment above TestRegistry class to enable type definitions
        # req. 1. owner attribute must be the class itself when accessed as class attribute
        self.assertEqual(Thing.class_registry.owner, Thing)
        self.assertEqual(OceanOpticsSpectrometer.class_registry.owner, OceanOpticsSpectrometer)
        # therefore owner instance must be None
        self.assertIsNone(Thing.class_registry.owner_inst)
        self.assertIsNone(OceanOpticsSpectrometer.class_registry.owner_inst)

        # req. 2. owner attribute must be the instance for instance registries (i.e. when accessed as instance attribute)
        self.assertEqual(self.thing.instance_registry.owner, self.thing)
        self.assertEqual(self.spectrometer.instance_registry.owner, self.spectrometer)
        self.assertEqual(self.thing.instance_registry.owner_cls, Thing)
        self.assertEqual(self.spectrometer.instance_registry.owner_cls, OceanOpticsSpectrometer)

        # req. 3. descriptor_object must be defined correctly and is a class
        self.assertEqual(Thing.class_registry.descriptor_object, self.registry_object)
        self.assertEqual(
            OceanOpticsSpectrometer.class_registry.descriptor_object,
            self.registry_object,
        )
        self.assertEqual(self.thing.instance_registry.descriptor_object, self.registry_object)
        self.assertEqual(
            self.thing.instance_registry.descriptor_object,
            Thing.class_registry.descriptor_object,
        )

    def test_2_descriptors(self):
        """Test descriptors access"""
        if self.is_abstract_test_class:
            return

        # req. 1. descriptors are instances of the descriptor object - Property | Action | Event
        for name, value in Thing.class_registry.descriptors.items():
            self.assertIsInstance(value, self.registry_object)
            self.assertIsInstance(name, str)
        for name, value in OceanOpticsSpectrometer.class_registry.descriptors.items():
            self.assertIsInstance(value, self.registry_object)
            self.assertIsInstance(name, str)
        # subclass have more descriptors than parent class because our example Thing OceanOpticsSpectrometer
        # has defined its own actions, properties and events
        self.assertTrue(len(OceanOpticsSpectrometer.class_registry.descriptors) > len(Thing.class_registry.descriptors))
        # req. 2. either class level or instance level descriptors are same - not a strict requirement for different
        # use cases, one can always add instance level descriptors
        for name, value in self.thing.instance_registry.descriptors.items():
            self.assertIsInstance(value, self.registry_object)
            self.assertIsInstance(name, str)
        for name, value in self.spectrometer.instance_registry.descriptors.items():
            self.assertIsInstance(value, self.registry_object)
            self.assertIsInstance(name, str)
        # req. 3. because class level and instance level descriptors are same, they are equal
        for (name, value), (name2, value2) in zip(
            Thing.class_registry.descriptors.items(),
            self.thing.instance_registry.descriptors.items(),
        ):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)
        for (name, value), (name2, value2) in zip(
            OceanOpticsSpectrometer.class_registry.descriptors.items(),
            self.spectrometer.instance_registry.descriptors.items(),
        ):
            self.assertEqual(name, name2)
            self.assertEqual(value, value2)
        # req. 4. descriptors can be cleared
        self.assertTrue(
            hasattr(
                self.thing.instance_registry,
                f"_{self.thing.instance_registry._qualified_prefix}_{self.registry_cls.__name__.lower()}",
            )
        )
        self.thing.instance_registry.clear()
        self.assertTrue(
            not hasattr(
                self.thing.instance_registry,
                f"_{self.thing.instance_registry._qualified_prefix}_{self.registry_cls.__name__.lower()}",
            )
        )
        # clearing again any number of times should not raise error
        self.thing.instance_registry.clear()
        self.thing.instance_registry.clear()
        self.assertTrue(
            not hasattr(
                self.thing.instance_registry,
                f"_{self.thing.instance_registry._qualified_prefix}_{self.registry_cls.__name__.lower()}",
            )
        )

    def test_3_dunders(self):
        """Test dunders of DescriptorRegistry"""
        if self.is_abstract_test_class:
            return

        # req. 1. __getitem__ must return the descriptor object
        for name, value in Thing.class_registry.descriptors.items():
            self.assertEqual(Thing.class_registry[name], value)
            # req. 2. __contains__ must return True if the descriptor is present
            self.assertIn(value, Thing.class_registry)
            self.assertIn(name, Thing.class_registry.descriptors.keys())

        # req. 2. __iter__ must return an iterator over the descriptors dictionary
        # which in turn iterates over the keys
        self.assertTrue(all(isinstance(descriptor_name, str) for descriptor_name in Thing.class_registry))
        self.assertTrue(
            all(isinstance(descriptor_name, str) for descriptor_name in OceanOpticsSpectrometer.class_registry)
        )
        # __iter__ can also be casted as other iterators like lists
        thing_descriptors = list(self.thing.instance_registry)
        spectrometer_descriptors = list(self.spectrometer.instance_registry)
        self.assertIsInstance(thing_descriptors, list)
        self.assertIsInstance(spectrometer_descriptors, list)
        self.assertTrue(all(isinstance(descriptor_name, str) for descriptor_name in thing_descriptors))
        self.assertTrue(all(isinstance(descriptor_name, str) for descriptor_name in spectrometer_descriptors))

        # req. 3. __len__ must return the number of descriptors
        self.assertTrue(len(Thing.class_registry) == len(Thing.class_registry.descriptors))
        self.assertTrue(
            len(OceanOpticsSpectrometer.class_registry) == len(OceanOpticsSpectrometer.class_registry.descriptors)
        )
        self.assertTrue(len(self.thing.instance_registry) == len(self.thing.instance_registry.descriptors))
        self.assertTrue(
            len(self.spectrometer.instance_registry) == len(self.spectrometer.instance_registry.descriptors)
        )
        self.assertTrue(len(self.thing.instance_registry) == len(Thing.class_registry))
        self.assertTrue(len(self.spectrometer.instance_registry) == len(OceanOpticsSpectrometer.class_registry))

        # req. 4. registries have their unique hashes
        # NOTE - not sure if this is really a useful feature or just plain stupid
        # The requirement was to be able to generate unique hashes for each registry like foodict[<some hash>] = Thing.actions
        foodict = {
            Thing.class_registry: 1,
            OceanOpticsSpectrometer.class_registry: 2,
            self.thing.instance_registry: 3,
            self.spectrometer.instance_registry: 4,
        }
        self.assertEqual(foodict[Thing.class_registry], 1)
        self.assertEqual(foodict[OceanOpticsSpectrometer.class_registry], 2)
        self.assertEqual(foodict[self.thing.instance_registry], 3)
        self.assertEqual(foodict[self.spectrometer.instance_registry], 4)

        # __dir__ not yet tested
        # __str__ will not be tested

    def test_4_bound_objects(self):
        """Test bound objects returned from descriptor access"""
        if self.is_abstract_test_class:
            return
        if self.registry_object not in [Property, Parameter, Action]:
            # Events work a little differently, may need to be tested separately or refactored to same implementation
            return

        # req. 1. number of bound objects must be equal to number of descriptors
        # for example, number of bound actions must be equal to number of actions
        self.assertEqual(
            len(self.thing.instance_registry),
            len(self.thing.instance_registry.descriptors),
        )
        self.assertEqual(
            len(self.spectrometer.instance_registry),
            len(self.spectrometer.instance_registry.descriptors),
        )

        # req. 2. bound objects must be instances of bound instances
        for name, value in self.thing.instance_registry.values.items():
            if self.bound_object != typing.Any:
                self.assertIsInstance(value, self.bound_object)
            self.assertIsInstance(name, str)
        for name, value in self.spectrometer.instance_registry.values.items():
            if self.bound_object != typing.Any:
                self.assertIsInstance(value, self.bound_object)
            self.assertIsInstance(name, str)


class TestActionRegistry(TestRegistry):
    """Test ActionRegistry class"""

    @classmethod
    def setUpRegistryObjects(cls):
        cls.registry_cls = ActionsRegistry
        cls.registry_object = Action


class TestEventRegistry(TestRegistry):
    @classmethod
    def setUpRegistryObjects(cls):
        cls.registry_cls = EventsRegistry
        cls.registry_object = Event

    def test_2_descriptors(self):
        if self.is_abstract_test_class:
            return

        super().test_2_descriptors()

        # req. 5. observables and change events are also descriptors
        for name, value in self.thing.events.observables.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
        for name, value in self.thing.events.change_events.items():
            self.assertIsInstance(value, Event)
            self.assertIsInstance(name, str)
        # req. 4. descriptors can be cleared
        self.assertTrue(
            hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}",
            )
        )
        self.assertTrue(
            hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
            )
        )
        self.assertTrue(
            hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
            )
        )
        self.thing.events.clear()
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}",
            )
        )
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
            )
        )
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
            )
        )
        self.thing.events.clear()
        self.thing.events.clear()
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}",
            )
        )
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
            )
        )
        self.assertTrue(
            not hasattr(
                self.thing.events,
                f"_{self.thing.events._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
            )
        )


class TestPropertiesRegistry(TestRegistry):
    @classmethod
    def setUpRegistryObjects(cls):
        cls.registry_cls = PropertiesRegistry
        cls.registry_object = Parameter

    def test_2_descriptors(self):
        if self.is_abstract_test_class:
            return

        super().test_2_descriptors()

        # req. 5. parameters that are subclass of Property are usually remote objects
        for name, value in self.thing.properties.remote_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
        for name, value in self.spectrometer.properties.remote_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
        # req. 6. db_objects, db_init_objects, db_persisting_objects, db_commit_objects are also descriptors
        for name, value in self.thing.properties.db_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
            self.assertTrue(value.db_init or value.db_persist or value.db_commit)
        for name, value in self.thing.properties.db_init_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
            self.assertTrue(value.db_init or value.db_persist)
            self.assertFalse(value.db_commit)
        for name, value in self.thing.properties.db_commit_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
            self.assertTrue(value.db_commit or value.db_persist)
            self.assertFalse(value.db_init)
        for name, value in self.thing.properties.db_persisting_objects.items():
            self.assertIsInstance(value, Property)
            self.assertIsInstance(name, str)
            self.assertTrue(value.db_persist)
            self.assertFalse(value.db_init)  # in user given cases, this could be true, this is not strict requirement
            self.assertFalse(value.db_commit)  # in user given cases, this could be true, this is not strict requirement

        # req. 4. descriptors can be cleared
        self.assertTrue(
            hasattr(
                self.thing.properties,
                f"_{self.thing.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
            )
        )
        self.thing.properties.clear()
        self.assertTrue(
            not hasattr(
                self.thing.properties,
                f"_{self.thing.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
            )
        )
        self.thing.properties.clear()
        self.thing.properties.clear()
        self.assertTrue(
            not hasattr(
                self.thing.properties,
                f"_{self.thing.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
            )
        )

    def test_5_bulk_read_write(self):
        """Test bulk read and write operations for properties"""

        # req. 1. test read in bulk for readAllProperties
        prop_values = self.spectrometer.properties.get()
        # read value is a dictionary
        self.assertIsInstance(prop_values, dict)
        self.assertTrue(len(prop_values) > 0)
        # all properties are read at instance level and get only reads remote objects
        self.assertTrue(len(prop_values) == len(self.spectrometer.properties.remote_objects))
        # read values are not descriptors themselves
        for name, value in prop_values.items():
            self.assertIsInstance(name, str)
            self.assertNotIsInstance(value, Parameter)  # descriptor has been read

        # req. 2. properties can be read with new names
        prop_values = self.spectrometer.properties.get(
            integration_time="integrationTime",
            state="State",
            trigger_mode="triggerMode",
        )
        self.assertIsInstance(prop_values, dict)
        self.assertTrue(len(prop_values) == 3)
        for name, value in prop_values.items():
            self.assertIsInstance(name, str)
            self.assertTrue(name in ["integrationTime", "triggerMode", "State"])
            self.assertNotIsInstance(value, Parameter)

        # req. 3. read in bulk for readMultipleProperties
        prop_values = self.spectrometer.properties.get(
            names=["integration_time", "trigger_mode", "state", "last_intensity"]
        )
        # read value is a dictionary
        self.assertIsInstance(prop_values, dict)
        self.assertTrue(len(prop_values) == 4)
        # read values are not descriptors themselves
        for name, value in prop_values.items():
            self.assertIsInstance(name, str)
            self.assertTrue(name in ["integration_time", "trigger_mode", "state", "last_intensity"])
            self.assertNotIsInstance(value, Parameter)

        # req. 4. read a property that is not present raises AttributeError
        with self.assertRaises(AttributeError) as ex:
            prop_values = self.spectrometer.properties.get(
                names=[
                    "integration_time",
                    "trigger_mode",
                    "non_existent_property",
                    "last_intensity",
                ]
            )
        self.assertTrue("property non_existent_property does not exist" in str(ex.exception))

        # req. 5. write in bulk
        prop_values = self.spectrometer.properties.get()
        self.spectrometer.properties.set(integration_time=10, trigger_mode=1)
        self.assertNotEqual(prop_values["integration_time"], self.spectrometer.integration_time)
        self.assertNotEqual(prop_values["trigger_mode"], self.spectrometer.trigger_mode)

        # req. 6. writing a non existent property raises RuntimeError
        with self.assertRaises(RuntimeError) as ex:
            self.spectrometer.properties.set(integration_time=120, trigger_mode=2, non_existent_property=10)
        self.assertTrue("Some properties could not be set due to errors" in str(ex.exception))
        self.assertTrue("non_existent_property" in str(ex.exception.__notes__))
        # but those that exist will still be written
        self.assertEqual(self.spectrometer.integration_time, 120)
        self.assertEqual(self.spectrometer.trigger_mode, 2)

    def test_6_db_properties(self):
        """Test db operations for properties"""

        # req. 1. db operations are supported only at instance level
        with self.assertRaises(AttributeError) as ex:
            Thing.properties.load_from_DB()
        self.assertTrue("database operations are only supported at instance level" in str(ex.exception))
        with self.assertRaises(AttributeError) as ex:
            Thing.properties.get_from_DB()
        self.assertTrue("database operations are only supported at instance level" in str(ex.exception))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestThingInit))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestOceanOpticsSpectrometer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestMetaclass))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestActionRegistry))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestPropertiesRegistry))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestEventRegistry))
    return suite


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))


"""
# Summary of tests and requirements:

TestThing class:
1. Test id requirements:
    - Instance name must be a string and cannot be changed after set.
    - Valid and invalid IDs based on regex (r'[A-Za-z]+[A-Za-z_0-9\\-\\/]*').
2. Test logger setup:
    - Logger must have remote access handler if remote_accessible_logger is True.
    - Logger is created automatically if not provided.
3. Test state and state_machine setup:
    - State property must be None when no state machine is present.
4. Test composition of subthings:
    - Subthings must be a dictionary.
    - Subthings are recomputed when accessed.
    - Subthings must be instances of Thing and have the parent as owner.
    - Name of subthing must match name of the attribute.
5. Test servers init:
    - rpc_server and event_publisher must be None when not run().
    - rpc_server and event_publisher must be instances of their respective classes when run().
6. Test thing model generation:
    - Basic test to ensure nothing is fundamentally wrong.

TestOceanOpticsSpectrometer class:
1. Test state and state_machine setup:
    - State and state machine must be present because subclass has a state machine.
    - State and state machine must be different for different instances.

TestMetaclass class:
1. Test metaclass of Thing class:
    - Metaclass must be ThingMeta for any Thing class.
2. Test registry creation and access:
    - Registry attributes must be instances of their respective classes.
    - New registries are not created on the fly and are same between accesses.
    - Different subclasses have different registries.
    - Registry attributes must be instances of their respective classes also for instances.
    - Registries are not created on the fly and are same between accesses also for instances.
    - Registries are not shared between instances.
    - Registries are not shared between instances and their classes.

TestRegistry class:
1. Test owner attribute:
    - Owner attribute must be the class itself when accessed as class attribute.
    - Owner attribute must be the instance for instance registries.
    - Descriptor_object must be defined correctly and is a class.
2. Test descriptors access:
    - Descriptors are instances of the descriptor object.
    - Class level or instance level descriptors are same.
    - Descriptors can be cleared.
3. Test dunders:
    - __getitem__ must return the descriptor object.
    - __contains__ must return True if the descriptor is present.
    - __iter__ must return an iterator over the descriptors dictionary.
    - __len__ must return the number of descriptors.
    - Registries have their unique hashes.
4. Test bound objects:
    - Number of bound objects must be equal to number of descriptors.
    - Bound objects must be instances of bound instances.

TestActionRegistry class:
- Inherits tests from TestRegistry.

TestEventRegistry class:
- Inherits tests from TestRegistry.
- Observables and change events are also descriptors.

TestPropertiesRegistry class:
- Inherits tests from TestRegistry.
- Parameters that are subclass of Property are usually remote objects.
- DB operations are supported only at instance level.
"""
