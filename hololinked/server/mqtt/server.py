import ssl

from typing import Optional, Type  # noqa: F401

import aiomqtt
import structlog

from ...core import Thing as CoreThing
from ...param.parameters import ClassSelector, String
from ...td.interaction_affordance import EventAffordance, PropertyAffordance
from ...utils import get_current_async_loop
from ..repository import thing_repository
from ..server import BaseProtocolServer
from .config import RuntimeConfig
from .controllers import ThingDescriptionPublisher, TopicPublisher
from .services import ThingDescriptionService


class MQTTPublisher(BaseProtocolServer):
    """
    MQTT Publisher. All events and observable properties defined on the Thing will be published to MQTT topics
    with topic name "{thing id}/{event name}".

    For setting up an MQTT broker if one does not exist,
    see [infrastructure project](https://github.com/hololinked-dev/daq-system-infrastructure).
    """

    hostname = String(default="localhost")
    """The MQTT broker hostname"""

    ssl_context = ClassSelector(class_=ssl.SSLContext, allow_None=True, default=None)
    """The SSL context to use for secure connections, or None for no SSL"""

    config = ClassSelector(class_=RuntimeConfig, default=None, allow_None=True)  # type: RuntimeConfig
    """Runtime configuration for the MQTT publisher"""

    def __init__(
        self,
        hostname: str,
        port: int,
        username: str,
        password: str,
        qos: int = 1,
        things: Optional[list[CoreThing]] = None,
        config: Optional[dict] = None,
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
            The (global) MQTT QoS level to use for publishing messages
        things: list[Thing]
            The `Thing`s that need to publish their events/properties to MQTT broker
        config: dict, optional
            Additional runtime configuration for the MQTT publisher, see `RuntimeConfig` object under
            `hololinked.server.mqtt.config`
        kwargs: dict
            Additional keyword arguments
        """
        endpoint = f"{self.hostname}{f':{self.port}' if self.port else ''}"

        default_config = dict(
            topic_publisher=kwargs.get("topic_publisher", TopicPublisher),
            thing_description_publisher=kwargs.get("thing_description_publisher", ThingDescriptionPublisher),
            thing_description_service=kwargs.get("thing_description_service", ThingDescriptionService),
            thing_repository=kwargs.get("thing_repository", thing_repository),
            qos=qos,
        )
        default_config.update(config or dict())
        config = RuntimeConfig(**default_config)

        self.hostname = hostname
        self.port = port
        self.config = config
        self.username = username
        self.password = password
        self.publishers = dict()  # type: dict[str, TopicPublisher]
        self.logger = kwargs.get("logger", structlog.get_logger()).bind(component="mqtt-publisher", hostname=endpoint)
        self.ssl_context = kwargs.get("ssl_context", None)
        self.add_things(*(things or []))

    async def start(self):
        """
        Sets up the MQTT client and starts publishing events from the `Thing`s.
        All events are dispatched to their own async tasks. This method returns and
        creates side-effects only & does not block. Use the `run()` method instead for a blocking call.
        """
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

    async def start_publishers(self, thing: CoreThing) -> None:
        """Start the publishers for a given `Thing`"""
        eventloop = get_current_async_loop()
        if not thing.rpc_server:
            raise ValueError(f"Thing {thing.id} is not associated with any RPC server")

        await self._instantiate_broker(server_id=thing.rpc_server.id, thing_id=thing.id, access_point="INPROC")
        TD = thing_repository[thing.id].TD

        for event_name in TD.get("events", {}).keys():
            event_affordance = EventAffordance.from_TD(event_name, TD)
            topic_publisher = self.config.topic_publisher(
                client=self.client,
                resource=event_affordance,
                logger=self.logger,
                config=self.config,
            )
            self.publishers[topic_publisher.topic] = topic_publisher
            eventloop.create_task(topic_publisher.publish())
            self.logger.info(f"MQTT will publish events for {event_name} of thing {thing.id}")
        for prop_name in TD.get("properties", {}).keys():
            property_affordance = PropertyAffordance.from_TD(prop_name, TD)
            if not property_affordance.observable:
                continue
            topic_publisher = self.config.topic_publisher(
                client=self.client,
                resource=property_affordance,
                logger=self.logger,
                config=self.config,
            )
            self.publishers[topic_publisher.topic] = topic_publisher
            eventloop.create_task(topic_publisher.publish())
            self.logger.info(f"MQTT will publish observable property changes for {prop_name} of thing {thing.id}")
        # TD publisher
        td_publisher = self.config.thing_description_publisher(
            client=self.client,
            logger=self.logger,
            ZMQ_TD=TD,
            config=self.config,
        )
        self.publishers[td_publisher.topic] = td_publisher
        eventloop.create_task(td_publisher.publish(TD))

    async def setup(self) -> None:
        """Setup MQTT publishers per `Thing` post connection to broker"""
        eventloop = get_current_async_loop()
        for thing in self.things:
            eventloop.create_task(self.start_publishers(thing))

    def stop(self):
        """stop publishing, the client is not closed automatically"""
        for publisher in self.publishers.values():
            publisher.stop()
