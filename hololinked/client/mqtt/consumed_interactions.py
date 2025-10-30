import aiomqtt
import logging
from typing import Any, Callable
from paho.mqtt.client import Client as PahoMQTTClient, MQTTMessage

from ..abstractions import SSE, ConsumedThingEvent
from ...td.interaction_affordance import EventAffordance
from ...td.forms import Form
from ...serializers import Serializers, BaseSerializer  # noqa: F401


class MQTTConsumer(ConsumedThingEvent):
    # An MQTT event consumer

    def __init__(
        self,
        sync_client: PahoMQTTClient,
        async_client: aiomqtt.Client,
        resource: EventAffordance,
        qos: int,
        logger: logging.Logger,
        owner_inst: Any,
    ) -> None:
        super().__init__(resource=resource, logger=logger, owner_inst=owner_inst)
        self.qos = qos
        self.sync_client = sync_client
        self.async_client = async_client
        self.subscribed = True

    def listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None:
        # This method is called from a different thread but also finishes quickly, we wont redo this way
        # for the time being.
        topic = form.mqv_topic or f"{self.resource.thing_id}/{self.resource.name}"

        def on_topic_message(client: PahoMQTTClient, userdata, message: MQTTMessage):
            try:
                payload = message.payload
                # message.properties.readProperty("content_type") if message.properties else form.contentType
                # TODO, fix this, make sure to that content_type is not empty after extracting
                content_type = form.contentType or "application/json"
                serializer = Serializers.content_types.get(content_type, None)  # type: BaseSerializer
                if deserialize and content_type and serializer:
                    try:
                        payload = serializer.loads(payload)
                    except Exception as ex:
                        self.logger.error(
                            f"Error deserializing MQTT message for topic {topic}, "
                            + f"passing payload as it is. message: {ex}"
                        )
                event_data = SSE()
                event_data.data = payload
                event_data.id = message.mid
                self.schedule_callbacks(callbacks=callbacks, event_data=event_data, concurrent=concurrent)
            except Exception as ex:
                self.logger.error(f"Error handling MQTT message for topic {topic}: {ex}")

        self.sync_client.message_callback_add(topic, on_topic_message)

    async def async_listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None:
        topic = form.mqv_topic or f"{self.resource.thing_id}/{self.resource.name}"
        try:
            await self.async_client.__aenter__()
        except aiomqtt.MqttReentrantError:
            pass
        await self.async_client.subscribe(topic, qos=self.qos)
        async for message in self.async_client.messages:
            if not self.subscribed:
                break
            if not message.topic.matches(topic):
                continue
            try:
                payload = message.payload
                # message.properties.readProperty("content_type") if message.properties else form.contentType
                # TODO, fix this, make sure to that content_type is not empty after extracting
                content_type = form.contentType or "application/json"
                serializer = Serializers.content_types.get(content_type, None)  # type: BaseSerializer
                if deserialize and content_type and serializer:
                    try:
                        payload = serializer.loads(payload)
                    except Exception as ex:
                        self.logger.error(
                            f"Error deserializing MQTT message for topic {topic}, "
                            + f"passing payload as it is. message: {ex}"
                        )
                event_data = SSE()
                event_data.data = payload
                event_data.id = message.mid
                await self.async_schedule_callbacks(callbacks=callbacks, event_data=event_data, concurrent=concurrent)
            except Exception as ex:
                self.logger.error(f"Error handling MQTT message for topic {topic}: {ex}")
        self.async_client.unsubscribe(topic)

    def unsubscribe(self) -> None:
        self.subscribed = False
        self.sync_client.message_callback_remove(f"{self.resource.thing_id}/{self.resource.name}")
