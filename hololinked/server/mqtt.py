import uuid
import aiomqtt
import copy
import ssl
import structlog
from typing import Any, Optional

from ..utils import get_current_async_loop
from .utils import consume_broker_queue, consume_broker_pubsub_per_event
from ..config import global_config
from ..constants import Operations
from ..serializers import Serializers
from ..param.parameters import Selector, String, ClassSelector
from ..core.zmq.message import EventMessage  # noqa: F401
from ..core import Thing
from ..td.interaction_affordance import EventAffordance, PropertyAffordance
from .server import BaseProtocolServer


class MQTTPublisher(BaseProtocolServer):
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

    ssl_context = ClassSelector(class_=ssl.SSLContext, allow_None=True, default=None)
    """The SSL context to use for secure connections, or None for no SSL"""

    def __init__(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str,
        things: Optional[list[Thing]] = None,
        qos: int = 1,
        **kwargs,
    ):
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
        self.username = username
        self.password = password
        self.add_things(*(things or []))
        endpoint = f"{self.hostname}{f':{self.port}' if self.port else ''}"
        self.logger = kwargs.get("logger", structlog.get_logger().bind(protocol="mqtt", hostname=endpoint))
        self.ssl_context = kwargs.get("ssl_context", None)
        self._stop_publishing = False

    async def start(self):
        """
        Sets up the MQTT client and starts publishing events from the configured things.
        All events are dispatched to their own async tasks. This method returns and
        creates side-effects only.
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
            endpoint = f"{self.hostname}{f':{self.port}' if self.port else ''}"
            self.logger.info(f"Connected to MQTT broker at {endpoint}")
        except aiomqtt.MqttReentrantError:
            pass
        # better to do later
        await self.setup()

    async def setup(self) -> None:
        eventloop = get_current_async_loop()
        for thing in self.things or []:
            if not thing.rpc_server:
                raise ValueError(f"Thing {thing.id} is not associated with any RPC server")
            self.add_thing_instance_through_broker(
                server_id=thing.rpc_server.id,
                access_point="INPROC",
                thing_id=thing.id,
            )
        for thing in self._broker_things:
            thing, td = await consume_broker_queue(
                id=f"{self.hostname}:{self.port}|mqtt-publisher|{uuid.uuid4().hex[:8]}",
                server_id=thing.server_id,
                thing_id=thing.thing_id,
                access_point=thing.access_point,
                context=global_config.zmq_context(),
            )
            for event_name in td.get("events", {}).keys():
                event_affordance = EventAffordance.from_TD(event_name, td)
                eventloop.create_task(self.publish(event_affordance))
                self.logger.info(f"MQTT will publish events for {event_name} of thing {thing.id}")
            eventloop.create_task(self.publish_thing_description(td))

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        self._stop_publishing = True

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
        self.logger.info(f"Starting to publish events for {resource.name} to MQTT broker on topic {topic}")
        while not self._stop_publishing:
            try:
                message = await consumer.receive()  # type: EventMessage | None
                if message is None:
                    continue
                payload = message.oneof_valid_payload
                await self.client.publish(
                    topic=topic,
                    payload=payload.value,
                    qos=self.qos,
                    properties=dict(content_type=payload.content_type),
                )
                self.logger.debug(f"Published MQTT message for {resource.name} on topic {topic}")
            except Exception as ex:
                self.logger.error(f"Error publishing MQTT message for {resource.name}: {ex}")
        self.logger.info(f"Stopped publishing events for {resource.name} to MQTT broker on topic {topic}")

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
        topic = f"{TD['id']}/thing-description"
        await self.client.publish(
            topic=topic,
            payload=Serializers.json.dumps(TD),
            qos=2,
            properties=dict(content_type="application/json"),
            retain=True,
        )
        self.logger.info(f"Published Thing Description for {TD['id']} to MQTT broker on topic {topic}")
