import logging
import uuid
import aiomqtt

from ..utils import get_current_async_loop
from .utils import connect_over_zmq_and_fetch_td, create_event_consumer
from ..td.interaction_affordance import EventAffordance
from ..config import global_config
from ..param.parameters import Selector, String, Integer, ClassSelector, Tuple


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

    things = Tuple(item_type=str, length=3)  # type: list[tuple[str, str, str]]
    """List of things to publish events from, each defined as a tuple of (server id, access point, thing id)"""

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
        """
        self.hostname = hostname
        self.port = port
        self.qos = qos
        self.logger = kwargs.get("logger", global_config.logger())
        self._stop_publishing = False
        self.client = aiomqtt.Client(hostname=hostname, port=port, username=username, password=password)

    async def setup(self):
        self._stop_publishing = False
        for server_id, thing_id, access_point in self.things:
            thing, td = await connect_over_zmq_and_fetch_td(
                id=f"{self.hostname}:{self.port}|mqtt-publisher|{uuid.uuid4().hex[:8]}",
                server_id=server_id,
                thing_id=thing_id,
                access_point=access_point,
                logger=self.logger,
                context=global_config.zmq_context(),
            )
            eventloop = get_current_async_loop()
            for event in td.get("events", {}).values():
                eventloop.call_soon(lambda: self.publish(event))

    async def publish(self, resource: EventAffordance):
        consumer = create_event_consumer(resource)
        consumer.subscribe()
        while not self._stop_publishing:
            try:
                payload = await consumer.receive()
                await self.client.publish(consumer.event_unique_identifier, payload.body[0].value, qos=self.qos)
            except Exception as ex:
                self.logger.error(f"Error publishing MQTT message: {ex}")

    def stop(self):
        self._stop_publishing = True

    def start(self):
        eventloop = get_current_async_loop()
        eventloop.create_task(self.setup())

    def add_thing(self, server_id: str, thing_id: str, access_point: str):
        """Adds a thing to the list of things to publish events from."""
        if access_point.upper() not in ["TCP", "IPC", "INPROC"]:
            raise ValueError("Access point must be 'TCP', 'IPC', or 'INPROC'")
        self.things.append((server_id, thing_id, access_point))
