import ssl
import threading
import warnings

from typing import Any

import aiomqtt
import httpx
import structlog

from paho.mqtt.client import CallbackAPIVersion, MQTTMessage, MQTTProtocolVersion
from paho.mqtt.client import Client as PahoMQTTClient

from ..constants import ZMQ_TRANSPORTS
from ..core import Thing
from ..core.zmq import AsyncZMQClient, SyncZMQClient
from ..serializers import Serializers
from ..td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ..utils import uuid_hex
from .abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty
from .http.consumed_interactions import HTTPAction, HTTPEvent, HTTPProperty
from .mqtt.consumed_interactions import MQTTConsumer  # only one type for now
from .proxy import ObjectProxy
from .security import BasicSecurity
from .zmq.consumed_interactions import (
    ReadMultipleProperties,
    WriteMultipleProperties,
    ZMQAction,
    ZMQEvent,
    ZMQProperty,
)


class ClientFactory:
    """
    A factory class for creating clients to interact with `Thing`s over different protocols.
    This object is not meant to be instantiated, but rather provides class methods for creating clients.

    ```python
    zmq_client = ClientFactory.zmq(server_id="server1", thing_id="thing1", access_point="ipc:///tmp/thing1")
    http_client = ClientFactory.http(url="https://example.com/thing-description")
    mqtt_client = ClientFactory.mqtt(hostname="broker.example.com", port=8883, thing_id="thing1", username="user", password="pass")
    ```
    """

    __wrapper_assignments__ = ("__name__", "__qualname__", "__doc__")

    @classmethod
    def zmq(
        self,
        server_id: str,
        thing_id: str,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        **kwargs,
    ) -> ObjectProxy:
        """
        Create a ZMQ client for the specified server and thing.

        Parameters
        ----------
        server_id: str
            The ID of the server to connect to
        thing_id: str
            The ID of the thing to interact with
        access_point: str
            The ZMQ protocol to use for communication (`IPC` or `INPROC`) or `tcp://<host>:<port>` for TCP
        kwargs:
            Additional configuration options:

            - `logger`: `structlog.stdlib.BoundLogger`, optional.
                 A custom logger instance to use for logging
            - `ignore_TD_errors`: `bool`, default `False`.
                Whether to ignore errors while fetching the Thing Description (TD)
            - `skip_interaction_affordances`: `list[str]`, default `[]`.
                A list of interaction names to skip (property, action or event names)
            - `invokation_timeout`: `float`, optional, default `5.0`.
                The timeout for invokation requests (in seconds)
            - `execution_timeout`: `float`, optional, default `5.0`.
                The timeout for execution requests (in seconds)

        Returns
        -------
        ObjectProxy
            An ObjectProxy instance representing the remote Thing
        """
        id = kwargs.get("id", f"{server_id}|{thing_id}|{access_point}|{uuid_hex()}")

        # configs
        ignore_TD_errors = kwargs.get("ignore_TD_errors", False)
        skip_interaction_affordances = kwargs.get("skip_interaction_affordances", [])
        invokation_timeout = kwargs.get("invokation_timeout", 5.0)
        execution_timeout = kwargs.get("execution_timeout", 5.0)
        logger = kwargs.get("logger", structlog.get_logger()).bind(
            component="client",
            client_id=id,
            protocol="zmq",
            thing_id=thing_id,
        )

        # ZMQ req-rep clients
        sync_zmq_client = SyncZMQClient(f"{id}|sync", server_id=server_id, logger=logger, access_point=access_point)
        async_zmq_client = AsyncZMQClient(f"{id}|async", server_id=server_id, logger=logger, access_point=access_point)

        # Fetch the TD
        Thing.get_thing_model  # type: Action
        FetchTDAffordance = Thing.get_thing_model.to_affordance()
        FetchTDAffordance.override_defaults(name="get_thing_description", thing_id=thing_id)
        FetchTD = ZMQAction(
            resource=FetchTDAffordance,
            sync_client=sync_zmq_client,
            async_client=async_zmq_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
            owner_inst=None,
            logger=logger,
        )
        TD = FetchTD(
            ignore_errors=ignore_TD_errors,
            protocol=access_point.split("://")[0].upper() if access_point else "IPC",
            skip_names=skip_interaction_affordances,
        )  # dict[str, Any]

        # create ObjectProxy
        object_proxy = ObjectProxy(
            id=id,
            td=TD,
            logger=logger,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
            security=kwargs.get("security", None),
        )

        # add properties
        for name in TD.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, TD)
            consumed_property = ZMQProperty(
                resource=affordance,
                sync_client=sync_zmq_client,
                async_client=async_zmq_client,
                owner_inst=object_proxy,
                invokation_timeout=invokation_timeout,
                execution_timeout=execution_timeout,
                logger=logger,
            )
            self.add_property(object_proxy, consumed_property)
            if hasattr(affordance, "observable") and affordance.observable:
                consumed_observable = ZMQEvent(
                    resource=affordance,
                    owner_inst=object_proxy,
                    logger=logger,
                )
                self.add_event(object_proxy, consumed_observable)
        # add actions
        for action in TD.get("actions", []):
            affordance = ActionAffordance.from_TD(action, TD)
            consumed_action = ZMQAction(
                resource=affordance,
                sync_client=sync_zmq_client,
                async_client=async_zmq_client,
                owner_inst=object_proxy,
                invokation_timeout=invokation_timeout,
                execution_timeout=execution_timeout,
                logger=logger,
            )
            self.add_action(object_proxy, consumed_action)
        # add events
        for event in TD.get("events", []):
            affordance = EventAffordance.from_TD(event, TD)
            consumed_event = ZMQEvent(
                resource=affordance,
                owner_inst=object_proxy,
                logger=logger,
            )
            self.add_event(object_proxy, consumed_event)
        # add top level form handlers (for ZMQ even if said form exists or not)
        for opname, ophandler in zip(
            ["_get_properties", "_set_properties"],
            [ReadMultipleProperties, WriteMultipleProperties],
        ):
            setattr(
                object_proxy,
                opname,
                ophandler(
                    sync_client=sync_zmq_client,
                    async_client=async_zmq_client,
                    owner_inst=object_proxy,
                    invokation_timeout=invokation_timeout,
                    execution_timeout=execution_timeout,
                    logger=logger,
                ),
            )
        return object_proxy

    @classmethod
    def http(self, url: str, **kwargs) -> ObjectProxy:
        """
        Create a HTTP client using the Thing Description (TD) available at the specified URL.

        Parameters
        ----------
        url: str
            The URL of the Thing Description (TD) to fetch.
        kwargs:
            Additional configuration options:

            - `logger`: `structlog.stdlib.BoundLogger`, optional.
                A custom logger instance to use for logging
            - `ignore_TD_errors`: `bool`, default `False`.
                Whether to ignore errors while fetching the Thing Description (TD)
            - `skip_interaction_affordances`: `list[str]`, default `[]`.
                A list of interaction names to skip (property, action or event names)
            - `invokation_timeout`: `float`, optional, default `5.0`.
                The timeout for operation invokation (in seconds)
            - `execution_timeout`: `float`, optional, default `5.0`.
                The timeout for operation execution (in seconds)
            - `connect_timeout`: `float`, optional, default `10.0`.
                The timeout for establishing a HTTP connection (in seconds)
            - `request_timeout`: `float`, optional, default `60.0`.
                The timeout for completing a HTTP request (in seconds)
            - `security`: `BasicSecurity` | `APIKeySecurity`, optional.
                The security scheme to use for authentication
            - `username`: `str`, optional.
                The username for HTTP Basic Authentication, shortcut for creating a `BasicSecurity` instance
            - `password`: `str`, optional.
                The password for HTTP Basic Authentication, shortcut for creating a `BasicSecurity` instance

        Returns
        -------
        ObjectProxy
            An ObjectProxy instance representing the remote Thing
        """

        # config
        skip_interaction_affordances = kwargs.get("skip_interaction_affordances", [])
        invokation_timeout = kwargs.get("invokation_timeout", 5.0)
        execution_timeout = kwargs.get("execution_timeout", 5.0)
        connect_timeout = kwargs.get("connect_timeout", 10.0)
        request_timeout = kwargs.get("request_timeout", 60.0)
        use_localhost = False
        if (
            "http://localhost" in url
            or "http://localhost" in url
            or "http://[::1]" in url
            or "http://[::1]" in url
            or "http://127.0.0.1" in url
        ):
            use_localhost = True

        # create clients
        req_rep_timeout = httpx.Timeout(
            connect=connect_timeout,
            read=request_timeout,
            write=request_timeout,
            pool=2,
        )
        sse_timeout = httpx.Timeout(
            connect=connect_timeout,
            read=3,
            write=request_timeout,
            pool=2,
        )

        req_rep_sync_client = httpx.Client(timeout=req_rep_timeout)
        req_rep_async_client = httpx.AsyncClient(timeout=req_rep_timeout)
        sse_sync_client = httpx.Client(timeout=sse_timeout)
        sse_async_client = httpx.AsyncClient(timeout=sse_timeout)

        # fetch TD
        url = (
            f"{url}?"
            + f"ignore_errors={str(kwargs.get('ignore_TD_errors', False)).lower()}"
            + (f"&skip_names={','.join(skip_interaction_affordances)}" if skip_interaction_affordances else "")
            + f"&use_localhost={str(use_localhost).lower()}"
        )

        # fetch TD
        headers = {"Content-Type": "application/json"}
        security = kwargs.pop("security", None)
        username = kwargs.pop("username", None)
        password = kwargs.pop("password", None)
        if not security and username and password:
            security = BasicSecurity(username=username, password=password)
        if security:
            headers[security.http_header_name] = security.http_header

        response = req_rep_sync_client.get(url, headers=headers)  # type: httpx.Response
        response.raise_for_status()

        TD = Serializers.json.loads(response.content)
        id = kwargs.get("id", f"client|{TD['id']}|HTTP|{uuid_hex()}")
        logger = kwargs.get("logger", structlog.get_logger()).bind(
            component="client",
            client_id=id,
            protocol="http",
            thing_id=TD["id"],
        )
        object_proxy = ObjectProxy(id, td=TD, logger=logger, security=security, **kwargs)

        for name in TD.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, TD)
            consumed_property = HTTPProperty(
                resource=affordance,
                sync_client=req_rep_sync_client,
                async_client=req_rep_async_client,
                invokation_timeout=invokation_timeout,
                execution_timeout=execution_timeout,
                owner_inst=object_proxy,
                logger=logger,
            )
            self.add_property(object_proxy, consumed_property)
            if affordance.observable:
                consumed_event = HTTPEvent(
                    resource=affordance,
                    sync_client=sse_sync_client,
                    async_client=sse_async_client,
                    invokation_timeout=invokation_timeout,
                    execution_timeout=execution_timeout,
                    owner_inst=object_proxy,
                    logger=logger,
                )
                self.add_event(object_proxy, consumed_event)
        for action in TD.get("actions", []):
            affordance = ActionAffordance.from_TD(action, TD)
            consumed_action = HTTPAction(
                resource=affordance,
                sync_client=req_rep_sync_client,
                async_client=req_rep_async_client,
                invokation_timeout=invokation_timeout,
                execution_timeout=execution_timeout,
                owner_inst=object_proxy,
                logger=logger,
            )
            self.add_action(object_proxy, consumed_action)
        for event in TD.get("events", []):
            affordance = EventAffordance.from_TD(event, TD)
            consumed_event = HTTPEvent(
                resource=affordance,
                sync_client=sse_sync_client,
                async_client=sse_async_client,
                invokation_timeout=invokation_timeout,
                execution_timeout=execution_timeout,
                owner_inst=object_proxy,
                logger=logger,
            )
            self.add_event(object_proxy, consumed_event)

        return object_proxy

    @classmethod
    def mqtt(
        self,
        hostname: str,
        port: int,
        thing_id: str,
        protocol_version: MQTTProtocolVersion = MQTTProtocolVersion.MQTTv5,
        qos: int = 1,
        username: str = None,
        password: str = None,
        ssl_context: ssl.SSLContext = None,
        **kwargs,
    ) -> ObjectProxy:
        """
        Create an MQTT client for the specified broker.

        Parameters
        ----------
        hostname: str
            The hostname of the MQTT broker
        port: int
            The port of the MQTT broker
        thing_id: str
            The ID of the thing to interact with
        protocol_version: paho.mqtt.client.MQTTProtocolVersion
            The MQTT protocol version (e.g., MQTTv5)
        qos: int
            The Quality of Service level for MQTT messages (0, 1, or 2)
        username: str, optional
            The username for authenticating with MQTT broker
        password: str, optional
            The password for authenticating with MQTT broker
        kwargs:
            Additional configuration options:

            - `logger`: `structlog.stdlib.BoundLogger`, optional.
                 A custom logger instance to use for logging
        """
        id = kwargs.get("id", f"mqtt-client|{hostname}:{port}|{uuid_hex()}")
        logger = kwargs.get("logger", structlog.get_logger()).bind(
            component="client",
            client_id=id,
            protocol="mqtt",
            thing_id=thing_id,
        )

        td_received_event = threading.Event()
        TD = None

        def fetch_td(client: PahoMQTTClient, userdata, message: MQTTMessage) -> None:
            nonlocal TD, thing_id, logger
            if message.topic != f"{thing_id}/thing-description":
                return
            TD = Serializers.json.loads(message.payload)
            td_received_event.set()

        def on_connect(
            client: PahoMQTTClient,
            userdata: Any,
            flags: Any,
            reason_code: list,
            properties: dict[str, Any],
        ) -> None:  # TODO fix signature
            nonlocal qos
            client.subscribe(f"{thing_id}/#", qos=qos)

        sync_client = PahoMQTTClient(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=id,
            clean_session=True if not protocol_version == MQTTProtocolVersion.MQTTv5 else None,
            protocol=protocol_version,
        )
        if username and password:
            sync_client.username_pw_set(username=username, password=password)
        if ssl_context is not None:
            sync_client.tls_set_context(ssl_context)
        elif kwargs.get("ca_certs", None):
            sync_client.tls_set(ca_certs=kwargs.get("ca_certs", None))
        sync_client.on_connect = on_connect
        sync_client.on_message = fetch_td
        sync_client.connect(hostname, port)
        sync_client.loop_start()

        td_received_event.wait(timeout=10)
        if not TD:
            raise TimeoutError("Timeout while fetching Thing Description (TD) over MQTT")

        if not sync_client._ssl_context and port != 1883:
            warnings.warn(
                "MQTT used without TLS, if you intended to use TLS with a recognised CA & you saw this warning, considering "
                + "opening an issue at https://github.com/hololinked-dev/hololinked. ",
                category=RuntimeWarning,
            )

        async_client = aiomqtt.Client(
            hostname=hostname,
            port=port,
            username=username,
            password=password,
            protocol=protocol_version,
            tls_context=sync_client._ssl_context,
        )

        object_proxy = ObjectProxy(id=id, logger=logger, td=TD)

        for name in TD.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, TD)
            consumed_property = MQTTConsumer(
                sync_client=sync_client,
                async_client=async_client,
                resource=affordance,
                qos=qos,
                logger=logger,
                owner_inst=object_proxy,
            )
            self.add_property(object_proxy, consumed_property)
        for name in TD.get("events", []):
            affordance = EventAffordance.from_TD(name, TD)
            consumed_event = MQTTConsumer(
                sync_client=sync_client,
                async_client=async_client,
                resource=affordance,
                qos=qos,
                logger=logger,
                owner_inst=object_proxy,
            )
            self.add_event(object_proxy, consumed_event)

        return object_proxy

    @classmethod
    def add_action(self, client, action: ConsumedThingAction) -> None:
        """add action to client instance"""
        setattr(action, "__name__", action.resource.name)
        setattr(action, "__qualname__", f"{client.__class__.__name__}.{action.resource.name}")
        setattr(
            action,
            "__doc__",
            action.resource.description or "Invokes the action {} on the remote Thing".format(action.resource.name),
        )
        setattr(client, action.resource.name, action)

    @classmethod
    def add_property(self, client, property: ConsumedThingProperty) -> None:
        """add property to client instance"""
        setattr(property, "__name__", property.resource.name)
        setattr(property, "__qualname__", f"{client.__class__.__name__}.{property.resource.name}")
        setattr(
            property,
            "__doc__",
            property.resource.description
            or "Represents the property {} on the remote Thing".format(property.resource.name),
        )
        setattr(client, property.resource.name, property)

    @classmethod
    def add_event(cls, client, event: ConsumedThingEvent) -> None:
        """add event to client instance"""
        setattr(event, "__name__", event.resource.name)
        setattr(event, "__qualname__", f"{client.__class__.__name__}.{event.resource.name}")
        setattr(
            event,
            "__doc__",
            event.resource.description or "Represents the event {} on the remote Thing".format(event.resource.name),
        )
        if hasattr(event.resource, "observable") and event.resource.observable:
            setattr(client, f"{event.resource.name}_change_event", event)
        else:
            setattr(client, event.resource.name, event)
