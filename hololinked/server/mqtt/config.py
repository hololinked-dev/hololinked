"""Runtime configuration for the MQTT publisher."""

from typing import Annotated, Any

from pydantic import BaseModel, Field

from hololinked.server.mqtt.handlers import ThingDescriptionPublisher, TopicPublisher
from hololinked.server.mqtt.services import ThingDescriptionService


class RuntimeConfig(BaseModel):
    """
    Runtime configuration for MQTT publishers, initialized in `MQTTPublisher` object.

    Pass the attributes of this class as a dictionary to the `config` argument of `MQTTPublisher`.
    """

    qos: Annotated[int, Field(ge=0, le=2)] = 1
    """The (global) MQTT QoS level to use for publishing messages"""

    use_websocket: bool = False
    """Whether to use WebSocket transport instead of TCP"""

    topic_publisher: type[TopicPublisher] | Any = TopicPublisher
    """handler class to be used for publishing to topics (global)"""
    thing_description_publisher: type[ThingDescriptionPublisher] | Any = ThingDescriptionPublisher
    """handler class to be used for publishing thing descriptions"""

    thing_description_service: type[ThingDescriptionService] | Any = ThingDescriptionService
    """Thing Description generation service, used by `ThingDescriptionPublisher` to generate the Thing Description"""


class TopicPublisherMetadata(BaseModel):
    """Per event/observable property overrides for `TopicPublisher`, unset fields use the defaults."""

    topic: str | None = None
    """MQTT topic name, defaults to `{thing_id}/{name}`"""

    qos: Annotated[int, Field(ge=0, le=2)] | None = None
    """MQTT QoS level, defaults to `RuntimeConfig.qos`"""

    publisher_class: type[TopicPublisher] | None = None
    """handler class to publish this topic, defaults to `RuntimeConfig.topic_publisher`"""
