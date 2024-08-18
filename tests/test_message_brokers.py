import threading, asyncio
import logging, multiprocessing, unittest
from uuid import UUID
from hololinked.server.zmq_message_brokers import (CM_INDEX_ADDRESS, CM_INDEX_CLIENT_TYPE, CM_INDEX_MESSAGE_TYPE,
                CM_INDEX_MESSAGE_ID, CM_INDEX_SERVER_EXEC_CONTEXT, CM_INDEX_THING_ID, CM_INDEX_OPERATION, CM_INDEX_OBJECT, CM_INDEX_ARGUMENTS,
                CM_INDEX_THING_EXEC_CONTEXT)  
from hololinked.server.zmq_message_brokers import (SM_INDEX_ADDRESS, SM_INDEX_MESSAGE_TYPE, SM_INDEX_MESSAGE_ID,
                                    SM_INDEX_SERVER_TYPE, SM_INDEX_DATA, SM_INDEX_PRE_ENCODED_DATA)
from hololinked.server.zmq_message_brokers import PROXY, REPLY, TIMEOUT, INVALID_MESSAGE, HANDSHAKE, EXIT, OPERATION
from hololinked.server.zmq_message_brokers import AsyncPollingZMQServer, AsyncZMQClient, SyncZMQClient
from hololinked.server.zmq_message_brokers import default_server_execution_context
from hololinked.server.utils import get_current_async_loop, get_default_logger

try:
    from .utils import TestCase, TestRunner
    # from .things import TestThing, start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    # from things import TestThing, start_thing_forked 


def start_server(server : AsyncPollingZMQServer, cls : "TestMessageBrokers",
                done_queue : multiprocessing.Queue = None):
    event_loop = get_current_async_loop()
    
    async def run():
        while True:
            message = await server.async_recv_request()
            cls.last_server_message = message
            if message[CM_INDEX_MESSAGE_TYPE] == b'EXIT':
                break    
            await asyncio.sleep(0.1)
    event_loop.run_until_complete(run())
    if done_queue:
        done_queue.put(True)



class TestMessageBrokers(TestCase):

    @classmethod
    def setUpClass(self):
        print("test ZMQ Message Brokers")
        logger = get_default_logger('test-message-brokers', logging.ERROR)
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.server_message_broker = AsyncPollingZMQServer(
                                                instance_name='test-message-broker',
                                                server_type='RPC',
                                                logger=logger
                                            )
        self._server_thread = threading.Thread(target=start_server, args=(self.server_message_broker, self, self.done_queue),
                            daemon=True)
        self._server_thread.start()
        self.client_message_broker = SyncZMQClient(server_instance_name='test-message-broker', logger=logger,
                                                identity='test-client', client_type=PROXY, handshake=False)
        
    @classmethod
    def tearDownClass(self):
        # print("tear down test RPC")
        # self.thing_client.exit()
        pass 

    def test_1_handshake_complete(self):
        self.client_message_broker.handshake()
        self.assertTrue(self.client_message_broker._monitor_socket is not None)

    def test_2_message_contract(self):
        # first test the length 
        client_message1 = self.client_message_broker.craft_request_from_arguments(b'test-device', b'readProperty', 
                                                                                b'someProp')
        self.assertEqual(len(client_message1), 11)
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

        server_message1 = self.server_message_broker.craft_response_from_arguments(b'test-device', PROXY, REPLY)
        self.assertEqual(len(server_message1), 7)
        for msg in server_message1:
            self.assertTrue(isinstance(msg, bytes))
        self.assertEqual(server_message1[SM_INDEX_ADDRESS], b'test-device')
        self.assertEqual(server_message1[SM_INDEX_SERVER_TYPE], b'RPC')
        self.assertEqual(server_message1[SM_INDEX_MESSAGE_TYPE], REPLY)
        self.assertEqual(server_message1[SM_INDEX_DATA], self.server_message_broker.zmq_serializer.dumps(None))
        self.assertEqual(server_message1[SM_INDEX_PRE_ENCODED_DATA], b'')


        # test specific way of crafting messages
        client_message2 = self.client_message_broker.craft_empty_message_with_type(b'EXIT')
        self.assertEqual(len(client_message2), 11)
        for msg in client_message2:
            self.assertTrue(isinstance(msg, bytes))

        server_message2 = self.server_message_broker.craft_reply_from_client_message(client_message2)
        self.assertEqual(len(server_message2), 7)
        self.assertEqual(server_message2[CM_INDEX_MESSAGE_TYPE], REPLY)
        for msg in server_message2:
            self.assertTrue(isinstance(msg, bytes))


    def test_3_message_contract_types(self):
        client_message = self.client_message_broker.craft_request_from_arguments(b'test-device', b'readProperty', 
                                                                                b'someProp')
        
        async def handle_message_types():
            client_message[CM_INDEX_ADDRESS] = b'test-client'
            await self.server_message_broker._handle_timeout(client_message)
            await self.server_message_broker._handle_invalid_message(client_message, Exception('test'))
            await self.server_message_broker._handshake(client_message)
            await self.server_message_broker.async_send_response(client_message)
        get_current_async_loop().run_until_complete(handle_message_types())
        
        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], TIMEOUT)

        msg = self.client_message_broker.recv_response(client_message[CM_INDEX_MESSAGE_ID])
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], INVALID_MESSAGE)

        msg = self.client_message_broker.socket.recv_multipart()
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], HANDSHAKE)

        msg = self.client_message_broker.socket.recv_multipart()
        self.assertEqual(msg[CM_INDEX_MESSAGE_TYPE], REPLY)

        client_message[CM_INDEX_ADDRESS] = b'test-message-broker'
        client_message[CM_INDEX_MESSAGE_TYPE] = EXIT
        self.client_message_broker.socket.send_multipart(client_message)

        self.assertTrue(self.done_queue.get())
        self._server_thread.join()


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())