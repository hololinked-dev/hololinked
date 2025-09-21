# an end to end through the zmq object proxy client with IPC protocol which is assumed to be most stable
import time
import unittest
import logging
from uuid import uuid4
from hololinked.client.abstractions import SSE
from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy

try:
    from .things import TestThing
    from .utils import TestCase, TestRunner, fake, AsyncTestCase
except ImportError:
    from things import TestThing
    from utils import TestCase, TestRunner, fake, AsyncTestCase


class TestRPCEndToEnd(TestCase):
    """Test the zmq object proxy client"""

    @classmethod
    def setUpClass(cls):
        cls.thing_id = f"test-thing-{uuid4().hex[:8]}"
        cls.server_id = cls.thing_id
        super().setUpClass()
        cls.setUpThing()
        print("Test ZMQ IPC End to End")

    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True)
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def tearDownClass(cls):
        """Test the stop of the zmq object proxy client"""
        cls._client = None
        cls.thing.rpc_server.stop()
        super().tearDownClass()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "IPC",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client

    def test_01_creation_and_handshake(self):
        """Test the creation and handshake of the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        self.assertTrue(
            len(thing.properties) + len(thing.actions) + len(thing.events)
            >= len(self.thing_model["properties"]) + len(self.thing_model["actions"]) + len(self.thing_model["events"])
        )

    def test_02_invoke_action(self):
        """Test the invocation of an action on the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        # Test invoke_action method with reply
        self.assertEqual(thing.invoke_action("action_echo", fake.text(max_nb_chars=100)), fake.last)
        self.assertEqual(thing.invoke_action("action_echo", fake.sentence()), fake.last)
        self.assertEqual(thing.invoke_action("action_echo", fake.json()), fake.last)
        # Test invoke_action with dot notation
        self.assertEqual(thing.action_echo(fake.chrome()), fake.last)
        self.assertEqual(thing.action_echo(fake.sha256()), fake.last)
        self.assertEqual(thing.action_echo(fake.address()), fake.last)
        # Test invoke_action with no reply
        self.assertEqual(
            thing.invoke_action("set_non_remote_number_prop", fake.random_number(), oneway=True),
            None,
        )
        self.assertEqual(thing.get_non_remote_number_prop(), fake.last)
        # Test invoke_action in non blocking mode
        noblock_payload = fake.pylist(20, value_types=[int, float, str, bool])
        noblock_msg_id = thing.invoke_action("action_echo", noblock_payload, noblock=True)
        self.assertIsInstance(noblock_msg_id, str)
        self.assertEqual(
            thing.invoke_action("action_echo", fake.pylist(20, value_types=[int, float, str, bool])),
            fake.last,
        )
        self.assertEqual(
            thing.invoke_action("action_echo", fake.pylist(10, value_types=[int, float, str, bool])),
            fake.last,
        )
        self.assertEqual(thing.read_reply(noblock_msg_id), noblock_payload)

    def test_03_rwd_properties(self):
        """Test the read, write and delete of properties on the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        # Test read_property method
        self.assertIsInstance(thing.read_property("number_prop"), (int, float))
        self.assertIsInstance(thing.read_property("string_prop"), str)
        self.assertIn(thing.read_property("selector_prop"), TestThing.selector_prop.objects)
        # Test write_property method
        thing.write_property("number_prop", fake.random_number())
        self.assertEqual(thing.read_property("number_prop"), fake.last)
        thing.write_property(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
        )
        self.assertEqual(
            thing.read_property("selector_prop"),
            TestThing.selector_prop.objects[fake.last],
        )
        thing.write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]))
        self.assertEqual(thing.read_property("observable_list_prop"), fake.last)
        # Test read property through dot notation attribute access
        self.assertIsInstance(thing.number_prop, (int, float))
        self.assertIsInstance(thing.string_prop, str)
        self.assertIn(thing.selector_prop, TestThing.selector_prop.objects)
        # Test write property through dot notation attribute access
        thing.number_prop = fake.random_number()
        self.assertEqual(thing.number_prop, fake.last)
        thing.selector_prop = TestThing.selector_prop.objects[
            fake.random_int(0, len(TestThing.selector_prop.objects) - 1)
        ]
        self.assertEqual(thing.selector_prop, TestThing.selector_prop.objects[fake.last])
        thing.observable_list_prop = fake.pylist(25, value_types=[int, float, str, bool])
        self.assertEqual(thing.observable_list_prop, fake.last)
        # Test one way write property
        thing.write_property("number_prop", fake.random_number(), oneway=True)
        self.assertEqual(thing.read_property("number_prop"), fake.last)
        thing.write_property(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
            oneway=True,
        )
        self.assertEqual(
            thing.read_property("selector_prop"),
            TestThing.selector_prop.objects[fake.last],
        )
        thing.write_property(
            "observable_list_prop",
            fake.pylist(25, value_types=[int, float, str, bool]),
            oneway=True,
        )
        self.assertEqual(thing.read_property("observable_list_prop"), fake.last)
        # Test noblock read property
        noblock_msg_id = thing.read_property("number_prop", noblock=True)
        self.assertIsInstance(noblock_msg_id, str)
        self.assertIn(thing.read_property("selector_prop"), TestThing.selector_prop.objects)
        self.assertIsInstance(thing.read_property("string_prop"), str)
        self.assertEqual(thing.read_reply(noblock_msg_id), thing.number_prop)
        # Test noblock write property
        noblock_msg_id = thing.write_property("number_prop", fake.random_number(), noblock=True)
        self.assertIsInstance(noblock_msg_id, str)
        self.assertEqual(thing.read_property("number_prop"), fake.last)  # noblock worked
        self.assertEqual(thing.read_reply(noblock_msg_id), None)
        # Test exception propagation to client
        thing.string_prop = "world"
        self.assertEqual(thing.string_prop, "world")
        with self.assertRaises(ValueError):
            thing.string_prop = "WORLD"
        with self.assertRaises(TypeError):
            thing.int_prop = "5"
        # Test non remote prop (non-)availability on client
        with self.assertRaises(AttributeError):
            thing.non_remote_number_prop

    def test_04_RW_multiple_properties(self):
        # TD is not well defined for this yet, although both client and server separately work.
        # Test partial list of read write properties
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        # Test read_multiple_properties method
        thing.write_multiple_properties(number_prop=15, string_prop="foobar")
        self.assertEqual(thing.number_prop, 15)
        self.assertEqual(thing.string_prop, "foobar")
        # check prop that was not set in multiple properties

        thing.int_prop = 5
        thing.selector_prop = "b"
        thing.number_prop = -15  # simply override
        props = thing.read_multiple_properties(names=["selector_prop", "int_prop", "number_prop", "string_prop"])
        self.assertEqual(props["selector_prop"], "b")
        self.assertEqual(props["int_prop"], 5)
        self.assertEqual(props["number_prop"], -15)
        self.assertEqual(props["string_prop"], "foobar")

    def test_05_subscribe_event(self):
        """Test the subscription to an event on the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)

        results = []

        def cb(value: SSE):
            results.append(value)

        thing.subscribe_event("test_event", cb)
        time.sleep(1)  # wait for the subscription to be established

        thing.push_events()
        time.sleep(3)  # wait for the event to be pushed
        self.assertGreater(len(results), 0, "No events received")
        self.assertEqual(len(results), 100)
        thing.unsubscribe_event("test_event")

    def test_06_observe_properties(self):
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)

        # First check if an attribute is set on the object proxy
        self.assertIsNotNone(thing, "observable_list_prop_change_event")
        self.assertIsNotNone(thing, "observable_readonly_prop_change_event")

        # req 1 - observable events come due to writing a property
        propective_values = [
            [1, 2, 3, 4, 5],
            ["a", "b", "c", "d", "e"],
            [1, "a", 2, "b", 3],
        ]
        result = []
        attempt = 0

        def cb(value: SSE):
            nonlocal attempt, result
            self.assertEqual(value.data, propective_values[attempt])
            result.append(value)
            attempt += 1

        thing.observe_property("observable_list_prop", cb)
        time.sleep(3)
        # Calm down for event publisher to connect fully as there is no handshake for events
        for value in propective_values:
            thing.observable_list_prop = value

        for i in range(20):
            if attempt == len(propective_values):
                break
            # wait for the callback to be called
            time.sleep(0.1)
        thing.unobserve_property("observable_list_prop")

        for res in result:
            self.assertIn(res.data, propective_values)

        # # req 2 - observable events come due to reading a property
        propective_values = [1, 2, 3, 4, 5]
        result = []
        attempt = 0

        def cb(value: SSE):
            nonlocal attempt, result
            self.assertEqual(value.data, propective_values[attempt])
            result.append(value)
            attempt += 1

        thing.observe_property("observable_readonly_prop", cb)
        time.sleep(3)
        # Calm down for event publisher to connect fully as there is no handshake for events
        for _ in propective_values:
            thing.observable_readonly_prop  # read property through do notation access

        for i in range(20):
            if attempt == len(propective_values):
                break
            # wait for the callback to be called
            time.sleep(0.1)

        thing.unobserve_property("observable_readonly_prop")
        for res in result:
            self.assertIn(res.data, propective_values)


class TestRPCEndToEndAsync(AsyncTestCase):
    @classmethod
    def setUpClass(cls):
        cls.thing_id = f"test-thing-{uuid4().hex[:8]}"
        cls.server_id = cls.thing_id
        super().setUpClass()
        cls.setUpThing()

    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True)
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def tearDownClass(cls):
        cls._client = None
        cls.thing.rpc_server.stop()
        super().tearDownClass()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "IPC",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client

    async def test_01_creation_and_handshake(self):
        """Test the creation and handshake of the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        self.assertTrue(
            len(thing.properties) + len(thing.actions) + len(thing.events)
            >= len(self.thing_model["properties"]) + len(self.thing_model["actions"]) + len(self.thing_model["events"])
        )

    async def test_02_invoke_action(self):
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        self.assertEqual(
            await thing.async_invoke_action("action_echo", fake.text(max_nb_chars=100)),
            fake.last,
        )
        self.assertEqual(await thing.async_invoke_action("action_echo", fake.sentence()), fake.last)
        self.assertEqual(await thing.async_invoke_action("action_echo", fake.json()), fake.last)

    async def test_03_rwd_properties(self):
        """Test the read, write and delete of properties on the zmq object proxy client"""
        thing = self.get_client()
        self.assertIsInstance(thing, ObjectProxy)
        # Test read_property method
        self.assertIsInstance(await thing.async_read_property("number_prop"), (int, float))
        self.assertIsInstance(await thing.async_read_property("string_prop"), str)
        self.assertIn(
            await thing.async_read_property("selector_prop"),
            TestThing.selector_prop.objects,
        )
        # Test write_property method
        await thing.async_write_property("number_prop", fake.random_number())
        self.assertEqual(await thing.async_read_property("number_prop"), fake.last)
        await thing.async_write_property(
            "selector_prop",
            TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects) - 1)],
        )
        self.assertEqual(
            await thing.async_read_property("selector_prop"),
            TestThing.selector_prop.objects[fake.last],
        )
        await thing.async_write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]))
        self.assertEqual(await thing.async_read_property("observable_list_prop"), fake.last)
        # await complete_pending_tasks_in_current_loop_async()


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRPCEndToEnd))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRPCEndToEndAsync))
    return suite


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
