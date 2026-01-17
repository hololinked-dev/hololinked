import socket
import ssl
import warnings

from copy import deepcopy
from typing import Any, Iterable, Type

import structlog

from tornado import ioloop
from tornado.httpserver import HTTPServer as TornadoHTTP1Server
from tornado.web import Application

from ...config import global_config
from ...constants import HTTP_METHODS
from ...core.actions import Action
from ...core.events import Event
from ...core.property import Property
from ...core.thing import Thing, ThingMeta
from ...core.zmq.brokers import MessageMappedZMQClientPool

# from tornado_http2.server import Server as TornadoHTTP2Server
from ...param.parameters import ClassSelector, IPAddress
from ...td import ActionAffordance, EventAffordance, PropertyAffordance
from ...utils import (
    get_current_async_loop,
    issubklass,
    pep8_to_dashed_name,
    run_callable_somehow,
)
from ..repository import thing_repository
from ..security import Security
from ..server import BaseProtocolServer
from .config import HandlerMetadata, RuntimeConfig
from .controllers import (
    ActionHandler,
    BaseHandler,
    EventHandler,
    LivenessProbeHandler,
    PropertyHandler,
    ReadinessProbeHandler,
    RWMultiplePropertiesHandler,
    StopHandler,
    ThingDescriptionHandler,
)
from .services import ThingDescriptionService


class HTTPServer(BaseProtocolServer):
    """
    HTTP(s) server to expose `Thing` over HTTP protocol. Supports HTTP 1.1.
    Use `add_thing`, or `add_property` or `add_action` or `add_event` methods to add things to the server.
    """

    address = IPAddress(default="0.0.0.0", doc="IP address")  # type: str
    # SAST(id='hololinked.server.http.HTTPServer.address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
    """IP address, especially to bind to all interfaces or not"""

    ssl_context = ClassSelector(
        class_=ssl.SSLContext,
        default=None,
        allow_None=True,
    )  # type: ssl.SSLContext | None
    """SSL context to provide encrypted communication"""

    config = ClassSelector(
        class_=RuntimeConfig,
        default=None,
        allow_None=True,
    )  # type: RuntimeConfig
    """Runtime configuration for the HTTP server. See `hololinked.server.http.config.RuntimeConfig` for details"""

    def __init__(
        self,
        *,
        port: int = 8080,
        address: str = "0.0.0.0",  # SAST(id='hololinked.server.http.HTTPServer.__init__.address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
        things: list[Thing] | None = None,
        # host: Optional[str] = None,
        logger: structlog.stdlib.BoundLogger | None = None,
        ssl_context: ssl.SSLContext | None = None,
        security_schemes: list[Security] | None = None,
        # protocol_version : int = 1, network_interface : str = 'Ethernet',
        allowed_clients: str | Iterable[str] | None = None,
        config: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        port: int, default 8080
            the port at which the server should be run
        address: str, default 0.0.0.0
            IP address, use 0.0.0.0 to bind to all interfaces to expose the server to other devices in the network
            and 127.0.0.1 to bind only to localhost
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

            - `property_handler`: `BaseHandler` | `PropertyHandler`, optional.
                custom web request handler for property read-write
            - `action_handler`: `BaseHandler` | `ActionHandler`, optional.
                custom web request handler for action
            - `event_handler`: `EventHandler` | `BaseHandler`, optional.
                custom event handler for sending HTTP SSE

            or RuntimeConfig attributes can be passed as keyword arguments.
        """
        default_config = dict(
            cors=global_config.ALLOW_CORS,
            property_handler=kwargs.get("property_handler", PropertyHandler),
            action_handler=kwargs.get("action_handler", ActionHandler),
            event_handler=kwargs.get("event_handler", EventHandler),
            thing_description_handler=kwargs.get("thing_description_handler", ThingDescriptionHandler),
            RW_multiple_properties_handler=kwargs.get("RW_multiple_properties_handler", RWMultiplePropertiesHandler),
            liveness_probe_handler=kwargs.get("liveness_handler", LivenessProbeHandler),
            readiness_probe_handler=kwargs.get("readiness_handler", ReadinessProbeHandler),
            stop_handler=kwargs.get("stop_handler", StopHandler),
            thing_description_service=kwargs.get("thing_description_service", ThingDescriptionService),
            thing_repository=kwargs.get("thing_repository", thing_repository),
            allowed_clients=allowed_clients,
            security_schemes=security_schemes,
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
        )

        self._IP = f"{self.address}:{self.port}"
        if self.logger is None:
            self.logger = structlog.get_logger().bind(component="http-server", host=f"{self.address}:{self.port}")

        self.tornado_instance = None
        self.app = Application(
            handlers=[
                (
                    r"/stop",
                    self.config.stop_handler,
                    dict(config=self.config, logger=self.logger, owner_inst=self),
                ),
                (
                    r"/liveness",
                    self.config.liveness_probe_handler,
                    dict(config=self.config, logger=self.logger, owner_inst=self),
                ),
                (
                    r"/readiness",
                    self.config.readiness_probe_handler,
                    dict(config=self.config, logger=self.logger, owner_inst=self),
                ),
            ]
        )
        self.router = ApplicationRouter(self.app, self)

        self.zmq_client_pool = MessageMappedZMQClientPool(
            id=self._IP,
            server_ids=[],
            client_ids=[],
            handshake=False,
            poll_timeout=100,
        )
        self.add_things(*(things or []))

    def setup(self) -> None:
        """check if all the requirements are met before starting the server, auto invoked by listen()"""
        # Add only those code here that needs to be redone always before restarting the server.
        # One time creation attributes/activities must be in init

        # Comments are above the relevant lines, not below
        # 1. clear the event loop in case any pending tasks exist, also restarting with same
        # event loop is buggy, so we remove it.
        ioloop.IOLoop.clear_current()
        # 2. sets async loop for a non-possessing thread as well
        event_loop = get_current_async_loop()
        # 3. schedule the ZMQ client pool polling
        event_loop.create_task(self.zmq_client_pool.poll_responses())
        # self.zmq_client_pool.handshake(), NOTE - handshake better done upfront as we already poll_responses here
        # which will prevent handshake function to succeed (although handshake will be done)
        # 4. Expose via broker
        for thing in self.things:
            if not thing.rpc_server:
                raise ValueError(f"You need to expose thing {thing.id} via a RPCServer before trying to serve it")
            event_loop.create_task(
                self._instantiate_broker(
                    thing.rpc_server.id,
                    thing.id,
                    "INPROC",
                )
            )
        # 5. finally also get a reference of the same event loop from tornado
        self.tornado_event_loop = ioloop.IOLoop.current()

        self.tornado_instance = TornadoHTTP1Server(self.app, ssl_options=self.ssl_context)  # type: TornadoHTTP1Server

    async def start(self) -> None:
        self.setup()
        self.tornado_instance.listen(port=self.port, address=self.address)
        self.logger.info(f"started HTTP webserver at {self._IP}, ready to receive requests.")

    def stop(self, attempt_async_stop: bool = True) -> None:
        """
        Stop the HTTP server - unreliable, use `async_stop()` if possible.
        A stop handler at the path `/stop` with POST method is already implemented that invokes this
        method for the clients.

        Parameters
        ----------
        attempt_async_stop: bool, default `True`
            if `True`, attempts to run the `async_stop` method to close all connections gracefully.
        """
        if attempt_async_stop:
            run_callable_somehow(self.async_stop())
            return
        self.zmq_client_pool.stop_polling()
        if not self.tornado_instance:
            return
        self.tornado_instance.stop()
        run_callable_somehow(self.tornado_instance.close_all_connections())

    async def async_stop(self) -> None:
        """
        Stop the HTTP server. A stop handler at the path `/stop` with POST method is already implemented
        that invokes this method for the clients.
        """
        self.zmq_client_pool.stop_polling()
        if not self.tornado_instance:
            return
        try:
            self.tornado_instance.stop()
            await self.tornado_instance.close_all_connections()
        except Exception as ex:
            self.logger.error(
                "error while stopping tornado server, use stop() method "
                + f"from hololinked.server and do not reuse the port - {ex}"
            )

    def add_property(
        self,
        URL_path: str,
        property: Property | PropertyAffordance,
        http_methods: str | tuple[str, str, str] = ("GET", "PUT"),
        handler: BaseHandler | PropertyHandler = PropertyHandler,
        **kwargs,
    ) -> None:
        """
        Add a property to be accessible by HTTP.

        Parameters
        ----------
        URL_path: str
            URL path to access the property
        property: Property | PropertyAffordance
            Property (object) to be served or its JSON representation
        http_methods: Tuple[str, str, str]
            tuple of http methods to be used for read, write and delete. Use None or omit HTTP method for
            unsupported operations. For example - for readonly property use ('GET', None, None) or ('GET',)
        handler: BaseHandler | PropertyHandler, optional
            custom handler for the property, otherwise the default handler will be used
        kwargs: dict
            additional keyword arguments to be passed to the handler's __init__
        """
        if not isinstance(property, (Property, PropertyAffordance)):
            raise TypeError(f"property should be of type Property, given type {type(property)}")
        if not issubklass(handler, BaseHandler):
            raise TypeError(f"handler should be subclass of BaseHandler, given type {type(handler)}")
        if isinstance(property, Property):
            property = property.to_affordance()
        read_http_method = write_http_method = delete_http_method = None
        http_methods = self.router.adapt_http_methods(http_methods)
        if len(http_methods) == 1:
            read_http_method = http_methods[0]
        elif len(http_methods) == 2:
            read_http_method, write_http_method = http_methods
        elif len(http_methods) == 3:
            read_http_method, write_http_method, delete_http_method = http_methods
        if read_http_method != "GET":
            raise ValueError("read method should be GET")
        if write_http_method and write_http_method not in ["POST", "PUT"]:
            raise ValueError("write method should be POST or PUT")
        if delete_http_method and delete_http_method != "DELETE":
            raise ValueError("delete method should be DELETE")
        kwargs["resource"] = property
        kwargs["logger"] = self.logger
        kwargs["config"] = self.config
        kwargs["metadata"] = HandlerMetadata(http_methods=http_methods)
        self.router.add_rule(affordance=property, URL_path=URL_path, handler=handler, kwargs=kwargs)

    def add_action(
        self,
        URL_path: str,
        action: Action | ActionAffordance,
        http_method: str | None = "POST",
        handler: BaseHandler | ActionHandler = ActionHandler,
        **kwargs,
    ) -> None:
        """
        Add an action to be accessible by HTTP

        Parameters
        ----------
        URL_path: str
            URL path to access the action
        action: Action | ActionAffordance
            Action (object) to be served or its JSON representation
        http_method: str
            http method to be used for the action
        handler: BaseHandler | ActionHandler, optional
            custom handler for the action
        kwargs: dict
            additional keyword arguments to be passed to the handler's __init__
        """
        if not isinstance(action, (Action, ActionAffordance)):
            raise TypeError(f"Given action should be of type Action or ActionAffordance, given type {type(action)}")
        if not issubklass(handler, BaseHandler):
            raise TypeError(f"handler should be subclass of BaseHandler, given type {type(handler)}")
        http_methods = self.router.adapt_http_methods(http_method)
        if isinstance(action, Action):
            action = action.to_affordance()  # type: ActionAffordance
        kwargs["resource"] = action
        kwargs["config"] = self.config
        kwargs["logger"] = self.logger
        kwargs["metadata"] = HandlerMetadata(http_methods=http_methods)
        self.router.add_rule(affordance=action, URL_path=URL_path, handler=handler, kwargs=kwargs)

    def add_event(
        self,
        URL_path: str,
        event: Event | EventAffordance | PropertyAffordance,
        handler: BaseHandler | EventHandler = EventHandler,
        **kwargs,
    ) -> None:
        """
        Add an event to be accessible by HTTP server; only GET method is supported for events.

        Parameters
        ----------
        URL_path: str
            URL path to access the event
        event: Event | EventAffordance
            Event (object) to be served or its JSON representation
        handler: BaseHandler | EventHandler, optional
            custom handler for the event
        kwargs: dict
            additional keyword arguments to be passed to the handler's __init__
        """
        if not isinstance(event, (Event, EventAffordance)) and (
            not isinstance(event, PropertyAffordance) or not event.observable
        ):
            raise TypeError(f"event should be of type Event or EventAffordance, given type {type(event)}")
        if not issubklass(handler, BaseHandler):
            raise TypeError(f"handler should be subclass of BaseHandler, given type {type(handler)}")
        if isinstance(event, Event):
            event = event.to_affordance()
        kwargs["resource"] = event
        kwargs["config"] = self.config
        kwargs["logger"] = self.logger
        kwargs["metadata"] = HandlerMetadata(http_methods=("GET",))
        self.router.add_rule(affordance=event, URL_path=URL_path, handler=handler, kwargs=kwargs)

    def add_thing(self, thing: Thing) -> None:
        self.router.add_thing(thing)
        self.things.append(thing)

    def __hash__(self):
        return hash(self._IP)

    def __eq__(self, other):
        if not isinstance(other, HTTPServer):
            return False
        return self._IP == other._IP

    def __str__(self):
        return f"{self.__class__.__name__}(address={self.address}, port={self.port})"


class ApplicationRouter:
    """
    Covering implementation (as in - a layer on top) of the application router to
    add rules to the tornado application. Not a real router, which is taken care of
    by the tornado application automatically.
    """

    def __init__(self, app: Application, server: HTTPServer) -> None:
        self.app = app
        self.server = server
        self.logger = server.logger.bind(component="http-router")
        self._pending_rules = []
        self._rules = dict()  # type: dict[str, Any]

    # can add a single property, action or event rule
    def add_rule(
        self,
        affordance: PropertyAffordance | ActionAffordance | EventAffordance,
        URL_path: str,
        handler: Type[BaseHandler],
        kwargs: dict[str, Any],
    ) -> None:
        """
        Add rule to the application router. Note that this method will replace existing rules and can duplicate
        endpoints for an affordance without checks (i.e. you could technically add two different endpoints for the
        same affordance).

        Parameters
        ----------
        affordance: PropertyAffordance | ActionAffordance | EventAffordance
            the interaction affordance for which the rule is being added
        URL_path: str
            URL path to access the affordance
        handler: Type[BaseHandler]
            handler class to be used for the affordance
        kwargs: dict[str, Any]
            additional keyword arguments to be passed to the handler's __init__
        """
        for rule in self.app.wildcard_router.rules:
            if rule.matcher == URL_path:
                warnings.warn(
                    f"URL path {URL_path} already exists in the router -"
                    + f" replacing it for {affordance.what} {affordance.name}",
                    category=UserWarning,
                )
        for rule in self._pending_rules:
            if rule[0] == URL_path:
                warnings.warn(
                    f"URL path {URL_path} already exists in the pending rules -"
                    + f" replacing it for {affordance.what} {affordance.name}",
                    category=UserWarning,
                )
        if getattr(affordance, "thing_id", None):
            if not URL_path.startswith(f"/{affordance.thing_id}"):
                warnings.warn(
                    f"URL path {URL_path} does not start with the thing id {affordance.thing_id},"
                    + f" adding it to the path, new path = {f'/{affordance.thing_id}{URL_path}'}. "
                    + " This warning can be usually safely ignored."
                )
                URL_path = f"/{affordance.thing_id}{URL_path}"
            self.logger.info(
                f"adding rule for {affordance.what} {affordance.name} at path {URL_path}"
                + f" for thing id {affordance.thing_id}"
            )
            self.app.wildcard_router.add_rules([(URL_path, handler, kwargs)])
        elif affordance.thing_cls is not None:
            self.logger.info(
                f"adding pending rule for {affordance.what} {affordance.name} at path {URL_path}"
                + f" for thing class {affordance.thing_cls.__name__}, probably no forms exist yet."
            )
            self._pending_rules.append((URL_path, handler, kwargs))
        else:
            raise RuntimeError("object has no thing id or thing class associated with it, cannot add rule")
        """
        for handler based tornado rule matcher, the Rule object has following
        signature
        
        def __init__(
            self,
            matcher: "Matcher",
            target: Any,
            target_kwargs: Optional[Dict[str, Any]] = None,
            name: Optional[str] = None,
        ) -> None:

        matcher - based on route
        target - handler
        target_kwargs - given to handler's initialize
        name - ...

        len == 2 tuple is route + handler
        len == 3 tuple is route + handler + target kwargs
    
        so we give (path, BaseHandler, {'resource' : PropertyAffordance, 'owner' : self})
        
        path is extracted from interaction affordance name or given by the user
        BaseHandler is the base handler of this package for interaction affordances
        resource goes into target kwargs which is needed for the handler to work correctly
        """

    # can add multiple properties, actions and events at once
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
            if property in self:
                continue
            route = self.adapt_route(property.name)
            if property.thing_id is not None:
                path = f"/{property.thing_id}{route}"
            self.server.add_property(
                URL_path=path,
                property=property,
                http_methods=("GET",) if property.readOnly else ("GET", "PUT"),
                # if prop.fdel is None else ('GET', 'PUT', 'DELETE')
                handler=self.server.config.property_handler,
            )
            if property.observable:
                self.server.add_event(
                    URL_path=f"{path}/change-event",
                    event=property,
                    handler=self.server.config.event_handler,
                )
        for action in actions:
            if action in self:
                continue
            elif action.name == "get_thing_model":
                continue
            route = self.adapt_route(action.name)
            if action.thing_id is not None:
                path = f"/{action.thing_id}{route}"
            self.server.add_action(URL_path=path, action=action, handler=self.server.config.action_handler)
        for event in events:
            if event in self:
                continue
            route = self.adapt_route(event.name)
            if event.thing_id is not None:
                path = f"/{event.thing_id}{route}"
            self.server.add_event(URL_path=path, event=event, handler=self.server.config.event_handler)

        # thing model handler
        get_thing_model_action = next((action for action in actions if action.name == "get_thing_model"), None)
        self.server.add_action(
            URL_path=f"/{thing_id}/resources/wot-tm" if thing_id else "/resources/wot-tm",
            action=get_thing_model_action,
            http_method=("GET",),
        )

        # thing description handler
        get_thing_description_action = deepcopy(get_thing_model_action)
        get_thing_description_action.override_defaults(name="get_thing_description")
        self.server.add_action(
            URL_path=f"/{thing_id}/resources/wot-td" if thing_id else "/resources/wot-td",
            action=get_thing_description_action,
            http_method=("GET",),
            handler=self.server.config.thing_description_handler,
            owner_inst=self.server,
        )

        # RW multiple properties handler
        read_properties = Thing._get_properties.to_affordance(Thing)
        write_properties = Thing._set_properties.to_affordance(Thing)
        read_properties.override_defaults(thing_id=get_thing_model_action.thing_id)
        write_properties.override_defaults(thing_id=get_thing_model_action.thing_id)
        self.server.add_action(
            URL_path=f"/{thing_id}/properties" if thing_id else "/properties",
            action=read_properties,
            http_method=("GET", "PUT", "PATCH"),
            handler=self.server.config.RW_multiple_properties_handler,
            read_properties_resource=read_properties,
            write_properties_resource=write_properties,
        )

    # can add an entire thing instance at once
    def add_thing(self, thing: Thing) -> None:
        """
        internal method to add a thing instance to be served by the HTTP server. Iterates through the
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
        self._resolve_rules(thing.id, thing.__class__)
        self.add_interaction_affordances(
            properties,
            actions,
            events,
            thing_id=thing.id,
        )

    def _resolve_rules(
        self,
        thing_id: str,
        thing_cls: ThingMeta,
    ) -> None:
        """
        Process the pending rules and add them to the application router.
        Rules become pending only when a property, action or event has a thing class associated
        but no thing instance.
        """
        pending_rules = self._pending_rules
        self._pending_rules = []
        for rule in pending_rules:
            affordance = rule[2].get("resource", None)  # type: PropertyAffordance | ActionAffordance | EventAffordance
            if not affordance or affordance.owner != thing_cls:
                self._pending_rules.append(rule)
                continue
            affordance.override_defaults(thing_cls=thing_cls, thing_id=thing_id)
            URL_path, handler, kwargs = rule
            URL_path = f"/{thing_id}{URL_path}"
            rule = (URL_path, handler, kwargs)
            self.add_rule(affordance=affordance, URL_path=URL_path, handler=handler, kwargs=kwargs)

    def __contains__(
        self,
        item: str | Property | Action | Event | PropertyAffordance | ActionAffordance | EventAffordance,
    ) -> bool:
        """
        Check if the item is in the application router.
        Not exact for torando's rules when a string is provided for the URL path,
        as you need to provide the Matcher object
        """
        if isinstance(item, str):
            for rule in self.app.wildcard_router.rules:
                if rule.matcher == item:
                    return True
                if hasattr(rule.matcher, "regex") and rule.matcher.regex.match(item):
                    return True
            for rule in self._pending_rules:
                if rule[0] == item:
                    return True
        elif isinstance(item, (Property, Action, Event)):
            item = item.to_affordance()
        if isinstance(item, (PropertyAffordance, ActionAffordance, EventAffordance)):
            for rule in self.app.wildcard_router.rules:
                if rule.target_kwargs.get("resource", None) == item:
                    return True
            for rule in self._pending_rules:
                if rule[2].get("resource", None) == item:
                    return True
        return False

    def get_href_for_affordance(self, affordance, authority: str = None, use_localhost: bool = False) -> str:
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
        if affordance not in self:
            raise ValueError(f"affordance {affordance} not found in the application router")
        for rule in self.app.wildcard_router.rules:
            if rule.target_kwargs.get("resource", None) == affordance:
                path = str(rule.matcher.regex.pattern).rstrip("$")
                return f"{self.get_basepath(authority, use_localhost)}{path}"

    def get_injected_dependencies(self, affordance) -> dict[str, Any]:
        """Get the target kwargs for the affordance in the application router"""
        if affordance not in self:
            raise ValueError(f"affordance {affordance} not found in the application router")
        for rule in self.app.wildcard_router.rules:
            if rule.target_kwargs.get("resource", None) == affordance:
                return rule.target_kwargs
        for rule in self._pending_rules:
            if rule[2].get("resource", None) == affordance:
                return rule[2]
        raise ValueError(f"affordance {affordance} not found in the application router rules")

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
        protocol = "https" if self.server.ssl_context else "http"
        port = f":{self.server.port}" if self.server.port != 80 else ""
        if not use_localhost:
            return f"{protocol}://{socket.gethostname()}{port}"
        if self.server.address == "0.0.0.0" or self.server.address == "127.0.0.1":
            # SAST(id='hololinked.server.http.ApplicationRouter.get_basepath', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
            return f"{protocol}://127.0.0.1{port}"
        elif self.server.address == "::":
            return f"{protocol}://[::1]{port}"
        return f"{protocol}://localhost{port}"

    basepath = property(fget=get_basepath, doc="basepath of the server")

    def adapt_route(self, interaction_affordance_name: str) -> str:
        """adapt the URL path to default conventions"""
        if interaction_affordance_name == "get_thing_model":
            return "/resources/wot-tm"
        return f"/{pep8_to_dashed_name(interaction_affordance_name)}"

    def adapt_http_methods(self, http_methods: Any):
        """comply the supplied HTTP method to the router to a tuple and check if the method is supported"""
        if isinstance(http_methods, str):
            http_methods = (http_methods,)
        if not isinstance(http_methods, tuple):
            raise TypeError("http_method should be a tuple")
        for method in http_methods:
            if method not in HTTP_METHODS.__members__.values() and method is not None:
                raise ValueError(f"method {method} not supported")
        return http_methods

    def print_rules(self) -> None:
        """
        Print the rules in the application router.
        prettytable is used if available, otherwise a simple print is done.
        """
        try:
            from prettytable import PrettyTable

            table = PrettyTable()
            table.field_names = ["URL Path", "Handler", "Resource Name"]

            for rule in self.app.wildcard_router.rules:
                table.add_row(
                    [
                        rule.matcher,
                        rule.target.__name__,
                        getattr(rule.target_kwargs.get("resource"), "name", "N/A"),
                    ]
                )
            for rule in self._pending_rules:
                table.add_row([rule[0], rule[1].__name__, rule[2]["resource"].name])
            print(table)
        except ImportError:
            print("Application Router Rules:")
            for rule in self.app.wildcard_router.rules:
                print(rule)
            for rule in self._pending_rules:
                print(rule[0], rule[2]["resource"].name)


__all__ = [HTTPServer.__name__]
