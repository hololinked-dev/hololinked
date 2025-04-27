import unittest
import logging
import warnings

from hololinked.server import Thing
from hololinked.server.schema_validators import JsonSchemaValidator, BaseSchemaValidator
from hololinked.server.serializers import JSONSerializer, PickleSerializer, MsgpackSerializer
from hololinked.server.utils import get_default_logger 
from hololinked.server.logger import RemoteAccessHandler
from hololinked.client import ObjectProxy
try:
    from .things import OceanOpticsSpectrometer, start_thing_forked
    from .utils import TestCase
except ImportError:
    from things import OceanOpticsSpectrometer, start_thing_forked
    from utils import TestCase


class TestThing(TestCase):
    """Test Thing class from hololinked.server.thing module."""
    
    @classmethod
    def setUpClass(self):
        print("test Thing init")
        self.thing_cls = Thing

    @classmethod
    def tearDownClass(self) -> None:
        print("tear down test Thing init")

    def test_1_instance_name(self):
        # instance name must be a string and cannot be changed after set
        thing = self.thing_cls(instance_name="test_instance_name", log_level=logging.WARN)
        self.assertEqual(thing.instance_name, "test_instance_name")
        with self.assertRaises(ValueError):
            thing.instance_name = "new_instance"
        with self.assertRaises(NotImplementedError):
            del thing.instance_name


    def test_2_logger(self):
        # logger must have remote access handler if logger_remote_access is True
        logger = get_default_logger("test_logger", log_level=logging.WARN)
        thing = self.thing_cls(instance_name="test_logger_remote_access", logger=logger, logger_remote_access=True)
        self.assertEqual(thing.logger, logger)
        self.assertTrue(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))

        # Therefore also check the false condition
        logger = get_default_logger("test_logger_2", log_level=logging.WARN)
        thing = self.thing_cls(instance_name="test_logger_without_remote_access", logger=logger, logger_remote_access=False)
        self.assertFalse(any(isinstance(handler, RemoteAccessHandler) for handler in thing.logger.handlers))
        # NOTE - logger is modifiable after instantiation 
        # What if user gives his own remote access handler?
        

    def test_3_JSON_serializer(self):
        # req 1 - if serializer is not provided, default is JSONSerializer and http and zmq serializers are same
        thing = self.thing_cls(instance_name="test_serializer_when_not_provided", log_level=logging.WARN)
        self.assertIsInstance(thing.zmq_serializer, JSONSerializer)
        self.assertEqual(thing.http_serializer, thing.zmq_serializer)

        # req 2 - similarly, serializer keyword argument creates same serialitzer for both zmq and http transports
        serializer = JSONSerializer()
        thing = self.thing_cls(instance_name="test_common_serializer", serializer=serializer, log_level=logging.WARN)
        self.assertEqual(thing.zmq_serializer, serializer)
        self.assertEqual(thing.http_serializer, serializer)

        # req 3 - serializer keyword argument must be JSONSerializer only, because this keyword should 
        # what is common to both zmq and http
        with self.assertRaises(TypeError) as ex:
            serializer = PickleSerializer()
            thing = self.thing_cls(instance_name="test_common_serializer_nonJSON", serializer=serializer, log_level=logging.WARN)
            self.assertTrue(str(ex), "serializer key word argument must be JSONSerializer")

        # req 4 - zmq_serializer and http_serializer is differently instantiated if zmq_serializer and http_serializer 
        # keyword arguments are provided, albeit the same serializer type
        serializer = JSONSerializer()
        thing = self.thing_cls(instance_name="test_common_serializer", zmq_serializer=serializer, log_level=logging.WARN)
        self.assertEqual(thing.zmq_serializer, serializer)
        self.assertNotEqual(thing.http_serializer, serializer) # OR, same as line below
        self.assertNotEqual(thing.http_serializer, thing.zmq_serializer)
        self.assertIsInstance(thing.http_serializer, JSONSerializer)
    

    def test_4_other_serializers(self):
        # req 1 - http_serializer cannot be anything except than JSON
        with self.assertRaises(ValueError) as ex:
            # currenty this has written this as ValueError although TypeError is more appropriate
            serializer = PickleSerializer()
            thing = self.thing_cls(instance_name="test_http_serializer_nonJSON", http_serializer=serializer, 
                        log_level=logging.WARN)
            self.assertTrue(str(ex), "invalid JSON serializer option")
        # test the same with MsgpackSerializer
        with self.assertRaises(ValueError) as ex:
            # currenty this has written this as ValueError although TypeError is more appropriate
            serializer = MsgpackSerializer()
            thing = self.thing_cls(instance_name="test_http_serializer_nonJSON", http_serializer=serializer, 
                        log_level=logging.WARN)
            self.assertTrue(str(ex), "invalid JSON serializer option")

        # req 2 - http_serializer and zmq_serializer can be different
        warnings.filterwarnings("ignore", category=UserWarning)
        http_serializer = JSONSerializer()
        zmq_serializer = PickleSerializer()
        thing = self.thing_cls(instance_name="test_different_serializers_1", http_serializer=http_serializer, 
                    zmq_serializer=zmq_serializer, log_level=logging.WARN)
        self.assertNotEqual(thing.http_serializer, thing.zmq_serializer)
        self.assertEqual(thing.http_serializer, http_serializer)
        self.assertEqual(thing.zmq_serializer, zmq_serializer)
        warnings.resetwarnings()

        # try the same with MsgpackSerializer
        http_serializer = JSONSerializer()
        zmq_serializer = MsgpackSerializer()
        thing = self.thing_cls(instance_name="test_different_serializers_2", http_serializer=http_serializer, 
                    zmq_serializer=zmq_serializer, log_level=logging.WARN)
        self.assertNotEqual(thing.http_serializer, thing.zmq_serializer)
        self.assertEqual(thing.http_serializer, http_serializer)
        self.assertEqual(thing.zmq_serializer, zmq_serializer)

        # req 3 - pickle serializer should raise warning
        http_serializer = JSONSerializer()
        zmq_serializer = PickleSerializer()
        with self.assertWarns(expected_warning=UserWarning): 
            thing = self.thing_cls(instance_name="test_pickle_serializer_warning", http_serializer=http_serializer, 
                    zmq_serializer=zmq_serializer, log_level=logging.WARN)


    def test_5_schema_validator(self):
        # schema_validator must be a class or subclass of BaseValidator
        validator = JsonSchemaValidator(schema=True)
        with self.assertRaises(ValueError):
            thing = self.thing_cls(instance_name="test_schema_validator_with_instance", schema_validator=validator)

        validator = JsonSchemaValidator
        thing = self.thing_cls(instance_name="test_schema_validator_with_subclass", schema_validator=validator,
                    log_level=logging.WARN)
        self.assertEqual(thing.schema_validator, validator)
       
        validator = BaseSchemaValidator
        thing = self.thing_cls(instance_name="test_schema_validator_with_subclass", schema_validator=validator,
                    log_level=logging.WARN)
        self.assertEqual(thing.schema_validator, validator)
       

    def test_6_state(self):
        # state property must be None when no state machine is present
        thing = self.thing_cls(instance_name="test_no_state_machine", log_level=logging.WARN)
        self.assertIsNone(thing.state)
        self.assertFalse(hasattr(thing, 'state_machine'))
        # detailed tests should be in another file
      
        
    def test_7_servers_init(self):
        # rpc_server, message_broker and event_publisher must be None when not run()
        thing = self.thing_cls(instance_name="test_servers_init", log_level=logging.WARN)
        self.assertIsNone(thing.rpc_server)
        self.assertIsNone(thing.message_broker)
        self.assertIsNone(thing.event_publisher)

    
    def test_8_resource_generation(self):
        # basic test only to make sure nothing is fundamentally wrong
        thing = self.thing_cls(instance_name="test_servers_init", log_level=logging.WARN)
        # thing._prepare_resources()
        self.assertIsInstance(thing.get_thing_description(), dict)
        self.assertIsInstance(thing.httpserver_resources, dict)
        self.assertIsInstance(thing.zmq_resources, dict)

        start_thing_forked(self.thing_cls, instance_name='test-gui-resource-generation', log_level=logging.WARN)
        thing_client = ObjectProxy('test-gui-resource-generation')
        self.assertIsInstance(thing_client.gui_resources, dict)
        thing_client.exit()



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
        thing = self.thing_cls(instance_name="test_state_machine", log_level=logging.WARN)
        self.assertIsNotNone(thing.state)
        self.assertTrue(hasattr(thing, 'state_machine'))
        # detailed tests should be in another file



if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner

    unittest.main(testRunner=TestRunner())
   
