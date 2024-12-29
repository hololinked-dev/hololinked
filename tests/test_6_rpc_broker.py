import threading
import unittest
import zmq.asyncio

from hololinked.client.proxy import _Action
from hololinked.server.rpc_server import RPCServer
from hololinked.protocols.zmq.brokers import AsyncZMQClient, SyncZMQClient
from hololinked.utils import get_current_async_loop
from tests.test_3_brokers import ActionMixin

try:
    from .things import TestThing
except ImportError:
    from things import TestThing



class TestInprocRPCServer(ActionMixin):


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
        self.client = AsyncZMQClient(
                                id=self.client_id,
                                server_id=self.server_id, 
                                logger=self.logger,
                                context=self.context,
                                handshake=False,
                                transport='INPROC'
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
                                            target=self.server.run, 
                                            daemon=False # to test exit daemon must be False
                                        )
        self._server_thread.start()

   
    @classmethod
    def setUpClass(self):
        print(f"test ZMQ RPC Server {self.__name__}")
        self.context = zmq.asyncio.Context()
        super().setUpClass()
        self.setUpActions()

    
    def test_1_creation_defaults(self):
        self.assertTrue(self.server.req_rep_server.socket_address.startswith('inproc://'))
        self.assertTrue(self.server.event_publisher.socket_address.startswith('inproc://'))


    def test_2_handshake(self):
        self.client.handshake()


    def test_3_invoke_action(self):
        async def async_call():
            await self.echo_action.async_call('value')
            return self.echo_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, 'value')
        self.client.handshake() 


    def test_4_return_binary_value(self):

        async def async_call():
            await self.get_mixed_content_action.async_call()
            return self.get_mixed_content_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, ('foobar', b'foobar'))

        async def async_call():
            await self.get_serialized_data_action.async_call()
            return self.get_serialized_data_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, b'foobar')


    def test_5_server_execution_context(self):
       
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


    # def test_6_thing_execution_context(self):
        
    #     async def test_thing_execution_timeout():
    #         try:
    #             await self.echo_action.async_call('value')
    #         except Exception as ex:
    #             self.assertIsInstance(ex, TimeoutError)
    #             self.assertIn('Execution timeout occured', str(ex))
    #         else:
    #             self.assertTrue(False)


    def test_7_stop(self):
        self.server.stop()
       
        

from hololinked.protocols.zmq.server import ZMQServer

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
        # self.tcp_client = SyncZMQClient(
        #                         id=self.client_id,
        #                         server_id=self.server_id, 
        #                         logger=self.logger,
        #                         handshake=False,
        #                         transport='TCP',
        #                         tcp_socket_address='tcp://localhost:59000'
        #                     )


    @classmethod
    def startServer(self):
        self._server_thread = threading.Thread(
                                            target=self.server.run, 
                                            daemon=False # to test exit daemon must be False
                                        )
        self._server_thread.start()


    @classmethod
    def setUpActions(self):
        super().setUpActions()
        self.echo_action._zmq_client = self.ipc_client
        self.get_serialized_data_action._zmq_client = self.ipc_client
        self.get_mixed_content_action._zmq_client = self.ipc_client
        self.sleep_action._zmq_client = self.ipc_client


    def test_1_creation_defaults(self):
        super().test_1_creation_defaults()
        self.assertTrue(self.server.ipc_server.socket_address.startswith('ipc://'))
        self.assertTrue(self.server.tcp_server.socket_address.startswith('tcp://'))
        self.assertTrue(self.server.tcp_server.socket_address.endswith(':59000'))


    def test_2_handshake(self):
        super().test_2_handshake()
        self.ipc_client.handshake()    


    def test_3_invoke_action(self):
        super().test_3_invoke_action()
        return_value = self.echo_action('ipc_value')
        self.assertEqual(return_value, 'ipc_value')
        

    def test_4_return_binary_value(self):
        super().test_4_return_binary_value()
        return_value = self.get_mixed_content_action()
        self.assertEqual(return_value, ('foobar', b'foobar'))
        return_value = self.get_serialized_data_action()
        self.assertEqual(return_value, b'foobar')


    def test_5_server_execution_context(self):
        super().test_5_server_execution_context()
        # test oneway action
        self.echo_action('ipc_value_2')
        self.echo_action.oneway('ipc_value_3')
        self.assertEqual(self.echo_action.last_return_value, 'ipc_value_2')
        return_value = self.echo_action('ipc_value_4')
        self.assertEqual(return_value, 'ipc_value_4')






if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner
    unittest.main(testRunner=TestRunner())