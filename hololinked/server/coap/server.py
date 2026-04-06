import asyncio
import socket
import ssl
import sys

from copy import deepcopy
from typing import Any, Iterable

import aiocoap
import structlog

from aiocoap.resource import Site, WKCResource

from hololinked.core import Thing
from hololinked.core.zmq.brokers import MessageMappedZMQClientPool
from hololinked.param.parameters import ClassSelector, IPAddress, TypedList
from hololinked.server import BaseProtocolServer
from hololinked.server.coap.config import ResourceMetadata, RuntimeConfig
from hololinked.server.coap.controllers import (
    ActionResource,
    LivenessProbeResource,
    PropertyResource,
    ReadinessProbeResource,
    RPCResource,
    RWMultiplePropertiesResource,
    StopResource,
    ThingDescriptionResource,
)
from hololinked.server.coap.services import ThingDescriptionService
from hololinked.td import ActionAffordance, EventAffordance, PropertyAffordance
from hololinked.td.interaction_affordance import InteractionAffordance


class CoAPServer(BaseProtocolServer):
    """CoAP server implementation using aiocoap library"""

    address = IPAddress(default="0.0.0.0", doc="IP address")  # type: str
    # SAST(id='hololinked.server.coap.CoAPServer.address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
    """IP address, especially to bind to all interfaces or not"""

    config = ClassSelector(
        class_=RuntimeConfig,
        default=None,
        allow_None=True,
    )  # type: RuntimeConfig
    """Runtime configuration for the CoAP server. See `hololinked.server.coap.config.RuntimeConfig` for details"""

    ssl_context = ClassSelector(
        class_=ssl.SSLContext,
        default=None,
        allow_None=True,
    )  # type: ssl.SSLContext | None
    """SSL context to provide encrypted communication"""

    transports = TypedList(
        item_type=str,
        default=None,
        allow_None=True,
        doc="List of transports to be used by the server. Default: ['simplesocketserver']",
    )
    """
    List of transports to be used by the server. Default: ['simplesocketserver'] for windows, 
    ['udp6'] for linux. Use 
    
    - `udp6` for supported systems (linux or similar)
    - `ws` for WebSocket TCP transport
    - `tinydtls` for DTLS transport
    - `tcpserver` and `simplesocketserver` for TCP transport
    - `tlsserver` for TLS transport
   
    Note that some transports may not be available depending on the platform and installed modules.
    """

    def __init__(
        self,
        *,
        port: int = 60000,
        address: str = "0.0.0.0",
        # SAST(id='hololinked.server.coap.CoAPServer.__init__.address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
        things: list[Thing] | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
        ssl_context: ssl.SSLContext | None = None,
        transports: list[str] | None = None,
        # security_schemes: list[Security] | None = None,
        # protocol_version : int = 1, network_interface : str = 'Ethernet',
        config: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        port: int, default 5683
            the port at which the server should be run
        address: str, default 0.0.0.0
            IP address, using 0.0.0.0 will be replaced to the machine's hostname.
            Therefore, use coap://<machine's hostname>:port to access the server from other devices in the network.
            Use 127.0.0.1 to bind only to localhost. Use suitable address according to the specific
            transport layer when transports are supplied.
        logger: structlog.stdlib.BoundLogger, optional
            structlog.stdlib.BoundLogger instance
        ssl_context: ssl.SSLContext
            SSL context to provide encrypted communication
        security_schemes: list[Security], optional
            list of security schemes to be used by the server. If None, no security scheme is used.
        allowed_clients: List[str]
            serves request and sets CORS only from these clients, other clients are reject with 403. Unlike pure CORS
            feature, the server resource is not even executed if the client is not an allowed client.
        **kwargs:
            additional keyword arguments for server configuration. Usually:

            - `property_resource`: `RPCResource` | `PropertyResource`, optional.
                custom web request resource for property read-write
            - `action_resource`: `RPCResource` | `ActionResource`, optional.
                custom web request resource for action
            - `event_resource`: `EventResource` | `BaseResource`, optional.
                custom event resource for sending CoAP SSE

            or RuntimeConfig attributes can be passed as keyword arguments.
        """
        default_config = dict(
            property_resource=kwargs.get("property_resource", PropertyResource),
            action_resource=kwargs.get("action_resource", ActionResource),
            # event_resource=kwargs.get("event_resource", EventResource),
            thing_description_resource=kwargs.get("thing_description_resource", ThingDescriptionResource),
            RW_multiple_properties_resource=kwargs.get("RW_multiple_properties_resource", RWMultiplePropertiesResource),
            liveness_probe_resource=kwargs.get("liveness_resource", LivenessProbeResource),
            readiness_probe_resource=kwargs.get("readiness_resource", ReadinessProbeResource),
            stop_resource=kwargs.get("stop_resource", StopResource),
            thing_description_service=kwargs.get("thing_description_service", ThingDescriptionService),
            thing_repository=kwargs.get("thing_repository", dict()),
            # security_schemes=security_schemes,
        )
        default_config.update(config or dict())
        config = RuntimeConfig(**default_config)
        # need to be extended when more options are added
        super().__init__(
            port=port,
            address=address,
            logger=logger,
            ssl_context=ssl_context,
            config=config,
            transports=transports,
        )

        self._IP = f"{self.address}:{self.port}"  # TODO, remove this variable later?
        self.id = self._IP
        if self.logger is None:
            self.logger = structlog.get_logger().bind(component="coap-server", host=f"{self.address}:{self.port}")

        self.root = Site()
        self.root.add_resource((".well-known", "core"), WKCResource(self.root.get_resources_as_linkheader))
        self.context = None  # type: aiocoap.Context | None
        self.router = Router(self)
        self.zmq_client_pool = MessageMappedZMQClientPool(
            id=self.id,
            server_ids=[],
            client_ids=[],
            handshake=False,
            poll_timeout=100,
        )
        self.add_things(*(things or []))

    async def setup(self) -> None:
        bind_address = self.address
        if sys.platform != "linux" and bind_address in ("0.0.0.0", "::", ""):
            # On non-Linux platforms, aiocoap's simplesocketserver transport does not support
            # binding to any-address. Resolve to the machine's actual routable IP.
            bind_address = socket.gethostname()
            self.logger.info(f"Non-Linux: resolved 0.0.0.0/[::] to specific interface address {bind_address}")
        self.context = await aiocoap.Context.create_server_context(
            self.root,
            bind=(bind_address, self.port),
            _ssl_context=self.ssl_context,
            transports=self.transports,
            loop=asyncio.get_running_loop(),
        )
        self.context.log = self.logger
        # This method should not block, just create side-effects
        event_loop = asyncio.get_running_loop()

        event_loop.create_task(self.zmq_client_pool.poll_responses())

        for thing in self.things:
            if not thing.rpc_server:
                raise ValueError(f"You need to expose thing {thing.id} via a RPCServer before trying to serve it")
            event_loop.create_task(self._instantiate_broker(thing.rpc_server.id, thing.id, "INPROC"))

    async def start(self) -> None:
        # This method should not block, just create side-effects
        await self.setup()
        self.logger.info(f"CoAP server started at coap://{self.address}:{self.port}")

    def stop(self) -> None:
        """Stop the CoAP server and cleanup resources"""
        self.zmq_client_pool.stop_polling()
        if self.context is not None:
            asyncio.create_task(self.context.shutdown())
            self.logger.info("CoAP server stopped")

    async def async_stop(self) -> None:
        """Async version of stop method to be used when the server is awaited on"""
        self.zmq_client_pool.stop_polling()
        if self.context is not None:
            await self.context.shutdown()
            self.logger.info("CoAP server stopped")

    def add_property(
        self,
        URL_path: str | list[str],
        property: PropertyAffordance,
        coap_methods: Iterable[str],
        resource_class_: type[RPCResource] = PropertyResource,
        **kwargs,
    ):
        """Add a property resource to the server at the specified path"""
        resource = resource_class_(
            resource=property,
            config=self.config,
            metadata=ResourceMetadata(coap_methods=tuple(coap_methods)),
            logger=self.logger,
            **kwargs,
        )
        self.logger.info(f"Adding property resource at path: {URL_path} with CoAP methods: {coap_methods}")
        if isinstance(URL_path, str):
            URL_path = [URL_path]
        self.root.add_resource(URL_path, resource)

    def add_action(
        self,
        URL_path: str | list[str],
        action: ActionAffordance,
        coap_methods: Iterable[str],
        resource_class_: type[RPCResource] = ActionResource,
        **kwargs,
    ):
        """Add an action resource to the server at the specified path"""
        resource = resource_class_(
            resource=action,
            config=self.config,
            metadata=ResourceMetadata(coap_methods=tuple(coap_methods)),
            logger=self.logger,
            **kwargs,
        )
        self.logger.info(f"Adding action resource at path: {URL_path} with CoAP methods: {coap_methods}")
        if isinstance(URL_path, str):
            URL_path = [URL_path]
        self.root.add_resource(URL_path, resource)

    def add_thing(self, thing: Thing) -> None:
        """
        Add a thing instance to be served by the CoAP server. Iterates through the
        interaction affordances and adds a route for each property, action and event.

        Parameters
        ----------
        thing: Thing
            thing instance to be added to the server
        """
        self.router.add_thing(thing)
        self.things.append(thing)


class Router:
    """
    Class Mimicking a HTTP router used for grouping methods
    to add resources to the CoAP server.
    """

    def __init__(self, server: CoAPServer) -> None:
        self.server = server

    def add_interaction_affordances(
        self,
        properties: Iterable[PropertyAffordance],
        actions: Iterable[ActionAffordance],
        events: Iterable[EventAffordance],
        thing_id: str = None,
    ) -> None:
        """
        Can add multiple properties, actions and events at once to the application router.
        Calls `add_rule` method internally for each affordance.

        Parameters
        ----------
        properties: Iterable[PropertyAffordance]
            list of properties to be added
        actions: Iterable[ActionAffordance]
            list of actions to be added
        events: Iterable[EventAffordance]
            list of events to be added
        thing_id: str, optional
            thing id to be prefixed to the URL path of each property, action, and event.
            If the thing_id is not provided, then the rule will be in pending state and not exposed
            until a thing instance with the given thing_id is added to the server.
        """
        for property in properties:
            if property.thing_id is not None:
                path = [property.thing_id, property.name]
            self.server.add_property(
                URL_path=path,
                property=property,
                coap_methods=("GET",) if property.readOnly else ("GET", "PUT"),
                # if prop.fdel is None else ('GET', 'PUT', 'DELETE')
                resource_class_=self.server.config.property_resource,
            )
            # if property.observable:
            #     self.add_event(
            #         URL_path=f"{path}/change-event",
            #         event=property,
            #         resource_class_=self.config.event_resource,
            #     )
        for action in actions:
            if action.name == "get_thing_model":
                continue
            if action.thing_id is not None:
                path = [action.thing_id, action.name]
            self.server.add_action(
                URL_path=path,
                action=action,
                coap_methods=("POST",),
                resource_class_=self.server.config.action_resource,
            )
        # for event in events:
        #     if event.thing_id is not None:
        #         path = [event.thing_id, event.name]
        #     self.server.add_event(URL_path=path, event=event, resource_class_=self.config.event_resource)

        # thing model resource
        get_thing_model_action = next((action for action in actions if action.name == "get_thing_model"), None)
        self.server.add_action(
            URL_path=[thing_id, "resources", "wot-tm"] if thing_id else ["resources", "wot-tm"],
            action=get_thing_model_action,
            coap_methods=("GET",),
            resource_class_=self.server.config.action_resource,
        )

        # # thing description resource
        get_thing_description_action = deepcopy(get_thing_model_action)
        get_thing_description_action.override_defaults(name="get_thing_description")
        self.server.add_action(
            URL_path=[thing_id, "resources", "wot-td"] if thing_id else ["resources", "wot-td"],
            action=get_thing_description_action,
            coap_methods=("GET",),
            resource_class_=self.server.config.thing_description_resource,
            owner_inst=self.server,
        )

        # # RW multiple properties resource
        read_properties = Thing._get_properties.to_affordance(Thing)
        write_properties = Thing._set_properties.to_affordance(Thing)
        read_properties.override_defaults(thing_id=get_thing_model_action.thing_id)
        write_properties.override_defaults(thing_id=get_thing_model_action.thing_id)
        self.server.add_action(
            URL_path=[thing_id, "properties"] if thing_id else ["properties"],
            action=read_properties,
            coap_methods=("GET", "PUT", "PATCH"),
            resource_class_=self.server.config.RW_multiple_properties_resource,
            read_properties_resource=read_properties,
            write_properties_resource=write_properties,
        )

    # can add an entire thing instance at once
    def add_thing(self, thing: Thing) -> None:
        """
        internal method to add a thing instance to be served by the CoAP server. Iterates through the
        interaction affordances and adds a route for each property, action and event.
        """
        # Prepare affordance lists with error handling (single loop)
        if not isinstance(thing, Thing):
            raise TypeError(f"thing should be of type Thing, unknown type given - {type(thing)}")
        TM = thing.get_thing_model(ignore_errors=True).json()
        properties, actions, events = [], [], []
        for prop in TM.get("properties", dict()).keys():
            affordance = PropertyAffordance.from_TD(prop, TM)
            affordance.override_defaults(thing_id=thing.id, thing_cls=thing.__class__, owner=thing)
            properties.append(affordance)
        for action in TM.get("actions", dict()).keys():
            affordance = ActionAffordance.from_TD(action, TM)
            affordance.override_defaults(thing_id=thing.id, thing_cls=thing.__class__, owner=thing)
            actions.append(affordance)
        for event in TM.get("events", dict()).keys():
            affordance = EventAffordance.from_TD(event, TM)
            affordance.override_defaults(thing_id=thing.id, thing_cls=thing.__class__, owner=thing)
            events.append(affordance)
        self.add_interaction_affordances(
            properties,
            actions,
            events,
            thing_id=thing.id,
        )

    def get_injected_dependencies(self, affordance: InteractionAffordance) -> RPCResource:
        for path, resource in self.server.root._resources.items():
            if not isinstance(resource, RPCResource) or not hasattr(resource, "resource"):
                continue
            if resource.resource == affordance:
                return resource

    def get_href_for_affordance(
        self,
        affordance: InteractionAffordance,
        authority: str = None,
        use_localhost: bool = False,
    ) -> str:
        """
        Get the full URL path for the affordance in the application router.

        Parameters
        ----------
        affordance: PropertyAffordance | ActionAffordance | EventAffordance
            the interaction affordance for which the URL path is to be retrieved
        authority: str, optional
            authority (protocol + host + port) to be used in the URL path. If None, the machine's hostname is used.
        use_localhost: bool, default `False`
            if `True`, localhost is used in the basepath instead of the server's hostname.

        Returns
        -------
        str
            full URL path for the affordance
        """
        for path, resource in self.server.root._resources.items():
            if not isinstance(resource, RPCResource) or not hasattr(resource, "resource"):
                continue
            if resource.resource == affordance:
                path = f"/{'/'.join(path)}"
                return f"{self.get_basepath(authority, use_localhost)}{path}"

    def get_basepath(self, authority: str = None, use_localhost: bool = False) -> str:
        """
        Get the basepath of the server.

        Parameters
        ----------
        authority: str, optional
            authority (protocol + host + port) to be used in the basepath. If None, the machine's hostname is used.
        use_localhost: bool, default `False`
            if `True`, localhost is used in the basepath instead of the server's hostname.
        """
        if authority:
            return authority
        protocol = "coaps" if self.server.ssl_context else "coap"
        port = f":{self.server.port}" if self.server.port != 80 else ""
        if not use_localhost:
            return f"{protocol}://{socket.gethostname()}{port}"
        if self.server.address == "0.0.0.0" or self.server.address == "127.0.0.1":
            # SAST(id='hololinked.server.coap.ApplicationRouter.get_basepath', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
            return f"{protocol}://127.0.0.1{port}"
        elif self.server.address == "::":
            return f"{protocol}://[::1]{port}"
        return f"{protocol}://localhost{port}"
