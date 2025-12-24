import pytest
import zmq.asyncio

from hololinked.config import global_config
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.zmq.brokers import BaseZMQ


def test_01_socket_creation_defaults():
    """check the default settings of socket creation - an IPC socket which is a ROUTER and async"""
    socket, socket_address = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=global_config.zmq_context(),
    )
    assert isinstance(socket, zmq.asyncio.Socket)
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert socket.socket_type == zmq.ROUTER
    assert socket_address.startswith("ipc://")
    assert socket_address.endswith(".ipc")
    socket.close()


def test_02_context_options():
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
    assert isinstance(socket, zmq.Socket)
    assert not isinstance(socket, zmq.asyncio.Socket)
    socket.close()
    context.term()

    context = zmq.asyncio.Context()
    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
    )
    assert isinstance(socket, zmq.Socket)
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()
    context.term()


def test_03_transport_options():
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
        assert sock_addr.startswith("tcp://")
        assert sock_addr.endswith(":5555")
    socket.close()

    socket, socket_address = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        access_point="IPC",
    )

    assert socket_address == socket.getsockopt_string(zmq.LAST_ENDPOINT)
    assert socket_address.startswith("ipc://")
    assert socket_address.endswith(".ipc")
    socket.close()

    socket, socket_address = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        access_point="INPROC",
    )
    assert socket_address == socket.getsockopt_string(zmq.LAST_ENDPOINT)
    assert socket_address.startswith("inproc://")
    assert socket_address.endswith("test-server")
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
    assert socket_address.startswith("inproc://")
    assert socket_address.endswith("test-server")
    socket.close()

    socket, socket_address = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        access_point=ZMQ_TRANSPORTS.IPC,
    )
    assert socket_address.startswith("ipc://")
    assert socket_address.endswith(".ipc")
    socket.close()

    socket, socket_address = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        access_point=ZMQ_TRANSPORTS.TCP,
    )
    assert socket_address.startswith("tcp://")
    # Strip the port number from TCP address and check if it's a valid port integer
    host, port_str = socket_address.rsplit(":", 1)
    assert port_str.isdigit()
    assert 0 < int(port_str) < 65536
    socket.close()
    context.term()

    # check that other transport options raise error
    context = zmq.asyncio.Context()
    with pytest.raises(NotImplementedError):
        BaseZMQ.get_socket(
            server_id="test-server",
            socket_id="test-server",
            node_type="server",
            context=context,
            access_point="PUB",
        )


def test_04_socket_options():
    """check that socket options are as expected"""
    context = zmq.asyncio.Context()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.ROUTER,
    )
    assert socket.socket_type == zmq.ROUTER
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.DEALER,
    )
    assert socket.socket_type == zmq.DEALER
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.PUB,
    )
    assert socket.socket_type == zmq.PUB
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.SUB,
    )
    assert socket.socket_type == zmq.SUB
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.PAIR,
    )
    assert socket.socket_type == zmq.PAIR
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.PUSH,
    )
    assert socket.socket_type == zmq.PUSH
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()

    socket, _ = BaseZMQ.get_socket(
        server_id="test-server",
        socket_id="test-server",
        node_type="server",
        context=context,
        socket_type=zmq.PULL,
    )
    assert socket.socket_type == zmq.PULL
    assert socket.getsockopt_string(zmq.IDENTITY) == "test-server"
    assert isinstance(socket, zmq.asyncio.Socket)
    socket.close()
    context.term()


"""
TODO:
1. check node_type values
2. check if TCP socket search happens
"""

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
