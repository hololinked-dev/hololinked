import threading, asyncio
import logging, multiprocessing, unittest

from hololinked.core.zmq.message import (ERROR, EXIT, OPERATION, HANDSHAKE, REPLY, 
                                PreserializedData, RequestHeader, RequestMessage, SerializableData) # client to server
from hololinked.core.zmq.message import (TIMEOUT, INVALID_MESSAGE, ERROR, 
                                ResponseMessage, ResponseHeader) # server to client
from hololinked.core.zmq.brokers import AsyncZMQServer, MessageMappedZMQClientPool, SyncZMQClient, AsyncZMQClient
from hololinked.utils import get_current_async_loop, get_default_logger

try:
    from .utils import TestRunner
    from .test_1_message import MessageValidatorMixin
    from .things.starter import run_zmq_server
    from .things import TestThing
except ImportError:
    from utils import TestRunner
    from test_1_message import MessageValidatorMixin
    from things.starter import run_zmq_server
    from things import TestThing



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
        self.sync_client = None 
        self.async_client = None

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



class TestBasicServerAndClient(TestBrokerMixin):

    @classmethod
    def setUpClient(self):
        super().setUpClient()
        self.sync_client = SyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        self.client = self.sync_client
        

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
            await self.server._handle_error_message(request_message, Exception('test')) # 6
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
        self.assertEqual(msg.type, ERROR)
        self.validate_response_message(msg)
       
        msg = self.client.recv_response(request_message.id)
        self.assertEqual(msg.type, REPLY)
        self.validate_response_message(msg)

        msg = self.client.recv_response(request_message.id)
        # custom crafted explicitly to be ERROR
        self.assertEqual(msg.type, ERROR)
        self.validate_response_message(msg)

        self.client.handshake()


    def test_3_verify_polling(self):
        """
        Test if polling may be stopped and started again
        """
        async def verify_poll_stopped(self: TestBasicServerAndClient) -> None:
            await self.server.poll_requests()
            self.server.poll_timeout = 1000
            await self.server.poll_requests()
            self.done_queue.put(True)

        async def stop_poll(self: TestBasicServerAndClient) -> None:
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
        self.client.handshake()


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
        

    # def test_5_server_disconnected(self):
      
    #     self.server.exit() # exit causes the server socket to send a ZMQ builtin termination message to the client
    #     # we need to complete all the tasks before we can exit other some loosely hanging tasks (which will anyway complete 
    #     # before the script quits) has invalid sockets because of the exit

    #     # SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # socket died - zmq's builtin event
    #     with self.assertRaises(ConnectionAbortedError) as ex:
    #         self.client.recv_response(message_id=b'not-necessary')
    #     self.assertTrue(str(ex.exception).startswith(f"server disconnected for {self.client_id}")) 
        
        # peer to peer
        # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling 
        # first test the length 



class TestAsyncZMQClient(TestBrokerMixin):

    @classmethod
    def setUpClient(self):
        self.async_client = AsyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                handshake=False
                            )
        self.client = self.async_client

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.client = self.async_client


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
            await self.server._handle_error_message(request_message, Exception('test'))
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
            self.assertEqual(msg.type, ERROR)
            self.validate_response_message(msg)

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
        

    def test_3_exit(self):
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
        
        async def handle_message_types():
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
            self.client.start_polling()
            
            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server._handle_timeout(request_message, timeout_type='invokation') # 5
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, TIMEOUT)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server._handle_invalid_message(request_message, SerializableData(Exception('test')))
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, INVALID_MESSAGE)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server._handshake(request_message)
            msg = await self.client.pool[self.client_id].socket.recv_multipart() # handshake don't come as response
            response_message = ResponseMessage(msg)
            self.assertEqual(response_message.type, HANDSHAKE)
            self.validate_response_message(response_message)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server.async_send_response(request_message)
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, REPLY)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server.async_send_response_with_message_type(request_message, ERROR, 
                                                                    SerializableData(Exception('test')))
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, ERROR)
            self.validate_response_message(msg)

            self.client.stop_polling()

        # exit checked separately at the end
        get_current_async_loop().run_until_complete(
            asyncio.gather(*[
                handle_message_types()
            ])
        )
        

    def test_3_verify_polling(self):
        """
        Test if polling may be stopped and started again
        """
        async def verify_poll_stopped(self: "TestMessageMappedClientPool") -> None:
            await self.client.poll_responses()
            self.client.poll_timeout = 1000
            await self.client.poll_responses()
            self.done_queue.put(True)

        async def stop_poll(self: "TestMessageMappedClientPool") -> None:
            await asyncio.sleep(0.1)
            self.client.stop_polling()
            await asyncio.sleep(0.1)
            self.client.stop_polling()
        # When the above two functions running, 
        # we dont send a message as the thread is also running
        get_current_async_loop().run_until_complete(
            asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)])
        )	
        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.client.poll_timeout, 1000)
        

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
        self.client[self.client_id].socket.send_multipart(request_message.byte_array)
        self.assertTrue(self.done_queue.get())
        self._server_thread.join()
        


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestBasicServerAndClient))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestAsyncZMQClient))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestMessageMappedClientPool))
    return suite

if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
