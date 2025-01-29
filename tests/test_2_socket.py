import unittest
import zmq.asyncio

from hololinked.core.zmq.brokers import BaseZMQ
from hololinked.constants import ZMQ_TRANSPORTS

try:
    from .utils import TestCase, TestRunner
except ImportError:
    from utils import TestCase, TestRunner
 


class TestSocket(TestCase):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        print(f"test ZMQ socket creation with {self.__name__}")


    def test_1_socket_creation_defaults(self):
        socket, socket_address = BaseZMQ.get_socket(
                                                id='test-server',
                                                node_type='server',
                                                context=zmq.asyncio.Context()
                                            )
        self.assertIsInstance(socket, zmq.asyncio.Socket)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(socket.socket_type == zmq.ROUTER)
        self.assertTrue(socket_address.startswith('ipc://'))
        self.assertTrue(socket_address.endswith('.ipc'))


    def test_2_context_options(self):
        """check that context and socket type are as expected"""
        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.Context()
                            )
        self.assertTrue(isinstance(socket, zmq.Socket))
        self.assertTrue(not isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context()
                            )       
        self.assertTrue(isinstance(socket, zmq.Socket))
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))


    def test_3_transport_options(self):
        """check only three transport options are supported"""
        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.asyncio.Context(),
                                        transport='TCP',
                                        socket_address='tcp://*:5555'
                                    )
        self.assertTrue(socket_address.startswith('tcp://'))
        self.assertTrue(socket_address.endswith(':5555'))

        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.asyncio.Context(),
                                        transport='IPC',
                                    )
        self.assertTrue(socket_address.startswith('ipc://'))
        self.assertTrue(socket_address.endswith('.ipc'))

        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.asyncio.Context(),
                                        transport='INPROC',
                                    )        
        self.assertTrue(socket_address.startswith('inproc://'))
        self.assertTrue(socket_address.endswith('test-server'))

        
        self.assertRaises(NotImplementedError, lambda: BaseZMQ.get_socket(
                                                                    id='test-server',
                                                                    node_type='server',
                                                                    context=zmq.asyncio.Context(),
                                                                    transport='PUB',
                                                                ))
        
        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.Context(),
                                        transport=ZMQ_TRANSPORTS.INPROC,
                                    )
        self.assertTrue(socket_address.startswith('inproc://'))
        self.assertTrue(socket_address.endswith('test-server'))
        
        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.Context(),
                                        transport=ZMQ_TRANSPORTS.IPC,
                                    )
        self.assertTrue(socket_address.startswith('ipc://'))
        self.assertTrue(socket_address.endswith('.ipc'))

        socket, socket_address = BaseZMQ.get_socket(
                                        id='test-server',
                                        node_type='server',
                                        context=zmq.Context(),
                                        transport=ZMQ_TRANSPORTS.TCP,
                                        socket_address='tcp://*:5556'
                                    )
        self.assertTrue(socket_address.startswith('tcp://'))
        self.assertTrue(socket_address.endswith(':5556'))
        
        
    def test_4_socket_options(self):
        """check that socket options are as expected"""
        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.ROUTER
                            )
        self.assertTrue(socket.socket_type == zmq.ROUTER)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.DEALER
                            )
        self.assertTrue(socket.socket_type == zmq.DEALER)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.PUB
                            )
        self.assertTrue(socket.socket_type == zmq.PUB)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.SUB
                            )
        self.assertTrue(socket.socket_type == zmq.SUB)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.PAIR
                            )
        self.assertTrue(socket.socket_type == zmq.PAIR)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        
        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.PUSH
                            )
        self.assertTrue(socket.socket_type == zmq.PUSH)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))

        socket, _ = BaseZMQ.get_socket(
                                id='test-server',
                                node_type='server',
                                context=zmq.asyncio.Context(),
                                socket_type=zmq.PULL
                            )
        self.assertTrue(socket.socket_type == zmq.PULL)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == 'test-server')
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))


   

if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())