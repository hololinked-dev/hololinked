import aiomqtt
from typing import Any, Callable
import logging

from ..abstractions import SSE, ConsumedThingEvent
from ...td.interaction_affordance import EventAffordance
from ...td.forms import Form
from ...serializers import Serializers, BaseSerializer  # noqa: F401


class MQTTConsumer(ConsumedThingEvent):
    # An MQTT event consumer

    def __init__(
        self,
        client: aiomqtt.Client,
        resource: EventAffordance,
        qos: int,
        logger: logging.Logger,
        owner_inst: Any,
    ) -> None:
        super().__init__(resource=resource, logger=logger, owner_inst=owner_inst)
        self.qos = qos
        self.client = client
        self.subscribed = True

    def listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None: ...

    async def async_listen(self, form: Form, callbacks: list[Callable], concurrent: bool, deserialize: bool) -> None:
        topic = f"{self.resource.thing_id}/{self.resource.name}"
        await self.client.subscribe(topic, qos=self.qos)
        async for message in self.client.messages:
            if not self._subscribed:
                break
            payload = message.payload
            content_type = message.properties.get("content_type") if message.properties else form.contentType  #
            serializer = Serializers.content_types.get(content_type, None)  # type: BaseSerializer
            if deserialize and content_type and serializer:
                payload = serializer.loads(payload)
            event_data = SSE(data=payload, id=message.mid)
            await self.async_schedule_callbacks(callbacks=callbacks, event_data=event_data, concurrent=concurrent)

    def unsubscribe(self) -> None:
        self._subscribed = False
