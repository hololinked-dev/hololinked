import pytest

from hololinked.core.events import Event, EventDispatcher
from hololinked.core.zmq.brokers import EventPublisher
from hololinked.td.interaction_affordance import EventAffordance
from hololinked.utils import uuid_hex


try:
    from .things import TestThing
except ImportError:
    from things import TestThing


def validate_event_dispatcher(descriptor: Event, dispatcher: EventDispatcher, thing: TestThing):
    # instance access returns dispatcher
    assert isinstance(dispatcher, EventDispatcher)
    # dispatcher has the owner instance
    assert dispatcher._owner_inst is thing
    # event publisher and RPC server presence depends on whether the thing has been started or not
    assert (
        thing.rpc_server and thing.rpc_server.event_publisher and isinstance(dispatcher.publisher, EventPublisher)
    ) or dispatcher.publisher is None
    # unique identifier is correctly formed, qualified by the thing ID
    assert dispatcher._unique_identifier == f"{thing._qualified_id}/{descriptor.name}"


def test_01_pure_events():
    """Test basic event functionality"""
    thing = TestThing(id=f"test-pure-events-{uuid_hex()}")
    # 1. Test class-level access to event descriptor
    assert isinstance(TestThing.test_event, Event)  # class access returns descriptor
    # 2. Test instance-level access to event dispatcher which is returned by the descriptor
    validate_event_dispatcher(TestThing.test_event, thing.test_event, thing)  # test dispatcher returned by descriptor
    # 3. Event with JSON schema has schema variable set


def test_02_observable_events():
    """Test observable event (of properties) functionality"""
    thing = TestThing(id=f"test-observable-events-{uuid_hex()}")
    # 1. observable properties have an event descriptor associated with them as a reference
    assert isinstance(TestThing.observable_list_prop._observable_event_descriptor, Event)
    assert isinstance(TestThing.state._observable_event_descriptor, Event)
    assert isinstance(TestThing.observable_readonly_prop._observable_event_descriptor, Event)

    # 2. observable descriptors have been assigned as an attribute of the owning class
    assert hasattr(TestThing, TestThing.observable_list_prop._observable_event_descriptor.name)
    assert hasattr(TestThing, TestThing.state._observable_event_descriptor.name)
    assert hasattr(TestThing, TestThing.observable_readonly_prop._observable_event_descriptor.name)

    # 3. accessing those descriptors returns the event dispatcher
    validate_event_dispatcher(
        TestThing.observable_list_prop._observable_event_descriptor,
        getattr(thing, TestThing.observable_list_prop._observable_event_descriptor.name, None),
        thing,
    )
    validate_event_dispatcher(
        TestThing.state._observable_event_descriptor,
        getattr(thing, TestThing.state._observable_event_descriptor.name, None),
        thing,
    )
    validate_event_dispatcher(
        TestThing.observable_readonly_prop._observable_event_descriptor,
        getattr(thing, TestThing.observable_readonly_prop._observable_event_descriptor.name, None),
        thing,
    )


def test_03_event_affordance():
    """Test event affordance generation"""
    thing = TestThing(id=f"test-event-affordance-{uuid_hex()}")
    event = TestThing.test_event.to_affordance(thing)
    assert isinstance(event, EventAffordance)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
