"""Runtime configuration for the MQTT publisher."""

from typing import Annotated, Any

from pydantic import BaseModel, Field

from ...core.eventloop import EventLoop  # noqa: F401
from .controllers import ThingDescriptionPublisher, TopicPublisher
from .services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for MQTT publishers, initialized in `MQTTPublisher` object.

    Pass the attributes of this class as a dictionary to the `config` argument of `MQTTPublisher`.
    """

    qos: Annotated[int, Field(ge=0, le=2)] = 1
    """The (global) MQTT QoS level to use for publishing messages"""

    topic_publisher: type[TopicPublisher] | Any = TopicPublisher
    """handler class to be used for publishing to topics (global)"""
    thing_description_publisher: type[ThingDescriptionPublisher] | Any = ThingDescriptionPublisher
    """handler class to be used for publishing thing descriptions"""

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """Thing Description generation service, used by `ThingDescriptionPublisher` to generate the Thing Description"""

    engine: Any = Field(default=None)  # type: EventLoop | None
    """the execution engine that runs operations on the served `Thing`s"""
