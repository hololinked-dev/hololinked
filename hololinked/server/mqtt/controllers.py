"""Publishers that push events, observable properties and Thing Descriptions to MQTT topics."""

from typing import Any

import aiomqtt
import structlog

from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from hololinked import Serializers
from hololinked.core.thing import Thing

from ...core.eventloop import EventSubscription
from ...metadata.td import EventAffordance, PropertyAffordance


class TopicPublisher:
    """
    Publishes an event to an MQTT topic. Supply a different class in `MQTTPublisher` to use a different one.

    This object would be a controller in layered architecture.
    """

    def __init__(
        self,
        client: aiomqtt.Client,
        resource: EventAffordance | PropertyAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        thing: Thing | None = None,
    ) -> None:
        """
        Initialize the publisher for one event or observable property.

        Parameters
        ----------
        client: aiomqtt.Client
            The MQTT client to use for publishing messages
        resource: EventAffordance | PropertyAffordance
            dataclass representation of observable property or event to be published
        config: RuntimeConfig
            The runtime configuration for the `MQTTPublisher`
        logger: structlog.stdlib.BoundLogger
            The logger to use for logging messages
        thing: Thing | None
            the `Thing` whose event or property this publisher pushes
        """
        from .config import RuntimeConfig  # noqa: F401

        self.client = client
        self.resource = resource
        self.topic = f"{self.resource.thing_id}/{self.resource.name}"
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(layer="controller", impl=self.__class__.__name__, topic=self.topic)
        self.thing = thing  # type: Thing | None
        self.qos = self.config.qos
        self._stop_publishing = False

    def stop(self):
        """Stop publishing, the client is not closed automatically."""
        self._stop_publishing = True

    async def publish(self):
        """Publishes events to the MQTT broker in an infinite loop."""
        subscription = EventSubscription(
            self.thing.eventloop.event_bus,
            f"{self.resource.thing_id}/{self.resource.name}",
        )
        self.logger.info(f"Starting to publish events for {self.resource.name} to MQTT broker on topic {self.topic}")
        try:
            while not self._stop_publishing:
                try:
                    data = await subscription.receive(timeout=10)
                    body, content_type = subscription.encode(data)
                    properties = Properties(PacketTypes.PUBLISH)
                    properties.ContentType = content_type
                    await self.client.publish(
                        topic=self.topic,
                        payload=body,
                        qos=self.qos,
                        properties=properties,
                    )
                    self.logger.debug(f"Published MQTT message for {self.resource.name} on topic {self.topic}")
                except TimeoutError:
                    continue  # nothing was pushed in that window, go round and check for a stop
                except Exception as ex:
                    self.logger.error(f"Error publishing MQTT message for {self.resource.name}: {ex}")
        finally:
            subscription.unsubscribe()
        self.logger.info(f"Stopped publishing events for {self.resource.name} to MQTT broker on topic {self.topic}")


class ThingDescriptionPublisher:
    """
    Publishes Thing Description to an MQTT Topic. Supply a different class in `MQTTPublisher` to use a different one.

    This object would be a controller in layered architecture.
    """

    def __init__(
        self,
        client: aiomqtt.Client,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        thing: Thing,
    ) -> None:
        """
        Initialize the Thing Description publisher.

        Parameters
        ----------
        client: aiomqtt.Client
            The MQTT client to use for publishing messages
        config: RuntimeConfig
            The runtime configuration for the MQTT publisher
        logger: structlog.stdlib.BoundLogger
            The logger to use for logging messages
        thing: Thing
            The `Thing` whose description is being published
        """
        from .config import RuntimeConfig  # noqa: F401

        self.client = client
        self.thing = thing  # type: Thing
        self.topic = f"{thing.id}/thing-description"
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(layer="controller", impl=self.__class__.__name__)
        self.thing_description = self.config.thing_description_service(
            hostname=self.client._hostname,
            port=self.client._port,
            logger=logger,
            thing=thing,
            ssl=self.client._client._ssl_context is not None,
        )

    async def publish(self) -> None:
        """Publishes Thing Description to the MQTT broker, one-time at startup, with qos=2 and retain=True."""
        TD = await self.thing_description.generate(ignore_errors=True)

        properties = Properties(PacketTypes.PUBLISH)
        properties.ContentType = "application/json"
        await self.client.publish(
            topic=self.topic,
            payload=Serializers.json.dumps(TD),
            qos=2,
            properties=properties,
            retain=True,
        )

        self.logger.info(f"Published Thing Description for {TD['id']} to MQTT broker on topic {self.topic}")
