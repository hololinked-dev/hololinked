import typing
import logging
from tornado.web import RequestHandler, StaticFileHandler
from tornado.iostream import StreamClosedError

from .webserver_utils import *
from .utils import current_datetime_ms_str
from .data_classes import HTTPResource, ServerSentEvent
from .serializers import JSONSerializer
from .zmq_message_brokers import  MessageMappedZMQClientPool, AsyncEventConsumer



class BaseHandler(RequestHandler):
    """
    Base request handler for RPC operations
    """

    def initialize(self, resource : typing.Union[HTTPResource, ServerSentEvent], 
                    zmq_client_pool : MessageMappedZMQClientPool, json_serializer : JSONSerializer,
                    logger : logging.Logger, allowed_clients : typing.List[str] = list()) -> None:
        self.resource = resource
        self.zmq_client_pool = zmq_client_pool 
        self.serializer = json_serializer
        self.logger = logger
        self.allowed_clients = allowed_clients
       
    def set_headers(self):
        """
        override this to set custom headers without having to reimplement entire handler
        """
        raise NotImplementedError("implement set headers in child class to call it",
                            " before directing the request to RemoteObject")
    
    def get_execution_parameters(self) -> typing.Tuple[typing.Dict[str, typing.Any], 
                                                typing.Dict[str, typing.Any], typing.Union[float, int, None]]:
        """
        merges all arguments to a single JSON body and retrieves execution context and timeouts
        """
        if len(self.request.body) > 0:
            arguments = self.serializer.loads(self.request.body)
        else:
            arguments = dict()
        if isinstance(arguments, dict):
            if len(self.request.query_arguments) >= 1:
                for key, value in self.request.query_arguments.items():
                    if len(value) == 1:
                        arguments[key] = self.serializer.loads(value[0]) 
                    else:
                        arguments[key] = [self.serializer.loads(val) for val in value]
            context = dict(fetch_execution_logs=arguments.pop('fetch_execution_logs', False))
            timeout = arguments.pop('timeout', None)
            if timeout is not None and timeout < 0:
                timeout = None
            if self.resource.request_as_argument:
                arguments['request'] = self.request
            return arguments, context, timeout
        return arguments, dict(), 5 # arguments, context is empty, 5 seconds invokation timeout
    
    @property
    def has_access_control(self):
        """
        For credential login, access control allow origin cannot be '*',
        See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#examples_of_access_control_scenarios
        """
        self.set_header("Access-Control-Allow-Origin", "*")
        return True
        if len(self.allowed_clients) == 0:
            return True
        origin = self.request.headers.get("Origin")
        if origin is not None and (origin in self.allowed_clients or origin + '/' in self.allowed_clients):
            self.set_header("Access-Control-Allow-Origin", origin)
        return False
    
    def set_access_control_allow_headers(self) -> None:
        """
        For credential login, access control allow headers cannot be '*'. 
        See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#examples_of_access_control_scenarios
        """
        headers = ", ".join(self.request.headers.keys())
        if self.request.headers.get("Access-Control-Request-Headers", None):
            headers += ", " + self.request.headers["Access-Control-Request-Headers"]
        self.set_header("Access-Control-Allow-Headers", headers)



class RPCHandler(BaseHandler):
    """
    Handler for parameter read-write and method calls
    """

    async def get(self):
        """
        get method
        """
        await self.handle_through_remote_object('GET')    

    async def post(self):
        """
        post method
        """
        await self.handle_through_remote_object('POST')
    
    async def patch(self):
        """
        patch method
        """
        await self.handle_through_remote_object('PATCH')        
    
    async def put(self):
        """
        put method
        """
        await self.handle_through_remote_object('PUT')        
    
    async def delete(self):
        """
        delete method
        """
        await self.handle_through_remote_object('DELETE')  
       
    def set_headers(self):
        """
        default headers for RPC.

        content-type: application/json
        access-control-allow-credentials: true
        """
        self.set_header("Content-Type" , "application/json")    
        self.set_header("Access-Control-Allow-Credentials", "true")
    
    async def options(self):
        """
        options for the resource
        """
        if self.has_access_control:
            self.set_status(204)
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Credentials", "true")
            self.set_header("Access-Control-Allow-Methods", ', '.join(self.resource.instructions.supported_methods()))
        else:
            self.set_status(403, "forbidden")
        self.finish()
    

    async def handle_through_remote_object(self, http_method : str) -> None:
        """
        handles the RPC call
        """
        if not self.has_access_control:
            self.set_status(403, "forbidden")    
        elif http_method not in self.resource.instructions:
            self.set_status(404, "not found")
        else:
            try:
                arguments, context, timeout = self.get_execution_parameters()
                reply = await self.zmq_client_pool.async_execute(
                                        instance_name=self.resource.instance_name, 
                                        instruction=self.resource.instructions.__dict__[http_method], 
                                        arguments=arguments,
                                        context=context, 
                                        raise_client_side_exception=False, 
                                        invokation_timeout=timeout, 
                                        execution_timeout=None, 
                                        argument_schema=self.resource.argument_schema
                                    ) # type: ignore
                # message mapped client pool currently strips the data part from return message
                # and provides that as reply directly 
                self.set_status(200, "ok")
            except Exception as ex:
                self.logger.error(f"error while scheduling RPC call - {str(ex)}")
                self.logger.debug(f"traceback - {ex.__traceback__}")
                self.set_status(500, "error while scheduling RPC call")
                reply = self.serializer.dumps({"exception" : format_exception_as_json(ex)})
            self.set_headers()
            if reply:
                self.write(reply)
        self.finish()
        
        
class EventHandler(BaseHandler):
    """
    handles events based on PUB-SUB
    """

    def initialize(self, resource : ServerSentEvent, json_serializer : JSONSerializer,
                logger : logging.Logger, allowed_clients : typing.List[str] = []) -> None:
        self.resource = resource
        self.serializer = json_serializer
        self.logger = logger
        self.allowed_clients = allowed_clients 

    def set_headers(self) -> None:
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")
        self.set_header("Access-Control-Allow-Credentials", "true")

    async def get(self):
        """
        get method
        """
        if self.has_access_control:
            self.set_headers()
            await self.handle_datastream()
        else:
            self.set_status(403, "forbidden")
        self.finish()

    async def options(self):
        """
        options for the resource
        """
        if self.has_access_control:
            self.set_status(204)
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Credentials", "true")
            self.set_header("Access-Control-Allow-Methods", 'GET')
        else:
            self.set_status(403, "forbidden")
        self.finish()

    async def handle_datastream(self) -> None:    
        """
        handles the event
        """
        try:                        
            data_header = b'data: %s\n\n'
            event_consumer = AsyncEventConsumer(self.resource.unique_identifier, self.resource.socket_address, 
                            f"{self.resource.unique_identifier}|HTTPEvent|{current_datetime_ms_str()}")
        except Exception as ex:
            self.logger.error(f"error while subscribing to event - {str(ex)}")
            self.set_status(500, "could not subscribe to event source from remote object")
            self.write(data_header % self.serializer.dumps(
                       {"exception" : format_exception_as_json(ex)}))
        else:
            self.set_status(200)
            while True:
                try:
                    data = await event_consumer.receive(timeout=10000, deserialize=False)
                    if data:
                        # already JSON serialized 
                        self.write(data_header % data)
                        await self.flush()
                        self.logger.debug(f"new data sent - {self.resource.name}")
                    else:
                        self.logger.debug(f"found no new data")
                except StreamClosedError:
                    break 
                except Exception as ex:
                    self.logger.error(f"error while pushing event - {str(ex)}")
                    self.write(data_header % self.serializer.dumps(
                        {"exception" : format_exception_as_json(ex)}))
            try:
                event_consumer.exit()
            except Exception as ex:
                self.logger.error(f"error while closing event consumer - {str(ex)}" )


class ImageEventHandler(EventHandler):
    """
    handles events with images with jpeg data header
    """

    async def handle_datastream(self) -> None:
        try:
            self.set_header("Content-Type", "application/x-mpegURL")
            event_consumer = AsyncEventConsumer(self.resource.unique_identifier, self.resource.socket_address, 
                            f"{self.resource.unique_identifier}|HTTPEvent|{current_datetime_ms_str()}", 
                            json_serializer=self.serializer)         
            self.write("#EXTM3U\n")
            delimiter = "#EXTINF:{},\n"
            data_header = b'data:image/jpeg;base64,%s\n'
            while True:
                try:
                    data = await event_consumer.receive(timeout=10000, deserialize=False)
                    if data:
                        # already serialized 
                        self.write(delimiter)
                        self.write(data_header % data)
                        await self.flush()
                        self.logger.debug(f"new image sent - {self.resource.name}")
                except StreamClosedError:
                    break 
                except Exception as ex:
                    self.write(data_header % self.serializer.dumps(
                        {"exception" : format_exception_as_json(ex)}))
            event_consumer.exit()
        except Exception as ex:
            self.write(data_header % self.serializer.dumps(
                        {"exception" : format_exception_as_json(ex)}))
    


class FileHandler(StaticFileHandler):

    @classmethod
    def get_absolute_path(cls, root: str, path: str) -> str:
        """
        Returns the absolute location of ``path`` relative to ``root``.

        ``root`` is the path configured for this `StaticFileHandler`
        (in most cases the ``static_path`` `Application` setting).

        This class method may be overridden in subclasses.  By default
        it returns a filesystem path, but other strings may be used
        as long as they are unique and understood by the subclass's
        overridden `get_content`.

        .. versionadded:: 3.1
        """
        return root+path
    


class RemoteObjectsHandler(BaseHandler):
    """
    add or remove remote objects
    """

    def initialize(self, resource: HTTPResource | ServerSentEvent, zmq_client_pool: MessageMappedZMQClientPool, 
                json_serializer: JSONSerializer, logger: logging.Logger, allowed_clients: typing.List[str] = list(), 
                request_handler : BaseHandler = RPCHandler, event_handler : EventHandler = EventHandler) -> None:
        self.request_handler = request_handler
        self.event_handler = event_handler
        return super().initialize(resource, zmq_client_pool, json_serializer, logger, allowed_clients)

    async def get(self):
        self.set_status(404)
        self.finish()
    
    async def post(self):
        if not self.has_access_control:
            self.set_status(403, 'forbidden')
        else:
            from .HTTPServer import update_router_with_remote_objects
            try:
                await update_router_with_remote_objects(application=self.application, zmq_client_pool=self.zmq_client_pool,
                                            request_handler=self.request_handler, event_handler=self.event_handler,
                                            json_serializer=self.serializer, logger=self.logger, 
                                            allowed_clients=self.allowed_clients)
                self.set_status(204, "ok")
            except Exception as ex:
                self.set_status(500, str(ex))
            self.set_headers()
        self.finish()

    async def options(self):
        if self.has_access_control:
            self.set_status(204)
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Credentials", "true")
            self.set_header("Access-Control-Allow-Methods", 'GET, POST')
        else:
            self.set_status(403, "forbidden")
        self.finish()
