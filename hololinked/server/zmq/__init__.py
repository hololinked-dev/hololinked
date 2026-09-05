"""ZeroMQ: the sockets, the wire format, and the protocol server for INPROC, IPC and TCP."""

from typing import TYPE_CHECKING


try:
    import zmq  # noqa: F401
except ImportError:
    raise ImportError(
        "Please install pyzmq to use ZMQ server or client - `pip install pyzmq`."
        + "Version should be less than 26.2 to support IPC in windows machines."
    )

from .brokers import (  # noqa: F401
    AsyncEventConsumer,
    AsyncZMQClient,
    AsyncZMQServer,
    EventConsumer,
    EventPublisher,
    MessageMappedZMQClientPool,
    SyncZMQClient,
    ZMQServerPool,
)


_lazy = {"RPCServer": (".server", "RPCServer"), "ZMQServer": (".server", "ZMQServer")}


def __getattr__(name: str):
    if name in _lazy:
        import importlib

        module_path, attr = _lazy[name]
        value = getattr(importlib.import_module(module_path, package=__name__), attr)
        globals()[name] = value  # cache so subsequent access skips __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .server import RPCServer as RPCServer
    from .server import ZMQServer as ZMQServer
