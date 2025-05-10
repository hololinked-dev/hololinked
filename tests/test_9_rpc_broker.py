import asyncio
import threading
import unittest
import zmq.asyncio
import jsonschema
import logging
import random
import time

from hololinked.core.actions import BoundAction
from hololinked.core.property import Property
from hololinked.core.thing import Thing
from hololinked.core.zmq.brokers import AsyncZMQClient, EventConsumer, SyncZMQClient
from hololinked.core.zmq.message import EXIT, RequestMessage
from hololinked.core.zmq.rpc_server import RPCServer
from hololinked.server.zmq import ZMQServer
from hololinked.td.utils import get_zmq_unique_identifier_from_event_affordance
from hololinked.utils import get_all_sub_things_recusively, get_current_async_loop
from hololinked.td import ActionAffordance, PropertyAffordance, EventAffordance
from hololinked.client.zmq.consumed_interactions import ZMQAction, ZMQProperty, ZMQEvent

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
        self.setUpEvents()
        
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
    
        self.action_get_serialized_data = ZMQAction(
                                resource=ActionAffordance.from_TD('get_serialized_data', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )
        
        self.action_sleep = ZMQAction(
                                resource=ActionAffordance.from_TD('sleep', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )

        self.action_get_mixed_content_data = ZMQAction(
                                resource= ActionAffordance.from_TD('get_mixed_content_data', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )
        self.action_push_events = ZMQAction(
                                resource=ActionAffordance.from_TD('push_events', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client,
                                invokation_timeout=5,
                                execution_timeout=5,
                                schema_validator=None
                            )
    
    @classmethod
    def setUpProperties(self):
        self.base_property = ZMQProperty(
                                resource=PropertyAffordance.from_TD('base_property', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client, 
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                schema_validator=None
                            )
        self.total_number_of_events = ZMQProperty(
                                resource=PropertyAffordance.from_TD('total_number_of_events', test_thing_TD),
                                sync_client=self.sync_client,
                                async_client=self.async_client,
                                invokation_timeout=5,
                                execution_timeout=5,
                                schema_validator=None
                            )      
    
    @classmethod
    def setUpEvents(self):
        self.test_event = ZMQEvent(
                                resource=EventAffordance.from_TD('test_event', test_thing_TD),
                                sync_zmq_client=None
                            )
       


class TestRPCServerMixin(InteractionAffordanceMixin):

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



class TestInprocRPCServer(TestRPCServerMixin):
    
    def test_1_creation_defaults(self):
        """test server configuration defaults"""
        self.assertTrue(self.server.req_rep_server.socket_address.startswith('inproc://'))
        self.assertTrue(self.server.event_publisher.socket_address.startswith('inproc://'))

        self.assertTrue(self.thing.rpc_server, self.server)
        self.assertTrue(self.thing.event_publisher, self.server.event_publisher)


    def test_2_handshake(self):
        """test handshake mechanisms"""
        self.sync_client.handshake()
        async def async_handshake():
            self.async_client.handshake()
            await self.async_client.handshake_complete()
        get_current_async_loop().run_until_complete(async_handshake()) 


    def test_3_action_abstractions(self):
        """"test if action can be invoked by a client"""
        
        async def test_basic_operations():
            """Test if action can be invoked by a client in basic request/response way, oneway and no block"""
            nonlocal self
            await self.action_echo.async_call('value')
            self.action_echo.oneway(5)
            noblock_msg_id = self.action_echo.noblock(10)
            self.assertEqual(self.action_echo.last_return_value, 'value')
            # test the responses for no block call, so read the socket - but, this is usually abstracte in a higher level API
            response = self.action_echo._sync_zmq_client.recv_response(noblock_msg_id)
            self.action_echo._last_zmq_response = response
            self.assertEqual(self.action_echo.last_return_value, 10)
            self.assertEqual(self.action_echo(2), 2)

        get_current_async_loop().run_until_complete(test_basic_operations())
        self.sync_client.handshake() 

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
                    response = self.action_echo._sync_zmq_client.recv_response(msg_ids[index-1])
                    self.action_echo._last_zmq_response = response
                    self.assertEqual(self.action_echo.last_return_value, data_structures[index-1])
                    
                last_call_type = call_type

        get_current_async_loop().run_until_complete(test_operations_thorough())
        self.sync_client.handshake() 


    def test_4_property_abstractions(self):
        """Test if property can be invoked by a client"""

        def test_basic_operations():
            nonlocal self
            self.base_property.set(100)
            self.assertEqual(self.base_property.get(), 100)
            self.base_property.oneway_set(200)
            self.assertEqual(self.base_property.get(), 200)

            async def test_async_property_abstractions():
                nonlocal self
                await self.base_property.async_set(300)
                self.assertEqual(self.base_property.get(), 300)
                await self.base_property.async_set(0)
                self.assertEqual(await self.base_property.async_get(), 0)

            get_current_async_loop().run_until_complete(test_async_property_abstractions())
        
        test_basic_operations()
        self.sync_client.handshake()

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
                    self.assertIsNone(await self.base_property.async_set(data))
                    self.assertEqual(await self.base_property.async_get(), data)
                elif call_type == "set":
                    self.assertIsNone(self.base_property.set(data))
                    self.assertEqual(self.base_property.get(), data)
                elif call_type == "oneway_set":
                    self.assertIsNone(self.base_property.oneway_set(data))
                    self.assertNotEqual(data, self.base_property.last_read_value)
                    self.assertEqual(data, self.base_property.get()) 
                    # for one way calls as well, get() will return the latest value 
                elif call_type == "noblock_get":
                    msg_ids[index] = self.base_property.noblock_get()
                    self.assertNotEqual(data, self.base_property.last_read_value)
                    
                #  print("last_call_type", last_call_type, "call_type", call_type, "data", data)
                if last_call_type == "noblock":
                    response = self.base_property._sync_zmq_client.recv_response(msg_ids[index-1])
                    self.base_property._last_zmq_response = response
                    self.assertEqual(self.base_property.last_read_value, data_structures[index-1])
                    
                last_call_type = call_type
        
        get_current_async_loop().run_until_complete(test_operations_thorough())
        self.sync_client.handshake()


    def test_5_thing_execution_context(self):
        """test if thing execution context is used correctly"""
        old_thing_execution_context = self.action_echo._thing_execution_context
        # Only fetch_execution_logs currently supported
        self.action_echo._thing_execution_context = dict(fetch_execution_logs=True)
        get_current_async_loop().run_until_complete(self.action_echo.async_call('value'))
        self.assertIsInstance(self.action_echo.last_return_value, dict)
        self.assertTrue('execution_logs' in self.action_echo.last_return_value.keys())
        self.assertTrue('return_value' in self.action_echo.last_return_value.keys())
        self.assertTrue(len(self.action_echo.last_return_value) == 2)
        self.assertFalse(self.action_echo.last_return_value == 'value') # because its a dict now
        self.assertIsInstance(self.action_echo.last_return_value['execution_logs'], list)
        self.assertTrue(self.action_echo.last_return_value['return_value'] == 'value')
        self.action_echo._thing_execution_context = old_thing_execution_context


    def test_6_server_execution_context(self):
        """test if server execution context is used correctly"""
        async def test_execution_timeout():
            try:
                await self.action_sleep.async_call()
            except Exception as ex:
                self.assertIsInstance(ex, TimeoutError)
                self.assertIn('Execution timeout occured', str(ex))
            else:
                self.assertTrue(False) # fail the test if reached here
        get_current_async_loop().run_until_complete(test_execution_timeout())
       
        async def test_invokation_timeout():
            try:
                old_timeout = self.action_sleep._invokation_timeout
                self.action_sleep._invokation_timeout = 0.1 # reduce the value to test timeout
                await self.action_sleep.async_call()
            except Exception as ex:
                self.assertIsInstance(ex, TimeoutError)
                self.assertIn('Invokation timeout occured', str(ex))
            else:
                self.assertTrue(False) # fail the test if reached here
            finally:
                self.action_sleep._invokation_timeout = old_timeout

        get_current_async_loop().run_until_complete(test_invokation_timeout())


    def test_7_binary_payloads(self):
        """test if binary payloads are handled correctly"""
        self.assertEqual(self.action_get_mixed_content_data(), ('foobar', b'foobar'))
        self.assertEqual(self.action_get_serialized_data(), b'foobar')

        async def async_call():
            await self.action_get_mixed_content_data.async_call()
            return self.action_get_mixed_content_data.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, ('foobar', b'foobar'))

        async def async_call():
            await self.action_get_serialized_data.async_call()
            return self.action_get_serialized_data.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, b'foobar')


    def test_8_stop(self):
        """test if server can be stopped"""
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
        self.sync_ipc_client = SyncZMQClient(
                                id=self.client_id+"-sync", 
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='IPC'
                            )
        self.sync_tcp_client = SyncZMQClient(
                                id=self.client_id+"-sync",
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='TCP',
                                socket_address='tcp://localhost:59000'
                            )
        self.async_ipc_client = AsyncZMQClient(
                                id=self.client_id+"-async", 
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='IPC'
                            )
        self.async_tcp_client = AsyncZMQClient(
                                id=self.client_id+"-async",
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False,
                                transport='TCP',
                                socket_address='tcp://localhost:59000'
                            )


    def test_1_creation_defaults(self):
        super().test_1_creation_defaults()
        # check socket creation defaults
        self.assertTrue(self.server.ipc_server.socket_address.startswith('ipc://'))
        self.assertTrue(self.server.tcp_server.socket_address.startswith('tcp://'))
        self.assertTrue(self.server.tcp_server.socket_address.endswith(':59000'))

        
    def test_2_handshake(self):
        super().test_2_handshake()
        self.sync_ipc_client.handshake()    
        self.sync_tcp_client.handshake()
        async def async_handshake():
            self.async_ipc_client.handshake()
            await self.async_ipc_client.handshake_complete()
            self.async_tcp_client.handshake()
            await self.async_tcp_client.handshake_complete()
        get_current_async_loop().run_until_complete(async_handshake())


    def test_3_action_abstractions(self):
        old_sync_client = self.action_echo._sync_zmq_client
        old_async_client = self.action_echo._async_zmq_client
        for clients in [(self.sync_tcp_client, self.async_tcp_client), (self.sync_ipc_client, self.async_ipc_client)]:
            self.action_echo._sync_zmq_client, self.action_echo._async_zmq_client = clients
            super().test_3_action_abstractions()
        self.action_echo._sync_zmq_client = old_sync_client
        self.action_echo._async_zmq_client = old_async_client

    
    def test_4_property_abstractions(self):
        old_sync_client = self.base_property._sync_zmq_client
        old_async_client = self.base_property._async_zmq_client
        for clients in [(self.sync_tcp_client, self.async_tcp_client), (self.sync_ipc_client, self.async_ipc_client)]:
            self.base_property._sync_zmq_client, self.base_property._async_zmq_client = clients
            super().test_4_property_abstractions()
        self.base_property._sync_zmq_client = old_sync_client
        self.base_property._async_zmq_client = old_async_client


    def test_5_thing_execution_context(self):
        old_sync_client = self.action_echo._sync_zmq_client
        old_async_client = self.action_echo._async_zmq_client
        for clients in [(self.sync_tcp_client, self.async_tcp_client), (self.sync_ipc_client, self.async_ipc_client)]:
            self.action_echo._sync_zmq_client, self.action_echo._async_zmq_client = clients
            super().test_5_thing_execution_context()
        self.action_echo._sync_zmq_client = old_sync_client
        self.action_echo._async_zmq_client = old_async_client


    def test_6_server_execution_context(self):
        old_sync_client = self.action_sleep._sync_zmq_client
        old_async_client = self.action_sleep._async_zmq_client
        for clients in [(self.sync_tcp_client, self.async_tcp_client), (self.sync_ipc_client, self.async_ipc_client)]:
            self.action_sleep._sync_zmq_client, self.action_sleep._async_zmq_client = clients
            super().test_6_server_execution_context()
        self.action_sleep._sync_zmq_client = old_sync_client
        self.action_sleep._async_zmq_client = old_async_client

    
    def test_7_binary_payloads(self):
        for clients in [(self.sync_tcp_client, self.async_tcp_client), (self.sync_ipc_client, self.async_ipc_client)]:
            for action in [self.action_get_serialized_data, self.action_get_mixed_content_data]:
                action._sync_zmq_client, action._async_zmq_client = clients
            super().test_7_binary_payloads()
            


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


    def test_1_exposed_actions(self):
        """
        Now that actions can be invoked by a client, test different types of actions
        and their behaviors
        """
        run_thing_with_zmq_server_forked(
            thing_cls=TestThing, 
            id='test-action', 
            log_level=logging.ERROR+10, 
            done_queue=self.done_queue,
            prerun_callback=replace_methods_with_actions,
        )
        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.sync_client.handshake()

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

        
    def test_2_schema_validation(self):
        """Test if schema validation is working correctly"""
        self._test_2_json_schema_validation()
        self._test_2_pydantic_validation()

    
    def _test_2_json_schema_validation(self):

        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.sync_client.handshake()

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


    def _test_2_pydantic_validation(self):

        thing = TestThing(id='test-action', log_level=logging.ERROR)
        self.sync_client.handshake()

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


    def test_3_exit(self):
        """Exit the server"""
        exit_message = RequestMessage.craft_with_message_type(
            sender_id='test-action-client', 
            receiver_id='test-action',
            message_type=EXIT
        )
        self.sync_client.socket.send_multipart(exit_message.byte_array)
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
            id=self.server_id, 
            log_level=logging.ERROR+10, 
            done_queue=self.done_queue,
        )
        thing = TestThing(id=self.server_id, log_level=logging.ERROR)
        self.sync_client.handshake()

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
                                server_id=self.server_id, 
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
            receiver_id=self.server_id,
            message_type=EXIT
        )
        self.sync_client.socket.send_multipart(exit_message.byte_array)

        self.assertEqual(self.done_queue.get(), self.server_id)



class TestExposedEvents(TestRPCServerMixin):

    @classmethod
    def setUpClient(self):
        super().setUpClient()
        event_affordance = EventAffordance.from_TD('test_event', test_thing_TD)
        self.sync_event_client = EventConsumer(
                    id=f"{event_affordance.thing_id}|{event_affordance.name}", 
                    event_unique_identifier=get_zmq_unique_identifier_from_event_affordance(event_affordance),
                    socket_address=self.server.event_publisher.socket_address,
                    logger=self.logger,
                    context=self.context
                )
        
    @classmethod
    def setUpEvents(self):
        self.test_event = ZMQEvent(
                                resource=EventAffordance.from_TD('test_event', test_thing_TD),
                                sync_zmq_client=self.sync_event_client,                        
                            )
        

    def test_1_creation_defaults(self):
        """test server configuration defaults"""
        all_things = get_all_sub_things_recusively(self.thing)
        self.assertTrue(len(all_things) > 1) # run the test only if there are sub things
        for thing in all_things:
            assert isinstance(thing, Thing)
            for name, event in thing.events.values.items():
                self.assertTrue(event.publisher, self.server.event_publisher)
                self.assertIsInstance(event._unique_identifier, bytes)
                self.assertEqual(event._owner_inst, thing)


    def test_2_event(self):
        """test if event can be invoked by a client"""
        self.assertEqual(
            get_zmq_unique_identifier_from_event_affordance(self.test_event._resource),
            self.thing.test_event._unique_identifier.decode('utf-8')
        )
        self.assertEqual(
            self.test_event._sync_zmq_client.socket_address, 
            self.server.event_publisher.socket_address
        )
        attempts = self.total_number_of_events.get()
        
        results = []
        def cb(value):
            nonlocal results
            # print("Event received:", value)
            results.append(value)

        self.test_event.subscribe(cb)
        time.sleep(3) # calm down for event publisher to connect fully as there is no handshake for events
        self.action_push_events()

        for i in range(attempts):
            if len(results) == attempts:
                break
            time.sleep(0.1)

        self.assertEqual(len(results), attempts)
        # self.assertEqual(results, ['test data']*attempts)
        self.test_event.unsubscribe(cb)


    def test_9_exit(self):
        exit_message = RequestMessage.craft_with_message_type(
            sender_id='test-event-client', 
            receiver_id=self.server_id,
            message_type=EXIT
        )
        self.sync_client.socket.send_multipart(exit_message.byte_array)

        # self.assertEqual(self.done_queue.get(), self.server_id)




def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestInprocRPCServer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRPCServer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestExposedActions))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestExposedProperties))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestExposedEvents))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))