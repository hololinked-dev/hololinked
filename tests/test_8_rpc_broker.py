import asyncio
import threading
import unittest
import zmq.asyncio
import jsonschema
import logging
import random

from hololinked.core.actions import BoundAction
from hololinked.core.property import Property
from hololinked.core.zmq.brokers import AsyncZMQClient, SyncZMQClient
from hololinked.core.zmq.message import EXIT, RequestMessage
from hololinked.core.zmq.rpc_server import RPCServer
from hololinked.server.zmq import ZMQServer
from hololinked.utils import get_current_async_loop
from hololinked.td import ActionAffordance, PropertyAffordance
from hololinked.client.zmq.consumed_interactions import ZMQAction, ZMQProperty, ZMQConsumedAffordanceMixin

try:
    from .test_5_brokers import TestBrokerMixin
    from .test_6_actions import replace_methods_with_actions
    from .utils import TestRunner
    from .things import run_thing_with_zmq_server_forked, test_thing_TD, TestThing
except ImportError:
    from test_5_brokers import TestBrokerMixin
    from test_6_actions import replace_methods_with_actions
    from utils import TestRunner
    from things import run_thing_with_zmq_server_forked, test_thing_TD, TestThing



data_structures = [
    {"key": "value"},
    [1, 2, 3], 
    "string", 
    42, 
    3.14, 
    True, 
    None,
    {"nested": {"key": "value"}},
    [{"list": "of"}, {"dicts": "here"}],
    {"complex": {"nested": {"list": [1, 2, 3]}, "mixed": [1, "two", 3.0, None]}},
    {"array": [1, 2, 3]}
] # to use for testing



class InteractionAffordanceMixin(TestBrokerMixin):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.setUpActions()
        self.setUpProperties()
        
    @classmethod
    def setUpActions(self):
        self.action_echo = ZMQAction(
                                resource=ActionAffordance.from_TD('action_echo', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )
    
        self.get_serialized_data_action = ZMQAction(
                                resource=ActionAffordance.from_TD('get_serialized_data', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )
        
        self.sleep_action = ZMQAction(
                                resource=ActionAffordance.from_TD('sleep', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )

        self.get_mixed_content_data_action = ZMQAction(
                        resource= ActionAffordance.from_TD('get_mixed_content_data', test_thing_TD),
                        sync_client=self.sync_client,
                        async_client=self.async_client, 
                        invokation_timeout=5, 
                        execution_timeout=5, 
                        schema_validator=None
                    )
    
    @classmethod
    def setUpProperties(self):
        self.test_prop = ZMQProperty(
                                resource=PropertyAffordance.from_TD('base_property', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )



class TestInprocRPCServer(InteractionAffordanceMixin):

    @classmethod
    def setUpThing(self):
        replace_methods_with_actions(TestThing)
        super().setUpThing()
        
    @classmethod
    def setUpServer(self):
        self.server = RPCServer(
                            id=self.server_id,
                            things=[self.thing],
                            logger=self.logger,
                            context=self.context
                        )

    @classmethod
    def setUpClient(self):
        self.async_client = AsyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                context=self.context,
                                handshake=False,
                                transport='INPROC'
                            )
        self.sync_client = SyncZMQClient(
                                id=self.client_id+'-sync',
                                server_id=self.server_id,
                                logger=self.logger,
                                context=self.context,
                                handshake=False,
                                transport='INPROC'
                            ) 
        self.client = self.async_client
    
        
    @classmethod
    def startServer(self):
        self._server_thread = threading.Thread(
                                            target=self.server.run, 
                                            daemon=False # to test exit daemon must be False
                                        )
        self._server_thread.start()
   
    @classmethod
    def setUpClass(self):
        self.context = zmq.asyncio.Context()
        super().setUpClass()
        print(f"test ZMQ RPC Server {self.__name__}")

    
    def test_1_creation_defaults(self):
        self.assertTrue(self.server.req_rep_server.socket_address.startswith('inproc://'))
        self.assertTrue(self.server.event_publisher.socket_address.startswith('inproc://'))


    def test_2_handshake(self):
        self.client.handshake()
        async def async_handshake():
            self.async_client.handshake()
            await self.async_client.handshake_complete()
        get_current_async_loop().run_until_complete(async_handshake()) 


    def test_3_action_abstractions(self):
        """"Test if action can be invoked by a client"""
        
        async def test_basic_operations():
            """Test if action can be invoked by a client in basic request/response way, oneway and no block"""
            nonlocal self
            await self.action_echo.async_call('value')
            self.action_echo.oneway(5)
            noblock_msg_id = self.action_echo.noblock(10)
            self.assertEqual(self.action_echo.last_return_value, 'value')
            # test the responses for no block call, so read the socket - but, this is usually abstracte in a higher level API
            response = self.action_echo._zmq_client.recv_response(noblock_msg_id)
            self.action_echo._last_zmq_response = response
            self.assertEqual(self.action_echo.last_return_value, 10)
            self.assertEqual(self.action_echo(2), 2)

        get_current_async_loop().run_until_complete(test_basic_operations())
        self.client.handshake() 

        async def test_operations_thorough():
            # Generate 20 random JSON serializable data structures
            nonlocal self
            global data_structures

            msg_ids = [None for i in range(len(data_structures))]
            last_call_type = None
            # Randomize calls to self.action_echo
            for index, data in enumerate(data_structures):
                call_type = random.choice(["async_call", "plain_call", "oneway", "noblock"])
                if call_type == "async_call":
                    result = await self.action_echo.async_call(data)
                    self.assertEqual(result, data)
                elif call_type == "plain_call":
                    result = self.action_echo(data)
                    self.assertEqual(result, data)
                elif call_type == "oneway":
                    self.action_echo.oneway(data)
                    self.assertNotEqual(data, self.action_echo.last_return_value)
                elif call_type == "noblock":
                    msg_ids[index] = self.action_echo.noblock(data)
                    self.assertNotEqual(data, self.action_echo.last_return_value)

                # print("last_call_type", last_call_type, "call_type", call_type, "data", data)
                if last_call_type == "noblock":
                    response = self.action_echo._zmq_client.recv_response(msg_ids[index-1])
                    self.action_echo._last_zmq_response = response
                    self.assertEqual(self.action_echo.last_return_value, data_structures[index-1])
                    
                last_call_type = call_type

        get_current_async_loop().run_until_complete(test_operations_thorough())
        self.client.handshake() 


    def test_4_property_abstractions(self):
        """Test if property can be invoked by a client"""

        def test_basic_operations():
            nonlocal self
            self.test_prop.set(100)
            self.assertEqual(self.test_prop.get(), 100)
            self.test_prop.oneway_set(200)
            self.assertEqual(self.test_prop.get(), 200)

            async def test_async_property_abstractions():
                nonlocal self
                await self.test_prop.async_set(300)
                self.assertEqual(self.test_prop.get(), 300)
                await self.test_prop.async_set(0)
                self.assertEqual(await self.test_prop.async_get(), 0)

            get_current_async_loop().run_until_complete(test_async_property_abstractions())
        
        test_basic_operations()
        self.client.handshake()

        async def test_operations_thorough():
            # Generate 20 random JSON serializable data structures
            nonlocal self
            global data_structures

            msg_ids = [None for i in range(len(data_structures))]
            last_call_type = None
            # Randomize calls to self.action_echo
            for index, data in enumerate(data_structures):
                call_type = random.choice(["async_set", "set", "oneway_set", "noblock_get"])
                if call_type == "async_set":
                    self.assertIsNone(await self.test_prop.async_set(data))
                    self.assertEqual(await self.test_prop.async_get(), data)
                elif call_type == "set":
                    self.assertIsNone(self.test_prop.set(data))
                    self.assertEqual(self.test_prop.get(), data)
                elif call_type == "oneway_set":
                    self.assertIsNone(self.test_prop.oneway_set(data))
                    self.assertNotEqual(data, self.test_prop.last_read_value)
                    self.assertEqual(data, self.test_prop.get()) 
                    # for one way calls as well, get() will return the latest value 
                elif call_type == "noblock_get":
                    msg_ids[index] = self.test_prop.noblock_get()
                    self.assertNotEqual(data, self.test_prop.last_read_value)
                    
                #  print("last_call_type", last_call_type, "call_type", call_type, "data", data)
                if last_call_type == "noblock":
                    response = self.test_prop._zmq_client.recv_response(msg_ids[index-1])
                    self.test_prop._last_zmq_response = response
                    self.assertEqual(self.test_prop.last_read_value, data_structures[index-1])
                    
                last_call_type = call_type
        
        get_current_async_loop().run_until_complete(test_operations_thorough())
        self.client.handshake()


    def test_5_thing_execution_context(self):
        """Test if thing execution context is used correctly"""
        old_thing_execution_context = self.action_echo._thing_execution_context
        self.action_echo._thing_execution_context = dict(fetch_execution_logs=True)
        get_current_async_loop().run_until_complete(self.action_echo.async_call('value'))
        self.assertIsInstance(self.action_echo.last_return_value, dict)
        self.assertFalse(self.action_echo.last_return_value == 'value')
        self.assertTrue(
                    'execution_logs' in self.action_echo.last_return_value.keys() and 
                    'return_value' in self.action_echo.last_return_value.keys()    
                )
        self.assertTrue(len(self.action_echo.last_return_value) == 2)
        self.action_echo._thing_execution_context = old_thing_execution_context


    def test_6_server_execution_context(self):
        """Test if server execution context is used correctly"""
        async def test_execution_timeout():
            try:
                await self.sleep_action.async_call()
            except Exception as ex:
                self.assertIsInstance(ex, TimeoutError)
                self.assertIn('Execution timeout occured', str(ex))
            else:
                self.assertTrue(False) # fail the test if reached here
        get_current_async_loop().run_until_complete(test_execution_timeout())
       
        async def test_invokation_timeout():
            try:
                old_timeout = self.sleep_action._invokation_timeout
                self.sleep_action._invokation_timeout = 1
                await self.sleep_action.async_call()
            except Exception as ex:
                self.assertIsInstance(ex, TimeoutError)
                self.assertIn('Invokation timeout occured', str(ex))
                self.sleep_action._invokation_timeout = old_timeout
            else:
                self.assertTrue(False) # fail the test if reached here
        get_current_async_loop().run_until_complete(test_invokation_timeout())


    # def test_4_return_binary_value(self):

    #     async def async_call():
    #         await self.get_mixed_content_data_action.async_call()
    #         return self.get_mixed_content_data_action.last_return_value
    #     result = get_current_async_loop().run_until_complete(async_call())
    #     self.assertEqual(result, ('foobar', b'foobar'))

    #     async def async_call():
    #         await self.get_serialized_data_action.async_call()
    #         return self.get_serialized_data_action.last_return_value
    #     result = get_current_async_loop().run_until_complete(async_call())
    #     self.assertEqual(result, b'foobar')


    def test_7_stop(self):
        self.server.stop()
       
        

class TestRPCServer(TestInprocRPCServer):

    @classmethod
    def setUpServer(self):
        self.server = ZMQServer(
                            id=self.server_id,
                            things=[self.thing],
                            logger=self.logger,
                            context=self.context,
                            transports=['INPROC', 'IPC', 'TCP'],
                            tcp_socket_address='tcp://*:59000'
                        )
        

    @classmethod
    def setUpClient(self):
        super().setUpClient()
        self.inproc_client = self.client 
        self.ipc_client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='IPC'
                            )
        self.tcp_client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='TCP',
                                tcp_socket_address='tcp://localhost:59000'
                            )


    @classmethod
    def setUpActions(self):
        super().setUpActions()
        self.action_echo._zmq_client = self.ipc_client
        self.get_serialized_data_action._zmq_client = self.ipc_client
        self.get_mixed_content_data_action._zmq_client = self.ipc_client
        self.sleep_action._zmq_client = self.ipc_client


    def test_1_creation_defaults(self):
        super().test_1_creation_defaults()
        self.assertTrue(self.server.ipc_server.socket_address.startswith('ipc://'))
        self.assertTrue(self.server.tcp_server.socket_address.startswith('tcp://'))
        self.assertTrue(self.server.tcp_server.socket_address.endswith(':59000'))


    def test_2_handshake(self):
        super().test_2_handshake()
        self.ipc_client.handshake()    
        self.tcp_client.handshake()


    def test_3_action_abstractions(self):
        old_client = self.action_echo._zmq_client
        for client in [self.tcp_client, self.ipc_client]:
            self.action_echo._zmq_client = client
            super().test_3_action_abstractions()
        self.action_echo._zmq_client = old_client

    
    def test_4_property_abstractions(self):
        old_client = self.test_prop._zmq_client
        for client in [self.tcp_client, self.ipc_client]:
            self.test_prop._zmq_client = client
            super().test_4_property_abstractions()
        self.test_prop._zmq_client = old_client

    # def test_4_return_binary_value(self):
    #     super().test_4_return_binary_value()
    #     old_client = self.sleep_action._zmq_client
    #     for client in [self.tcp_client, self.ipc_client]:
    #         self.sleep_action._zmq_client = client
    #         return_value = self.get_mixed_content_data_action()
    #         self.assertEqual(return_value, ('foobar', b'foobar'))
    #         return_value = self.get_serialized_data_action()
    #         self.assertEqual(return_value, b'foobar')
    #     self.sleep_action._zmq_client = old_client


    def test_6_server_execution_context(self):
        super().test_6_server_execution_context()
        # test oneway action
        old_client = self.sleep_action._zmq_client
        for client in [self.tcp_client, self.ipc_client]:
            self.action_echo._zmq_client = client
            self.action_echo('ipc_value_2')
            self.assertEqual(self.action_echo.last_return_value, 'ipc_value_2')
            self.action_echo.oneway('ipc_value_3')
            self.assertEqual(self.action_echo.last_return_value, 'ipc_value_2')
            return_value = self.action_echo('ipc_value_4')
            self.assertEqual(return_value, 'ipc_value_4')        
        self.sleep_action._zmq_client = old_client



class TestExposedActions(InteractionAffordanceMixin):


    @classmethod
    def setUpClient(self):
        super().setUpClient()
        self.server_id = 'test-action'
        self.sync_client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        self.client = self.sync_client


    def test_7_exposed_actions(self):
        """Test if actions can be invoked by a client"""
        run_thing_with_zmq_server_forked(
            thing_cls=TestThing, 
            id='test-action', 
            log_level=logging.ERROR+10, 
            done_queue=self.done_queue,
            prerun_callback=replace_methods_with_actions,
        )
        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # thing_client = ObjectProxy('test-action', log_level=logging.ERROR) # type: TestThing
        assert isinstance(thing.action_echo, BoundAction) # type definition
        action_echo = ZMQAction(
            resource=thing.action_echo.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo(1), 1)
        
        assert isinstance(thing.action_echo_with_classmethod, BoundAction) # type definition
        action_echo_with_classmethod = ZMQAction(
            resource=thing.action_echo_with_classmethod.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_with_classmethod(2), 2)

        assert isinstance(thing.action_echo_async, BoundAction) # type definition
        action_echo_async = ZMQAction(
            resource=thing.action_echo_async.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_async("string"), "string")

        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction) # type definition
        action_echo_async_with_classmethod = ZMQAction(
            resource=thing.action_echo_async_with_classmethod.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_async_with_classmethod([1, 2]), [1, 2])

        assert isinstance(thing.parameterized_action, BoundAction) # type definition
        parameterized_action = ZMQAction(
            resource=thing.parameterized_action.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(parameterized_action(arg1=1, arg2='hello', arg3=5), ['test-action', 1, 'hello', 5])

        assert isinstance(thing.parameterized_action_async, BoundAction) # type definition
        parameterized_action_async = ZMQAction(
            resource=thing.parameterized_action_async.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(parameterized_action_async(arg1=2.5, arg2='hello', arg3='foo'), ['test-action', 2.5, 'hello', 'foo'])

        assert isinstance(thing.parameterized_action_without_call, BoundAction) # type definition
        parameterized_action_without_call = ZMQAction(
            resource=thing.parameterized_action_without_call.to_affordance(),
            sync_client=self.client
        )
        with self.assertRaises(NotImplementedError) as ex:
            parameterized_action_without_call(arg1=2, arg2='hello', arg3=5)
        self.assertTrue(str(ex.exception).startswith("Subclasses must implement __call__"))

        
    def test_8_schema_validation(self):
        """Test if schema validation is working correctly"""
        self._test_8_json_schema_validation()
        self._test_8_pydantic_validation()

    
    def _test_8_json_schema_validation(self):

        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # JSON schema validation
        assert isinstance(thing.json_schema_validated_action, BoundAction) # type definition
        action_affordance = thing.json_schema_validated_action.to_affordance()
        json_schema_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=self.client
        )
        # data with invalid schema 
        with self.assertRaises(Exception) as ex1:
            json_schema_validated_action(val1='1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex1.exception).startswith("'1' is not of type 'integer'"))
        with self.assertRaises(Exception) as ex2:
            json_schema_validated_action('1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex2.exception).startswith("'1' is not of type 'integer'"))
        with self.assertRaises(Exception) as ex3:
            json_schema_validated_action(1, 2, val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex3.exception).startswith("2 is not of type 'string'"))
        with self.assertRaises(Exception) as ex4:
            json_schema_validated_action(1, 'hello', val3='field', val4=[])
        self.assertTrue(str(ex4.exception).startswith("'field' is not of type 'object'"))
        with self.assertRaises(Exception) as ex5:
            json_schema_validated_action(1, 'hello', val3={'field' : 'value'}, val4='[]')
        self.assertTrue(str(ex5.exception).startswith("'[]' is not of type 'array'"))
        # data with valid schema
        return_value = json_schema_validated_action(val1=1, val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertEqual(return_value, {'val1': 1, 'val3': {'field': 'value'}})
        jsonschema.Draft7Validator(action_affordance.output).validate(return_value)


    def _test_8_pydantic_validation(self):

        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # Pydantic schema validation
        assert isinstance(thing.pydantic_validated_action, BoundAction) # type definition
        action_affordance = thing.pydantic_validated_action.to_affordance()
        pydantic_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=self.client
        )
        # data with invalid schema
        with self.assertRaises(Exception) as ex1:
            pydantic_validated_action(val1='1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex1.exception) and 
            'val1' in str(ex1.exception) and 'val2' not in str(ex1.exception) and 'val3' not in str(ex1.exception) and 
            'val4' not in str(ex1.exception)
        ) # {obj.name}_input is the pydantic model name
        with self.assertRaises(Exception) as ex2:
            pydantic_validated_action('1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex2.exception) and 
            'val1' in str(ex2.exception) and 'val2' not in str(ex2.exception) and 'val3' not in str(ex2.exception) and
            'val4' not in str(ex2.exception)
        )
        with self.assertRaises(Exception) as ex3:
            pydantic_validated_action(1, 2, val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex3.exception) and 
            'val1' not in str(ex3.exception) and 'val2' in str(ex3.exception) and 'val3' not in str(ex3.exception) and
            'val4' not in str(ex3.exception)           
        )
        with self.assertRaises(Exception) as ex4:
            pydantic_validated_action(1, 'hello', val3='field', val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex4.exception) and 
            'val1' not in str(ex4.exception) and 'val2' not in str(ex4.exception) and 'val3' in str(ex4.exception) and
            'val4' not in str(ex4.exception)            
        )
        with self.assertRaises(Exception) as ex5:
            pydantic_validated_action(1, 'hello', val3={'field' : 'value'}, val4='[]')
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex5.exception) and 
            'val1' not in str(ex5.exception) and 'val2' not in str(ex5.exception) and 'val3' not in str(ex5.exception) and
            'val4' in str(ex5.exception)
        )
        # data with valid schema
        return_value = pydantic_validated_action(val1=1, val2='hello', val3={'field' : 'value'}, val4=[])        
        self.assertEqual(return_value, {'val2': 'hello', 'val4': []})


    def test_9_exit(self):
        exit_message = RequestMessage.craft_with_message_type(
            sender_id='test-action-client', 
            receiver_id='test-action',
            message_type=EXIT
        )
        self.client.socket.send_multipart(exit_message.byte_array)

        self.assertEqual(self.done_queue.get(), 'test-action')
        


class TestExposedProperties(InteractionAffordanceMixin):

    @classmethod
    def setUpClient(self):
        super().setUpClient()
        self.server_id = 'test-property'
        self.sync_client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        self.client = self.sync_client


    def test_6_property_abstractions(self):
  
        run_thing_with_zmq_server_forked(
            thing_cls=TestThing, 
            id='test-property', 
            log_level=logging.ERROR+10, 
            done_queue=self.done_queue,
        )
        thing = TestThing(id='test-property', log_level=logging.ERROR)
        self.client.handshake()

        descriptor = thing.properties['number_prop']
        assert isinstance(descriptor, Property) # type definition
        number_prop = ZMQProperty(
            resource=descriptor.to_affordance(thing),
            sync_client=self.client
        )
        self.assertEqual(number_prop.get(), descriptor.default)
        number_prop.set(100)
        self.assertEqual(number_prop.get(), 100)
        number_prop.oneway_set(200)
        self.assertEqual(number_prop.get(), 200)

        async def test_6_async_property_abstractions(self: "TestThing"):
            nonlocal number_prop
            async_client = AsyncZMQClient(
                                id='test-property-async-client',
                                server_id='test-property', 
                                log_level=logging.ERROR, 
                                handshake=False
                            )
            number_prop._async_zmq_client = async_client
            async_client.handshake()
            await async_client.handshake_complete()
            await number_prop.async_set(300)
            self.assertEqual(number_prop.get(), 300)
            await number_prop.async_set(0)
            self.assertEqual(await number_prop.async_get(), 0)

        get_current_async_loop().run_until_complete(test_6_async_property_abstractions(self))


    def test_9_exit(self):
        exit_message = RequestMessage.craft_with_message_type(
            sender_id='test-property-client', 
            receiver_id='test-property',
            message_type=EXIT
        )
        self.client.socket.send_multipart(exit_message.byte_array)

        self.assertEqual(self.done_queue.get(), 'test-property')



def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestInprocRPCServer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRPCServer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestExposedActions))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestExposedProperties))
    return suite
        


if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))