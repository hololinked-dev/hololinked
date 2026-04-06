from typing import Any

from pydantic import BaseModel, Field

from ..repository import BrokerThing  # noqa: F401
from ..security import Security
from .controllers import (
    ActionResource,
    LivenessProbeResource,
    PropertyResource,
    ReadinessProbeResource,
    RWMultiplePropertiesResource,
    StopResource,
    ThingDescriptionResource,
)
from .services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for CoAP server and resources.
    Pass the attributes of this class as a dictionary to the `config` argument of `CoAPServer`.
    """

    property_resource: Any = PropertyResource
    """resource class to be used for property interactions"""
    action_resource: Any = ActionResource
    """resource class to be used for action interactions"""

    # event_resource: type[EventHandler] | Any = EventHandler
    # """resource class to be used for event interactions"""
    RW_multiple_properties_resource: type[RWMultiplePropertiesResource] | Any = RWMultiplePropertiesResource
    """resource class to be used for read/write multiple properties interactions"""
    thing_description_resource: type[ThingDescriptionResource] | Any = ThingDescriptionResource
    """resource class to be used for thing description"""
    liveness_probe_resource: type[LivenessProbeResource] | Any = LivenessProbeResource
    """resource class to be used for liveness probe"""
    readiness_probe_resource: type[ReadinessProbeResource] | Any = ReadinessProbeResource
    """resource class to be used for readiness probe"""
    stop_resource: type[StopResource] | Any = StopResource
    """resource class to be used for stopping server"""

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """service class to be used for generating thing description"""

    thing_repository: Any = Field(default_factory=dict)  # type: dict[str, BrokerThing]
    """repository layer thing model to be used by the CoAP server and resources"""

    security_schemes: list[Security] | None = Field(default=None)
    """
    List of security schemes to be used by the server, 
    it is sufficient that one scheme passes for a request to be authorized.
    Combo security schemes are not yet supported (but will be in future).
    """


class ResourceMetadata(BaseModel):
    """Specific metadata when a request resource has been initialized, in other words, resource specific metadata"""

    coap_methods: tuple[str, ...] = tuple()
    """CoAP methods supported by the resource, e.g. ("GET", "POST")"""
