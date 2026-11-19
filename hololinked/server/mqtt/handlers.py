"""Publishers that push events, observable properties and Thing Descriptions to MQTT topics."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiomqtt
import structlog

from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from hololinked import Serializers
from hololinked.core.eventloop import EventSubscription
from hololinked.core.thing import Thing
from hololinked.metadata.td import EventAffordance, PropertyAffordance


if TYPE_CHECKING:
    from hololinked.server.mqtt.config import RuntimeConfig, TopicPublisherMetadata


class TopicPublisher:
    """Publishes an event to an MQTT topic. Supply a different class in `MQTTPublisher` to use a different one."""

    # This object would be a controller in layered architecture.

    def __init__(
        self,
        client: aiomqtt.Client,
        resource: EventAffordance | PropertyAffordance,
        config: RuntimeConfig,
        logger: structlog.stdlib.BoundLogger,
        thing: Thing,
        metadata: TopicPublisherMetadata | None = None,
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
        thing: Thing
            the `Thing` whose event or property this publisher pushes
        metadata: TopicPublisherMetadata, optional
            overrides for topic name and QoS, unset fields fall back to `{thing_id}/{name}` and `config.qos`
        """
        from hololinked.server.mqtt.config import TopicPublisherMetadata

        metadata = metadata or TopicPublisherMetadata()
        self.client = client
        self.resource = resource
        self.topic = metadata.topic or f"{self.resource.thing_id}/{self.resource.name}"
        self.config = config
        self.logger = logger.bind(impl=self.__class__.__name__, topic=self.topic)
        self.thing: Thing = thing
        self.qos = metadata.qos if metadata.qos is not None else self.config.qos
        self._stop_publishing = False

    def stop(self):
        """Stop publishing, the client is not closed automatically."""
        self._stop_publishing = True

    async def publish(self):
        """Publishes events to the MQTT broker in an infinite loop."""  # noqa: DOC501
        if not self.thing.eventloop:  # type gaurd, not a real logic.
            raise RuntimeError("Thing is not served by an event loop")
        subscription = EventSubscription(
            self.thing.eventloop.event_bus,
            self.resource.event_unique_identifier,
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
    """Publishes Thing Description to an MQTT Topic. Supply a different class in `MQTTPublisher` to use a different one."""

    # This object would be a controller in layered architecture.

    def __init__(
        self,
        client: aiomqtt.Client,
        config: RuntimeConfig,
        logger: structlog.stdlib.BoundLogger,
        thing: Thing,
        publisher_overrides: dict[tuple[str, str], TopicPublisherMetadata] | None = None,
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
        publisher_overrides: dict[tuple[str, str], TopicPublisherMetadata], optional
            per event/observable property overrides keyed by (thing_id, name), used for the topics in the TD forms
        """
        self.client = client
        self.thing = thing  # type: Thing
        self.topic = f"{thing.id}/thing-description"
        self.config = config
        self.logger = logger.bind(impl=self.__class__.__name__)
        self.thing_description = self.config.thing_description_service(
            hostname=self.client._hostname,
            port=self.client._port,
            logger=logger,
            thing=thing,
            ssl=self.client._client._ssl_context is not None,
            use_websocket=self.config.use_websocket,
            publisher_overrides=publisher_overrides,
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
