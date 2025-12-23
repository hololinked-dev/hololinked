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
    RWMultiplePropertiesHandler,
    StopHandler,
    ThingDescriptionHandler,
)
from .services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """Runtime configuration for HTTP server and handlers."""

    cors: bool = False
    """
    Set CORS headers for the HTTP server. If set to False, CORS headers are not set.
    This is useful when the server is used in a controlled environment where CORS is not needed.
    """

    property_handler: type[PropertyHandler] = PropertyHandler
    """handler class to be used for property interactions"""
    action_handler: type[ActionHandler] = ActionHandler
    """handler class to be used for action interactions"""
    event_handler: type[EventHandler] = EventHandler
    """handler class to be used for event interactions"""
    RW_multiple_properties_handler: type[RWMultiplePropertiesHandler] = RWMultiplePropertiesHandler
    """handler class to be used for read/write multiple properties interactions"""
    thing_description_handler: type[ThingDescriptionHandler] = ThingDescriptionHandler
    """handler class to be used for generating thing description"""
    liveness_probe_handler: type[LivenessProbeHandler] = LivenessProbeHandler
    """handler class to be used for liveness probe"""
    readiness_probe_handler: type[ReadinessProbeHandler] = ReadinessProbeHandler
    """handler class to be used for readiness probe"""
    stop_handler: type[StopHandler] = StopHandler
    """handler class to be used for stop server"""

    thing_description_service: type[ThingDescriptionService] = ThingDescriptionService
    """service class to be used for generating thing description"""

    thing_repository: Any = thing_repository  # type: dict[str, BrokerThing]
    """repository layer thing model to be used by the HTTP server and handlers"""

    allowed_clients: list[str] | None = Field(default_factory=list, default=None)
    """
    Serves request and sets CORS only from these clients, other clients are rejected with 401. 
    Unlike pure CORS, the server resource is not even executed if the client is not 
    an allowed client. if None, any client is served. Not inherently a safety feature in public networks, 
    and more useful in private networks when the remote origin is known.
    """

    security_schemes: list[Security] | None = Field(default_factory=list, default=None)
    """
    List of security schemes to be used by the server, 
    it is sufficient that one scheme passes for a request to be authorized.
    """


class HandlerMetadata(BaseModel):
    """Specific metadata when a request handler has been initialized"""

    http_methods: tuple[str, ...] = tuple()
    """HTTP methods supported by the handler."""
