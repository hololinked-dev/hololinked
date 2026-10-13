"""MQTT publisher that exposes `Thing` events and properties through an MQTT broker."""

import ssl

from typing import Any, Optional, Self  # noqa: F401

import aiomqtt
import structlog

from hololinked.core import Thing
from hololinked.core import Thing as CoreThing
from hololinked.core.interfaces import BaseProtocolServer
from hololinked.core.property import Property
from hololinked.metadata.td.interaction_affordance import EventAffordance, PropertyAffordance
from hololinked.param.parameters import ClassSelector, String
from hololinked.server.mqtt.config import RuntimeConfig
from hololinked.server.mqtt.handlers import ThingDescriptionPublisher, TopicPublisher
from hololinked.server.mqtt.services import ThingDescriptionService
from hololinked.utils import get_current_async_loop


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
        use_websocket: bool = False,
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
        use_websocket: bool
            Whether to use WebSocket transport instead of TCP
        kwargs: dict
            Additional keyword arguments
        """
        default_config: dict[str, Any] = dict(
            topic_publisher=kwargs.get("topic_publisher", TopicPublisher),
            thing_description_publisher=kwargs.get("thing_description_publisher", ThingDescriptionPublisher),
            thing_description_service=kwargs.get("thing_description_service", ThingDescriptionService),
            qos=qos,
            use_websocket=use_websocket,
        )
        default_config.update(config or dict())

        super().__init__(config=RuntimeConfig(**default_config))

        endpoint = f"{hostname}{f':{port}' if port else ''}"

        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.publishers = dict()  # type: dict[str, TopicPublisher]
        self.custom_topics: dict[tuple[str, str], str] = dict()  # (thing_id, name) → topic
        self.custom_qos: dict[tuple[str, str], int] = dict()  # (thing_id, name) → qos
        self.custom_publishers: dict[tuple[str, str], type[TopicPublisher]] = dict()  # (thing_id, name) → publisher class
        self.logger = kwargs.get("logger", structlog.get_logger()).bind(component="mqtt-publisher", hostname=endpoint)
        self.ssl_context = kwargs.get("ssl_context", None)
        self.id = endpoint
        self.add_things(*(things or []))

    @classmethod
    def from_params(cls, id: str, params: str | int | dict | list[str] | None) -> Self:  # noqa: D102
        # doc already provided in the base class
        if isinstance(params, str):
            params = dict(hostname=params)
        elif not isinstance(params, dict):
            raise ValueError("MQTT parameters must be supplied as a dictionary or the broker hostname as a string.")
        return cls(**params)

    def welcome_lines(self) -> list[str]:  # noqa: D102
        # doc already provided in the base class
        lines = ["", "📡 MQTT:", f" • Broker:   {self.hostname}:{self.port}"]
        for thing in self.things.values():
            lines.append(f"   ➜ Topic tree: {thing.id}/thing-description")
        return lines

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
            key = (thing.id, event_name)
            custom_qos = self.custom_qos.get(key)
            custom_publisher = self.custom_publishers.get(key, self.config.topic_publisher)

            topic_publisher = custom_publisher(
                client=self.client,
                resource=event_affordance,
                logger=self.logger,
                config=self.config,
                thing=thing,
                topic=self.custom_topics.get(key, None),
                qos=custom_qos,
            )
            self.publishers[topic_publisher.topic] = topic_publisher
            loop.create_task(topic_publisher.publish())
            self.logger.info(f"MQTT will publish events for {event_name} of thing {thing.id}")
        for prop_name in TD.get("properties", {}).keys():
            property_affordance = PropertyAffordance.from_TD(prop_name, TD)
            if not property_affordance.observable:
                continue

            key = (thing.id, prop_name)
            custom_qos = self.custom_qos.get(key)
            custom_publisher = self.custom_publishers.get(key, self.config.topic_publisher)

            topic_publisher = custom_publisher(
                client=self.client,
                resource=property_affordance,
                logger=self.logger,
                config=self.config,
                thing=thing,
                topic=self.custom_topics.get(key, None),
                qos=custom_qos,
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
            custom_topics=self.custom_topics,
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
            transport="websockets" if self.config.use_websocket else "tcp",
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

    def add_observable(
        self,
        name: str,
        thing: Thing | CoreThing,
        topic_name: str,
        publisher: type[TopicPublisher] = TopicPublisher,
        qos: int | None = None,
    ) -> None:
        """
        Add an observable property with a custom MQTT topic name.

        Parameters
        ----------
        name: str
            The name of the observable property
        thing: Thing | CoreThing
            The Thing containing the property
        topic_name: str
            The custom MQTT topic name to use
        publisher: type[TopicPublisher], optional
            Custom publisher class (default: TopicPublisher)
        qos: int, optional
            MQTT QoS level (default: None → use global config.qos)

        Raises
        ------
        RuntimeError
            If the property is not observable
        TypeError
            If `thing` is not a Thing/CoreThing
        """
        if not isinstance(thing, (Thing, CoreThing)):
            raise TypeError(f"thing should be type Thing/CoreThing, given type {type(thing)}")

        # Get property from thing class
        property = getattr(thing.__class__, name, None)
        if not isinstance(property, Property):
            raise TypeError(f"{name} is not a Property of {thing.__class__.__name__}")

        affordance = PropertyAffordance.from_descriptor(property, owner=thing)
        if not affordance.observable:
            raise RuntimeError(f"Property {name} is not observable, cannot add to MQTT publisher")

        # Store custom topic, qos, and publisher
        key = (thing.id, name)
        self.custom_topics[key] = topic_name
        if qos is not None:
            self.custom_qos[key] = qos
        self.custom_publishers[key] = publisher

    def add_property(
        self,
        name: str,
        thing: Thing | CoreThing,
        topic_name: str,
        publisher: type[TopicPublisher] = TopicPublisher,
        qos: int | None = None,
    ) -> None:
        """Alias for add_observable."""
        self.add_observable(name, thing, topic_name, publisher, qos)

    def add_event(
        self,
        name: str,
        thing: Thing | CoreThing,
        topic_name: str,
        publisher: type[TopicPublisher] = TopicPublisher,
        qos: int | None = None,
    ) -> None:
        """
        Add an event with a custom MQTT topic name.

        Parameters
        ----------
        name: str
            The name of the event
        thing: Thing | CoreThing
            The Thing containing the event
        topic_name: str
            The custom MQTT topic name to use
        publisher: type[TopicPublisher], optional
            Custom publisher class (default: TopicPublisher)
        qos: int, optional
            MQTT QoS level (default: None → use global config.qos)

        Raises
        ------
        TypeError
            If `thing` is not a Thing/CoreThing
        """
        if not isinstance(thing, (Thing, CoreThing)):
            raise TypeError(f"thing should be type Thing/CoreThing, given type {type(thing)}")

        # Store custom topic, qos, and publisher
        key = (thing.id, name)
        self.custom_topics[key] = topic_name
        if qos is not None:
            self.custom_qos[key] = qos
        self.custom_publishers[key] = publisher
