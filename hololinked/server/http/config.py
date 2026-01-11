from typing import Any

from pydantic import BaseModel, Field

from ..repository import BrokerThing, thing_repository  # noqa: F401
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

    thing_repository: Any = thing_repository  # type: dict[str, BrokerThing]
    """repository layer thing model to be used by the HTTP server and handlers"""

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


class HandlerMetadata(BaseModel):
    """Specific metadata when a request handler has been initialized, in other words, handler specific metadata"""

    http_methods: tuple[str, ...] = tuple()
    """HTTP methods supported by the handler"""
