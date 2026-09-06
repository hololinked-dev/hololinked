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

# currently only ZMQ is optional
_lazy = {"ZMQServer": (".zmq", "ZMQServer")}


def __getattr__(name: str):
    if name in _lazy:
        import importlib

        module_path, attr = _lazy[name]
        value = getattr(importlib.import_module(module_path, package=__name__), attr)
        globals()[name] = value  # cache so subsequent access skips __getattr__
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from .zmq import ZMQServer as ZMQServer
