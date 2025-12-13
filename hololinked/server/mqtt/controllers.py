from typing import Any

import aiomqtt
import structlog

from ...core.zmq.message import EventMessage  # noqa: F401
from ...serializers import Serializers
from ...td import EventAffordance, PropertyAffordance
from ..thing import thing_repository
from .services import ThingDescriptionService


class TopicPublisher:
    """Publishes an event to an MQTT topic"""

    def __init__(
        self,
        client: aiomqtt.Client,
        resource: EventAffordance | PropertyAffordance,
        logger: structlog.stdlib.BoundLogger,
        qos: int,
    ) -> None:
        self.client = client
        self.thing = thing_repository[resource.thing_id]
        self.logger = logger
        self.qos = qos
        self.resource = resource
        self.topic = f"{self.resource.thing_id}/{self.resource.name}"
        self._stop_publishing = False

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        self._stop_publishing = True

    async def publish(self):
        """
        Publishes an event to the MQTT broker.

        Parameters
        ----------
        resource: EventAffordance
            The event affordance for which the events are to be published
        """
        consumer = self.thing.subscribe_event(self.resource)
        self.logger.info(f"Starting to publish events for {self.resource.name} to MQTT broker on topic {self.topic}")
        while not self._stop_publishing:
            try:
                message = await consumer.receive()  # type: EventMessage | None
                if message is None:
                    continue
                payload = message.oneof_valid_payload
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
    """Publishes Thing Description over MQTT Topic"""

    def __init__(self, client: aiomqtt.Client, logger: structlog.stdlib.BoundLogger, ZMQ_TD: dict[str, Any]) -> None:
        self.client = client
        self.logger = logger
        self.topic = f"{ZMQ_TD['id']}/thing-description"
        self.thing = thing_repository[ZMQ_TD["id"]]
        self.thing_description = ThingDescriptionService(
            hostname=self.client._hostname,
            port=self.client._port,
            logger=logger,
            ssl=self.client._client._ssl_context is not None,
        )

    async def publish(self, ZMQ_TD: dict[str, Any]) -> dict[str, Any]:
        """Returns the Thing Description of the specified thing."""
        TD = await self.thing_description.generate(ZMQ_TD)

        await self.client.publish(
            topic=self.topic,
            payload=Serializers.json.dumps(TD),
            qos=2,
            properties=dict(content_type="application/json"),
            retain=True,
        )

        self.logger.info(f"Published Thing Description for {TD['id']} to MQTT broker on topic {self.topic}")
