import logging
import pytest
from hololinked.core.events import Event, EventDispatcher
from hololinked.core.zmq.brokers import EventPublisher
from hololinked.td.interaction_affordance import EventAffordance
from hololinked.logger import setup_logging

try:
    from .things import TestThing
except ImportError:
    from things import TestThing

setup_logging(log_level=logging.ERROR)


@pytest.fixture(scope="module")
def thing():
    return TestThing(id="test-event")


def _test_dispatcher(descriptor: Event, dispatcher: EventDispatcher, thing: TestThing):
    assert isinstance(dispatcher, EventDispatcher)  # instance access returns dispatcher
    assert dispatcher._owner_inst is thing  # dispatcher has the owner instance
    assert (
        thing.rpc_server and thing.rpc_server.event_publisher and isinstance(dispatcher.publisher, EventPublisher)
    ) or dispatcher.publisher is None
    assert dispatcher._unique_identifier == f"{thing._qualified_id}/{descriptor.name}"


def test_1_pure_events(thing):
    """Test basic event functionality"""
    # 1. Test class-level access to event descriptor
    assert isinstance(TestThing.test_event, Event)  # class access returns descriptor
    # 2. Test instance-level access to event dispatcher which is returned by the descriptor
    _test_dispatcher(TestThing.test_event, thing.test_event, thing)  # test dispatcher returned by descriptor
    # 3. Event with JSON schema has schema variable set


def test_2_observable_events(thing):
    """Test observable event (of properties) functionality"""
    # 1. observable properties have an event descriptor associated with them as a reference
    assert isinstance(TestThing.observable_list_prop._observable_event_descriptor, Event)
    assert isinstance(TestThing.state._observable_event_descriptor, Event)
    assert isinstance(TestThing.observable_readonly_prop._observable_event_descriptor, Event)

    # 2. observable descriptors have been assigned as an attribute of the owning class
    assert hasattr(
        TestThing,
        TestThing.observable_list_prop._observable_event_descriptor.name,
    )
    assert hasattr(TestThing, TestThing.state._observable_event_descriptor.name)
    assert hasattr(
        TestThing,
        TestThing.observable_readonly_prop._observable_event_descriptor.name,
    )

    # 3. accessing those descriptors returns the event dispatcher
    _test_dispatcher(
        TestThing.observable_list_prop._observable_event_descriptor,
        getattr(
            thing,
            TestThing.observable_list_prop._observable_event_descriptor.name,
            None,
        ),
        thing,
    )
    _test_dispatcher(
        TestThing.state._observable_event_descriptor,
        getattr(thing, TestThing.state._observable_event_descriptor.name, None),
        thing,
    )
    _test_dispatcher(
        TestThing.observable_readonly_prop._observable_event_descriptor,
        getattr(
            thing,
            TestThing.observable_readonly_prop._observable_event_descriptor.name,
            None,
        ),
        thing,
    )


def test_3_event_affordance(thing):
    """Test event affordance generation"""
    event = TestThing.test_event.to_affordance(thing)
    assert isinstance(event, EventAffordance)
