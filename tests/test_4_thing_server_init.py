import unittest
import logging
import warnings

from hololinked.core import Thing
from hololinked.utils import get_default_logger 
from hololinked.core.logger import RemoteAccessHandler
from hololinked.client import ObjectProxy
try:
    from .things import OceanOpticsSpectrometer, start_thing_forked
    from .utils import TestCase
except ImportError:
    from things import OceanOpticsSpectrometer, start_thing_forked
    from utils import TestCase


class TestThing(TestCase):
    """Test Thing class from hololinked.core.thing module."""
    
    @classmethod
    def setUpClass(self):
        print("test Thing init")
        self.thing_cls = Thing

    @classmethod
    def tearDownClass(self) -> None:
        print("tear down test Thing init")


    def test_1_id(self):
        # instance name must be a string and cannot be changed after set
        thing = self.thing_cls(id="test_id", log_level=logging.WARN)
        self.assertEqual(thing.id, "test_id")
        with self.assertRaises(ValueError):
            thing.id = "new_instance"
        with self.assertRaises(NotImplementedError):
            del thing.id


    def test_2_logger(self):
        # logger must have remote access handler if logger_remote_access is True
        logger = get_default_logger("test_logger", log_level=logging.WARN)
        thing = self.thing_cls(id="test_logger_remote_access", logger=logger, logger_remote_access=True)
        self.assertEqual(thing.logger, logger)
        self.assertTrue(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))

        # Therefore also check the false condition
        logger = get_default_logger("test_logger_2", log_level=logging.WARN)
        thing = self.thing_cls(id="test_logger_without_remote_access", logger=logger, logger_remote_access=False)
        self.assertFalse(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        # NOTE - logger is modifiable after instantiation 
        # What if user gives his own remote access handler?
        

    def test_3_state(self):
        # state property must be None when no state machine is present
        thing = self.thing_cls(id="test_no_state_machine", log_level=logging.WARN)
        self.assertIsNone(thing.state)
        self.assertFalse(hasattr(thing, 'state_machine'))
        # detailed tests should be in another file
      
        
    def test_7_servers_init(self):
        # rpc_server, message_broker and event_publisher must be None when not run()
        thing = self.thing_cls(id="test_servers_init", log_level=logging.WARN)
        self.assertIsNone(thing.rpc_server)
        # self.assertIsNone(thing.message_broker)
        self.assertIsNone(thing.event_publisher)

    
    def test_8_resource_generation(self):
        pass
        # basic test only to make sure nothing is fundamentally wrong
        # thing = self.thing_cls(id="test_servers_init", log_level=logging.WARN)
        # self.assertIsInstance(thing.get_thing_description(), dict)
        # self.assertIsInstance(thing.get_our_temp_thing_description(), dict)
        # self.assertIsInstance(thing.httpserver_resources, dict)
        # self.assertIsInstance(thing.zmq_resources, dict)

        # start_thing_forked(self.thing_cls, id='test-gui-resource-generation', log_level=logging.WARN)
        # thing_client = ObjectProxy('test-gui-resource-generation')
        # self.assertIsInstance(thing_client.get_our_temp_thing_description(), dict)
        # thing_client.exit()



class TestOceanOpticsSpectrometer(TestThing):

    @classmethod
    def setUpClass(self):
        print("test OceanOpticsSpectrometer init")
        self.thing_cls = OceanOpticsSpectrometer

    @classmethod
    def tearDownClass(self) -> None:
        print("tear down test OceanOpticsSpectrometer init")

    def test_6_state(self):
        # req 1 - state property must be None when no state machine is present
        thing = self.thing_cls(id="test_state_machine", log_level=logging.WARN)
        self.assertIsNotNone(thing.state)
        self.assertTrue(hasattr(thing, 'state_machine'))
        # detailed tests should be in another file



if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner

    unittest.main(testRunner=TestRunner())
   
