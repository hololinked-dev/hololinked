"""ZeroMQ: the sockets, the wire format, and the protocol server for INPROC, IPC and TCP."""

from typing import TYPE_CHECKING

from hololinked.utils import lazy_module_getattr


try:
    import zmq  # noqa: F401
except ImportError as ex:
    raise ImportError(
        "Please install pyzmq to use ZMQ server or client - `pip install pyzmq`."
        + "Version should be less than 26.2 to support IPC in windows machines."
    ) from ex

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


_lazy: dict[str, str] = {"ZMQServer": ".server"}
"""Name of an export mapped to the module it is imported from, resolved lazily."""

__getattr__ = lazy_module_getattr(__name__, _lazy, globals())


if TYPE_CHECKING:
    from .server import ZMQServer as ZMQServer
