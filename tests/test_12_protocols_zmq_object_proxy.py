# only client side tests, server tests already carried out
import time, unittest, logging
from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy

try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import TestCase, TestRunner, fake, AsyncTestCase
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from utils import TestCase, TestRunner, fake, AsyncTestCase



class TestZMQObjectProxyClient(TestCase):
    """Test the zmq object proxy client"""
    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.setUpThing()

    @classmethod
    def setUpThing(self):
        """Set up the thing for the zmq object proxy client"""
        self.thing = TestThing(id="test-thing", log_level=logging.ERROR+10)
        self.thing.run_with_zmq_server(forked=True)
        self.thing_model = self.thing.get_thing_model(ignore_errors=True).json()


    def test_01_creation_and_handshake(self):
        """Test the creation and handshake of the zmq object proxy client"""
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)
        self.assertTrue(
                len(thing.properties) + len(thing.actions) + len(thing.events) >=
                len(self.thing_model["properties"]) + len(self.thing_model["actions"]) + len(self.thing_model["events"])
            )                
        
        
    def test_02_invoke_action(self):
        """Test the invocation of an action on the zmq object proxy client"""
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)  
        self.assertEqual(thing.invoke_action("action_echo", fake.text(max_nb_chars=100)), fake.last)
        self.assertEqual(thing.invoke_action("action_echo", fake.sentence()), fake.last)
        self.assertEqual(thing.invoke_action("action_echo", fake.json()), fake.last)
        self.assertEqual(thing.action_echo(fake.chrome()), fake.last)
        self.assertEqual(thing.action_echo(fake.sha256()), fake.last)
        self.assertEqual(thing.action_echo(fake.address()), fake.last)


    def test_03_rwd_properties(self):
        """Test the read, write and delete of properties on the zmq object proxy client"""
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)  
        # Test read_property method
        self.assertIsInstance(thing.read_property("number_prop"), (int, float))
        self.assertIsInstance(thing.read_property("string_prop"), str)
        self.assertIn(thing.read_property("selector_prop"), TestThing.selector_prop.objects)
        # Test write_property method
        thing.write_property("number_prop", fake.random_number())
        self.assertEqual(thing.read_property("number_prop"), fake.last)
        thing.write_property("selector_prop", TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects)-1)])
        self.assertEqual(thing.read_property("selector_prop"), TestThing.selector_prop.objects[fake.last])
        thing.write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]))
        self.assertEqual(thing.read_property("observable_list_prop"), fake.last)
        # Test read property through dot notation attribute access
        self.assertIsInstance(thing.number_prop, (int, float))
        self.assertIsInstance(thing.string_prop, str)
        self.assertIn(thing.selector_prop, TestThing.selector_prop.objects)
        # Test write property through dot notation attribute access
        thing.number_prop = fake.random_number()
        self.assertEqual(thing.number_prop, fake.last)
        thing.selector_prop = TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects)-1)]
        self.assertEqual(thing.selector_prop, TestThing.selector_prop.objects[fake.last])
        thing.observable_list_prop = fake.pylist(25, value_types=[int, float, str, bool])
        self.assertEqual(thing.observable_list_prop, fake.last)
        # Test one way write property
        thing.write_property("number_prop", fake.random_number(), oneway=True)
        self.assertEqual(thing.read_property("number_prop"), fake.last)
        thing.write_property("selector_prop", TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects)-1)], oneway=True)
        self.assertEqual(thing.read_property("selector_prop"), TestThing.selector_prop.objects[fake.last])
        thing.write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]), oneway=True)
        self.assertEqual(thing.read_property("observable_list_prop"), fake.last)
        # Test noblock read property
        # ...
        # Test noblock write property
        # ...

    def test_04_stop(self):
        """Test the stop of the zmq object proxy client"""
        self.thing.rpc_server.stop()       



class TestZMQObjectProxyClientAsync(AsyncTestCase):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.setUpThing()

    @classmethod
    def setUpThing(self):
        """Set up the thing for the zmq object proxy client"""
        self.thing = TestThing(id="test-thing", log_level=logging.ERROR+10)
        self.thing.run_with_zmq_server(forked=True)
        self.thing_model = self.thing.get_thing_model(ignore_errors=True).json()


    async def test_01_creation_and_handshake(self):
        """Test the creation and handshake of the zmq object proxy client"""
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)
        self.assertTrue(
                len(thing.properties) + len(thing.actions) + len(thing.events) >=
                len(self.thing_model["properties"]) + len(self.thing_model["actions"]) + len(self.thing_model["events"])
            )
        
    async def test_02_invoke_action(self):
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)  
        self.assertEqual(await thing.async_invoke_action("action_echo", fake.text(max_nb_chars=100)), fake.last)
        self.assertEqual(await thing.async_invoke_action("action_echo", fake.sentence()), fake.last)
        self.assertEqual(await thing.async_invoke_action("action_echo", fake.json()), fake.last)
       

    async def test_03_rwd_properties(self):
        """Test the read, write and delete of properties on the zmq object proxy client"""
        thing = ClientFactory.zmq("test-thing", "test-thing", "IPC")
        self.assertIsInstance(thing, ObjectProxy)  
        # Test read_property method
        self.assertIsInstance(await thing.async_read_property("number_prop"), (int, float))
        self.assertIsInstance(await thing.async_read_property("string_prop"), str)
        self.assertIn(await thing.async_read_property("selector_prop"), TestThing.selector_prop.objects)
        # Test write_property method
        await thing.async_write_property("number_prop", fake.random_number())
        self.assertEqual(await thing.async_read_property("number_prop"), fake.last)
        await thing.async_write_property("selector_prop", TestThing.selector_prop.objects[fake.random_int(0, len(TestThing.selector_prop.objects)-1)])
        self.assertEqual(await thing.async_read_property("selector_prop"), TestThing.selector_prop.objects[fake.last])
        await thing.async_write_property("observable_list_prop", fake.pylist(25, value_types=[int, float, str, bool]))
        self.assertEqual(await thing.async_read_property("observable_list_prop"), fake.last)
      


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQObjectProxyClient))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQObjectProxyClientAsync))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
    




