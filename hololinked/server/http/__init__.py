import asyncio
import warnings
import logging
import socket
import ssl
import typing
from copy import deepcopy
from tornado import ioloop
from tornado.web import Application
from tornado.httpserver import HTTPServer as TornadoHTTP1Server
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

# from tornado_http2.server import Server as TornadoHTTP2Server

from ...param import Parameterized
from ...param.parameters import (
    Integer,
    IPAddress,
    ClassSelector,
    Selector,
    TypedList,
    String,
    TypedDict,
)
from ...constants import HTTP_METHODS
from ...utils import (
    complete_pending_tasks_in_current_loop,
    forkable,
    get_IP_from_interface,
    get_current_async_loop,
    issubklass,
    pep8_to_dashed_name,
    get_default_logger,
    run_callable_somehow,
)
from ...serializers import Serializers
from ...schema_validators import BaseSchemaValidator, JSONSchemaValidator
from ...core.property import Property
from ...core.actions import Action
from ...core.events import Event
from ...core.thing import Thing, ThingMeta
from ...td import ActionAffordance, EventAffordance, PropertyAffordance
from ...core.zmq.brokers import AsyncZMQClient, MessageMappedZMQClientPool
from ..security import Security
from .handlers import (
    ActionHandler,
    LivenessProbeHandler,
    PropertyHandler,
    EventHandler,
    BaseHandler,
    RWMultiplePropertiesHandler,
    StopHandler,
    ThingDescriptionHandler,
    RPCHandler,
)


class HTTPServer(Parameterized):
    """
    HTTP(s) server to expose `Thing` over HTTP protocol. Supports HTTP 1.1.
    Use `add_thing` or `add_property` or `add_action` or `add_event` methods to add things to the server.
    """

    things = TypedList(
        item_type=(str, Thing),
        default=None,
        allow_None=True,
        doc="id(s) of the things to be served by the HTTP server.",
    )  # type: typing.List[str]

    port = Integer(
        default=8080,
        bounds=(1, 65535),
        doc="the port at which the server should be run",
    )  # type: int

    address = IPAddress(default="0.0.0.0", doc="IP address")  # type: str

    # protocol_version = Selector(objects=[1, 1.1, 2], default=2,
    #                 doc="for HTTP 2, SSL is mandatory. HTTP2 is recommended. \
    #                 When no SSL configurations are provided, defaults to 1.1" ) # type: float

    logger = ClassSelector(class_=logging.Logger, default=None, allow_None=True, doc="logging.Logger")  # type: logging.Logger

    log_level = Selector(
        objects=[
            logging.DEBUG,
            logging.INFO,
            logging.ERROR,
            logging.WARN,
            logging.CRITICAL,
            logging.ERROR,
        ],
        default=logging.INFO,
        doc="""alternative to logger, this creates an internal logger with the specified log level 
                    along with a IO stream handler.""",
    )  # type: int

    ssl_context = ClassSelector(
        class_=ssl.SSLContext,
        default=None,
        allow_None=True,
        doc="SSL context to provide encrypted communication",
    )  # type: typing.Optional[ssl.SSLContext]

    allowed_clients = TypedList(
        item_type=str,
        doc="""Serves request and sets CORS only from these clients, other clients are rejected with 403. 
            Unlike pure CORS, the server resource is not even executed if the client is not 
            an allowed client. if None any client is served.""",
    )

    host = String(
        default=None,
        allow_None=True,
        doc="Host Server to subscribe to coordinate starting sequence of remote objects & web GUI",
    )  # type: str

    # network_interface = String(default='Ethernet',
    #                         doc="Currently there is no logic to detect the IP addresss (as externally visible) correctly, \
    #                         therefore please send the network interface name to retrieve the IP. If a DNS server is present, \
    #                         you may leave this field" ) # type: str

    property_handler = ClassSelector(
        default=PropertyHandler,
        class_=(PropertyHandler, RPCHandler),
        isinstance=False,
        doc="custom web request handler for property read-write",
    )  # type: typing.Union[RPCHandler, PropertyHandler]

    action_handler = ClassSelector(
        default=ActionHandler,
        class_=(ActionHandler, RPCHandler),
        isinstance=False,
        doc="custom web request handler for actions",
    )  # type: typing.Union[RPCHandler, ActionHandler]

    event_handler = ClassSelector(
        default=EventHandler,
        class_=(EventHandler, RPCHandler),
        isinstance=False,
        doc="custom event handler for sending HTTP SSE",
    )  # type: typing.Union[RPCHandler, EventHandler]

    schema_validator = ClassSelector(
        class_=BaseSchemaValidator,
        default=JSONSchemaValidator,
        allow_None=True,
        isinstance=False,
        doc="""Validator for JSON schema. If not supplied, a default JSON schema validator is created.""",
    )  # type: BaseSchemaValidator

    security_schemes = TypedList(
        default=None,
        allow_None=True,
        item_type=Security,
        doc="List of security schemes to be used by the server",
    )  # type: typing.Optional[typing.List[Security]]

    config = TypedDict(
        default=None,
        allow_None=True,
        doc="""Set CORS headers for the HTTP server. If set to False, CORS headers are not set. 
            This is useful when the server is used in a controlled environment where CORS is not needed.""",
    )  # type: bool

    def __init__(
        self,
        *,
        port: int = 8080,
        address: str = "0.0.0.0",
        # host: typing.Optional[str] = None,
        logger: typing.Optional[logging.Logger] = None,
        log_level: int = logging.INFO,
        ssl_context: typing.Optional[ssl.SSLContext] = None,
        security_schemes: typing.Optional[typing.List[Security]] = None,
        # schema_validator: typing.Optional[BaseSchemaValidator] = JSONSchemaValidator,
        # protocol_version : int = 1, network_interface : str = 'Ethernet',
        allowed_clients: typing.Optional[typing.Union[str, typing.Iterable[str]]] = None,
        config: typing.Optional[dict[str, typing.Any]] = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        port: int, default 8080
            the port at which the server should be run
        address: str, default 0.0.0.0
            IP address
        logger: logging.Logger, optional
            logging.Logger instance
        log_level: int
            alternative to logger, this creates an internal logger with the specified log level along with a IO stream handler.
        ssl_context: ssl.SSLContext
            SSL context to provide encrypted communication
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
        """
        super().__init__(
            port=port,
            address=address,
            # host=host,
            logger=logger,
            log_level=log_level,
            # protocol_version=1,
            # schema_validator=schema_validator,
            security_schemes=security_schemes,
            ssl_context=ssl_context,
            # network_interface='Ethernet',# network_interface,
            property_handler=kwargs.get("property_handler", PropertyHandler),
            action_handler=kwargs.get("action_handler", ActionHandler),
            event_handler=kwargs.get("event_handler", EventHandler),
            allowed_clients=allowed_clients if allowed_clients is not None else [],
            config=config or dict(),
        )

        self._IP = f"{self.address}:{self.port}"
        if self.logger is None:
            self.logger = get_default_logger(
                "{}|{}".format(self.__class__.__name__, f"{self.address}:{self.port}"),
                self.log_level,
            )

        self.tornado_instance = None
        self.app = Application(
            handlers=[
                (r"/stop", StopHandler, dict(owner_inst=self)),
                (r"/liveness", LivenessProbeHandler, dict(owner_inst=self)),
            ]
        )
        self.router = ApplicationRouter(self.app, self)

        self.zmq_client_pool = MessageMappedZMQClientPool(
            id=self._IP,
            server_ids=[],
            client_ids=[],
            handshake=False,
            poll_timeout=100,
            logger=self.logger,
        )
        self._disconnected_things = dict()
        self._registered_things = dict()  # type: typing.Dict[typing.Type[ThingMeta], typing.List[str]]

    @property
    def all_ok(self) -> bool:
        """check if all the requirements are met before starting the server, auto invoked by listen()"""
        # Add only those code here that needs to be redone always before restarting the server.
        # One time creation attributes/activities must be in init
        ioloop.IOLoop.clear_current()  # cleat the event in case any pending tasks exist, also restarting with same
        # event loop is buggy, so we remove it.
        event_loop = get_current_async_loop()  # sets async loop for a non-possessing thread as well
        # event_loop.call_soon(lambda : asyncio.create_task(self.update_router_with_things()))
        event_loop.call_soon(lambda: asyncio.create_task(self.subscribe_to_host()))
        event_loop.call_soon(lambda: asyncio.create_task(self.zmq_client_pool.poll_responses()))
        # self.zmq_client_pool.handshake(), NOTE - handshake better done upfront as we already poll_responses here
        # which will prevent handshake function to succeed (although handshake will be done)

        self.tornado_event_loop = ioloop.IOLoop.current()
        # set value based on what event loop we use, there is some difference
        # between the asyncio event loop and the tornado event loop

        self.tornado_instance = TornadoHTTP1Server(self.app, ssl_options=self.ssl_context)  # type: TornadoHTTP1Server
        return True

    @forkable
    def listen(self, forked: bool = False) -> None:
        """
        Start the HTTP server. This method is blocking.
        Async event loops intending to schedule the HTTP server should instead use
        the inner tornado instance's (`HTTPServer.tornado_instance`) listen() method.

        Parameters
        ----------
        forked: bool, default `False`
            if `True`, the server is started in a separate thread and the method returns immediately.
            If `False`, the method blocks until the server is stopped.
        """
        assert self.all_ok, (
            "HTTPServer all is not ok before starting"
        )  # Will always be True or cause some other exception
        self.tornado_instance.listen(port=self.port, address=self.address)
        self.logger.info(f"started webserver at {self._IP}, ready to receive requests.")
        self.tornado_event_loop.start()
        if forked:
            complete_pending_tasks_in_current_loop()  # will reach here only when the server is stopped, so complete pending tasks

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
        if self.tornado_event_loop is not None:
            self.tornado_event_loop.stop()
        complete_pending_tasks_in_current_loop()

    async def async_stop(self) -> None:
        """
        Stop the HTTP server. A stop handler at the path `/stop` with POST method is already implemented that invokes this
        method for the clients.
        """
        self.zmq_client_pool.stop_polling()
        if not self.tornado_instance:
            return
        self.tornado_instance.stop()
        await self.tornado_instance.close_all_connections()
        if self.tornado_event_loop is not None:
            self.tornado_event_loop.stop()
            self.logger.info(f"stopped tornado event loop for server {self._IP}")

    def add_things(self, *things: Thing | dict | str) -> None:
        """
        Add things to be served by the HTTP server

        Parameters
        ----------
        *things: Thing | dict | str
            the thing instance(s) or thing classe(s) to be served, or a map of address/ZMQ protocol to thing id,
            for example - `{'tcp://my-pc:5555': 'my-thing-id', 'IPC' : 'my-thing-id-2'}`
            The server ID needs to match the thing ID, otherwise this method would be unable to find the thing.
        """
        for thing in things:
            if isinstance(thing, Thing):
                self.router.add_thing_instance(thing)
            elif isinstance(thing, ThingMeta):
                raise ValueError(
                    f"class {thing} is not a thing instance, no need to add it to the server."
                    + " Just supply a thing instance to the server. skipping..."
                )
            elif isinstance(thing, (dict, str)):
                if isinstance(thing, str):
                    # if protocol not given, try INPROC first
                    self.router.add_zmq_thing_instance(thing, thing, access_point="INPROC")
                    if not self.zmq_client_pool.get_client_id_from_thing_id(thing):
                        self.router.add_zmq_thing_instance(thing, thing, access_point="IPC")
                    self.router._resolve_rules_per_thing_id(thing)
                else:
                    for address, thing_id in thing.items():
                        self.router.add_zmq_thing_instance(server_id=thing_id, thing_id=thing_id, access_point=address)
            elif issubklass(thing, ThingMeta):
                raise TypeError("thing should be of type Thing, not ThingMeta")
            else:
                raise TypeError(f"thing should be of type Thing, unknown type given - {type(thing)}")

    def add_thing(self, server_id: str, thing: Thing | str, access_point: str) -> None:
        """
        Add thing to be served by the HTTP server

        Parameters
        ----------
        thing: str | Thing
            id of the thing or the thing instance or thing class to be served
        """
        self.router.add_zmq_thing_instance(
            server_id=server_id,
            thing_id=thing if isinstance(thing, str) else thing.id,
            access_point=access_point,
        )

    def register_id_for_thing(self, thing_cls: typing.Type[ThingMeta], thing_id: str) -> None:
        """register an expected thing id for a thing class"""
        assert isinstance(thing_id, str), f"thing_id should be a string, given {type(thing_id)}"
        if not self._registered_things.get(thing_cls, None):
            self._registered_things[thing_cls] = []
        if isinstance(thing_id, list):
            self._registered_things[thing_cls].extend(thing_id)
        else:
            self._registered_things[thing_cls].append(thing_id)

    def get_thing_from_id(self, id: str) -> typing.Type[ThingMeta] | None:
        """get the thing id for a thing class"""
        for thing_cls, thing_ids in self._registered_things.items():
            if id in thing_ids:
                return thing_cls
        return None

    def add_property(
        self,
        URL_path: str,
        property: Property | PropertyAffordance,
        http_methods: typing.Tuple[str, typing.Optional[str], typing.Optional[str]] | None = ("GET", "PUT", None),
        handler: BaseHandler | PropertyHandler = PropertyHandler,
        **kwargs,
    ) -> None:
        """
        Add a property to be accessible by HTTP

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
        http_methods = _comply_http_method(http_methods)
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
        kwargs["owner_inst"] = self
        kwargs["metadata"] = dict(http_methods=http_methods)
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
        http_methods = _comply_http_method(http_method)
        if isinstance(action, Action):
            action = action.to_affordance()  # type: ActionAffordance
        kwargs["resource"] = action
        kwargs["owner_inst"] = self
        kwargs["metadata"] = dict(http_methods=http_methods)
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
        kwargs["owner_inst"] = self
        self.router.add_rule(affordance=event, URL_path=URL_path, handler=handler, kwargs=kwargs)

    async def subscribe_to_host(self):
        if self.host is None:
            return
        client = AsyncHTTPClient()
        for i in range(300):  # try for five minutes
            try:
                res = await client.fetch(
                    HTTPRequest(
                        url=f"{self.host}/subscribers",
                        method="POST",
                        body=Serializers.json.dumps(
                            dict(
                                hostname=socket.gethostname(),
                                IPAddress=get_IP_from_interface(self.network_interface),
                                port=self.port,
                                type=self._type,
                                https=self.ssl_context is not None,
                            )
                        ),
                        validate_cert=False,
                        headers={"content-type": "application/json"},
                    )
                )
            except Exception as ex:
                self.logger.error(
                    f"Could not subscribe to host {self.host}. error : {str(ex)}, error type : {type(ex)}."
                )
                if i >= 299:
                    raise ex from None
            else:
                if res.code in [200, 201]:
                    self.logger.info(f"subsribed successfully to host {self.host}")
                    break
                elif i >= 299:
                    raise RuntimeError(
                        f"could not subsribe to host {self.host}. response {Serializers.json.loads(res.body)}"
                    )
            await asyncio.sleep(1)
        # we lose the client anyway so we close it. if we decide to reuse the client, changes needed
        client.close()

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
    Covering implementation (as in - a layer on top of it) of the application router to
    add rules to the tornado application. Not a real router, which is taken care of
    by the tornado application automatically.
    """

    def __init__(self, app: Application, server: HTTPServer) -> None:
        self.app = app
        self.server = server
        self._pending_rules = []

    def add_rule(
        self,
        affordance: PropertyAffordance | ActionAffordance | EventAffordance,
        URL_path: str,
        handler: typing.Type[BaseHandler],
        kwargs: dict,
    ) -> None:
        """
        Add rules to the application router. Note that this method will replace existing rules and can duplicate
        endpoints for an affordance without checks (i.e. you could technically add two different endpoints for the
        same affordance).
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
        if getattr(affordance, "thing_id", None) is not None:
            if not URL_path.startswith(f"/{affordance.thing_id}"):
                warnings.warn(
                    f"URL path {URL_path} does not start with the thing id {affordance.thing_id},"
                    + f" adding it to the path, new path = {f'/{affordance.thing_id}{URL_path}'}. "
                    + " This warning can be usually safely ignored."
                )
                URL_path = f"/{affordance.thing_id}{URL_path}"
            self.app.wildcard_router.add_rules([(URL_path, handler, kwargs)])
        else:
            self._pending_rules.append((URL_path, handler, kwargs))
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

    def _resolve_rules_per_thing_id(self, id: str) -> None:
        """
        Process the pending rules and add them to the application router.
        """
        thing_cls = self.server.get_thing_from_id(id)
        pending_rules = []
        for rule in self._pending_rules:
            if rule[2]["resource"].owner != thing_cls:
                pending_rules.append(rule)
                continue
            URL_path, handler, kwargs = rule
            URL_path = f"/{id}{URL_path}"
            rule = (URL_path, handler, kwargs)
            self.app.wildcard_router.add_rules([rule])
        self._pending_rules = pending_rules

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

    def add_interaction_affordances(
        self,
        properties: typing.Iterable[PropertyAffordance],
        actions: typing.Iterable[ActionAffordance],
        events: typing.Iterable[EventAffordance],
        thing_id: str = None,
    ) -> None:
        for property in properties:
            if property in self:
                continue
            self.server.logger.debug(f"adding property {property.name} for thing id {property.thing_id}")
            if property.thing_id is not None:
                path = f"/{property.thing_id}/{pep8_to_dashed_name(property.name)}"
            else:
                path = f"/{pep8_to_dashed_name(property.name)}"
            self.server.add_property(
                URL_path=path,
                property=property,
                http_methods=("GET")
                if property.readOnly
                else (
                    "GET",
                    "PUT",
                ),  # if prop.fdel is None else ('GET', 'PUT', 'DELETE'),
                handler=self.server.property_handler,
            )
            if property.observable:
                self.server.add_event(
                    URL_path=f"{path}/change-event",
                    event=property,
                    handler=self.server.event_handler,
                )
        for action in actions:
            if action in self:
                continue
            self.server.logger.debug(f"adding action {action.name} for thing id {action.thing_id}")
            name = get_alternate_name(action.name)
            if action.thing_id is not None:
                path = f"/{action.thing_id}/{pep8_to_dashed_name(name)}"
            else:
                path = f"/{pep8_to_dashed_name(name)}"
            self.server.add_action(URL_path=path, action=action, handler=self.server.action_handler)
        for event in events:
            if event in self:
                continue
            self.server.logger.debug(f"adding event {event.name} for thing id {event.thing_id}")
            if event.thing_id is not None:
                path = f"/{event.thing_id}/{pep8_to_dashed_name(event.name)}"
            else:
                path = f"/{pep8_to_dashed_name(event.name)}"
            self.server.add_event(URL_path=path, event=event, handler=self.server.event_handler)

        # thing description handler
        get_thing_model_action = next((action for action in actions if action.name == "get_thing_model"), None)
        get_thing_description_action = deepcopy(get_thing_model_action)
        get_thing_description_action.override_defaults(name="get_thing_description")
        self.server.add_action(
            URL_path=f"/{thing_id}/resources/wot-td" if thing_id else "/resources/wot-td",
            action=get_thing_description_action,
            http_method=("GET",),
            handler=ThingDescriptionHandler,
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
            handler=RWMultiplePropertiesHandler,
            read_properties_resource=read_properties,
            write_properties_resource=write_properties,
        )

        self.server.logger.debug(
            f"added thing description action for thing id {thing_id if thing_id else 'unknown'} at path "
            + f"{f'/{thing_id}/resources/wot-td' if thing_id else '/resources/wot-td'}"
        )

    def add_thing_instance(self, thing: Thing) -> None:
        """
        internal method to add a thing instance to be served by the HTTP server. Iterates through the
        interaction affordances and adds a route for each property, action and event.
        """
        # Prepare affordance lists with error handling (single loop)
        properties, actions, events = [], [], []
        affordances = [
            (thing.properties.remote_objects.values(), properties, "property"),
            (thing.actions.descriptors.values(), actions, "action"),
            (thing.events.descriptors.values(), events, "event"),
        ]
        for objs, target_list, affordance_type in affordances:
            for obj in objs:
                try:
                    target_list.append(obj.to_affordance(thing))
                except Exception as ex:
                    self.server.logger.error(
                        f"Failed to convert {affordance_type} {getattr(obj, 'name', obj)} to affordance: {ex}"
                    )

        self.add_interaction_affordances(
            properties,
            actions,
            events,
            thing_id=thing.id if isinstance(thing.id, str) else None,
        )

    def add_zmq_thing_instance(self, server_id: str, thing_id: str, access_point: str) -> None:
        """
        Add a thing served by ZMQ server to the HTTP server. Mostly useful for INPROC transport which behaves like a local object.
        Iterates through the interaction affordances and adds a route for each property, action and event.
        """
        run_callable_somehow(
            self.async_add_zmq_thing_instance(thing_id=thing_id, server_id=server_id, access_point=access_point)
        )

    async def async_add_zmq_thing_instance(
        self,
        server_id: str,
        thing_id: str,
        access_point: str = None,
    ) -> None:
        try:
            from ...client.zmq.consumed_interactions import ZMQAction
            from ...core import Thing

            # create client
            client = AsyncZMQClient(
                id=self.server._IP,
                server_id=server_id,
                access_point=access_point,
                context=self.server.zmq_client_pool.context,
                poll_timeout=self.server.zmq_client_pool.poll_timeout,
                handshake=False,
                logger=self.server.logger,
            )
            # connect client
            client.handshake(10000)
            await client.handshake_complete(10000)
            # fetch TD
            assert isinstance(Thing.get_thing_model, Action)  # type definition
            FetchTMAffordance = Thing.get_thing_model.to_affordance()
            FetchTMAffordance.override_defaults(thing_id=thing_id, name="get_thing_description")
            fetch_td = ZMQAction(
                resource=FetchTMAffordance,
                sync_client=None,
                async_client=client,
                logger=self.server.logger,
                owner_inst=None,
            )
            if isinstance(access_point, str) and len(access_point) in [3, 6]:
                access_point = access_point.upper()
            elif access_point.lower().startswith("tcp://"):
                access_point = "TCP"
            TD = await fetch_td.async_call(ignore_errors=True, protocol=access_point)  # type: typing.Dict[str, typing.Any]
            # Add to server
            self.add_interaction_affordances(
                [PropertyAffordance.from_TD(name, TD) for name in TD["properties"].keys()],
                [ActionAffordance.from_TD(name, TD) for name in TD["actions"].keys()],
                [EventAffordance.from_TD(name, TD) for name in TD["events"].keys()],
                thing_id=thing_id,
            )
            # Resolve any rules that could have been locally added
            self._resolve_rules_per_thing_id(thing_id)
            self.server.zmq_client_pool.register(client, thing_id)
        except ConnectionError:
            self.server.logger.warning(
                f"could not connect to {thing_id} using on server {server_id} with access_point {access_point}"
            )
        except Exception as ex:
            self.server.logger.error(
                f"could not connect to {thing_id} using on server {server_id} with access_point {access_point}. error: {str(ex)}"
            )

    def get_href_for_affordance(self, affordance, authority: str = None, use_localhost: bool = False) -> str:
        if affordance not in self:
            raise ValueError(f"affordance {affordance} not found in the application router")
        for rule in self.app.wildcard_router.rules:
            if rule.target_kwargs.get("resource", None) == affordance:
                path = str(rule.matcher.regex.pattern).rstrip("$")
                return f"{self.get_basepath(authority, use_localhost)}{path}"

    def get_basepath(self, authority: str = None, use_localhost: bool = False) -> str:
        if authority:
            return authority
        protocol = "https" if self.server.ssl_context else "http"
        port = f":{self.server.port}" if self.server.port != 80 else ""
        if not use_localhost:
            return f"{protocol}://{socket.gethostname()}{port}"
        if self.server.address == "0.0.0.0" or self.server.address == "127.0.0.1":
            return f"{protocol}://127.0.0.1{port}"
        elif self.server.address == "::":
            return f"{protocol}://[::1]{port}"
        return f"{protocol}://localhost{port}"

    basepath = property(fget=get_basepath, doc="basepath of the server")

    def get_target_kwargs_for_affordance(self, affordance) -> dict:
        """
        Get the target kwargs for the affordance in the application router.
        """
        if affordance not in self:
            raise ValueError(f"affordance {affordance} not found in the application router")
        for rule in self.app.wildcard_router.rules:
            if rule.target_kwargs.get("resource", None) == affordance:
                return rule.target_kwargs
        for rule in self._pending_rules:
            if rule[2].get("resource", None) == affordance:
                return rule[2]
        raise ValueError(f"affordance {affordance} not found in the application router rules")

    def print_rules(self) -> None:
        """
        Print the rules in the application router.
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


def get_alternate_name(interaction_affordance_name: str) -> str:
    if interaction_affordance_name == "get_thing_model":
        return "resources/wot-tm"
    return interaction_affordance_name


def _comply_http_method(http_methods: typing.Any):
    """comply the supplied HTTP method to the router to a tuple and check if the method is supported"""
    if isinstance(http_methods, str):
        http_methods = (http_methods,)
    if not isinstance(http_methods, tuple):
        raise TypeError("http_method should be a tuple")
    for method in http_methods:
        if method not in HTTP_METHODS.__members__.values() and method is not None:
            raise ValueError(f"method {method} not supported")
    return http_methods


__all__ = [HTTPServer.__name__]
