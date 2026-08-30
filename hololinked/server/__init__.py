"""Protocol servers that expose a `Thing`."""

from typing import TYPE_CHECKING


from .server import BaseProtocolServer, run, stop  # noqa: F401, isort: skip
from .http import HTTPServer  # noqa: F401
from .mqtt import MQTTPublisher  # noqa: F401


from .security import (  # noqa: F401, isort: skip
    APIKeySecurity,
    Argon2BasicSecurity,
    BcryptBasicSecurity,
    OIDCSecurity,
)


# `pyzmq` is an extra, so importing this package must not require it. Reaching for `ZMQServer` is
# what asks for ZMQ, and that is where the ImportError belongs.
_lazy = {"RPCServer": (".zmq", "RPCServer"), "ZMQServer": (".zmq", "ZMQServer")}


def __getattr__(name: str):
    if name in _lazy:
        import importlib

        module_path, attr = _lazy[name]
        try:
            value = getattr(importlib.import_module(module_path, package=__name__), attr)
        except ModuleNotFoundError as ex:
            if ex.name != "zmq" and not (ex.name or "").startswith("zmq."):
                raise
            raise ImportError(
                f"{name} needs the ZMQ transport, which is an optional dependency. "
                + "Install it with `pip install hololinked[zmq]`."
            ) from ex
        globals()[name] = value  # cache so subsequent access skips __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .zmq import RPCServer as RPCServer
    from .zmq import ZMQServer as ZMQServer
