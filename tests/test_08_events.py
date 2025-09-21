import asyncio
import unittest
import logging


from hololinked.core.events import Event, EventDispatcher
from hololinked.core.zmq.brokers import EventPublisher
from hololinked.td.interaction_affordance import EventAffordance
from hololinked.schema_validators import JSONSchemaValidator

try:
    from .utils import TestCase, TestRunner
    from .things import TestThing
except ImportError:
    from utils import TestCase, TestRunner
    from things import TestThing


class TestEvents(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print(f"test events with {cls.__name__}")

    def _test_dispatcher(self, descriptor: Event, dispatcher: EventDispatcher, thing: TestThing):
        """pass the event descriptor and the dispatcher to test the dispatcher"""
        self.assertIsInstance(dispatcher, EventDispatcher)  # instance access returns dispatcher
        self.assertTrue(dispatcher._owner_inst is thing)  # dispatcher has the owner instance
        self.assertTrue(
            (
                thing.rpc_server
                and thing.rpc_server.event_publisher
                and isinstance(dispatcher.publisher, EventPublisher)
            )  # publisher is set
            or dispatcher.publisher is None  # publisher is not set if no rpc_server
        )
        self.assertEqual(dispatcher._unique_identifier, f"{thing._qualified_id}/{descriptor.name}")

    def test_1_pure_events(self):
        """Test basic event functionality"""

        # 1. Test class-level access to event descriptor
        self.assertIsInstance(TestThing.test_event, Event)  # class access returns descriptor
        # self.assertFalse(TestThing.test_event._observable) # not an oberservable property

        # 2. Test instance-level access to event dispatcher which is returned by the descriptor
        thing = TestThing(id="test-event", log_level=logging.WARN)
        self._test_dispatcher(TestThing.test_event, thing.test_event, thing)  # test dispatcher returned by descriptor

        # 3. Event with JSON schema has schema variable set

    def test_2_observable_events(self):
        """Test observable event (of properties) functionality"""

        # 1. observable properties have an event descriptor associated with them as a reference
        self.assertIsInstance(TestThing.observable_list_prop._observable_event_descriptor, Event)
        self.assertIsInstance(TestThing.state._observable_event_descriptor, Event)
        self.assertIsInstance(TestThing.observable_readonly_prop._observable_event_descriptor, Event)

        # 2. observable descriptors have been assigned as an attribute of the owning class
        self.assertTrue(
            hasattr(
                TestThing,
                TestThing.observable_list_prop._observable_event_descriptor.name,
            )
        )
        self.assertTrue(hasattr(TestThing, TestThing.state._observable_event_descriptor.name))
        self.assertTrue(
            hasattr(
                TestThing,
                TestThing.observable_readonly_prop._observable_event_descriptor.name,
            )
        )

        # 3. accessing those descriptors returns the event dispatcher
        thing = TestThing(id="test-event", log_level=logging.WARN)
        self._test_dispatcher(
            TestThing.observable_list_prop._observable_event_descriptor,
            getattr(
                thing,
                TestThing.observable_list_prop._observable_event_descriptor.name,
                None,
            ),
            thing,
        )  # test dispatcher returned by descriptor
        self._test_dispatcher(
            TestThing.state._observable_event_descriptor,
            getattr(thing, TestThing.state._observable_event_descriptor.name, None),
            thing,
        )
        self._test_dispatcher(
            TestThing.observable_readonly_prop._observable_event_descriptor,
            getattr(
                thing,
                TestThing.observable_readonly_prop._observable_event_descriptor.name,
                None,
            ),
            thing,
        )

    def test_3_event_affordance(self):
        """Test event affordance generation"""

        # 1. Test event affordance generation
        thing = TestThing(id="test-event", log_level=logging.WARN)
        event = TestThing.test_event.to_affordance(thing)
        self.assertIsInstance(event, EventAffordance)


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
