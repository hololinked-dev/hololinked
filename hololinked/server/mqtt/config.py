from typing import Annotated

from pydantic import BaseModel, Field

from ..thing import BrokerThing, thing_repository
from .controllers import ThingDescriptionPublisher, TopicPublisher
from .services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """Runtime configuration for HTTP server and handlers."""

    topic_publisher: type[TopicPublisher] = TopicPublisher
    """handler class to be used for property interactions"""
    thing_description_publisher: type[ThingDescriptionPublisher] = ThingDescriptionPublisher
    """handler class to be used for action interactions"""

    thing_description_service: type[ThingDescriptionService] = ThingDescriptionService
    """handler class to be used for event interactions"""

    thing_repository: dict[str, BrokerThing] = thing_repository
    """repository layer thing model to be used by the HTTP server and handlers"""

    qos: Annotated[int, Field(ge=0, le=2)] = 1
    """The MQTT QoS level to use for publishing messages"""
