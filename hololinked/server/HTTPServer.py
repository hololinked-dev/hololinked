import asyncio
from types import FunctionType, MethodType
import zmq
import zmq.asyncio
import logging
import socket
import ssl
import typing
from dataclasses import dataclass
from tornado import ioloop
from tornado.web import Application
from tornado.httpserver import HTTPServer as TornadoHTTP1Server
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

# from tornado_http2.server import Server as TornadoHTTP2Server 
from ..param import Parameterized
from ..param.parameters import (Integer, IPAddress, ClassSelector, Selector, TypedList, String)
from .constants import ZMQ_PROTOCOLS, CommonRPC, HTTPServerTypes, ResourceTypes, ServerMessage
from .utils import get_IP_from_interface, issubklass
from .dataklasses import HTTPResource, ServerSentEvent
from .utils import get_default_logger
from .serializers import JSONSerializer
from .database import ThingInformation
from .zmq_message_brokers import  AsyncZMQClient, MessageMappedZMQClientPool
from .handlers import RPCHandler, BaseHandler, EventHandler, ThingsHandler, StopHandler
from .schema_validators import BaseSchemaValidator, JsonSchemaValidator
from .events import Event
from .eventloop import EventLoop
from .config import global_config
from .property import Property
from .action import Action
from .events import Event


@dataclass 
class __interaction_affordance_added_locally__:
    obj : typing.Union[Property, Action, Event]
    http_methods : typing.Tuple[str, typing.Optional[str], typing.Optional[str]]
    handler : BaseHandler
    kwargs : dict




@dataclass 
class InteractionAffordance:
    URL_path : str
    obj : Event # typing.Union[Property, Action, Event]
    http_methods : typing.Tuple[str, typing.Optional[str], typing.Optional[str]]
    handler : BaseHandler
    kwargs : dict 

    def __eq__(self, other : "InteractionAffordance") -> bool:
        return self.obj == other.obj 
    
    

class HTTPServer(Parameterized):
    """
    HTTP(s) server to route requests to ``Thing``.
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
                doc="Host Server to subscribe to coordinate starting sequence of things & web GUI" ) # type: str
    # network_interface = String(default='Ethernet',  
    #                         doc="Currently there is no logic to detect the IP addresss (as externally visible) correctly, \
    #                         therefore please send the network interface name to retrieve the IP. If a DNS server is present, \
    #                         you may leave this field" ) # type: str
    request_handler = ClassSelector(default=RPCHandler, class_=RPCHandler, isinstance=False, 
                            doc="custom web request handler of your choice for property read-write & action execution" ) # type: typing.Union[BaseHandler, RPCHandler]
    event_handler = ClassSelector(default=EventHandler, class_=(EventHandler, BaseHandler), isinstance=False, 
                            doc="custom event handler of your choice for handling events") # type: typing.Union[BaseHandler, EventHandler]
    schema_validator = ClassSelector(class_=BaseSchemaValidator, default=JsonSchemaValidator, allow_None=True, isinstance=False,
                        doc="""Validator for JSON schema. If not supplied, a default JSON schema validator is created.""") # type: BaseSchemaValidator
    
   
    
    def __init__(self, things : typing.List[str], *, port : int = 8080, address : str = '0.0.0.0', 
                host : typing.Optional[str] = None, logger : typing.Optional[logging.Logger] = None, log_level : int = logging.INFO, 
                serializer : typing.Optional[JSONSerializer] = None, ssl_context : typing.Optional[ssl.SSLContext] = None, 
                schema_validator : typing.Optional[BaseSchemaValidator] = JsonSchemaValidator,
                certfile : str = None, keyfile : str = None, 
                # protocol_version : int = 1, network_interface : str = 'Ethernet', 
                allowed_clients : typing.Optional[typing.Union[str, typing.Iterable[str]]] = None,   
                **kwargs) -> None:
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
            request_handler=kwargs.get('request_handler', RPCHandler),
            event_handler=kwargs.get('event_handler', EventHandler),
            allowed_clients=allowed_clients if allowed_clients is not None else []
        )
        self._type = HTTPServerTypes.THING_SERVER
        self._lost_things = dict() # see update_router_with_thing
        self._zmq_protocol = ZMQ_PROTOCOLS.IPC
        self._zmq_inproc_socket_context = None 
        self._zmq_inproc_event_context = None
        self._local_rules = dict() # type: typing.Dict[str, typing.Dict[str, __interaction_affordance_added_locally__]]
        self._checked = False
 
    @property
    def all_ok(self) -> bool:
        self._IP = f"{self.address}:{self.port}"
        if self.logger is None:
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, 
                                            f"{self.address}:{self.port}"), 
                                            self.log_level)
            
        if self._zmq_protocol == ZMQ_PROTOCOLS.INPROC and (self._zmq_inproc_socket_context is None or self._zmq_inproc_event_context is None):
            raise ValueError("Inproc socket context is not provided. Logic Error.")
            
        self.app = Application(handlers=[
            (r'/remote-objects', ThingsHandler, dict(request_handler=self.request_handler, 
                                                        event_handler=self.event_handler)),
            (r'/stop', StopHandler, dict(owner=self))
        ])
        
        self.zmq_client_pool = MessageMappedZMQClientPool(self.things, identity=self._IP, 
                                                    deserialize_server_messages=False, handshake=False,
                                                    http_serializer=self.serializer, 
                                                    context=self._zmq_inproc_socket_context,
                                                    protocol=self._zmq_protocol,
                                                    logger=self.logger
                                                )
        # print("client pool context", self.zmq_client_pool.context)
        event_loop = EventLoop.get_async_loop() # sets async loop for a non-possessing thread as well
        self.update_router_with_things()
        event_loop.call_soon(lambda : asyncio.create_task(self.subscribe_to_host()))
        event_loop.call_soon(lambda : asyncio.create_task(self.zmq_client_pool.poll()) )
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


    def listen(self) -> None:
        """
        Start HTTP server. This method is blocking, async event loops intending to schedule the HTTP server should instead use  
        the inner tornado instance's (``HTTPServer.tornado_instance``) listen() method. 
        """
        if not self._checked:
            assert self.all_ok, 'HTTPServer all is not ok before starting' # Will always be True or cause some other exception   
        self.tornado_event_loop = ioloop.IOLoop.current()
        self.tornado_instance.listen(port=self.port, address=self.address)    
        self.logger.info(f'started webserver at {self._IP}, ready to receive requests.')
        self.tornado_event_loop.start()


    async def stop(self) -> None:
        """
        Stop the event loop & the HTTP server. This method is async and should be awaited, mostly within a request
        handler. The stop handler at the path '/stop' with POST request is already implemented.
        """
        self.tornado_instance.stop()
        self.zmq_client_pool.stop_polling()
        await self.tornado_instance.close_all_connections()
        if self.tornado_event_loop is not None:
            self.tornado_event_loop.stop()
        
       
    def update_router_with_things(self) -> None:
        """
        updates HTTP router with paths from ``Thing`` (s)
        """
        event_loop = EventLoop.get_async_loop() # sets async loop for a non-possessing thread as well
        for client in self.zmq_client_pool:
            event_loop.call_soon(lambda : asyncio.create_task(self.update_router_with_thing(client)))
            

        
    async def update_router_with_thing(self, client : AsyncZMQClient):
        if client.instance_name in self._lost_things:
            # Just to avoid duplication of this call as we proceed at single client level and not message mapped level
            return 
        self.logger.info(f"attempting to update router with thing {client.instance_name}.")
        self._lost_things[client.instance_name] = client
        self.logger.info(f"attempting to update router with remote object {client.instance_name}.")

        def added_local_object(self : HTTPServer, handlers : typing.List[BaseHandler], 
                               interaction : typing.Union[Property, Action, Event]) -> bool: 
            if resource.class_name in self._local_rules:
                objects = self._local_rules[resource.class_name]
                for path, interaction_affordance_added_locally in objects.items():
                    if not isinstance(interaction_affordance_added_locally.obj, interaction):
                        continue 
                    if f'/{client.instance_name}/{path}' == resource.fullpath:
                        handlers.append((resource.fullpath, interaction_affordance_added_locally.handler, dict(
                                                                            **dict(
                                                                                resource=resource,
                                                                                validator=None,
                                                                                owner=self
                                                                            ),
                                                                            **interaction_affordance_added_locally.kwargs
                                                                        )))
                        return True
                return False
            return False
        
        while True:
            try:
                await client.handshake_complete()
                resources = dict() # type: typing.Dict[str, HTTPResource]
                reply = (await client.async_execute(
                                instruction=CommonRPC.http_resource_read(client.instance_name), 
                                raise_client_side_exception=True
                            ))[ServerMessage.DATA]
                resources.update(reply)

                handlers = []
                for instruction, http_resource in resources.items():
                    if http_resource["what"] == ResourceTypes.PROPERTY:
                        resource = HTTPResource(**http_resource)
                        if added_local_object(self, handlers, Property):
                            continue
                        handlers.append((resource.fullpath, self.request_handler, dict(
                                                            resource=resource,
                                                            validator=self.schema_validator(resource.argument_schema) if global_config.validate_schema_on_client and resource.argument_schema else None,
                                                            owner=self 
                                                        )))
                    if http_resource["what"] == ResourceTypes.ACTION:
                        resource = HTTPResource(**http_resource)
                        if added_local_object(self, handlers, Action):
                            continue
                        handlers.append((resource.fullpath, self.request_handler, dict(
                                                                resource=resource,
                                                                validator=self.schema_validator(resource.argument_schema) if global_config.validate_schema_on_client and resource.argument_schema else None,
                                                                owner=self                                                     
                                                            )))
                    elif http_resource["what"] == ResourceTypes.EVENT:
                        resource = ServerSentEvent(**http_resource)
                        if added_local_object(self, handlers, Event):
                            continue
                        handlers.append((instruction, self.event_handler, dict(
                                                            resource=resource,
                                                            validator=None,
                                                            owner=self 
                                                        )))
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
                
                    so we give (path, RPCHandler, {'resource' : HTTPResource})
                    
                    path is extracted from remote_method(URL_path='....')
                    RPCHandler is the base handler of this package for RPC purposes
                    resource goes into target kwargs as the HTTPResource generated by 
                        remote_method and RemoteParamater contains all the info given 
                        to make RPCHandler work
                    """
                self.app.wildcard_router.add_rules(handlers)
                self.logger.info(f"updated router with thing {client.instance_name}.")
                break
            except Exception as ex:
                print("error", ex)
                self.logger.error(f"error while trying to update router with thing - {str(ex)}. " +
                                  "Trying again in 5 seconds")
                await asyncio.sleep(5)
       
        try:
            reply = (await client.async_execute(
                        instruction=CommonRPC.object_info_read(client.instance_name), 
                        raise_client_side_exception=True
                    ))[ServerMessage.DATA]
            object_info = ThingInformation(**reply)
            object_info.http_server ="{}://{}:{}".format("https" if self.ssl_context is not None else "http", 
                                                socket.gethostname(), self.port)
    
            await client.async_execute(
                        instruction=CommonRPC.object_info_write(client.instance_name),
                        arguments=dict(value=object_info), 
                        raise_client_side_exception=True
                    )
            self.logger.info(f"updated ThingInformation to {client.instance_name}")
        except Exception as ex:
            self.logger.error(f"error while trying to update thing with HTTP server details - {str(ex)}. " +
                                "Trying again in 5 seconds")
        self.zmq_client_pool.poller.register(client.socket, zmq.POLLIN)
        self._lost_things.pop(client.instance_name)


    def add_things(self, *things : str) -> None:
        raise NotImplementedError("Not implemented yet")
        self.things.extend(things)
        self._lost_things.update({thing : None for thing in things})
        event_loop = EventLoop.get_async_loop()
        event_loop.call_soon(lambda : asyncio.create_task(self.update_router_with_things()))


    def add_property(self, URL_path : str, http_methods : typing.Tuple[str, typing.Optional[str], typing.Optional[str]], 
                    property : Property, handler : BaseHandler, **kwargs) -> None:
        """
        Add a property to be handler by HTTP server
        """
        if not isinstance(property, Property):
            raise TypeError("event should be of type EventDispatcher")
        if not issubklass(handler, BaseHandler):
            raise TypeError("handler should be subclass of BaseHandler")
        if property.owner.__name__ not in self._local_rules:
            self._local_rules[property.owner.__name__] = dict() 
        self._local_rules[property.owner.__name__][URL_path] = __interaction_affordance_added_locally__(
                                                                    property, http_methods, handler, kwargs)


    def add_action(self, URL_path : str, http_method : str,
                        action : Action, handler : BaseHandler, **kwargs) -> None:
        if not isinstance(action, Action):
            raise TypeError("event should be of type EventDispatcher")
        if not issubklass(handler, BaseHandler):
            raise TypeError("handler should be subclass of BaseHandler")
        if action.owner.__name__ not in self._local_rules:
            self._local_rules[action.owner.__name__] = dict() 
        self._local_rules[action.owner.__name__][URL_path] = __interaction_affordance_added_locally__(
                                                                    action, http_method, handler, kwargs)

    
    def add_event(self, URL_path : str, event : Event, handler : BaseHandler, **kwargs) -> None:
        if not isinstance(event, Event):
            raise TypeError("event should be of type Event")
        if not issubklass(handler, BaseHandler):
            raise TypeError("handler should be subclass of BaseHandler")
        if event.owner.__name__ not in self._local_rules:
            self._local_rules[event.owner.__name__] = dict() 
        self._local_rules[event.owner.__name__][URL_path] = __interaction_affordance_added_locally__(
                                                                    event, 'GET', handler, kwargs)


__all__ = [
    HTTPServer.__name__
]