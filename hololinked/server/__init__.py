"""Protocol servers that expose a `Thing`."""

from typing import TYPE_CHECKING

from hololinked.core.interfaces import BaseProtocolServer  # noqa: F401
from hololinked.utils import lazy_module_getattr


from hololinked.server.security import (  # noqa: F401, isort: skip
    APIKeySecurity,
    Argon2BasicSecurity,
    BcryptBasicSecurity,
    OIDCSecurity,
)
from hololinked.server.server import parse_params, run, stop  # noqa: F401, isort: skip


__all__ = [
    "APIKeySecurity",
    "Argon2BasicSecurity",
    "BaseProtocolServer",
    "BcryptBasicSecurity",
    "HTTPServer",
    "MQTTPublisher",
    "ZMQServer",
    "OIDCSecurity",
    "parse_params",
    "run",
    "stop",
]

_lazy: dict[str, str] = {
    "HTTPServer": ".http",
    "MQTTPublisher": ".mqtt",
    "ZMQServer": ".zmq",
}
"""Name of a protocol server mapped to the module it is imported from, resolved lazily."""

__getattr__ = lazy_module_getattr(__name__, _lazy, globals())


if TYPE_CHECKING:
    from hololinked.server.http import HTTPServer as HTTPServer
    from hololinked.server.mqtt import MQTTPublisher as MQTTPublisher
    from hololinked.server.zmq import ZMQServer as ZMQServer
