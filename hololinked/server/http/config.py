"""Runtime configuration for the HTTP server and metadata for its request handlers."""

from collections import OrderedDict
from concurrent.futures import Future
from typing import Any

from pydantic import BaseModel, Field

from ...core.eventloop import EventLoop  # noqa: F401
from ..security import Security
from .controllers import (
    ActionHandler,
    EventHandler,
    LivenessProbeHandler,
    PropertyHandler,
    ReadinessProbeHandler,
    RPCHandler,
    RWMultiplePropertiesHandler,
    StopHandler,
    ThingDescriptionHandler,
)
from .services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for HTTP server and handlers.

    Pass the attributes of this class as a dictionary to the `config` argument of `HTTPServer`.
    """

    cors: bool = False
    """use `True` to set CORS headers for the HTTP server, this is useful for local networks"""

    property_handler: type[RPCHandler] | Any = PropertyHandler
    """handler class to be used for property interactions"""
    action_handler: type[RPCHandler] | Any = ActionHandler
    """handler class to be used for action interactions"""
    event_handler: type[EventHandler] | Any = EventHandler
    """handler class to be used for event interactions"""
    RW_multiple_properties_handler: type[RPCHandler] | Any = RWMultiplePropertiesHandler
    """handler class to be used for read/write multiple properties interactions"""
    thing_description_handler: type[ThingDescriptionHandler] | Any = ThingDescriptionHandler
    """handler class to be used for thing description"""
    liveness_probe_handler: type[LivenessProbeHandler] | Any = LivenessProbeHandler
    """handler class to be used for liveness probe"""
    readiness_probe_handler: type[ReadinessProbeHandler] | Any = ReadinessProbeHandler
    """handler class to be used for readiness probe"""
    stop_handler: type[StopHandler] | Any = StopHandler
    """handler class to be used for stopping server"""

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """service class to be used for generating thing description"""

    eventloop: Any = Field(default=None)  # type: EventLoop | None
    """the event loop that runs operations on the served `Thing`s"""

    thing_models: Any = Field(default_factory=dict)  # type: dict[str, dict[str, Any]]
    """Thing Model per served `Thing`, which this server's Thing Descriptions are built on"""

    pending_operations: Any = Field(default_factory=dict)  # type: PendingOperations
    """no-block operations still to be collected, keyed by the token handed to the client"""

    allowed_clients: list[str] | None = Field(default=None)
    """
    Serves request and sets CORS only from these clients, other clients are rejected with 401. 
    Unlike pure CORS, the server resource is not even executed if the client is not 
    an allowed client. if None, any client is served. Not inherently a safety feature in public networks, 
    and more useful in private networks when the remote origin is known reliably.
    """

    security_schemes: list[Security] | None = Field(default=None)
    """
    List of security schemes to be used by the server, 
    it is sufficient that one scheme passes for a request to be authorized.
    Combo security schemes are not yet supported (but will be in future).
    """


class PendingOperations:
    """
    No-block operations whose reply nobody has collected yet.

    A no-block request is answered with a token and the client comes back for the reply on a second
    request. Some never do, so this is bounded and drops the oldest rather than growing forever.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._futures = OrderedDict()  # type: OrderedDict[str, Future]

    def add(self, token: str, future: Future) -> None:
        """
        Remember one operation under the token handed to the client.

        Parameters
        ----------
        token: str
            the token the client will come back with
        future: concurrent.futures.Future
            the promise of the operation's reply
        """
        self._futures[token] = future
        while len(self._futures) > self._maxsize:
            self._futures.popitem(last=False)

    def take(self, token: str) -> Future:
        """
        Hand back one operation's future, which can only be collected once.

        Parameters
        ----------
        token: str
            the token handed to the client

        Returns
        -------
        concurrent.futures.Future
            the promise of the operation's reply

        Raises
        ------
        KeyError
            if the token is unknown, or was already collected, or was evicted
        """
        return self._futures.pop(token)


class HandlerMetadata(BaseModel):
    """Specific metadata when a request handler has been initialized, in other words, handler specific metadata."""

    http_methods: tuple[str, ...] = tuple()
    """HTTP methods supported by the handler"""
