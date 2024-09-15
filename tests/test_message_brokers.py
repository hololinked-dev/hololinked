import threading, asyncio, typing
import logging, multiprocessing, unittest
from uuid import UUID
from hololinked.server.zmq_message_brokers import (CM_INDEX_ADDRESS, CM_INDEX_CLIENT_TYPE, CM_INDEX_MESSAGE_TYPE,
                CM_INDEX_MESSAGE_ID, CM_INDEX_SERVER_EXEC_CONTEXT, CM_INDEX_THING_ID, CM_INDEX_OPERATION,
                CM_INDEX_OBJECT, CM_INDEX_ARGUMENTS, CM_INDEX_THING_EXEC_CONTEXT, CM_MESSAGE_LENGTH, EXCEPTION)  
from hololinked.server.zmq_message_brokers import (SM_INDEX_ADDRESS, SM_INDEX_MESSAGE_TYPE, SM_INDEX_MESSAGE_ID,
                                    SM_INDEX_SERVER_TYPE, SM_INDEX_DATA, SM_INDEX_PRE_ENCODED_DATA, SM_MESSAGE_LENGTH)
from hololinked.server.zmq_message_brokers import PROXY, REPLY, TIMEOUT, INVALID_MESSAGE, HANDSHAKE, EXIT, OPERATION
from hololinked.server.zmq_message_brokers import AsyncPollingZMQServer, SyncZMQClient, AsyncZMQServer
from hololinked.server.zmq_message_brokers import default_server_execution_context
from hololinked.server.utils import get_current_async_loop, get_default_logger
from hololinked.server.dataklasses import ZMQAction, ZMQResource
from hololinked.server.constants import ZMQ_PROTOCOLS, ResourceTypes, ServerTypes
from hololinked.server.zmq_server import RPCServer
from hololinked.client.proxy import _Action, _Property


try:
    from .utils import TestCase, TestRunner
    # from .things import TestThing, start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    # from things import TestThing, start_thing_forked 




def start_server(server : typing.Union[AsyncPollingZMQServer, AsyncZMQServer], 
                owner : "TestMessageBrokers", done_queue : multiprocessing.Queue = None):
    event_loop = get_current_async_loop()
    async def run():
        while True:
            messages = await server.async_recv_requests()
            owner.last_server_message = messages[0]
            for message in messages:
                if message[CM_INDEX_MESSAGE_TYPE] == b'EXIT':
                    return    
            await asyncio.sleep(0.01)
    event_loop.run_until_complete(run())
    if done_queue:
        done_queue.put(True)



class TestMessageBrokers(TestCase):

    @classmethod
    def setUpClass(self):
        print("test ZMQ Message Brokers")
        self.logger = get_default_logger('test-message-brokers', logging.ERROR)        
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.server_message_broker = AsyncPollingZMQServer(
                                                instance_name='test-message-broker',
                                                server_type='RPC',
                                                logger=self.logger
                                            )
        self._server_thread = threading.Thread(target=start_server, 
                                            args=(self.server_message_broker, self, self.done_queue),
                                            daemon=True)
        self._server_thread.start()
        self.client_message_broker = SyncZMQClient(server_instance_name='test-message-broker', logger=self.logger,
                                                identity='test-client', client_type=PROXY, handshake=False)
        
    @classmethod
    def tearDownClass(self):
        print("tear down test message brokers")

    
    def check_server_message(self, message):
        self.assertEqual(len(message), SM_MESSAGE_LENGTH)
        for index, msg in enumerate(message):
            if index <= 4 or index == 6:
                self.assertIsInstance(msg, bytes)
        if message[SM_INDEX_MESSAGE_TYPE] == INVALID_MESSAGE:
            self.assertEqual(message[SM_INDEX_DATA]["type"], "Exception")
        elif message[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
            self.assertEqual(message[SM_INDEX_DATA], b'null')
        elif message[SM_INDEX_MESSAGE_TYPE] == EXCEPTION:
            self.assertEqual(message[SM_INDEX_DATA]["type"], "Exception")

    def check_client_message(self, message):
        self.assertEqual(len(message), CM_MESSAGE_LENGTH)
        for index, msg in enumerate(message):
            if index <= 4 or index == 9 or index == 7:
                self.assertIsInstance(msg, bytes)
            elif index >= 10 or index == 8:
                self.assertTrue(not isinstance(msg, bytes))


    def test_1_handshake_complete(self):
        self.client_message_broker.handshake()
        self.assertTrue(self.client_message_broker._monitor_socket is not None)
        # both directions
        # HANDSHAKE = b'HANDSHAKE'


    def test_2_message_contract_indices(self):
        # client to server 
        # OPERATION = b'OPERATION' # operation request from client to server
        client_message1 = self.client_message_broker.craft_request_from_arguments(b'test-device', 
                                                                    b'someProp', b'readProperty')
        # test message contract length
        self.assertEqual(len(client_message1), CM_MESSAGE_LENGTH)
        # check all are bytes encoded at least in a loose sense
        for msg in client_message1:
            self.assertTrue(isinstance(msg, bytes))
        self.assertEqual(client_message1[CM_INDEX_ADDRESS], 
                        bytes(self.server_message_broker.instance_name, encoding='utf-8'))
        self.assertEqual(client_message1[1], b'')
        self.assertEqual(client_message1[CM_INDEX_CLIENT_TYPE], PROXY)
        self.assertEqual(client_message1[CM_INDEX_MESSAGE_TYPE], OPERATION)
        self.assertIsInstance(UUID(client_message1[CM_INDEX_MESSAGE_ID].decode(), version=4), UUID)
        self.assertEqual(self.client_message_broker.zmq_serializer.loads(client_message1[CM_INDEX_SERVER_EXEC_CONTEXT]), 
                            default_server_execution_context)
        self.assertEqual(client_message1[CM_INDEX_THING_ID], b'test-device')
        self.assertEqual(client_message1[CM_INDEX_OPERATION], b'readProperty')
        self.assertEqual(client_message1[CM_INDEX_OBJECT], b'someProp')
        self.assertEqual(self.client_message_broker.zmq_serializer.loads(client_message1[CM_INDEX_ARGUMENTS]), dict())
        self.assertEqual(self.client_message_broker.zmq_serializer.loads(client_message1[CM_INDEX_THING_EXEC_CONTEXT]), 
                            dict())

        server_message1 = self.server_message_broker.craft_response_from_arguments(b'test-device', 
                                                PROXY, REPLY, client_message1[CM_INDEX_MESSAGE_ID])
        self.assertEqual(len(server_message1), 7)
        for msg in server_message1:
            self.assertTrue(isinstance(msg, bytes))
        self.assertEqual(server_message1[SM_INDEX_ADDRESS], b'test-device')
        self.assertEqual(server_message1[1], b'')
        self.assertEqual(server_message1[SM_INDEX_SERVER_TYPE], b'RPC')
        self.assertEqual(server_message1[SM_INDEX_MESSAGE_TYPE], REPLY)
        self.assertIsInstance(UUID(server_message1[SM_INDEX_MESSAGE_ID].decode(), version=4), UUID)
        self.assertEqual(server_message1[SM_INDEX_DATA], self.server_message_broker.zmq_serializer.dumps(None))
        self.assertEqual(server_message1[SM_INDEX_PRE_ENCODED_DATA], b'')

        # test specific way of crafting messages
        # client side - only other second method that generates message
        client_message2 = self.client_message_broker.craft_empty_message_with_type(b'EXIT')
        self.assertEqual(len(client_message2), CM_MESSAGE_LENGTH)
        for msg in client_message2:
            self.assertTrue(isinstance(msg, bytes))

        # server side - only other second method that generates message
        server_message2 = self.server_message_broker.craft_reply_from_client_message(client_message2)
        self.assertEqual(len(server_message2), 7)
        self.assertEqual(server_message2[CM_INDEX_MESSAGE_TYPE], REPLY)
        for msg in server_message2:
            self.assertTrue(isinstance(msg, bytes))


    def test_3_message_contract_types(self):
        # message types
        client_message = self.client_message_broker.craft_request_from_arguments(b'test-device', 
                                                                    b'readProperty', b'someProp')
        
        async def handle_message_types():
            # server to client
            # REPLY = b'REPLY' # reply for operation
            # TIMEOUT = b'TIMEOUT' # timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # invalid message
            client_message[CM_INDEX_ADDRESS] = b'test-client'
            await self.server_message_broker._handle_timeout(client_message)
            await self.server_message_broker._handle_invalid_message(client_message, Exception('test'))
            await self.server_message_broker._handshake(client_message)
            await self.server_message_broker.async_send_response(client_message)
            await self.server_message_broker.async_send_response_with_message_type(client_message, EXCEPTION,
                                                                                   Exception('test'))
            
        get_current_async_loop().run_until_complete(handle_message_types())

        # # message types
        # # both directions
        # HANDSHAKE = b'HANDSHAKE'
        # # client to server 
        # OPERATION = b'OPERATION' # operation request from client to server
        # EXIT = b'EXIT' # exit the server
        # # server to client
        # REPLY = b'REPLY' # reply for operation
        # TIMEOUT = b'TIMEOUT' # timeout message, operation could not be completed
        # EXCEPTION = b'EXCEPTION' # exception occurred while executing operation
        # INVALID_MESSAGE = b'INVALID_MESSAGE' # invalid message
        # SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # socket died - zmq's builtin event
        # # peer to peer
        # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling 
        
        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], TIMEOUT)
        self.check_server_message(msg)

        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], INVALID_MESSAGE)
        self.check_server_message(msg)

        msg = self.client_message_broker.socket.recv_multipart() # handshake dont come as response
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], HANDSHAKE)
        self.check_server_message(msg)

        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], REPLY)
        self.check_server_message(msg)

        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], EXCEPTION)
        self.check_server_message(msg)
        
        # exit checked separately at the end

    def test_pending(self):
        pass 
        # SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # socket died - zmq's builtin event
        # # peer to peer
        # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling 
        # # first test the length 


    def test_4_action_call_abstraction(self):
        resource_info = ZMQResource(what=ResourceTypes.ACTION, class_name='TestThing', instance_name='test-thing',
                    obj_name='test_echo', qualname='TestThing.test_echo', doc="returns value as it is to the client",
                    request_as_argument=False)
        action_abstractor = _Action(sync_client=self.client_message_broker, resource_info=resource_info,
                    invokation_timeout=5, execution_timeout=5, async_client=None, schema_validator=None)
        action_abstractor.oneway() # because we dont have a thing running
        self.client_message_broker.handshake() # force a reply from server so that last_server_message is set
        self.check_client_message(self.last_server_message)


    def test_5_property_abstraction(self):
        resource_info = ZMQResource(what=ResourceTypes.PROPERTY, class_name='TestThing', instance_name='test-thing',
                    obj_name='test_prop', qualname='TestThing.test_prop', doc="a random property",
                    request_as_argument=False)
        property_abstractor = _Property(sync_client=self.client_message_broker, resource_info=resource_info,
                    invokation_timeout=5, execution_timeout=5, async_client=None)
        property_abstractor.oneway_set(5) # because we dont have a thing running
        self.client_message_broker.handshake() # force a reply from server so that last_server_message is sets
        self.check_client_message(self.last_server_message)


    def test_6_message_broker_async(self):

        async def verify_poll_stop(self : "TestMessageBrokers"):
            await self.server_message_broker.poll_requests()
            self.server_message_broker.poll_timeout = 1000
            await self.server_message_broker.poll_requests()
            self.done_queue.put(True)

        async def stop_poll(self : "TestMessageBrokers"):
            await asyncio.sleep(0.1)
            self.server_message_broker.stop_polling()
            await asyncio.sleep(0.1)
            self.server_message_broker.stop_polling()

        get_current_async_loop().run_until_complete(
            asyncio.gather(*[verify_poll_stop(self), stop_poll(self)])
        )	

        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.server_message_broker.poll_timeout, 1000)        


    def test_7_exit(self):
        # EXIT = b'EXIT' # exit the server
        client_message = self.client_message_broker.craft_request_from_arguments(b'test-device', 
                                                                    b'readProperty', b'someProp')
        client_message[CM_INDEX_ADDRESS] = b'test-message-broker'
        client_message[CM_INDEX_MESSAGE_TYPE] = EXIT
        self.client_message_broker.socket.send_multipart(client_message)

        self.assertTrue(self.done_queue.get())
        self._server_thread.join()        


    def test_8_broker_with_RPC(self):
        def start_rpc_server():
            server = RPCServer(instance_name='test-server', logger=self.logger,
                        things=[])
        
            inner_server = AsyncZMQServer(
                                instance_name=f'test-server/inner', # hardcoded be very careful
                                server_type=ServerTypes.THING,
                                context=server.context,
                                logger=self.logger,
                                protocol=ZMQ_PROTOCOLS.INPROC, 
                            ) 
            threading.Thread(target=start_server, args=(inner_server, self), 
                            daemon=True).start()
            server.run()

        threading.Thread(target=start_rpc_server, daemon=True).start()

        client = SyncZMQClient(server_instance_name='test-server', identity='test-client', 
                    client_type=PROXY) 
        
        resource_info = ZMQResource(what=ResourceTypes.ACTION, class_name='TestThing', instance_name='test-thing/inner',
                    obj_name='test_echo', qualname='TestThing.test_echo', doc="returns value as it is to the client",
                    request_as_argument=False)
        action_abstractor = _Action(sync_client=client, resource_info=resource_info,
                    invokation_timeout=5, execution_timeout=5, async_client=None, schema_validator=None)
        action_abstractor.oneway() # because we dont have a thing running
        client.handshake() # force a reply from server so that last_server_message is set
        self.check_client_message(self.last_server_message)
        
        self.assertEqual(self.last_server_message[CM_INDEX_THING_ID], b'test-client/inner')
        

if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())