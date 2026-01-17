from typing import Any

import pytest
import structlog

from things import OceanOpticsSpectrometer

from hololinked.core import Action, Event, Property, Thing, ThingMeta
from hololinked.core.actions import BoundAction
from hololinked.core.events import EventDispatcher
from hololinked.core.logger import RemoteAccessHandler
from hololinked.core.meta import (
    ActionsRegistry,
    DescriptorRegistry,  # noqa: F401
    EventsRegistry,
    PropertiesRegistry,
)
from hololinked.core.properties import Parameter  # noqa: F401
from hololinked.core.state_machine import BoundFSM
from hololinked.core.zmq.brokers import EventPublisher
from hololinked.core.zmq.rpc_server import RPCServer


"""
The tests in this file are for the initialization of the Thing class and its subclasses.
1. Test Thing class 
2. Test Thing subclass
3. Test ThingMeta metaclass
4. Test ActionRegistry class
5. Test EventRegistry class
6. Test PropertiesRegistry class

Test sequence is as follows:
1. Test id requirements 
2. Test logger setup
3. Test state and state_machine setup
4. Test composition of subthings
5. Test servers init
6. Test thing model generation
"""


@pytest.mark.parametrize("thing_cls", [Thing, OceanOpticsSpectrometer])
def test_01_id(thing_cls: ThingMeta):
    """Test id property of Thing class"""
    # req. 1. instance name must be a string and cannot be changed after set
    thing = thing_cls(id="test_id")  # type: Thing
    assert thing.id == "test_id"
    with pytest.raises(ValueError):
        thing.id = "new_instance"
    with pytest.raises(NotImplementedError):
        del thing.id
    # req. 2. regex is r'[A-Za-z]+[A-Za-z_0-9\-\/]*', simple URI like
    valid_ids = ["test_id", "A123", "valid_id-123", "another/valid-id"]
    invalid_ids = ["123_invalid", "invalid id", "invalid@id", ""]
    for valid_id in valid_ids:
        thing.properties.descriptors["id"].validate_and_adapt(valid_id)
    for invalid_id in invalid_ids:
        with pytest.raises(ValueError):
            thing.properties.descriptors["id"].validate_and_adapt(invalid_id)


@pytest.mark.parametrize("thing_cls", [Thing, OceanOpticsSpectrometer])
def notest_02_logger(thing_cls: ThingMeta):
    """Test logger setup"""
    # req. 1. logger must have remote access handler if remote_accessible_logger is True
    logger = structlog.get_logger("test_logger")
    thing = thing_cls(
        id="test_remote_accessible_logger",
        logger=logger,
        remote_accessible_logger=True,
    )  # type: Thing
    assert thing.logger == logger
    assert any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers)
    # Therefore also check the false condition
    logger = structlog.get_logger("test_logger_no_remote_access")
    thing = thing_cls(
        id="test_logger_without_remote_access",
        logger=logger,
        remote_accessible_logger=False,
    )  # type: Thing
    assert not any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers)
    # NOTE - logger is modifiable after instantiation

    # req. 2. logger is created automatically if not provided
    thing = thing_cls(id="test_logger_auto_creation")
    assert thing.logger is not None
    assert not any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers)
    assert thing.logger != logger  # not the above logger that we used.
    # remote accessible only when we ask for it
    thing = thing_cls(id="test_logger_auto_creation_2", remote_accessible_logger=True)  # type: Thing
    assert thing.logger is not None
    assert any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers)
    assert thing.logger != logger


@pytest.mark.parametrize("thing_cls", [Thing])
def test_03_has_no_fsm(thing_cls: ThingMeta):
    """Test state and state_machine setup"""
    # req. 1. state property must be None when no state machine is present
    thing = thing_cls(id="test_no_state_machine")  # type: Thing
    if thing.state_machine is None:
        assert thing.state is None
        assert thing.state_machine is None


@pytest.mark.parametrize("thing_cls", [OceanOpticsSpectrometer])
def test_04_bound_fsm(thing_cls: ThingMeta):
    """Test state and state_machine setup"""
    thing1 = thing_cls(id="test_state_machine")  # type: Thing
    # req. 1. state and state machine must be present because we create this subclass with a state machine
    assert thing1.state is not None
    assert isinstance(thing1.state_machine, BoundFSM)
    # req. 2. state and state machine must be different for different instances
    thing2 = thing_cls(id="test_state_machine_2")  # type: Thing
    # first check if state machine exists
    assert thing2.state is not None
    assert isinstance(thing2.state_machine, BoundFSM)
    # then check if they are different
    assert thing1.state_machine != thing2.state_machine
    # until state is set, initial state is equal
    assert thing1.state == thing2.state
    assert thing1.state_machine.initial_state == thing2.state_machine.initial_state
    # after state is set, they are different
    thing1.state_machine.set_state(thing1.states.ALARM)
    assert thing1.state != thing2.state
    assert thing1.state_machine != thing2.state_machine
    # initial state is still same
    assert thing1.state_machine.initial_state == thing2.state_machine.initial_state
    # detailed checks in another file


@pytest.mark.parametrize("thing_cls", [Thing, OceanOpticsSpectrometer])
def test_05_subthings(thing_cls: ThingMeta):
    """Test object composition"""
    thing = thing_cls(id="test_subthings", remote_accessible_logger=True)  # type: Thing
    # req. 1. subthings must be a dictionary
    assert isinstance(thing.sub_things, dict)
    assert len(thing.sub_things) == 1  # logger
    # req. 2. subthings are always recomputed when accessed (at least thats the way it is right now),
    # so we can add new subthings anytime
    thing.another_thing = OceanOpticsSpectrometer(id="another_thing")
    assert isinstance(thing.sub_things, dict)
    assert len(thing.sub_things) == 2  # logger + another_thing
    # req. 3. subthings must be instances of Thing and have the parent as owner
    for name, subthing in thing.sub_things.items():
        assert thing in subthing._owners  # type: ignore[attr-defined]
        assert isinstance(subthing, Thing)
        # req. 4. name of subthing must match name of the attribute
        assert hasattr(thing, name)


@pytest.mark.parametrize("thing_cls", [Thing, OceanOpticsSpectrometer])
def test_06_servers_init(thing_cls: ThingMeta):
    """Test if servers can be initialized/instantiated"""
    # req. 1. rpc_server and event_publisher must be None when not run()
    thing = thing_cls(id="test_servers_init")  # type: Thing
    assert thing.rpc_server is None
    assert thing.event_publisher is None
    # req. 2. rpc_server and event_publisher must be instances of their respective classes when run()
    RPCServer(id="test-rpc-server-init", things=[thing], logger=thing.logger)  # prepare server class
    assert isinstance(thing.rpc_server, RPCServer)
    assert isinstance(thing.event_publisher, EventPublisher)
    # exit to quit nicely
    thing.rpc_server.exit()
    thing.event_publisher.exit()


"""
Test sequence is as follows:
1. Test metaclass of Thing class
2. Test registry creation and access which is currently the main purpose of the metaclass
"""


@pytest.mark.parametrize("thing_cls", [Thing, OceanOpticsSpectrometer])
def test_07_metaclass_assigned(thing_cls: ThingMeta):
    """test metaclass of Thing class"""
    # req. 1 metaclass must be ThingMeta of any Thing class
    assert thing_cls.__class__ == ThingMeta
    assert OceanOpticsSpectrometer.__class__ == ThingMeta
    assert Thing.__class__ == OceanOpticsSpectrometer.__class__


def test_08_registry_creation():
    """test registry creation and access which is currently the main purpose of the metaclass"""
    # req. 1. registry attributes must be instances of their respective classes
    assert isinstance(Thing.properties, PropertiesRegistry)
    assert isinstance(Thing.actions, ActionsRegistry)
    assert isinstance(Thing.events, EventsRegistry)

    # req. 2. new registries are not created on the fly and are same between accesses
    assert Thing.properties == Thing.properties
    assert Thing.actions == Thing.actions
    assert Thing.events == Thing.events
    # This test is done as the implementation deviates from `param`

    # req. 3. different subclasses have different registries
    assert Thing.properties != OceanOpticsSpectrometer.properties
    assert Thing.actions != OceanOpticsSpectrometer.actions
    assert Thing.events != OceanOpticsSpectrometer.events

    # create instances for further tests
    thing = Thing(id="test_registry_creation")
    spectrometer = OceanOpticsSpectrometer(id="test_registry_creation_2")

    # req. 4. registry attributes must be instances of their respective classes also for instances
    assert isinstance(thing.properties, PropertiesRegistry)
    assert isinstance(thing.actions, ActionsRegistry)
    assert isinstance(thing.events, EventsRegistry)

    # req. 5. registries are not created on the fly and are same between accesses also for instances
    assert thing.properties == thing.properties
    assert thing.actions == thing.actions
    assert thing.events == thing.events

    # req. 6. registries are not shared between instances
    assert thing.properties != spectrometer.properties
    assert thing.actions != spectrometer.actions
    assert thing.events != spectrometer.events

    # req. 7. registries are not shared between instances and their classes
    assert thing.properties != Thing.properties
    assert thing.actions != Thing.actions
    assert thing.events != Thing.events
    assert spectrometer.properties != OceanOpticsSpectrometer.properties
    assert spectrometer.actions != OceanOpticsSpectrometer.actions
    assert spectrometer.events != OceanOpticsSpectrometer.events


"""
Test action registry first because actions are the easiest to test.
1. Test owner attribute
2. Test descriptors access
3. Test dunders
"""


class Registry:
    """Class to hold registry class and object for parameterized tests"""

    cls: type[PropertiesRegistry | ActionsRegistry | EventsRegistry]
    cls_object: PropertiesRegistry | ActionsRegistry | EventsRegistry
    inst_object: PropertiesRegistry | ActionsRegistry | EventsRegistry | None
    obj: type[Property | Action | Event]
    bound_object: type[BoundAction | EventDispatcher] | Any  # any is for property value
    thing_cls: ThingMeta
    thing_inst: Thing

    def __init__(self) -> None:
        pass


@pytest.fixture(
    params=[
        pytest.param((Thing, PropertiesRegistry), id="Thing-PropertiesRegistry"),
        pytest.param((Thing, ActionsRegistry), id="Thing-ActionsRegistry"),
        pytest.param((Thing, EventsRegistry), id="Thing-EventsRegistry"),
        pytest.param((OceanOpticsSpectrometer, PropertiesRegistry), id="OceanOpticsSpectrometer-PropertiesRegistry"),
        pytest.param((OceanOpticsSpectrometer, ActionsRegistry), id="OceanOpticsSpectrometer-ActionsRegistry"),
        pytest.param((OceanOpticsSpectrometer, EventsRegistry), id="OceanOpticsSpectrometer-EventsRegistry"),
    ],
)
def registry(request) -> Registry:
    # create instances for further tests
    cls, registry_cls = request.param
    thing = cls(id=f"test_{registry_cls.__name__}_registry")
    registry = Registry()
    registry.thing_cls = cls
    registry.thing_inst = thing
    registry.cls = registry_cls
    if registry_cls == ActionsRegistry:
        registry.cls_object = cls.actions
        registry.inst_object = thing.actions
        registry.obj = Action
        registry.bound_object = BoundAction
    elif registry_cls == PropertiesRegistry:
        registry.cls_object = cls.properties
        registry.inst_object = thing.properties
        registry.obj = Parameter
        registry.bound_object = Any
    elif registry_cls == EventsRegistry:
        registry.cls_object = cls.events
        registry.inst_object = thing.events
        registry.obj = Event
        registry.bound_object = EventDispatcher
    else:
        raise NotImplementedError("This registry class is not implemented")
    return registry


def test_09_registry_owner(registry: Registry):
    """Test owner attribute of DescriptorRegistry"""
    # See comment above TestRegistry class to enable type definitions
    # req. 1. owner attribute must be the class itself when accessed as class attribute
    assert registry.cls_object.owner == registry.thing_cls
    # therefore owner instance must be None
    assert registry.cls_object.owner_inst is None

    # req. 2. owner attribute must be the instance for instance registries (i.e. when accessed as instance attribute)
    assert registry.inst_object.owner == registry.thing_inst
    assert registry.inst_object.owner_cls == registry.thing_cls

    # req. 3. descriptor_object must be defined correctly and is a class
    assert registry.cls_object.descriptor_object == registry.obj
    assert registry.inst_object.descriptor_object == registry.obj
    assert registry.cls_object.descriptor_object == registry.inst_object.descriptor_object


def test_10_descriptors_access(registry: Registry):
    """Test descriptors access"""

    # req. 1. descriptors are instances of the descriptor object - Property | Action | Event
    for name, value in registry.cls_object.descriptors.items():
        assert isinstance(value, registry.obj)
        assert isinstance(name, str)

    # req. 2. either class level or instance level descriptors are same - not a strict requirement for different
    # use cases, one can always add instance level descriptors
    for name, value in registry.inst_object.descriptors.items():
        assert isinstance(value, registry.obj)
        assert isinstance(name, str)

    # req. 3. because class level and instance level descriptors are same, they are equal
    for (name, value), (name2, value2) in zip(
        registry.cls_object.descriptors.items(),
        registry.inst_object.descriptors.items(),
    ):
        assert name == name2
        assert value == value2

    # req. 4. descriptors can be cleared
    assert hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{registry.cls.__name__.lower()}",
    )
    registry.inst_object.clear()
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{registry.cls.__name__.lower()}",
    )
    # clearing again any number of times should not raise error
    registry.inst_object.clear()
    registry.inst_object.clear()
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{registry.cls.__name__.lower()}",
    )


def test_11_registry_dunders(registry: Registry):
    """Test dunders of DescriptorRegistry"""

    # req. 1. __getitem__ must return the descriptor object
    for name, value in registry.cls_object.descriptors.items():
        assert registry.cls_object[name] == value
        # req. 2. __contains__ must return True if the descriptor is present
        assert value in registry.cls_object
        assert name in registry.cls_object.descriptors.keys()

    # req. 2. __iter__ must return an iterator over the descriptors dictionary
    # which in turn iterates over the keys
    assert all(isinstance(descriptor_name, str) for descriptor_name in registry.cls_object)
    assert all(isinstance(descriptor_name, str) for descriptor_name in registry.inst_object)
    # __iter__ can also be casted as other iterators like lists
    descriptors = list(registry.inst_object)
    assert isinstance(descriptors, list)
    assert all(isinstance(descriptor_name, str) for descriptor_name in descriptors)

    # req. 3. __len__ must return the number of descriptors
    assert len(registry.cls_object) == len(registry.cls_object.descriptors)
    assert len(registry.inst_object) == len(registry.inst_object.descriptors)
    assert len(registry.inst_object) == len(registry.cls_object)

    # req. 4. registries have their unique hashes
    # NOTE - not sure if this is really a useful feature or just plain stupid
    # The requirement was to be able to generate unique hashes for each registry like foodict[<some hash>] = Thing.actions
    foodict = {
        registry.cls_object: 1,
        registry.inst_object: 3,
    }
    assert foodict[registry.cls_object] == 1
    assert foodict[registry.inst_object] == 3

    # __dir__ not yet tested
    # __str__ will not be tested


def test_12_bound_objects(registry: Registry):
    """Test bound objects returned from descriptor access"""
    # req. 1. number of bound objects must be equal to number of descriptors
    # for example, number of bound actions must be equal to number of actions
    assert len(registry.inst_object) == len(registry.inst_object.descriptors)

    # req. 2. bound objects must be instances of bound instances
    for name, value in registry.inst_object.values.items():
        if registry.bound_object != Any:
            assert isinstance(value, registry.bound_object)
        assert isinstance(name, str)


@pytest.fixture(
    params=[
        pytest.param((Thing, EventsRegistry), id="Thing-EventsRegistry"),
        pytest.param((OceanOpticsSpectrometer, EventsRegistry), id="OceanOpticsSpectrometer-EventsRegistry"),
    ],
)
def event_registry(request) -> Registry:
    cls, registry_cls = request.param
    thing = cls(id=f"test_{registry_cls.__name__}_registry")
    registry = Registry()
    registry.thing_cls = cls
    registry.thing_inst = thing
    registry.cls = registry_cls
    registry.cls_object = cls.events
    registry.inst_object = thing.events
    registry.obj = Event
    registry.bound_object = EventDispatcher
    return registry


def test_13_descriptors_access_events(event_registry: Registry):
    registry = event_registry
    # req. 5. observables and change events are also descriptors
    for name, value in registry.inst_object.observables.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)
    for name, value in registry.inst_object.change_events.items():
        assert isinstance(value, Event)
        assert isinstance(name, str)
    # req. 4. descriptors can be cleared
    assert hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}",
    )
    assert hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
    )
    assert hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
    )
    registry.inst_object.clear()
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}",
    )
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
    )
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
    )
    registry.inst_object.clear()
    registry.inst_object.clear()
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}",
    )
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_change_events",
    )
    assert not hasattr(
        registry.inst_object,
        f"_{registry.inst_object._qualified_prefix}_{EventsRegistry.__name__.lower()}_observables",
    )


@pytest.fixture(
    params=[
        pytest.param((Thing, PropertiesRegistry), id="Thing-PropertiesRegistry"),
        pytest.param((OceanOpticsSpectrometer, PropertiesRegistry), id="OceanOpticsSpectrometer-PropertiesRegistry"),
    ],
)
def properties_registry(request) -> Registry:
    cls, registry_cls = request.param
    thing = cls(id=f"test_{registry_cls.__name__}_registry")
    registry = Registry()
    registry.thing_cls = cls
    registry.thing_inst = thing
    registry.cls = registry_cls
    registry.cls_object = cls.properties
    registry.inst_object = thing.properties
    registry.obj = Property
    registry.bound_object = Any
    return registry


def test_14_descriptors_access_properties(properties_registry: Registry):
    registry = properties_registry

    # req. 5. parameters that are subclass of Property are usually remote objects
    for name, value in registry.thing_inst.properties.remote_objects.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)

    # req. 6. db_objects, db_init_objects, db_persisting_objects, db_commit_objects are also descriptors
    for name, value in registry.thing_inst.properties.db_objects.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)
        assert value.db_init or value.db_persist or value.db_commit
    for name, value in registry.thing_inst.properties.db_init_objects.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)
        assert value.db_init or value.db_persist
        assert not value.db_commit
    for name, value in registry.thing_inst.properties.db_commit_objects.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)
        assert value.db_commit or value.db_persist
        assert not value.db_init
    for name, value in registry.thing_inst.properties.db_persisting_objects.items():
        assert isinstance(value, Property)
        assert isinstance(name, str)
        assert value.db_persist
        assert not value.db_init  # in user given cases, this could be true, this is not strict requirement
        assert not value.db_commit  # in user given cases, this could be true, this is not strict requirement

    # req. 4. descriptors can be cleared
    assert hasattr(
        registry.thing_inst.properties,
        f"_{registry.thing_inst.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
    )

    registry.thing_inst.properties.clear()
    assert not hasattr(
        registry.thing_inst.properties,
        f"_{registry.thing_inst.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
    )

    registry.thing_inst.properties.clear()
    registry.thing_inst.properties.clear()
    assert not hasattr(
        registry.thing_inst.properties,
        f"_{registry.thing_inst.properties._qualified_prefix}_{PropertiesRegistry.__name__.lower()}",
    )


@pytest.fixture(
    params=[
        pytest.param((OceanOpticsSpectrometer, PropertiesRegistry), id="OceanOpticsSpectrometer-PropertiesRegistry"),
    ],
)
def spectrometer_registry(request) -> Registry:
    cls, registry_cls = request.param
    thing = cls(id=f"test_{registry_cls.__name__}_registry")
    registry = Registry()
    registry.thing_cls = cls
    registry.thing_inst = thing
    registry.cls = registry_cls
    registry.cls_object = cls.properties
    registry.inst_object = thing.properties
    registry.obj = Property
    registry.bound_object = Any
    return registry


def test_15_bulk_read_write_properties(spectrometer_registry: Registry):
    """Test bulk read and write operations for properties"""
    registry = spectrometer_registry

    # req. 1. test read in bulk for readAllProperties
    prop_values = registry.thing_inst.properties.get()
    # read value is a dictionary
    assert isinstance(prop_values, dict)
    assert len(prop_values) > 0
    # all properties are read at instance level and get only reads remote objects
    assert len(prop_values) == len(registry.thing_inst.properties.remote_objects)
    # read values are not descriptors themselves
    for name, value in prop_values.items():
        assert isinstance(name, str)
        assert not isinstance(value, Parameter)  # descriptor has been read

    # req. 2. properties can be read with new names
    prop_values = registry.thing_inst.properties.get(
        integration_time="integrationTime",
        state="State",
        trigger_mode="triggerMode",
    )
    assert isinstance(prop_values, dict)
    assert len(prop_values) == 3
    for name, value in prop_values.items():
        assert isinstance(name, str)
        assert name in ["integrationTime", "triggerMode", "State"]
        assert not isinstance(value, Parameter)

    # req. 3. read in bulk for readMultipleProperties
    prop_values = registry.thing_inst.properties.get(
        names=["integration_time", "trigger_mode", "state", "last_intensity"]
    )
    # read value is a dictionary
    assert isinstance(prop_values, dict)
    assert len(prop_values) == 4
    # read values are not descriptors themselves
    for name, value in prop_values.items():
        assert isinstance(name, str)
        assert name in ["integration_time", "trigger_mode", "state", "last_intensity"]
        assert not isinstance(value, Parameter)

    # req. 4. read a property that is not present raises AttributeError
    with pytest.raises(AttributeError) as ex:
        prop_values = registry.thing_inst.properties.get(
            names=[
                "integration_time",
                "trigger_mode",
                "non_existent_property",
                "last_intensity",
            ]
        )
    assert "property non_existent_property does not exist" in str(ex.value)

    # req. 5. write in bulk
    prop_values = registry.thing_inst.properties.get()
    registry.thing_inst.properties.set(integration_time=10, trigger_mode=1)
    assert prop_values["integration_time"] != registry.thing_inst.integration_time
    assert prop_values["trigger_mode"] != registry.thing_inst.trigger_mode

    # req. 6. writing a non existent property raises RuntimeError
    with pytest.raises(RuntimeError) as ex:
        registry.thing_inst.properties.set(integration_time=120, trigger_mode=2, non_existent_property=10)
    assert "Some properties could not be set due to errors" in str(ex.value)
    # __notes__ is not standard in pytest exceptions, so we skip that assertion
    # but those that exist will still be written
    assert registry.thing_inst.integration_time == 120
    assert registry.thing_inst.trigger_mode == 2


def test_16_db_properties():
    """Test db operations for properties"""
    # req. 1. db operations are supported only at instance level
    with pytest.raises(AttributeError) as ex:
        Thing.properties.load_from_DB()
    assert "database operations are only supported at instance level" in str(ex.value)
    with pytest.raises(AttributeError) as ex:
        Thing.properties.get_from_DB()
    assert "database operations are only supported at instance level" in str(ex.value)


def test_17_inheritance_of_registries():
    """Test that registries are inherited properly"""
    # req. 1. subclass have more descriptors than parent class because our example Thing OceanOpticsSpectrometer
    # has defined its own actions, properties and events
    assert len(OceanOpticsSpectrometer.properties.descriptors) > len(Thing.properties.descriptors)
    assert len(OceanOpticsSpectrometer.actions.descriptors) > len(Thing.actions.descriptors)
    assert len(OceanOpticsSpectrometer.events.descriptors) > len(Thing.events.descriptors)


# """
# # Summary of tests and requirements:

# TestThing class:
# 1. Test id requirements:
#     - Instance name must be a string and cannot be changed after set.
#     - Valid and invalid IDs based on regex (r'[A-Za-z]+[A-Za-z_0-9\\-\\/]*').
# 2. Test logger setup:
#     - Logger must have remote access handler if remote_accessible_logger is True.
#     - Logger is created automatically if not provided.
# 3. Test state and state_machine setup:
#     - State property must be None when no state machine is present.
# 4. Test composition of subthings:
#     - Subthings must be a dictionary.
#     - Subthings are recomputed when accessed.
#     - Subthings must be instances of Thing and have the parent as owner.
#     - Name of subthing must match name of the attribute.
# 5. Test servers init:
#     - rpc_server and event_publisher must be None when not run().
#     - rpc_server and event_publisher must be instances of their respective classes when run().
# 6. Test thing model generation:
#     - Basic test to ensure nothing is fundamentally wrong.

# TestOceanOpticsSpectrometer class:
# 1. Test state and state_machine setup:
#     - State and state machine must be present because subclass has a state machine.
#     - State and state machine must be different for different instances.

# TestMetaclass class:
# 1. Test metaclass of Thing class:
#     - Metaclass must be ThingMeta for any Thing class.
# 2. Test registry creation and access:
#     - Registry attributes must be instances of their respective classes.
#     - New registries are not created on the fly and are same between accesses.
#     - Different subclasses have different registries.
#     - Registry attributes must be instances of their respective classes also for instances.
#     - Registries are not created on the fly and are same between accesses also for instances.
#     - Registries are not shared between instances.
#     - Registries are not shared between instances and their classes.

# TestRegistry class:
# 1. Test owner attribute:
#     - Owner attribute must be the class itself when accessed as class attribute.
#     - Owner attribute must be the instance for instance registries.
#     - Descriptor_object must be defined correctly and is a class.
# 2. Test descriptors access:
#     - Descriptors are instances of the descriptor object.
#     - Class level or instance level descriptors are same.
#     - Descriptors can be cleared.
# 3. Test dunders:
#     - __getitem__ must return the descriptor object.
#     - __contains__ must return True if the descriptor is present.
#     - __iter__ must return an iterator over the descriptors dictionary.
#     - __len__ must return the number of descriptors.
#     - Registries have their unique hashes.
# 4. Test bound objects:
#     - Number of bound objects must be equal to number of descriptors.
#     - Bound objects must be instances of bound instances.

# TestActionRegistry class:
# - Inherits tests from TestRegistry.

# TestEventRegistry class:
# - Inherits tests from TestRegistry.
# - Observables and change events are also descriptors.

# TestPropertiesRegistry class:
# - Inherits tests from TestRegistry.
# - Parameters that are subclass of Property are usually remote objects.
# - DB operations are supported only at instance level.
# """


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
