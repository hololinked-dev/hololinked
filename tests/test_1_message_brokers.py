import threading, asyncio, typing
import logging, multiprocessing, unittest
import zmq.asyncio 
from uuid import UUID
from hololinked.server.protocols.zmq.brokers import (CM_INDEX_ADDRESS, CM_INDEX_CLIENT_TYPE, CM_INDEX_MESSAGE_TYPE,
                CM_INDEX_MESSAGE_ID, CM_INDEX_SERVER_EXEC_CONTEXT, CM_INDEX_THING_ID, CM_INDEX_OPERATION,
                CM_INDEX_OBJECT, CM_INDEX_ARGUMENTS, CM_INDEX_THING_EXEC_CONTEXT, CM_MESSAGE_LENGTH, EXCEPTION)  
from hololinked.server.protocols.zmq.brokers import (SM_INDEX_ADDRESS, SM_INDEX_MESSAGE_TYPE, SM_INDEX_MESSAGE_ID,
                                    SM_INDEX_SERVER_TYPE, SM_INDEX_DATA, SM_INDEX_PRE_ENCODED_DATA, SM_MESSAGE_LENGTH)
from hololinked.server.protocols.zmq.brokers import PROXY, REPLY, TIMEOUT, INVALID_MESSAGE, HANDSHAKE, EXIT, OPERATION
from hololinked.server.protocols.zmq.brokers import AsyncZMQServer, SyncZMQClient
from hololinked.server.protocols.zmq.brokers import default_server_execution_context
from hololinked.server.utils import get_current_async_loop, get_default_logger
from hololinked.server.dataklasses import ZMQAction, ZMQResource
from hololinked.server.constants import ZMQ_PROTOCOLS, ResourceTypes, ServerTypes
from hololinked.server.rpc_server import RPCServer
from hololinked.client.proxy import _Action, _Property


try:
    from .utils import TestCase, TestRunner
    # from .things import TestThing, start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    # from things import TestThing, start_thing_forked 




def run_server(server : AsyncZMQServer, owner : "TestServerBroker", done_queue : multiprocessing.Queue) -> None:
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



class TestServerBroker(TestCase):
    """Tests Individual ZMQ Server"""

    @classmethod
    def setUpServer(self):
        self.server_message_broker = AsyncZMQServer(
                                                instance_name='test-message-broker',
                                                server_type='RPC',
                                                logger=self.logger
                                            )
        self._server_thread = threading.Thread(
                                            target=run_server, 
                                            args=(self.server_message_broker, self, self.done_queue),
                                            daemon=True
                                        )
        self._server_thread.start()
        

    @classmethod
    def setUpClient(self):
        self.client_message_broker = SyncZMQClient(
                                            server_instance_name='test-message-broker', 
                                            logger=self.logger,
                                            identity='test-client', 
                                            client_type=PROXY, handshake=False
                                        )

    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

    @classmethod
    def setUpClass(self):
        print(f"test ZMQ Message Broker with {self.__name__}")
        self.logger = get_default_logger('test-message-broker', logging.ERROR)        
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.setUpServer()
        self.setUpClient()


    @classmethod
    def tearDownClass(self):
        print("tear down test message broker")

    
    def check_server_message(self, message):
        """
        Utility function to check types of indices within the message created by the server
        """
        self.assertEqual(len(message), SM_MESSAGE_LENGTH)
        """
        SM_INDEX_ADDRESS = 0, SM_INDEX_SERVER_TYPE = 2, SM_INDEX_MESSAGE_TYPE = 3, SM_INDEX_MESSAGE_ID = 4, 
        SM_INDEX_DATA = 5, SM_INDEX_PRE_ENCODED_DATA = 6, 
        """
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
        """
        Utility function to check types of indices within the message created by the client
        """
        self.assertEqual(len(message), CM_MESSAGE_LENGTH)
        """
        CM_INDEX_ADDRESS = 0, CM_INDEX_CLIENT_TYPE = 2, CM_INDEX_MESSAGE_TYPE = 3, CM_INDEX_MESSAGE_ID = 4, 
        CM_INDEX_SERVER_EXEC_CONTEXT = 5, CM_INDEX_THING_ID = 7, CM_INDEX_OBJECT = 8, CM_INDEX_OPERATION = 9,
        CM_INDEX_ARGUMENTS = 10, CM_INDEX_THING_EXEC_CONTEXT = 11
        """
        for index, msg in enumerate(message):
            if index <= 4 or index == 9 or index == 7: # 0, 2, 3, 4, 7, 9 
                self.assertIsInstance(msg, bytes)
            elif index >= 10 or index == 8: # 8, 10, 11
                self.assertTrue(not isinstance(msg, bytes))
            # 1 and 6 are empty bytes
            # 5 - server execution context is deserialized only by RPC server


    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        self.client_message_broker.handshake()
        self.assertTrue(self.client_message_broker._monitor_socket is not None)
        # both directions
        # HANDSHAKE = b'HANDSHAKE' # 1 - find out if the server is alive


    def test_2_message_contract_indices(self):
        """
        Test message composition for every composition way possible.
        Before production release, this is to freeze the message contract.
        """
        # client to server 
        # OPERATION = b'OPERATION' # 2 - operation request from client to server
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
        """
        CM_INDEX_ADDRESS = 0, CM_INDEX_CLIENT_TYPE = 2, CM_INDEX_MESSAGE_TYPE = 3, CM_INDEX_MESSAGE_ID = 4, 
        CM_INDEX_SERVER_EXEC_CONTEXT = 5, CM_INDEX_THING_ID = 7, CM_INDEX_OBJECT = 8, CM_INDEX_OPERATION = 9,
        CM_INDEX_ARGUMENTS = 10, CM_INDEX_THING_EXEC_CONTEXT = 11
        """

        # test specific way of crafting messages
        # client side - only other second method that generates message
        # 3 - exit the server
        client_message2 = self.client_message_broker.craft_empty_request_with_message_type(b'EXIT')
        self.assertEqual(len(client_message2), CM_MESSAGE_LENGTH)
        for msg in client_message2:
            self.assertTrue(isinstance(msg, bytes))
            
        # Server to client
        # REPLY = b'REPLY' # 4 - response for operation
        server_message1 = self.server_message_broker.craft_response_from_arguments(b'test-device', 
                                                PROXY, REPLY, client_message1[CM_INDEX_MESSAGE_ID])
        self.assertEqual(len(server_message1), SM_MESSAGE_LENGTH)
        for msg in server_message1:
            self.assertTrue(isinstance(msg, bytes))
        self.assertEqual(server_message1[SM_INDEX_ADDRESS], b'test-device')
        self.assertEqual(server_message1[1], b'')
        self.assertEqual(server_message1[SM_INDEX_SERVER_TYPE], b'RPC')
        self.assertEqual(server_message1[SM_INDEX_MESSAGE_TYPE], REPLY)
        self.assertIsInstance(UUID(server_message1[SM_INDEX_MESSAGE_ID].decode(), version=4), UUID)
        self.assertEqual(server_message1[SM_INDEX_DATA], self.server_message_broker.zmq_serializer.dumps(None))
        self.assertEqual(server_message1[SM_INDEX_PRE_ENCODED_DATA], b'')
        """
        SM_INDEX_ADDRESS = 0, SM_INDEX_SERVER_TYPE = 2, SM_INDEX_MESSAGE_TYPE = 3, SM_INDEX_MESSAGE_ID = 4, 
        SM_INDEX_DATA = 5, SM_INDEX_PRE_ENCODED_DATA = 6, 
        """
        # server side - only other second method that generates message
        server_message2 = self.server_message_broker.craft_response_from_client_message(client_message2)
        self.assertEqual(len(server_message2), SM_MESSAGE_LENGTH)
        self.assertEqual(server_message2[CM_INDEX_MESSAGE_TYPE], REPLY)
        for msg in server_message2:
            self.assertTrue(isinstance(msg, bytes))


    def test_3_message_contract_types(self):
        """
        Once composition is checked, check different message types
        """
        # message types
        client_message = self.client_message_broker.craft_request_from_arguments(b'test-device', 
                                                                b'someProp', b'readProperty')
        
        async def handle_message_types():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # 7 INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            client_message[CM_INDEX_ADDRESS] = b'test-client'
            await self.server_message_broker._handle_timeout(client_message) # 5
            await self.server_message_broker._handle_invalid_message(client_message, Exception('test')) # 7
            await self.server_message_broker._handshake(client_message) # 1
            await self.server_message_broker.async_send_response(client_message) # 4
            await self.server_message_broker.async_send_response_with_message_type(client_message, EXCEPTION,
                                                                                   Exception('test')) # 6
            
        get_current_async_loop().run_until_complete(handle_message_types())

        """
        message types

        both directions
        HANDSHAKE = b'HANDSHAKE' # 1 - taken care by test_1...
        
        client to server 
        OPERATION = b'OPERATION' 2 - taken care by test_2_... # operation request from client to server
        EXIT = b'EXIT' # 3 - taken care by test_7... # exit the server
        
        server to client
        REPLY = b'REPLY' # 4 - response for operation
        TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
        EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
        INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
        SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' not yet tested # socket died - zmq's builtin event
        
        peer to peer
        INTERRUPT = b'INTERRUPT' not yet tested # interrupt a socket while polling 
        """
        
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


    def test_4_abstractions(self):
        """
        Once message types are checked, operations need to be checked. But exeuction of operations on the server 
        are implemeneted by event loop so that we skip that here. We check abstractions of message type and operation to a 
        higher level object, and said higher level object should send the message and message should have 
        been received by the server.
        """
        self._test_action_call_abstraction()
        self._test_property_abstraction()


    def _test_action_call_abstraction(self):
        """
        Higher level action object should be able to send messages to server
        """
        resource_info = ZMQResource(what=ResourceTypes.ACTION, class_name='TestThing', instance_name='test-thing',
                    obj_name='test_echo', qualname='TestThing.test_echo', doc="returns value as it is to the client",
                    request_as_argument=False)
        action_abstractor = _Action(sync_client=self.client_message_broker, resource_info=resource_info,
                    invokation_timeout=5, execution_timeout=5, async_client=None, schema_validator=None)
        action_abstractor.oneway() # because we dont have a thing running
        self.client_message_broker.handshake() # force a response from server so that last_server_message is set
        self.check_client_message(self.last_server_message) # last message received by server which is the client message


    def _test_property_abstraction(self):
        """
        Higher level property object should be able to send messages to server
        """
        resource_info = ZMQResource(what=ResourceTypes.PROPERTY, class_name='TestThing', instance_name='test-thing',
                    obj_name='test_prop', qualname='TestThing.test_prop', doc="a random property",
                    request_as_argument=False)
        property_abstractor = _Property(sync_client=self.client_message_broker, resource_info=resource_info,
                    invokation_timeout=5, execution_timeout=5, async_client=None)
        property_abstractor.oneway_set(5) # because we dont have a thing running
        self.client_message_broker.handshake() # force a response from server so that last_server_message is set
        self.check_client_message(self.last_server_message) # last message received by server which is the client message


    def test_6_message_broker_async(self):
        """
        Test if server can be started and stopped using builtin functions on the server side
        """
       
        async def verify_poll_stopped(self : "TestServerBroker"):
            await self.server_message_broker.poll_requests()
            self.server_message_broker.poll_timeout = 1000
            await self.server_message_broker.poll_requests()
            self.done_queue.put(True)

        async def stop_poll(self : "TestServerBroker"):
            await asyncio.sleep(0.1)
            self.server_message_broker.stop_polling()
            await asyncio.sleep(0.1)
            self.server_message_broker.stop_polling()
        # When the above two functions running, we dont send a message as the thread is
        # also running
        get_current_async_loop().run_until_complete(
            asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)])
        )	

        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.server_message_broker.poll_timeout, 1000)        


    def test_7_exit(self):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        client_message = self.client_message_broker.craft_empty_request_with_message_type(EXIT)
        client_message[CM_INDEX_ADDRESS] = b'test-message-broker'
        self.client_message_broker.socket.send_multipart(client_message)

        self.assertTrue(self.done_queue.get())
        self._server_thread.join()        



class TestRPCServer(TestCase):

    @classmethod
    def setUpClass(self):
        print(f"test RPC Message Broker with {self.__name__}")
        self.logger = get_default_logger('test-rpc-broker', logging.ERROR)    
        self.done_queue = multiprocessing.Queue()
        self.start_rpc_server()
        self.client_message_broker = SyncZMQClient(
                                        server_instance_name='test-rpc-server', 
                                        identity='test-client', 
                                        client_type=PROXY,
                                        log_level=logging.ERROR
                                    ) 
        

    @classmethod
    def start_rpc_server(self):
        context = zmq.asyncio.Context() 
        self.rpc_server = RPCServer(instance_name='test-rpc-server', logger=self.logger,
                    things=[], context=context)
        self.inner_server = AsyncZMQServer(
                            instance_name=f'test-rpc-server/inner', # hardcoded be very careful
                            server_type=ServerTypes.THING,
                            context=context,
                            logger=self.logger,
                            protocol=ZMQ_PROTOCOLS.INPROC, 
                
                        ) 
        self._server_thread = threading.Thread(target=run_server, args=(self.inner_server, self, self.done_queue), 
                        daemon=True)
        self._server_thread.start()
        
        self.rpc_server.run()


    def test_7_exit(self):
        """
        Test if exit reaches to server
        """
        # # EXIT = b'EXIT' # exit the server
        # client_message = self.client_message_broker.craft_request_from_arguments(b'test-device', 
        #                                                             b'readProperty', b'someProp')
        # client_message[CM_INDEX_ADDRESS] = b'test-rpc-server/inner'
        # client_message[CM_INDEX_MESSAGE_TYPE] = EXIT
        # self.client_message_broker.socket.send_multipart(client_message)
        # self.assertTrue(self.done_queue.get())
        # self._server_thread.join()    

    @classmethod  
    def tearDownClass(self):
        self.inner_server.exit()
        self.rpc_server.exit()
      

#     resource_info = ZMQResource(what=ResourceTypes.ACTION, class_name='TestThing', instance_name='test-thing/inner',
#                 obj_name='test_echo', qualname='TestThing.test_echo', doc="returns value as it is to the client",
#                 request_as_argument=False)
#     action_abstractor = _Action(sync_client=client, resource_info=resource_info,
#                 invokation_timeout=5, execution_timeout=5, async_client=None, schema_validator=None)
#     action_abstractor.oneway() # because we dont have a thing running
#     client.handshake() # force a response from server so that last_server_message is set
#     self.check_client_message(self.last_server_message)
    
#     self.assertEqual(self.last_server_message[CM_INDEX_THING_ID], b'test-client/inner')



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())