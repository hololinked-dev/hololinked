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
    def setUpClass(cls):
        super().setUpClass()
        print(f"test ZMQ socket creation with {cls.__name__}")

    def test_1_socket_creation_defaults(self):
        """check the default settings of socket creation - an IPC socket which is a ROUTER and async"""
        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=zmq.asyncio.Context(),
        )
        self.assertIsInstance(socket, zmq.asyncio.Socket)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(socket.socket_type == zmq.ROUTER)
        self.assertTrue(socket_address.startswith("ipc://"))
        self.assertTrue(socket_address.endswith(".ipc"))
        socket.close()

    def test_2_context_options(self):
        """
        Check that context and socket type are as expected.
        Async context should be used for async socket and sync context for sync socket.
        """
        context = zmq.Context()
        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
        )
        self.assertTrue(isinstance(socket, zmq.Socket))
        self.assertTrue(not isinstance(socket, zmq.asyncio.Socket))
        socket.close()
        context.term()

        context = zmq.asyncio.Context()
        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
        )
        self.assertTrue(isinstance(socket, zmq.Socket))
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()
        context.term()

    def test_3_transport_options(self):
        """check only three transport options are supported"""
        context = zmq.asyncio.Context()
        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point="tcp://*:5555",
        )
        for sock_addr in [socket_address, socket.getsockopt_string(zmq.LAST_ENDPOINT)]:
            self.assertTrue(sock_addr.startswith("tcp://"))
            self.assertTrue(sock_addr.endswith(":5555"))
        socket.close()

        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point="IPC",
        )

        self.assertEqual(socket_address, socket.getsockopt_string(zmq.LAST_ENDPOINT))
        self.assertTrue(socket_address.startswith("ipc://"))
        self.assertTrue(socket_address.endswith(".ipc"))
        socket.close()

        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point="INPROC",
        )
        self.assertEqual(socket_address, socket.getsockopt_string(zmq.LAST_ENDPOINT))
        self.assertTrue(socket_address.startswith("inproc://"))
        self.assertTrue(socket_address.endswith("test-server"))
        socket.close()
        context.term()

        # Specify transport as enum and do the same tests
        context = zmq.Context()
        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point=ZMQ_TRANSPORTS.INPROC,
        )
        self.assertTrue(socket_address.startswith("inproc://"))
        self.assertTrue(socket_address.endswith("test-server"))
        socket.close()

        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point=ZMQ_TRANSPORTS.IPC,
        )
        self.assertTrue(socket_address.startswith("ipc://"))
        self.assertTrue(socket_address.endswith(".ipc"))
        socket.close()

        socket, socket_address = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point=ZMQ_TRANSPORTS.TCP,
        )
        self.assertTrue(socket_address.startswith("tcp://"))
        # Strip the port number from TCP address and check if it's a valid port integer
        host, port_str = socket_address.rsplit(":", 1)
        self.assertTrue(port_str.isdigit())
        self.assertTrue(0 < int(port_str) < 65536)
        socket.close()
        context.term()

        # check that other transport options raise error
        context = zmq.asyncio.Context()
        self.assertRaises(
            NotImplementedError,
            lambda: BaseZMQ.get_socket(
                server_id="test-server",
                socket_id="test-server",
                node_type="server",
                context=context,
                access_point="PUB",
            ),
        )
        context.term()

    def test_4_socket_options(self):
        """check that socket options are as expected"""
        context = zmq.asyncio.Context()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.ROUTER,
        )
        self.assertTrue(socket.socket_type == zmq.ROUTER)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.DEALER,
        )
        self.assertTrue(socket.socket_type == zmq.DEALER)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.PUB,
        )
        self.assertTrue(socket.socket_type == zmq.PUB)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.SUB,
        )
        self.assertTrue(socket.socket_type == zmq.SUB)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.PAIR,
        )
        self.assertTrue(socket.socket_type == zmq.PAIR)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.PUSH,
        )
        self.assertTrue(socket.socket_type == zmq.PUSH)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()

        socket, _ = BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            socket_type=zmq.PULL,
        )
        self.assertTrue(socket.socket_type == zmq.PULL)
        self.assertTrue(socket.getsockopt_string(zmq.IDENTITY) == "test-server")
        self.assertTrue(isinstance(socket, zmq.asyncio.Socket))
        socket.close()
        context.term()


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())


"""
TODO:
1. check node_type values
2. check if TCP socket search happens
"""
