"""ZeroMQ: the sockets, the wire format, and the protocol server for INPROC, IPC and TCP."""

from typing import TYPE_CHECKING

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


# `ZMQServer` is the only thing here that needs `BaseProtocolServer`, and `server/server.py` imports
# `repository.py`, which imports the brokers from this package, while it is still initialising.
# Resolving the server on first access keeps the sockets and the wire format importable on their own.
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
