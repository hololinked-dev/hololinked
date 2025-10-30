from typing import Any
import logging
import uuid
import aiomqtt
import copy
import ssl


from ..utils import get_current_async_loop
from .utils import consume_broker_queue, consume_broker_pubsub_per_event
from ..config import global_config
from ..constants import Operations
from ..serializers import Serializers
from ..td.interaction_affordance import EventAffordance, PropertyAffordance
from ..param.parameters import Selector, String, Integer, ClassSelector, List


class MQTTPublisher:
    """
    MQTT Publisher for publishing messages to a specific topic.
    All events defined on the Thing will be published to MQTT topics with topic name "{thing id}/{event name}"

    For setting up an MQTT broker if one does not exist,
    see [infrastructure project](https://github.com/hololinked-dev/daq-system-infrastructure).
    """

    qos = Selector(objects=[0, 1, 2], default=0)
    """The MQTT QoS level to use for publishing messages"""

    hostname = String(default="localhost")
    """The MQTT broker hostname"""

    port = Integer(default=1883)
    """The MQTT broker port"""

    logger = ClassSelector(class_=logging.Logger, default=global_config.logger())  # type: logging.Logger
    """Logger instance"""

    things = List(default=None, allow_None=True, item_type=tuple)  # type: list[tuple[str, str, str]]
    """List of things to publish events from, each defined as a tuple of (server id, access point, thing id)"""

    ssl_context = ClassSelector(class_=ssl.SSLContext, allow_None=True, default=None)

    def __init__(self, hostname: str, port: int, username: str, password: str, qos: int = 1, **kwargs):
        """
        Parameters
        ----------
        hostname: str
            The MQTT broker hostname
        port: int
            The MQTT broker port
        username: str
            The MQTT broker username
        password: str
            The MQTT broker password
        qos: int
            The MQTT QoS level to use for publishing messages
        kwargs: dict
            Additional keyword arguments
        """
        self.hostname = hostname
        self.port = port
        self.qos = qos
        self.things = []
        self.username = username
        self.password = password
        self.logger = kwargs.get("logger", global_config.logger())
        self.ssl_context = kwargs.get("ssl_context", None)
        self._stop_publishing = False

    async def setup(self):
        """
        Sets up the MQTT client and starts publishing events from the configured things.
        All events are dispatched to their own async tasks. This method returns when setup is complete.
        """
        self._stop_publishing = False
        self.client = aiomqtt.Client(
            hostname=self.hostname,
            port=self.port,
            username=self.username,
            password=self.password,
            tls_context=self.ssl_context,
        )
        try:
            await self.client.__aenter__()
        except aiomqtt.MqttReentrantError:
            pass
        for server_id, thing_id, access_point in self.things:
            thing, td = await consume_broker_queue(
                id=f"{self.hostname}:{self.port}|mqtt-publisher|{uuid.uuid4().hex[:8]}",
                server_id=server_id,
                thing_id=thing_id,
                access_point=access_point,
                logger=self.logger,
                context=global_config.zmq_context(),
            )
            eventloop = get_current_async_loop()
            for event_name in td.get("events", {}).keys():
                event_affordance = EventAffordance.from_TD(event_name, td)
                eventloop.create_task(self.publish(event_affordance))
            eventloop.create_task(self.publish_thing_description(td))

    async def publish(self, resource: EventAffordance):
        """
        Publishes an event to the MQTT broker.

        Parameters
        ----------
        resource: EventAffordance
            The event affordance for which the events are to be published
        """
        consumer = consume_broker_pubsub_per_event(resource)
        consumer.subscribe()
        topic = f"{resource.thing_id}/{resource.name}"
        while not self._stop_publishing:
            try:
                message = await consumer.receive()
                if message is None:
                    continue
                if message.body[1].value != b"":
                    payload = message.body[1]
                else:
                    payload = message.body[0]
                await self.client.publish(
                    topic=topic,
                    payload=payload.value,
                    qos=self.qos,
                    properties=dict(content_type=payload.content_type),
                )
            except Exception as ex:
                self.logger.error(f"Error publishing MQTT message: {ex}")

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        self._stop_publishing = True

    def start(self):
        eventloop = get_current_async_loop()
        eventloop.create_task(self.setup())

    def add_thing(self, server_id: str, thing_id: str, access_point: str):
        """Adds a thing to the list of things to publish events from."""
        if access_point.upper() not in ["TCP", "IPC", "INPROC"]:
            raise ValueError("Access point must be 'TCP', 'IPC', or 'INPROC'")
        self.things.append((server_id, thing_id, access_point))

    async def publish_thing_description(self, ZMQ_TD: dict[str, Any]) -> dict[str, Any]:
        """Returns the Thing Description of the specified thing."""
        TD = copy.deepcopy(ZMQ_TD)
        # remove actions as they dont push events
        TD.pop("actions", None)
        # remove properties that are not observable
        for name in ZMQ_TD.get("properties", {}).keys():
            affordance = PropertyAffordance.from_TD(name, ZMQ_TD)
            if not affordance.observable:
                TD["properties"].pop(name)
                continue
            TD["properties"][name]["forms"] = []
            form = affordance.retrieve_form(Operations.observeproperty)
            form.href = f"mqtt{'s' if self.ssl_context else ''}://{self.hostname}:{self.port}"
            form.mqv_topic = f"{TD['id']}/{name}"
            TD["properties"][name]["forms"].append(form.json())
        # repurpose event
        for name in ZMQ_TD.get("events", {}).keys():
            affordance = EventAffordance.from_TD(name, ZMQ_TD)
            TD["events"][name]["forms"] = []
            form = affordance.retrieve_form(Operations.subscribeevent)
            form.href = f"mqtt{'s' if self.ssl_context else ''}://{self.hostname}:{self.port}"
            form.mqv_topic = f"{TD['id']}/{name}"
            TD["events"][name]["forms"].append(form.json())
        await self.client.publish(
            topic=f"{TD['id']}/thing-description",
            payload=Serializers.json.dumps(TD),
            qos=2,
            properties=dict(content_type="application/json"),
            retain=True,
        )
