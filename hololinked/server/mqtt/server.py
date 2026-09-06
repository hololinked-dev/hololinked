"""MQTT publisher that exposes `Thing` events and properties through an MQTT broker."""

import ssl

from typing import Any, Optional, Type  # noqa: F401

import aiomqtt
import structlog

from ...core import Thing as CoreThing
from ...metadata.td.interaction_affordance import EventAffordance, PropertyAffordance
from ...param.parameters import ClassSelector, String
from ...utils import get_current_async_loop
from ..server import BaseProtocolServer
from .config import RuntimeConfig
from .controllers import ThingDescriptionPublisher, TopicPublisher
from .services import ThingDescriptionService


class MQTTPublisher(BaseProtocolServer):
    """
    MQTT Publisher.

    All events and observable properties defined on the Thing will be published to MQTT topics
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
        Initialize the MQTT publisher.

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
        default_config: dict[str, Any] = dict(
            topic_publisher=kwargs.get("topic_publisher", TopicPublisher),
            thing_description_publisher=kwargs.get("thing_description_publisher", ThingDescriptionPublisher),
            thing_description_service=kwargs.get("thing_description_service", ThingDescriptionService),
            qos=qos,
        )
        default_config.update(config or dict())

        super().__init__(config=RuntimeConfig(**default_config))

        endpoint = f"{hostname}{f':{port}' if port else ''}"

        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.publishers = dict()  # type: dict[str, TopicPublisher]
        self.logger = kwargs.get("logger", structlog.get_logger()).bind(component="mqtt-publisher", hostname=endpoint)
        self.ssl_context = kwargs.get("ssl_context", None)
        self.id = endpoint
        self.add_things(*(things or []))

    async def start(self):
        """
        Sets up the MQTT client and starts publishing events from the `Thing`s.

        All events are dispatched to their own async tasks. This method returns and
        creates side-effects only & does not block. Use the `run()` method instead for a blocking call.
        """
        await self.setup()
        loop = get_current_async_loop()
        for thing in self.things.values():
            loop.create_task(self.start_publishers(thing))

    async def start_publishers(self, thing: CoreThing) -> None:
        """
        Start the publishers for a given `Thing`.

        Raises
        ------
        ValueError
            if the `Thing` is not bound to an event loop
        """
        loop = get_current_async_loop()
        if not thing.eventloop:
            raise ValueError(f"Thing {thing.id} is not associated with any event loop")
        TD = thing.get_thing_model(ignore_errors=True).json()

        for event_name in TD.get("events", {}).keys():
            event_affordance = EventAffordance.from_TD(event_name, TD)
            topic_publisher = self.config.topic_publisher(
                client=self.client,
                resource=event_affordance,
                logger=self.logger,
                config=self.config,
                thing=thing,
            )
            self.publishers[topic_publisher.topic] = topic_publisher
            loop.create_task(topic_publisher.publish())
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
                thing=thing,
            )
            self.publishers[topic_publisher.topic] = topic_publisher
            loop.create_task(topic_publisher.publish())
            self.logger.info(f"MQTT will publish observable property changes for {prop_name} of thing {thing.id}")
        # TD publisher
        td_publisher = self.config.thing_description_publisher(
            client=self.client,
            logger=self.logger,
            thing=thing,
            config=self.config,
        )
        self.publishers[td_publisher.topic] = td_publisher
        loop.create_task(td_publisher.publish())

    async def setup(self) -> None:
        """Setup MQTT publishers per `Thing` post connection to broker."""
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

    def stop(self):
        """Stop publishing, the client is not closed automatically."""
        for publisher in self.publishers.values():
            publisher.stop()
