import asyncio
import warnings
import logging
import socket
import ssl
import typing
from tornado import ioloop
from tornado.web import Application
from tornado.httpserver import HTTPServer as TornadoHTTP1Server
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
# from tornado_http2.server import Server as TornadoHTTP2Server 

from ....param import Parameterized
from ....param.parameters import Integer, IPAddress, ClassSelector, Selector, TypedList, String
from ....constants import HTTP_METHODS, ZMQ_TRANSPORTS, HTTPServerTypes, Operations
from ....utils import get_IP_from_interface, get_current_async_loop, issubklass, pep8_to_dashed_name, get_default_logger, run_callable_somehow
from ....serializers.serializers import JSONSerializer
from ....schema_validators import BaseSchemaValidator, JSONSchemaValidator
from ....core.property import Property
from ....core.actions import Action
from ....core.events import Event
from ....core.thing import Thing, ThingMeta
from ....td import ActionAffordance, EventAffordance, PropertyAffordance
from ....core.zmq.brokers import AsyncZMQClient, MessageMappedZMQClientPool
from .handlers import ActionHandler, PropertyHandler, BaseHandler, EventHandler, ThingsHandler, StopHandler



class HTTPServer(Parameterized):
    """
    HTTP(s) server to route requests to `Thing`.
    """
    
    things = TypedList(item_type=str, default=None, allow_None=True, 
                       doc="instance name of the things to be served by the HTTP server." ) # type: typing.List[str]
    port = Integer(default=8080, bounds=(1, 65535),  
                    doc="the port at which the server should be run" ) # type: int
    address = IPAddress(default='0.0.0.0', 
                    doc="IP address") # type: str
    # protocol_version = Selector(objects=[1, 1.1, 2], default=2, 
    #                 doc="for HTTP 2, SSL is mandatory. HTTP2 is recommended. \
    #                 When no SSL configurations are provided, defaults to 1.1" ) # type: float
    logger = ClassSelector(class_=logging.Logger, default=None, allow_None=True, 
                    doc="logging.Logger" ) # type: logging.Logger
    log_level = Selector(objects=[logging.DEBUG, logging.INFO, logging.ERROR, logging.WARN, 
                                logging.CRITICAL, logging.ERROR], 
                    default=logging.INFO, 
                    doc="""alternative to logger, this creates an internal logger with the specified log level 
                    along with a IO stream handler.""" ) # type: int
    serializer = ClassSelector(class_=JSONSerializer,  default=None, allow_None=True,
                    doc="""json serializer used by the server""" ) # type: JSONSerializer
    ssl_context = ClassSelector(class_=ssl.SSLContext, default=None, allow_None=True, 
                    doc="SSL context to provide encrypted communication") # type: typing.Optional[ssl.SSLContext]    
    certfile = String(default=None, allow_None=True, 
                    doc="""alternative to SSL context, provide certificate file & key file to allow the server to 
                        create a SSL context""") # type: str
    keyfile = String(default=None, allow_None=True, 
                    doc="""alternative to SSL context, provide certificate file & key file to allow the server to 
                        create a SSL context""") # type: str
    allowed_clients = TypedList(item_type=str,
                            doc="""Serves request and sets CORS only from these clients, other clients are rejected with 403. 
                                Unlike pure CORS, the server resource is not even executed if the client is not 
                                an allowed client. if None any client is served.""")
    host = String(default=None, allow_None=True, 
                doc="Host Server to subscribe to coordinate starting sequence of remote objects & web GUI" ) # type: str
    # network_interface = String(default='Ethernet',  
    #                         doc="Currently there is no logic to detect the IP addresss (as externally visible) correctly, \
    #                         therefore please send the network interface name to retrieve the IP. If a DNS server is present, \
    #                         you may leave this field" ) # type: str
    property_handler = ClassSelector(default=PropertyHandler, class_=(PropertyHandler, BaseHandler), isinstance=False, 
                            doc="custom web request handler of your choice for property read-write & action execution" ) # type: typing.Union[BaseHandler, PropertyHandler]
    action_handler = ClassSelector(default=ActionHandler, class_=(ActionHandler, BaseHandler), isinstance=False, 
                            doc="custom web request handler of your choice for property read-write & action execution" ) # type: typing.Union[BaseHandler, ActionHandler]
    event_handler = ClassSelector(default=EventHandler, class_=(EventHandler, BaseHandler), isinstance=False, 
                            doc="custom event handler of your choice for handling events") # type: typing.Union[BaseHandler, EventHandler]
    schema_validator = ClassSelector(class_=BaseSchemaValidator, default=JSONSchemaValidator, allow_None=True, isinstance=False,
                        doc="""Validator for JSON schema. If not supplied, a default JSON schema validator is created.""") # type: BaseSchemaValidator
    
   
    
    def __init__(self, 
                things : typing.List[str] | typing.List[Thing] | typing.List[ThingMeta] | None = None, *, 
                port : int = 8080, address : str = '0.0.0.0', host : typing.Optional[str] = None, 
                logger : typing.Optional[logging.Logger] = None, log_level : int = logging.INFO, 
                serializer : typing.Optional[JSONSerializer] = None, ssl_context : typing.Optional[ssl.SSLContext] = None, 
                schema_validator : typing.Optional[BaseSchemaValidator] = JSONSchemaValidator,
                certfile : str = None, keyfile : str = None, 
                # protocol_version : int = 1, network_interface : str = 'Ethernet', 
                allowed_clients : typing.Optional[typing.Union[str, typing.Iterable[str]]] = None,   
                **kwargs
            ) -> None:
        """
        Parameters
        ----------
        things: List[str]
            instance name of the things to be served as a list.
        port: int, default 8080
            the port at which the server should be run
        address: str, default 0.0.0.0
            IP address
        logger: logging.Logger, optional
            logging.Logger instance
        log_level: int
            alternative to logger, this creates an internal logger with the specified log level along with a IO stream handler. 
        serializer: JSONSerializer, optional
            json serializer used by the server
        ssl_context: ssl.SSLContext
            SSL context to provide encrypted communication
        certfile: str
            alternative to SSL context, provide certificate file & key file to allow the server to create a SSL context 
        keyfile: str
            alternative to SSL context, provide certificate file & key file to allow the server to create a SSL context 
        allowed_clients: List[str] 
            serves request and sets CORS only from these clients, other clients are reject with 403. Unlike pure CORS
            feature, the server resource is not even executed if the client is not an allowed client.
        **kwargs:
            rpc_handler: RPCHandler | BaseHandler, optional
                custom web request handler of your choice for property read-write & action execution
            event_handler: EventHandler | BaseHandler, optional
                custom event handler of your choice for handling events
        """
        super().__init__(
            things=things,
            port=port, 
            address=address, 
            host=host,
            logger=logger, 
            log_level=log_level,
            serializer=serializer or JSONSerializer(), 
            # protocol_version=1, 
            schema_validator=schema_validator,
            certfile=certfile, 
            keyfile=keyfile,
            ssl_context=ssl_context,
            # network_interface='Ethernet',# network_interface,
            property_handler=kwargs.get('property_handler', PropertyHandler),
            action_handler=kwargs.get('action_handler', ActionHandler),
            event_handler=kwargs.get('event_handler', EventHandler),
            allowed_clients=allowed_clients if allowed_clients is not None else []
        )

        self._IP = f"{self.address}:{self.port}"
        if self.logger is None:
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, 
                                            f"{self.address}:{self.port}"), 
                                            self.log_level)
            
        self.app = Application(handlers=[
            (r'/things', ThingsHandler, dict(owner=self)),
            (r'/stop', StopHandler, dict(owner=self))
        ])
        
        self.zmq_client_pool = MessageMappedZMQClientPool(
                                                    id=self._IP,
                                                    server_ids=[],
                                                    client_ids=[],
                                                    handshake=False,
                                                    poll_timeout=100,                                                   
                                                    logger=self.logger
                                                )

        self._type = HTTPServerTypes.THING_SERVER
        self._disconnected_things = dict() # see update_router_with_thing
        
        self._zmq_protocol = ZMQ_TRANSPORTS.IPC
        self._zmq_inproc_socket_context = None 
        self._zmq_inproc_event_context = None
        
        self._checked = False
 

    @property
    def all_ok(self) -> bool:
        """
        check if all the requirements are met before starting the server, auto invoked by listen().
        """
        if self._checked:
            return True
        # print("client pool context", self.zmq_client_pool.context)
        event_loop = get_current_async_loop() # sets async loop for a non-possessing thread as well
        event_loop.call_soon(lambda : asyncio.create_task(self.update_router_with_things()))
        event_loop.call_soon(lambda : asyncio.create_task(self.subscribe_to_host()))
        event_loop.call_soon(lambda : asyncio.create_task(self.zmq_client_pool.poll_responses()) )
        for client in self.zmq_client_pool: 
            event_loop.call_soon(lambda : asyncio.create_task(client._handshake(timeout=60000)))
 
        self.tornado_event_loop = None 
        # set value based on what event loop we use, there is some difference 
        # between the asyncio event loop and the tornado event loop
        
        # if self.protocol_version == 2:
        #     raise NotImplementedError("Current HTTP2 is not implemented.")
        #     self.tornado_instance = TornadoHTTP2Server(self.app, ssl_options=self.ssl_context)
        # else:
        self.tornado_instance = TornadoHTTP1Server(self.app, ssl_options=self.ssl_context)
        self._checked = True
        return True
    

    def listen(self) -> None:
        """
        Start the HTTP server. This method is blocking. Async event loops intending to schedule the HTTP server should instead use
        the inner tornado instance's (``HTTPServer.tornado_instance``) listen() method. 
        """
        if not self._checked:
            assert self.all_ok, 'HTTPServer all is not ok before starting' # Will always be True or cause some other exception   
        self.tornado_event_loop = ioloop.IOLoop.current()
        self.tornado_instance.listen(port=self.port, address=self.address)    
        self.logger.info(f'started webserver at {self._IP}, ready to receive requests.')
        self.tornado_event_loop.start()


    def stop(self) -> None:
        """
        Stop the HTTP server. A stop handler at the path '/stop' with POST method is already implemented that invokes this 
        method for the clients. 
        """
        self.tornado_instance.stop()
        self.zmq_client_pool.stop_polling()
        run_callable_somehow(self.tornado_instance.close_all_connections())
        if self.tornado_event_loop is not None:
            self.tornado_event_loop.stop()


    async def _stop_async(self) -> None:
        """
        Stop the HTTP server. A stop handler at the path '/stop' with POST method is already implemented that invokes this 
        method for the clients. 
        """
        self.tornado_instance.stop()
        self.zmq_client_pool.stop_polling()
        await self.tornado_instance.close_all_connections()
        if self.tornado_event_loop is not None:
            self.tornado_event_loop.stop()
        
       
    def add_things(self, *things: Thing | ThingMeta | dict | str) -> None:
        """
        Add things to be served by the HTTP server

        Parameters
        ----------
        *things: Thing | ThingMeta | dict | str
            the thing instance(s) or thing classe(s) to be served, or a map of address/ZMQ protocol to thing id, 
            for example - {'tcp://my-pc:5555': 'my-thing-id', 'IPC' : 'my-thing-id-2'}
        """
        for thing in things:
            if isinstance(thing, Thing): 
                add_thing_instance(self, thing)
            elif isinstance(thing, dict):
                add_zmq_served_thing(self, thing)
            elif issubklass(thing, ThingMeta):
                raise TypeError(f"thing should be of type Thing or ThingMeta, given type {type(thing)}")

    
    def add_thing(self, thing: Thing | ThingMeta | dict | str) -> None:
        """
        Add thing to be served by the HTTP server

        Parameters
        ----------
        thing: str | Thing | ThingMeta
            id of the thing or the thing instance or thing class to be served
        """
        self.add_things(thing)
  

    def add_property(self, 
                    URL_path: str, 
                    property: Property | PropertyAffordance, 
                    http_methods: typing.Tuple[str, typing.Optional[str], typing.Optional[str]] | None = ('GET', 'PUT', None), 
                    handler: BaseHandler | PropertyHandler = PropertyHandler, 
                    **kwargs
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
        http_methods = _comply_http_method(http_methods)
        read_http_method = write_http_method = delete_http_method = None
        if len(http_methods) == 1:
            read_http_method = http_methods[0]
        elif len(http_methods) == 2:
            read_http_method, write_http_method = http_methods
        elif len(http_methods) == 3:
            read_http_method, write_http_method, delete_http_method = http_methods
        if read_http_method != 'GET':
            raise ValueError("read method should be GET")
        if write_http_method and write_http_method not in ['POST', 'PUT']:
            raise ValueError("write method should be POST or PUT")
        if delete_http_method and delete_http_method != 'DELETE':
            raise ValueError("delete method should be DELETE")
        if isinstance(property, Property):
            property = property.to_affordance()
            property._build_forms()
        kwargs['resource'] = property
        kwargs['owner'] = self
        for rule in self.app.wildcard_router.rules:
            if rule.matcher == URL_path:
                warnings.warn(f"property {property.name} already exists in the router - replacing it.",
                        category=UserWarning)
                # raise ValueError(f"URL path {URL_path} already exists in the router")
        self.app.wildcard_router.add_rules([(URL_path, handler, kwargs)])

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
                

    def add_action(self, 
                URL_path: str, 
                action: Action | ActionAffordance, 
                http_method: str | None = 'POST',
                handler: BaseHandler | ActionHandler = ActionHandler, 
                **kwargs
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
        kwargs : dict
            additional keyword arguments to be passed to the handler's __init__
        """
        if not isinstance(action, (Action, ActionAffordance)):
            raise TypeError(f"Given action should be of type Action or ActionAffordance, given type {type(action)}")
        if not issubklass(handler, BaseHandler):
            raise TypeError(f"handler should be subclass of BaseHandler, given type {type(handler)}")
        http_methods = _comply_http_method(http_method)
        if len(http_methods) != 1:
            raise ValueError("http_method should be a single HTTP method")
        if isinstance(action, Action):
            action = action.to_affordance() # type: ActionAffordance
            action._build_forms()
        kwargs['resource'] = action
        kwargs['owner'] = self
        for rule in self.app.wildcard_router.rules:
            if rule.matcher == URL_path:
                warnings.warn(f"URL path {URL_path} already exists in the router -" +
                        " replacing it for action {action.name}", category=UserWarning)
        self.app.wildcard_router.add_rules([(URL_path, handler, kwargs)])

    
    def add_event(self, 
                URL_path: str, 
                event: Event | EventAffordance, 
                handler: BaseHandler | EventHandler = EventHandler, 
                **kwargs
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
        if not isinstance(event, (Event, EventAffordance)):
            raise TypeError(f"event should be of type Event or EventAffordance, given type {type(event)}")
        if not issubklass(handler, BaseHandler):
            raise TypeError(f"handler should be subclass of BaseHandler, given type {type(handler)}")
        if isinstance(event, Event):
            event = event.to_affordance()
            event._build_forms()
        kwargs['resource'] = event
        kwargs['owner'] = self
        for rule in self.app.wildcard_router.rules:
            if rule.matcher == URL_path:
                warnings.warn(f"URL path {URL_path} already exists in the router -" + 
                        " replacing it for event {event.friendly_name}", category=UserWarning)
        self.app.wildcard_router.add_rules([(URL_path, handler, kwargs)])


    async def subscribe_to_host(self):
        if self.host is None:
            return
        client = AsyncHTTPClient()
        for i in range(300): # try for five minutes
            try:
                res = await client.fetch(HTTPRequest(
                        url=f"{self.host}/subscribers",
                        method='POST',
                        body=JSONSerializer.dumps(dict(
                                hostname=socket.gethostname(),
                                IPAddress=get_IP_from_interface(self.network_interface), 
                                port=self.port, 
                                type=self._type,
                                https=self.ssl_context is not None 
                            )),
                        validate_cert=False,
                        headers={"content-type" : "application/json"}
                    ))
            except Exception as ex:
                self.logger.error(f"Could not subscribe to host {self.host}. error : {str(ex)}, error type : {type(ex)}.")
                if i >= 299:
                    raise ex from None
            else: 
                if res.code in [200, 201]:
                    self.logger.info(f"subsribed successfully to host {self.host}")
                    break
                elif i >= 299:
                    raise RuntimeError(f"could not subsribe to host {self.host}. response {JSONSerializer.loads(res.body)}")
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
    
    def __del__(self):
        self.stop()

        
   
def _comply_http_method(http_methods : typing.Any):
    """comply the supplied HTTP method to the router to a tuple and check if the method is supported"""
    if isinstance(http_methods, str):
        http_methods = (http_methods,)
    if not isinstance(http_methods, tuple):
        raise TypeError("http_method should be a tuple")
    for method in http_methods:
        if method not in HTTP_METHODS.__members__.values():
            raise ValueError(f"method {method} not supported")
    return http_methods


def add_thing_instance(server: HTTPServer, thing: Thing | ThingMeta) -> None:
    """
    internal method to add a thing instance to be served by the HTTP server. Iterates through the 
    interaction affordances and adds a route for each property, action and event.
    """
    for prop in thing.properties.descriptors.values():
        server.add_property(
            URL_path=f'/{thing.id}/{pep8_to_dashed_name(prop.name)}', 
            property=prop,
            http_methods=('GET') if prop.readonly else ('GET', 'PUT') if prop.fdel is None else ('GET', 'PUT', 'DELETE'),
            handler=server.property_handler
        )
    for action in thing.actions.values():
        server.add_action(
            URL_path=f'/{thing.id}/{pep8_to_dashed_name(action.name)}', 
            action=action, 
            http_method='POST', 
            handler=server.action_handler
        )
    for event in thing.events.values():
        server.add_event(
            URL_path=f'/{thing.id}/{pep8_to_dashed_name(event.friendly_name)}', 
            event=event, 
            handler=server.event_handler
        )




async def add_zmq_served_thing(server: HTTPServer, thing: dict | str) -> None:
    """
    Add a thing served by ZMQ server to the HTTP server. Mostly useful for INPROC transport which behaves like a local object.  
    Iterates through the interaction affordances and adds a route for each property, action and event.
    """
    def update_router_with_thing(server: HTTPServer, client: AsyncZMQClient):
        TD = run_callable_somehow(
                client.async_execute(
                    thing_id='',
                    objekt='get_thing_description',
                    operation=Operations.invokeAction,
                )
            )
        for name in TD["properties"].keys():
            resource = PropertyAffordance.from_TD(name, TD)
            server.add_property(
                URL_path=f'/{client.id}/{pep8_to_dashed_name(name)}',
                property=resource,
                handler=server.property_handler,
            )   
        for name in TD["actions"].keys():
            resource = ActionAffordance.from_TD(name, TD)
            server.add_action(
                URL_path=f'/{client.id}/{pep8_to_dashed_name(name)}',
                action=resource,
                http_method='POST',
                handler=server.action_handler
            )
        for name in TD["events"].keys():
            resource = EventAffordance.from_TD(name, TD)
            server.add_event(
                URL_path=f'/{client.id}/{pep8_to_dashed_name(name)}',
                event=resource,
                handler=server.event_handler
            )

    if isinstance(thing, str):
        for protocol in ['INRPOC', 'IPC']:
            try:
                client = AsyncZMQClient(
                            id=server._IP, 
                            server_id=thing,
                            handshake=False,
                            transport='INPROC',
                            context=server.zmq_client_pool.context,
                            poll_timeout=server.zmq_client_pool.poll_timeout,
                            logger=server.logger    
                        )
                client.handshake(timeout=10000)
                server.zmq_client_pool.register(client)
                update_router_with_thing(server, client)
                break 
            except TimeoutError:
                server.logger.warning(f"could not connect to {thing} using {protocol} transport")

    elif isinstance(thing, dict):
        for protocol, id in thing.items():
            try:
                client = AsyncZMQClient(
                            id=server._IP, 
                            server_id=id,
                            handshake=False,
                            transport=protocol,
                            context=server.zmq_client_pool.context,
                            poll_timeout=server.zmq_client_pool.poll_timeout,
                            logger=server.logger    
                        )
                client.handshake(timeout=10000)
                server.zmq_client_pool.register(client)
                update_router_with_thing(server, client)
            except TimeoutError:
                server.logger.warning(f"could not connect to {id} using {protocol} transport")
            except Exception as ex:
                server.logger.error(f"could not connect to {id} using {protocol} transport. error : {str(ex)}")

            

__all__ = [
    HTTPServer.__name__
]