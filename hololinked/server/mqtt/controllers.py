from typing import Any

import aiomqtt
import structlog

from ...core.zmq.message import EventMessage  # noqa: F401
from ...serializers import Serializers
from ...td import EventAffordance, PropertyAffordance
from ..repository import BrokerThing  # noqa: F401


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
    ) -> None:
        """
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
        """
        from .config import RuntimeConfig  # noqa: F401

        self.client = client
        self.resource = resource
        self.topic = f"{self.resource.thing_id}/{self.resource.name}"
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(layer="controller", impl=self.__class__.__name__, topic=self.topic)
        self.thing = self.config.thing_repository[resource.thing_id]  # type: BrokerThing
        self.qos = self.config.qos
        self._stop_publishing = False

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        self._stop_publishing = True

    async def publish(self):
        """Publishes events to the MQTT broker in an infinite loop"""
        consumer = self.thing.subscribe_event(self.resource)
        self.logger.info(f"Starting to publish events for {self.resource.name} to MQTT broker on topic {self.topic}")
        while not self._stop_publishing:
            try:
                message = await consumer.receive()  # type: EventMessage | None
                if message is None:
                    continue
                payload = self.thing.get_response_payload(message)
                await self.client.publish(
                    topic=self.topic,
                    payload=payload.value,
                    qos=self.qos,
                    properties=dict(content_type=payload.content_type),
                )
                self.logger.debug(f"Published MQTT message for {self.resource.name} on topic {self.topic}")
            except Exception as ex:
                self.logger.error(f"Error publishing MQTT message for {self.resource.name}: {ex}")
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
        ZMQ_TD: dict[str, Any],
    ) -> None:
        """
        Parameters
        ----------
        client: aiomqtt.Client
            The MQTT client to use for publishing messages
        config: RuntimeConfig
            The runtime configuration for the MQTT publisher
        logger: structlog.stdlib.BoundLogger
            The logger to use for logging messages
        ZMQ_TD: dict[str, Any]
            The ZMQ Thing Description message received from ZMQ broker
        """
        from .config import RuntimeConfig  # noqa: F401

        self.client = client
        self.topic = f"{ZMQ_TD['id']}/thing-description"
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(layer="controller", impl=self.__class__.__name__)
        self.thing = self.config.thing_repository[ZMQ_TD["id"]]
        self.thing_description = self.config.thing_description_service(
            hostname=self.client._hostname,
            port=self.client._port,
            logger=logger,
            ssl=self.client._client._ssl_context is not None,
        )

    async def publish(self, ZMQ_TD: dict[str, Any]) -> dict[str, Any]:
        """Publishes Thing Description to the MQTT broker, one-time at startup, with qos=2 and retain=True"""
        TD = await self.thing_description.generate(ZMQ_TD)

        await self.client.publish(
            topic=self.topic,
            payload=Serializers.json.dumps(TD),
            qos=2,
            properties=dict(content_type="application/json"),
            retain=True,
        )

        self.logger.info(f"Published Thing Description for {TD['id']} to MQTT broker on topic {self.topic}")
