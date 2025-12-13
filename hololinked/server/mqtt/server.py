import ssl

from typing import Optional

import aiomqtt
import structlog

from ...core import Thing as CoreThing
from ...param.parameters import ClassSelector, Selector, String
from ...td.interaction_affordance import EventAffordance, PropertyAffordance
from ...utils import get_current_async_loop
from ..server import BaseProtocolServer
from ..thing import thing_repository
from .controllers import ThingDescriptionPublisher, TopicPublisher


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

    topic_publisher = ClassSelector(class_=TopicPublisher, allow_None=False, default=TopicPublisher)
    """The TopicPublisher class to use for publishing messages"""

    thing_description_publisher = ClassSelector(
        class_=ThingDescriptionPublisher,
        allow_None=False,
        default=ThingDescriptionPublisher,
    )
    """The ThingDescriptionPublisher class to use for publishing Thing Descriptions"""

    def __init__(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str,
        things: Optional[list[CoreThing]] = None,
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
        endpoint = f"{self.hostname}{f':{self.port}' if self.port else ''}"

        self.hostname = hostname
        self.port = port
        self.qos = qos
        self.username = username
        self.password = password
        self.publishers = dict()  # type: dict[str, TopicPublisher]
        self.topic_publisher = kwargs.get("topic_publisher", TopicPublisher)
        self.thing_description_publisher = kwargs.get("thing_description_publisher", ThingDescriptionPublisher)
        self.logger = kwargs.get("logger", structlog.get_logger()).bind(component="mqtt-publisher", hostname=endpoint)
        self.ssl_context = kwargs.get("ssl_context", None)
        self.add_things(*(things or []))

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
        async def start_publishers(thing: CoreThing):
            eventloop = get_current_async_loop()
            if not thing.rpc_server:
                raise ValueError(f"Thing {thing.id} is not associated with any RPC server")

            await self._instantiate_broker(server_id=thing.rpc_server.id, thing_id=thing.id, access_point="INPROC")
            broker_thing = thing_repository[thing.id]
            td = broker_thing.TD

            for event_name in td.get("events", {}).keys():
                event_affordance = EventAffordance.from_TD(event_name, td)
                topic_publisher = self.topic_publisher(
                    client=self.client,
                    resource=event_affordance,
                    logger=self.logger,
                    qos=self.qos,
                )
                self.publishers[topic_publisher.topic] = topic_publisher
                eventloop.create_task(topic_publisher.publish())
                self.logger.info(f"MQTT will publish events for {event_name} of thing {thing.id}")
            for prop_name in td.get("properties", {}).keys():
                property_affordance = PropertyAffordance.from_TD(prop_name, td)
                if not property_affordance.observable:
                    continue
                topic_publisher = self.topic_publisher(
                    client=self.client,
                    resource=property_affordance,
                    logger=self.logger,
                    qos=self.qos,
                )
                self.publishers[topic_publisher.topic] = topic_publisher
                eventloop.create_task(topic_publisher.publish())
                self.logger.info(f"MQTT will publish observable property changes for {prop_name} of thing {thing.id}")
            # TD publisher
            td_publisher = self.thing_description_publisher(client=self.client, logger=self.logger, ZMQ_TD=td)
            self.publishers[td_publisher.topic] = td_publisher
            eventloop.create_task(td_publisher.publish(td))

        eventloop = get_current_async_loop()
        for thing in self.things:
            eventloop.create_task(start_publishers(thing))

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        for publisher in self.publishers.values():
            publisher.stop()
