import threading, asyncio
import logging, multiprocessing, unittest

from hololinked.constants import ResourceTypes
from hololinked.protocols.zmq.message import (ERROR, EXIT, OPERATION, HANDSHAKE, REPLY, 
                                            PreserializedData, RequestHeader, RequestMessage, SerializableData) # client to server
from hololinked.protocols.zmq.message import (TIMEOUT, INVALID_MESSAGE, ERROR, 
                                            ResponseMessage, ResponseHeader) # server to client
from hololinked.protocols.zmq.brokers import AsyncZMQServer, MessageMappedZMQClientPool, SyncZMQClient, AsyncZMQClient
from hololinked.utils import get_current_async_loop, get_default_logger
from hololinked.td import ActionAffordance
# from hololinked.server.constants import ZMQ_PROTOCOLS, ResourceTypes, ServerTypes
from hololinked.protocols.zmq.client import Action, Property


try:
    from .utils import TestRunner
    from .test_1_message import MessageValidatorMixin
    from .things.starter import run_zmq_server
    from .things import TestThing, test_thing_TD
except ImportError:
    from utils import TestRunner
    from test_1_message import MessageValidatorMixin
    from things.starter import run_zmq_server
    from things import TestThing, test_thing_TD




class TestBrokerMixin(MessageValidatorMixin):
    """Tests Individual ZMQ Server"""

    @classmethod
    def setUpServer(self):
        self.server = AsyncZMQServer(
                                    id=self.server_id,
                                    logger=self.logger
                                )
    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

    @classmethod
    def setUpClient(self):
        self.client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        
    
    @classmethod
    def setUpThing(self):
        self.thing = TestThing(
                            id=self.thing_id,
                            logger=self.logger
                        )

        

    @classmethod
    def startServer(self):
        self._server_thread = threading.Thread(
                                            target=run_zmq_server, 
                                            args=(self.server, self, self.done_queue),
                                            daemon=True
                                        )
        self._server_thread.start()

   
    @classmethod
    def setUpClass(self):
        super().setUpClass()
        print(f"test ZMQ message brokers {self.__name__}")
        self.logger = get_default_logger('test-message-broker', logging.ERROR)        
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.setUpThing()
        self.setUpServer()
        self.setUpClient()
        self.startServer()



class ActionMixin(TestBrokerMixin):

    @classmethod
    def setUpActions(self):
        self.echo_action = Action(
                                sync_client=None,
                                resource=ActionAffordance.from_TD('echo_action', test_thing_TD),
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )
    
        self.get_serialized_data_action = Action(
                                sync_client=None,
                                resource=ActionAffordance.from_TD('get_serialized_data', test_thing_TD)
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )
        
        self.sleep_action = Action(
                                sync_client=None,
                                resource=ActionAffordance.from_TD('sleep', test_thing_TD),
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )

        self.get_mixed_content_data_action = Action(
                        sync_client=None,
                        resource= ActionAffordance.from_TD('get_mixed_content_data', test_thing_TD),
                        invokation_timeout=5, 
                        execution_timeout=5, 
                        async_client=self.client, 
                        schema_validator=None
                    )
   


class TestAsyncZMQServer(ActionMixin):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.setUpActions()
        print(f"test ZMQ RPC Server {self.__name__}")

    
    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        self.client.handshake()
        self.assertTrue(self.client._monitor_socket is not None)
        # both directions
        # HANDSHAKE = 'HANDSHAKE' # 1 - find out if the server is alive


    def test_2_message_contract_types(self):
        """
        Once composition is checked, check different message types
        """
        # message types
        request_message = RequestMessage.craft_from_arguments(
                                                        receiver_id=self.server_id,
                                                        sender_id=self.client_id,
                                                        thing_id=self.thing_id,
                                                        objekt='some_prop',
                                                        operation='readProperty'
                                                    )
        
        async def handle_message_types_server():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            await self.server._handle_timeout(request_message, timeout_type='execution') # 5
            await self.server._handle_invalid_message(request_message, SerializableData(Exception('test'))) # 7
            await self.server._handshake(request_message) # 1
            await self.server.async_send_response(request_message) # 4
            await self.server.async_send_response_with_message_type(request_message, ERROR, 
                                                                    SerializableData(Exception('test'))) # 6
            
        get_current_async_loop().run_until_complete(handle_message_types_server())

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
        
        msg = self.client.recv_response(request_message.id)
        self.assertEqual(msg.type, TIMEOUT)
        self.validate_response_message(msg)

        msg = self.client.recv_response(request_message.id)
        self.assertEqual(msg.type, INVALID_MESSAGE)
        self.validate_response_message(msg)

        msg = self.client.socket.recv_multipart() # handshake dont come as response
        response_message = ResponseMessage(msg)
        self.assertEqual(response_message.type, HANDSHAKE)
        self.validate_response_message(response_message)

        msg = self.client.recv_response(request_message.id)
        self.assertEqual(msg.type, REPLY)
        self.validate_response_message(msg)

        msg = self.client.recv_response(request_message.id)
        self.assertEqual(msg.type, ERROR)
        self.validate_response_message(msg)

        # exit checked separately at the end


    def test_3_verify_polling(self):
        """
        Test if polling may be stopped and started again
        """
        async def verify_poll_stopped(self: "TestAsyncZMQServer") -> None:
            await self.server.poll_requests()
            self.server.poll_timeout = 1000
            await self.server.poll_requests()
            self.done_queue.put(True)

        async def stop_poll(self: "TestAsyncZMQServer") -> None:
            await asyncio.sleep(0.1)
            self.server.stop_polling()
            await asyncio.sleep(0.1)
            self.server.stop_polling()
        # When the above two functions running, 
        # we dont send a message as the thread is also running
        get_current_async_loop().run_until_complete(
            asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)])
        )	

        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.server.poll_timeout, 1000)        


    def test_4_abstractions(self):
        """
        Once message types are checked, operations need to be checked. But exeuction of operations on the server 
        are implemeneted by event loop so that we skip that here. We check abstractions of message type and operation to a 
        higher level object, and said higher level object should send the message and message should have 
        been received by the server.
        """
        self._test_action_call_abstraction()
        # self._test_property_abstraction()


    def _test_action_call_abstraction(self):
        """
        Higher level action object should be able to send messages to server
        """
        self.echo_action._zmq_client = self.client
        self.echo_action.oneway() # because we dont have a thing running
        self.client.handshake() # force a response from server so that last_server_message is set
        # self.check_client_message(self.last_server_message) # last message received by server which is the client message


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



    def test_5_exit(self):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        request_message = RequestMessage.craft_with_message_type(
                                                            receiver_id=self.server_id,
                                                            sender_id=self.client_id,
                                                            message_type=EXIT
                                                        )
        self.client.socket.send_multipart(request_message.byte_array)
        self.assertTrue(self.done_queue.get())
        self._server_thread.join()        


    def test_5_pending(self):
        pass 
        # SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # socket died - zmq's builtin event
        # # peer to peer
        # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling 
        # # first test the length 



class TestAsyncZMQClient(TestBrokerMixin):

    @classmethod
    def setUpClient(self):
        self.client = AsyncZMQClient(
                                    id=self.client_id,
                                    server_id=self.server_id, 
                                    logger=self.logger,
                                    handshake=False
                                )
        

    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        async def test():
            self.client.handshake()
            await self.client.handshake_complete()
            self.assertTrue(self.client._monitor_socket is not None)
        get_current_async_loop().run_until_complete(test())
        # both directions
        # HANDSHAKE = 'HANDSHAKE' # 1 - find out if the server is alive    


    def test_2_message_contract_types(self):
        """
        Once composition is checked, check different message types
        """
        # message types
        request_message = RequestMessage.craft_from_arguments(
                                                        receiver_id=self.server_id,
                                                        sender_id=self.client_id,
                                                        thing_id=self.thing_id,
                                                        objekt='some_prop',
                                                        operation='readProperty'
                                                    )
        
        async def handle_message_types_server():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            await self.server._handle_timeout(request_message, timeout_type='invokation') # 5
            await self.server._handle_invalid_message(request_message, SerializableData(Exception('test')))
            await self.server._handshake(request_message)
            await self.server.async_send_response(request_message)
            await self.server.async_send_response_with_message_type(request_message, ERROR, 
                                                                    SerializableData(Exception('test')))
        
        async def handle_message_types_client():
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
            msg = await self.client.async_recv_response(request_message.id)
            self.assertEqual(msg.type, TIMEOUT)
            self.validate_response_message(msg)

            msg = await self.client.async_recv_response(request_message.id)
            self.assertEqual(msg.type, INVALID_MESSAGE)
            self.validate_response_message(msg)

            msg = await self.client.socket.recv_multipart() # handshake don't come as response
            response_message = ResponseMessage(msg)
            self.assertEqual(response_message.type, HANDSHAKE)
            self.validate_response_message(response_message)

            msg = await self.client.async_recv_response(request_message.id)
            self.assertEqual(msg.type, REPLY)
            self.validate_response_message(msg)

            msg = await self.client.async_recv_response(request_message.id)
            self.assertEqual(msg.type, ERROR)
            self.validate_response_message(msg)

        # exit checked separately at the end
        get_current_async_loop().run_until_complete(
            asyncio.gather(*[
                handle_message_types_server(), 
                handle_message_types_client()
            ])
        )


    # def test_3_verify_polling(self):
    #     """
    #     Test if polling may be stopped and started again
    #     """
    #     async def verify_poll_stopped(self: "TestAsyncZMQClient") -> None:
    #         await self.client.poll_responses()
    #         self.client.poll_timeout = 1000
    #         await self.client.poll_responses()
    #         self.done_queue.put(True)

    #     async def stop_poll(self: "TestAsyncZMQClient") -> None:
    #         await asyncio.sleep(0.1)
    #         self.client.stop_polling()
    #         await asyncio.sleep(0.1)
    #         self.client.stop_polling()
    #     # When the above two functions running, 
    #     # we dont send a message as the thread is also running
    #     get_current_async_loop().run_until_complete(
    #         asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)])
    #     )	

    #     self.assertTrue(self.done_queue.get())
    #     self.assertEqual(self.client.poll_timeout, 1000)


    def test_4_exit(self):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        request_message = RequestMessage.craft_with_message_type(
                                                            receiver_id=self.server_id,
                                                            sender_id=self.client_id,
                                                            message_type=EXIT
                                                        )
        self.client.socket.send_multipart(request_message.byte_array)
        self.assertTrue(self.done_queue.get())
        self._server_thread.join()



class TestMessageMappedClientPool(TestBrokerMixin):

    @classmethod
    def setUpClient(self):
        self.client = MessageMappedZMQClientPool(
                                    id='client-pool',
                                    client_ids=[self.client_id],
                                    server_ids=[self.server_id], 
                                    logger=self.logger,
                                    handshake=False
                                )
      
      
    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        async def test():
            self.client.handshake()
            await self.client.handshake_complete()
            for client in self.client.pool.values():
                self.assertTrue(client._monitor_socket is not None)
        get_current_async_loop().run_until_complete(test())
        # both directions
        # HANDSHAKE = 'HANDSHAKE' # 1 - find out if the server is alive    


    # def test_2_message_contract_types(self):
    #     """
    #     Once composition is checked, check different message types
    #     """
    #     # message types
    #     request_message = RequestMessage.craft_from_arguments(
    #                                                     receiver_id=self.server_id,
    #                                                     sender_id=self.client_id,
    #                                                     thing_id=self.thing_id,
    #                                                     objekt='some_prop',
    #                                                     operation='readProperty'
    #                                                 )
        
    #     async def handle_message_types_server():
    #         # server to client
    #         # REPLY = b'REPLY' # 4 - response for operation
    #         # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
    #         # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
    #         # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
    #         await self.server._handle_timeout(request_message) # 5
    #         await self.server._handle_invalid_message(request_message, SerializableData(Exception('test')))
    #         await self.server._handshake(request_message)
    #         await self.server.async_send_response(request_message)
    #         await self.server.async_send_response_with_message_type(request_message, ERROR, 
    #                                                                 SerializableData(Exception('test')))
        
    #     async def handle_message_types_client():
    #         """
    #         message types
    #         both directions
    #         HANDSHAKE = b'HANDSHAKE' # 1 - taken care by test_1...
            
    #         client to server 
    #         OPERATION = b'OPERATION' 2 - taken care by test_2_... # operation request from client to server
    #         EXIT = b'EXIT' # 3 - taken care by test_7... # exit the server
            
    #         server to client
    #         REPLY = b'REPLY' # 4 - response for operation
    #         TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
    #         EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
    #         INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
    #         SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' not yet tested # socket died - zmq's builtin event
            
    #         peer to peer
    #         INTERRUPT = b'INTERRUPT' not yet tested # interrupt a socket while polling 
    #         """
    #         msg = await self.client.async_recv_response(self.client_id, request_message.id)
    #         self.assertEqual(msg.type, TIMEOUT)
    #         self.validate_response_message(msg)

    #         msg = await self.client.async_recv_response(self.client_id, request_message.id)
    #         self.assertEqual(msg.type, INVALID_MESSAGE)
    #         self.validate_response_message(msg)

    #         msg = await self.client.socket.recv_multipart() # handshake don't come as response
    #         response_message = ResponseMessage(msg)
    #         self.assertEqual(response_message.type, HANDSHAKE)
    #         self.validate_response_message(response_message)

    #         msg = await self.client.async_recv_response(request_message.id)
    #         self.assertEqual(msg.type, REPLY)
    #         self.validate_response_message(msg)

    #         msg = await self.client.async_recv_response(request_message.id)
    #         self.assertEqual(msg.type, ERROR)
    #         self.validate_response_message(msg)

    #     # exit checked separately at the end
    #     get_current_async_loop().run_until_complete(
    #         asyncio.gather(*[
    #             handle_message_types_server(), 
    #             handle_message_types_client()
    #         ])
    #     )


    # def test_3_verify_polling(self):
    #     """
    #     Test if polling may be stopped and started again
    #     """
    #     async def verify_poll_stopped(self: "TestMessageMappedClientPool") -> None:
    #         await self.client.poll_responses()
    #         self.client.poll_timeout = 1000
    #         await self.client.poll_responses()
    #         self.done_queue.put(True)

    #     async def stop_poll(self: "TestMessageMappedClientPool") -> None:
    #         await asyncio.sleep(0.1)
    #         self.client.stop_polling()
    #         await asyncio.sleep(0.1)
    #         self.client.stop_polling()
    #     # When the above two functions running, 
    #     # we dont send a message as the thread is also running
    #     get_current_async_loop().run_until_complete(
    #         asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)])
    #     )	

    #     self.assertTrue(self.done_queue.get())
    #     self.assertEqual(self.client.poll_timeout, 1000)


    # def test_4_exit(self):
    #     """
    #     Test if exit reaches to server
    #     """
    #     # EXIT = b'EXIT' # 7 - exit the server
    #     request_message = RequestMessage.craft_with_message_type(
    #                                                         receiver_id=self.server_id,
    #                                                         sender_id=self.client_id,
    #                                                         message_type=EXIT
    #                                                     )
    #     self.client.async_send_request(request_message.byte_array)
    #     self.assertTrue(self.done_queue.get())
    #     self._server_thread.join()


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
