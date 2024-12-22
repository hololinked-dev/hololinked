import threading, asyncio, typing
import logging, multiprocessing, unittest
import uuid
import zmq.asyncio 
from uuid import UUID




from hololinked.server.protocols.zmq.message import (ERROR, EXIT, OPERATION, HANDSHAKE, REPLY, 
                                            PreserializedData, RequestHeader, RequestMessage, SerializableData) # client to server
from hololinked.server.protocols.zmq.message import (TIMEOUT, INVALID_MESSAGE, ERROR, 
                                            ResponseMessage, ResponseHeader) # server to client
from hololinked.server.protocols.zmq.brokers import AsyncZMQServer, SyncZMQClient
from hololinked.server.serializers import Serializers
# from hololinked.server.protocols.zmq.brokers import default_server_execution_context
from hololinked.server.utils import get_current_async_loop, get_default_logger
from hololinked.server.dataklasses import ZMQAction, ZMQResource
# from hololinked.server.constants import ZMQ_PROTOCOLS, ResourceTypes, ServerTypes
from hololinked.server.rpc_server import RPCServer
from hololinked.client.proxy import _Action, _Property


try:
    from .utils import TestCase, TestRunner
    from .test_1_message import MessageValidatorMixin
    # from .things import TestThing, start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    from test_1_message import MessageValidatorMixin
    # from things import TestThing, start_thing_forked 




def run_server(server: AsyncZMQServer, owner: "TestServerBroker", done_queue: multiprocessing.Queue) -> None:
    event_loop = get_current_async_loop()
    async def run():
        while True:
            messages = await server.async_recv_requests()           
            owner.last_server_message = messages[0]
            for message in messages:
                if message.type == EXIT:
                    return    
                
            await asyncio.sleep(0.01)
    event_loop.run_until_complete(run())
    if done_queue:
        done_queue.put(True)



class TestServerBroker(MessageValidatorMixin):
    """Tests Individual ZMQ Server"""

    @classmethod
    def setUpServer(self):
        self.server_message_broker = AsyncZMQServer(
                                                id=self.server_id,
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
                                            id=self.client_id,
                                            server_id=self.server_id, 
                                            logger=self.logger,
                                            handshake=False
                                        )

    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

    @classmethod
    def setUpClass(self):
        print(f"test ZMQ Message Broker with {self.__name__}")
        self.server_id = 'test-server'
        self.client_id = 'test-client'
        self.thing_id = 'test-thing'
        self.logger = get_default_logger('test-message-broker', logging.DEBUG)        
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.setUpServer()
        self.setUpClient()


    @classmethod
    def tearDownClass(self):
        print("\ntear down test message broker")

    
    # def check_server_message(self, message):
    #     """
    #     Utility function to check types of indices within the message created by the server
    #     """
    #     self.assertEqual(len(message), SM_MESSAGE_LENGTH)
    #     """
    #     SM_INDEX_ADDRESS = 0, SM_INDEX_SERVER_TYPE = 2, SM_INDEX_MESSAGE_TYPE = 3, SM_INDEX_MESSAGE_ID = 4, 
    #     SM_INDEX_DATA = 5, SM_INDEX_PRE_ENCODED_DATA = 6, 
    #     """
    #     for index, msg in enumerate(message):
    #         if index <= 4 or index == 6:
    #             self.assertIsInstance(msg, bytes)
    #     if message[SM_INDEX_MESSAGE_TYPE] == INVALID_MESSAGE:
    #         self.assertEqual(message[SM_INDEX_DATA]["type"], "Exception")
    #     elif message[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
    #         self.assertEqual(message[SM_INDEX_DATA], b'null')
    #     elif message[SM_INDEX_MESSAGE_TYPE] == EXCEPTION:
    #         self.assertEqual(message[SM_INDEX_DATA]["type"], "Exception")


    # def check_client_message(self, message):
    #     """
    #     Utility function to check types of indices within the message created by the client
    #     """
    #     self.assertEqual(len(message), CM_MESSAGE_LENGTH)
    #     """
    #     CM_INDEX_ADDRESS = 0, CM_INDEX_CLIENT_TYPE = 2, CM_INDEX_MESSAGE_TYPE = 3, CM_INDEX_MESSAGE_ID = 4, 
    #     CM_INDEX_SERVER_EXEC_CONTEXT = 5, CM_INDEX_THING_ID = 7, CM_INDEX_OBJECT = 8, CM_INDEX_OPERATION = 9,
    #     CM_INDEX_ARGUMENTS = 10, CM_INDEX_THING_EXEC_CONTEXT = 11
    #     """
    #     for index, msg in enumerate(message):
    #         if index <= 4 or index == 9 or index == 7: # 0, 2, 3, 4, 7, 9 
    #             self.assertIsInstance(msg, bytes)
    #         elif index >= 10 or index == 8: # 8, 10, 11
    #             self.assertTrue(not isinstance(msg, bytes))
    #         # 1 and 6 are empty bytes
    #         # 5 - server execution context is deserialized only by RPC server


    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        self.client_message_broker.handshake()
        self.assertTrue(self.client_message_broker._monitor_socket is not None)
        # both directions
        # HANDSHAKE = 'HANDSHAKE' # 1 - find out if the server is alive


    def test_2_message_contract_types(self):
        """
        Once composition is checked, check different message types
        """
        # message types
        request_message = RequestMessage.craft_from_arguments(
                                                        server_id=self.server_id,
                                                        thing_id=self.thing_id,
                                                        objekt='some_prop',
                                                        operation='readProperty'
                                                    )
        
                
        async def handle_message_types():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            request_message._sender_id = self.client_id
            await self.server_message_broker._handle_timeout(request_message) # 5
            await self.server_message_broker._handle_invalid_message(request_message, 
                                                                    SerializableData(Exception('test'))) # 7
            await self.server_message_broker._handshake(request_message) # 1
            await self.server_message_broker.async_send_response(request_message) # 4
            await self.server_message_broker.async_send_response_with_message_type(request_message, ERROR, 
                                                                    SerializableData(Exception('test'))) # 6
            
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
        
        msg = self.client_message_broker.recv_response(request_message.id)
        self.assertEqual(msg.type, TIMEOUT)
        self.validate_response_message(msg)

        msg = self.client_message_broker.recv_response(request_message.id)
        self.assertEqual(msg.type, INVALID_MESSAGE)
        self.validate_response_message(msg)

        msg = self.client_message_broker.socket.recv_multipart() # handshake dont come as response
        response_message = ResponseMessage.craft_from_self(msg)
        self.assertEqual(response_message.type, HANDSHAKE)
        self.validate_response_message(response_message)

        msg = self.client_message_broker.recv_response(request_message.id)
        self.assertEqual(msg.type, REPLY)
        self.validate_response_message(msg)

        msg = self.client_message_broker.recv_response(request_message.id)
        self.assertEqual(msg.type, ERROR)
        self.validate_response_message(msg)
        
        # exit checked separately at the end

    # def test_pending(self):
    #     pass 
    #     # SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # socket died - zmq's builtin event
    #     # # peer to peer
    #     # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling 
    #     # # first test the length 



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
