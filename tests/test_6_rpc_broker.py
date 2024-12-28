import threading
import typing
import unittest
import multiprocessing 
import logging
import zmq.asyncio

from hololinked.client.proxy import _Action
from hololinked.server import Thing
from hololinked.client import ObjectProxy
from hololinked.constants import ResourceTypes
from hololinked.server.dataklasses import ZMQResource
from hololinked.server.rpc_server import RPCServer
from hololinked.protocols.zmq.brokers import AsyncZMQClient, SyncZMQClient
from hololinked.protocols.zmq.message import SerializableData
from hololinked.utils import get_current_async_loop, get_default_logger
from tests.test_3_brokers import ActionMixin, TestBrokerMixin
try:
    from .things import TestThing, OceanOpticsSpectrometer
    from .utils import TestCase
except ImportError:
    from things import TestThing, OceanOpticsSpectrometer
    from utils import TestCase




class TestRPCBroker(ActionMixin):


    @classmethod
    def setUpServer(self):
        self.server = RPCServer(
                            id=self.server_id,
                            things=[self.thing],
                            logger=self.logger,
                            context=self.context
                        )
    """
    Base class: BaseZMQ, BaseAsyncZMQ, BaseSyncZMQ
    Servers: BaseZMQServer, AsyncZMQServer, ZMQServerPool
    Clients: BaseZMQClient, SyncZMQClient, AsyncZMQClient, MessageMappedZMQClientPool
    """

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
                                            daemon=True
                                        )
        self._server_thread.start()

   
    @classmethod
    def setUpClass(self):
        print(f"test ZMQ Message Broker {self.__name__}")
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
            else:
                self.assertTrue(False)        
        get_current_async_loop().run_until_complete(test_execution_timeout())
       
        async def test_invokation_timeout():
            try:
                self.sleep_action._invokation_timeout = 1
                await self.sleep_action.async_call()
            except Exception as ex:
                self.assertIsInstance(ex, TimeoutError)
            else:
                self.assertTrue(False)
        get_current_async_loop().run_until_complete(test_invokation_timeout())

        # async def test_oneway():
        #     self.echo_action.oneway('value')
        #     return_value = await self.echo_action.async_call('value2')
        #     self.assertEqual(return_value, 'value2')
        # get_current_async_loop().run_until_complete(test_oneway())

    # def test_6_thing_execution_context(self):
    #     pass 


    # def test_7_stop_polling(self):
    #     self.server.stop_polling()

        
            

if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner

    unittest.main(testRunner=TestRunner())