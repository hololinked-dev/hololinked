import threading, asyncio
import logging, multiprocessing, unittest

from hololinked.core.zmq.message import (
    ERROR,
    EXIT,
    OPERATION,
    HANDSHAKE,
    REPLY,
    PreserializedData,
    RequestHeader,
    RequestMessage,
    SerializableData,
)  # client to server
from hololinked.core.zmq.message import (
    TIMEOUT,
    INVALID_MESSAGE,
    ERROR,
    ResponseMessage,
    ResponseHeader,
)  # server to client
from hololinked.core.zmq.brokers import (
    AsyncZMQServer,
    MessageMappedZMQClientPool,
    SyncZMQClient,
    AsyncZMQClient,
)
from hololinked.utils import get_current_async_loop, get_default_logger

try:
    from .utils import TestRunner
    from .test_01_message import MessageValidatorMixin
    from .things.starter import run_zmq_server
    from .things import TestThing
except ImportError:
    from utils import TestRunner
    from test_01_message import MessageValidatorMixin
    from things.starter import run_zmq_server
    from things import TestThing


class TestBrokerMixin(MessageValidatorMixin):
    """Tests Individual ZMQ Server"""

    @classmethod
    def setUpServer(cls):
        cls.server = AsyncZMQServer(id=cls.server_id, logger=cls.logger)

    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

    @classmethod
    def setUpClient(cls):
        cls.sync_client = None
        cls.async_client = None

    @classmethod
    def setUpThing(cls):
        cls.thing = TestThing(id=cls.thing_id, logger=cls.logger, remote_accessible_logger=True)

    @classmethod
    def startServer(cls):
        cls._server_thread = threading.Thread(
            target=run_zmq_server, args=(cls.server, cls, cls.done_queue), daemon=True
        )
        cls._server_thread.start()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print(f"test ZMQ message brokers {cls.__name__}")
        cls.logger = get_default_logger("test-message-broker", logging.ERROR)
        cls.done_queue = multiprocessing.Queue()
        cls.last_server_message = None
        cls.setUpThing()
        cls.setUpServer()
        cls.setUpClient()
        cls.startServer()


class TestBasicServerAndClient(TestBrokerMixin):
    @classmethod
    def setUpClient(cls):
        super().setUpClient()
        cls.sync_client = SyncZMQClient(
            id=cls.client_id,
            server_id=cls.server_id,
            logger=cls.logger,
            handshake=False,
        )
        cls.client = cls.sync_client

    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """
        self.client.handshake()
        self.assertTrue(self.client._monitor_socket is not None)
        self.assertTrue(self.client._monitor_socket in self.client.poller)
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
            objekt="some_prop",
            operation="readProperty",
        )

        async def handle_message_types_server():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            await self.server._handle_timeout(request_message, timeout_type="execution")  # 5
            await self.server._handle_invalid_message(request_message, SerializableData(Exception("test")))  # 7
            await self.server._handshake(request_message)  # 1
            await self.server._handle_error_message(request_message, Exception("test"))  # 6
            await self.server.async_send_response(request_message)  # 4
            await self.server.async_send_response_with_message_type(
                request_message, ERROR, SerializableData(Exception("test"))
            )  # 6

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

        msg = self.client.socket.recv_multipart()  # handshake dont come as response
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
        get_current_async_loop().run_until_complete(asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)]))

        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.server.poll_timeout, 1000)
        self.client.handshake()

    @classmethod
    def tearDownClass(cls):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        request_message = RequestMessage.craft_with_message_type(
            receiver_id=cls.server_id, sender_id=cls.client_id, message_type=EXIT
        )
        cls.client.socket.send_multipart(request_message.byte_array)

        # TODO - fix the following, somehow socket is not closing fully,
        # although we have previously tested this and its known to work.
        # try:
        #     cls.client.recv_response(message_id=b'not-necessary')
        #     assert False, "Expected ConnectionAbortedError"
        # except ConnectionAbortedError as ex:
        #     assert str(ex).startswith(f"server disconnected for {cls.client_id}"), f"Unexpected error message: {str(ex)}"

        done = cls.done_queue.get(timeout=3)
        if done:
            cls._server_thread.join()
        else:
            print("Server did not properly process exit request")
        super().tearDownClass()

    # TODO
    # peer to peer
    # INTERRUPT = b'INTERRUPT' # interrupt a socket while polling
    # first test the length


class TestAsyncZMQClient(TestBrokerMixin):
    @classmethod
    def setUpClient(cls):
        cls.async_client = AsyncZMQClient(
            id=cls.client_id,
            server_id=cls.server_id,
            logger=cls.logger,
            handshake=False,
        )
        cls.client = cls.async_client

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_1_handshake_complete(self):
        """
        Test handshake so that client can connect to server. Once client connects to server,
        verify a ZMQ internal monitoring socket is available.
        """

        async def test():
            self.client.handshake()
            await self.client.handshake_complete()
            self.assertTrue(self.client._monitor_socket is not None)
            self.assertTrue(self.client._monitor_socket in self.client.poller)

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
            objekt="some_prop",
            operation="readProperty",
        )

        async def handle_message_types_server():
            # server to client
            # REPLY = b'REPLY' # 4 - response for operation
            # TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
            # EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
            # INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
            await self.server._handle_timeout(request_message, timeout_type="invokation")  # 5
            await self.server._handle_invalid_message(request_message, SerializableData(Exception("test1")))
            await self.server._handshake(request_message)
            await self.server._handle_error_message(request_message, Exception("test2"))
            await self.server.async_send_response(request_message)
            await self.server.async_send_response_with_message_type(
                request_message, ERROR, SerializableData(Exception("test3"))
            )

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

            msg = await self.client.socket.recv_multipart()  # handshake don't come as response
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
            asyncio.gather(*[handle_message_types_server(), handle_message_types_client()])
        )

    @classmethod
    def tearDownClass(cls):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        request_message = RequestMessage.craft_with_message_type(
            receiver_id=cls.server_id, sender_id=cls.client_id, message_type=EXIT
        )
        cls.client.socket.send_multipart(request_message.byte_array)
        done = cls.done_queue.get(timeout=3)

        # TODO - check server disconnected like previous test

        if done:
            cls._server_thread.join()
        else:
            print("Server did not properly process exit request")
        super().tearDownClass()


class TestMessageMappedClientPool(TestBrokerMixin):
    @classmethod
    def setUpClient(cls):
        cls.client = MessageMappedZMQClientPool(
            id="client-pool",
            client_ids=[cls.client_id],
            server_ids=[cls.server_id],
            logger=cls.logger,
            handshake=False,
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
                self.assertTrue(client._monitor_socket in self.client.poller)

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
            objekt="some_prop",
            operation="readProperty",
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
            await self.server._handle_timeout(request_message, timeout_type="invokation")  # 5
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, TIMEOUT)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server._handle_invalid_message(request_message, SerializableData(Exception("test")))
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, INVALID_MESSAGE)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server._handshake(request_message)
            msg = await self.client.pool[self.client_id].socket.recv_multipart()  # handshake don't come as response
            response_message = ResponseMessage(msg)
            self.assertEqual(response_message.type, HANDSHAKE)
            self.validate_response_message(response_message)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server.async_send_response(request_message)
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, REPLY)
            self.validate_response_message(msg)

            self.client.events_map[request_message.id] = self.client.event_pool.pop()
            await self.server.async_send_response_with_message_type(
                request_message, ERROR, SerializableData(Exception("test"))
            )
            msg = await self.client.async_recv_response(self.client_id, request_message.id)
            self.assertEqual(msg.type, ERROR)
            self.validate_response_message(msg)

            self.client.stop_polling()

        # exit checked separately at the end
        get_current_async_loop().run_until_complete(asyncio.gather(*[handle_message_types()]))

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
        get_current_async_loop().run_until_complete(asyncio.gather(*[verify_poll_stopped(self), stop_poll(self)]))
        self.assertTrue(self.done_queue.get())
        self.assertEqual(self.client.poll_timeout, 1000)

    @classmethod
    def tearDownClass(cls):
        """
        Test if exit reaches to server
        """
        # EXIT = b'EXIT' # 7 - exit the server
        request_message = RequestMessage.craft_with_message_type(
            receiver_id=cls.server_id, sender_id=cls.client_id, message_type=EXIT
        )
        cls.client[cls.client_id].socket.send_multipart(request_message.byte_array)
        done = cls.done_queue.get(timeout=3)
        if done:
            cls._server_thread.join()
        else:
            print("Server did not process exit message correctly")
        super().tearDownClass()


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestBasicServerAndClient))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestAsyncZMQClient))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestMessageMappedClientPool))
    return suite


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
