import threading
import typing
import unittest
import multiprocessing 
import logging
import zmq.asyncio

from hololinked.client.proxy import _Action
from hololinked.server import Thing
from hololinked.client import ObjectProxy
from hololinked.server.constants import ResourceTypes
from hololinked.server.dataklasses import ZMQResource
from hololinked.server.protocols.zmq import RPCServer
from hololinked.server.protocols.zmq.brokers import AsyncZMQClient, SyncZMQClient
from hololinked.server.protocols.zmq.message import SerializableData
from hololinked.server.utils import get_current_async_loop, get_default_logger
try:
    from .things import TestThing, OceanOpticsSpectrometer
    from .utils import TestCase
except ImportError:
    from things import TestThing, OceanOpticsSpectrometer
    from utils import TestCase




class TestRPCBroker(TestCase):


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
        self.server_id = 'test-server'
        self.client_id = 'test-client'
        self.thing_id = 'test-thing'
        self.logger = get_default_logger('test-message-broker', logging.DEBUG)        
        self.done_queue = multiprocessing.Queue()
        self.last_server_message = None
        self.context = zmq.asyncio.Context()
        self.setUpThing()
        self.setUpServer()
        self.setUpClient()
        self.startServer()

        

    def test_1_creation_defaults(self):
        self.assertTrue(self.server.inproc_server.socket_address.startswith('inproc://'))
        self.assertTrue(self.server.event_publisher.socket_address.startswith('inproc://'))


    def test_2_handshake(self):
        self.client.handshake()


    def test_3_invoke_action(self):
        resource_info = ZMQResource(
                            what=ResourceTypes.ACTION, 
                            class_name='TestThing', 
                            id='test-thing',
                            obj_name='test_echo', 
                            qualname='TestThing.test_echo', 
                            doc="returns value as it is to the client",
                            request_as_argument=False
                        )
        self.echo_action = _Action(
                                sync_client=None,
                                resource_info=resource_info,
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )
        
        async def async_call():
            await self.echo_action.async_call('value')
            return self.echo_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, 'value')
        self.client.handshake() 


    # def test_4_server_execution_context(self):
    #     resource_info = ZMQResource(
    #                         what=ResourceTypes.ACTION, 
    #                         class_name='TestThing', 
    #                         id='test-thing',
    #                         obj_name='sleep', 
    #                         qualname='TestThing.sleep', 
    #                         doc="returns value as it is to the client",
    #                         request_as_argument=False
    #                     )
    #     self.sleep_action = _Action(
    #                             sync_client=None,
    #                             resource_info=resource_info,
    #                             invokation_timeout=5, 
    #                             execution_timeout=5, 
    #                             async_client=self.client, 
    #                             schema_validator=None
    #                         )
    #     async def async_call():
    #         await self.sleep_action.async_call()
    #         return self.echo_action.last_return_value
    #     result = get_current_async_loop().run_until_complete(async_call())
    #     self.assertEqual(result, 6)

    
    def test_5_return_value(self):
        resource_info = ZMQResource(
                            what=ResourceTypes.ACTION, 
                            class_name='TestThing', 
                            id='test-thing',
                            obj_name='get_serialized_data', 
                            qualname='TestThing.get_serialized_data', 
                            doc="returns value as it is to the client",
                            request_as_argument=False
                        )
        self.echo_action = _Action(
                                sync_client=None,
                                resource_info=resource_info,
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )
        async def async_call():
            await self.echo_action.async_call('value')
            return self.echo_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, 'value')
        self.client.handshake()

        resource_info = ZMQResource(
                                what=ResourceTypes.ACTION, 
                                class_name='TestThing', 
                                id='test-thing',
                                obj_name='get_mixed_content_type', 
                                qualname='TestThing.get_mixed_content_type', 
                                doc="returns mixed content type to the client",
                                request_as_argument=False
                            )
        self.echo_action = _Action(
                                sync_client=None,
                                resource_info=resource_info,
                                invokation_timeout=5, 
                                execution_timeout=5, 
                                async_client=self.client, 
                                schema_validator=None
                            )
        async def async_call():
            await self.echo_action.async_call()
            return self.echo_action.last_return_value
        result = get_current_async_loop().run_until_complete(async_call())
        self.assertEqual(result, ('foobar', b'foorbar'))
        self.client.handshake()


    def test_6_thing_execution_context(self):
        pass 


    def test_7_stop_polling(self):
        self.server.stop_polling()

        
            

if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner

    unittest.main(testRunner=TestRunner())