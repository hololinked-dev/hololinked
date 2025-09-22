import copy
import typing
import uuid
from tornado.web import RequestHandler, StaticFileHandler
from tornado.iostream import StreamClosedError


from ...utils import format_exception_as_json, run_callable_somehow
from ...config import global_config
from ...core.zmq.brokers import AsyncEventConsumer, EventConsumer
from ...core.zmq.message import (
    EMPTY_BYTE,
    ResponseMessage,
    default_server_execution_context,
    default_thing_execution_context,
    ThingExecutionContext,
    ServerExecutionContext,
)
from ...constants import JSONSerializable, Operations
from ...schema_validators import BaseSchemaValidator
from ...serializers.payloads import PreserializedData, SerializableData
from ...serializers import Serializers
from ...td import (
    InteractionAffordance,
    PropertyAffordance,
    ActionAffordance,
    EventAffordance,
)

try:
    from ..security import BcryptBasicSecurity
except ImportError:
    BcryptBasicSecurity = None  # type: ignore

try:
    from ..security import Argon2BasicSecurity
except ImportError:
    Argon2BasicSecurity = None  # type: ignore


class BaseHandler(RequestHandler):
    """
    Base request handler for running operations on the Thing
    """

    def initialize(
        self,
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance,
        owner_inst=None,
        metadata: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> None:
        """
        Parameters
        ----------
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance
            JSON representation of Thing's exposed object using a dataclass that can quickly convert to a
            ZMQ Request object
        owner_inst: HTTPServer
            owning `hololinked.server.HTTPServer` instance
        """
        from . import HTTPServer

        assert isinstance(owner_inst, HTTPServer)
        self.resource = resource
        self.schema_validator = None  # self.server.schema_validator # not supported yet
        self.server = owner_inst
        self.zmq_client_pool = self.server.zmq_client_pool
        self.logger = self.server.logger
        self.allowed_clients = self.server.allowed_clients
        self.security_schemes = self.server.security_schemes
        self.metadata = metadata or {}

    @property
    def has_access_control(self) -> bool:
        """
        Checks if a client is an allowed client. Requests from un-allowed clients are rejected without execution.
        Custom web request handlers can use this property to check if a client has access control on the server or ``Thing``
        and automatically generate a 401.
        """
        if not self.allowed_clients and not self.security_schemes:
            return True
        # a flag
        authenticated = False
        # First check if the client is allowed to access the server
        origin = self.request.headers.get("Origin")
        if (
            self.allowed_clients
            and origin is not None
            and (origin not in self.allowed_clients and origin + "/" not in self.allowed_clients)
        ):
            self.set_status(401, "Unauthorized")
            return False
        # Then check an authentication scheme either if the client is allowed or if there is no such list of allowed clients
        if not self.security_schemes:
            authenticated = True
        try:
            authorization_header = self.request.headers.get("Authorization", None)  # type: str
            # will simply pass through if no such header is present
            if authorization_header and "basic " in authorization_header.lower():
                for security_scheme in self.security_schemes:
                    if isinstance(security_scheme, (BcryptBasicSecurity, Argon2BasicSecurity)):
                        authenticated = (
                            security_scheme.validate_base64(authorization_header.split()[1])
                            if security_scheme.expect_base64
                            else security_scheme.validate(
                                username=authorization_header.split()[1].split(":", 1)[0],
                                password=authorization_header.split()[1].split(":", 1)[1],
                            )
                        )
                        break
        except Exception as ex:
            self.set_status(500, "Authentication error")
            self.logger.error(f"error while authenticating client - {str(ex)}")
            return False
        if authenticated:
            return True
        self.set_status(401, "Unauthorized")
        return False  # keep False always at the end

    def set_access_control_allow_headers(self) -> None:
        """
        For credential login, access control allow headers cannot be a wildcard '*'.
        Some requests require exact list of allowed headers for the client to access the response.
        Use this method in set_custom_default_headers() override if necessary.
        """
        headers = ", ".join(self.request.headers.keys())
        if self.request.headers.get("Access-Control-Request-Headers", None):
            headers += ", " + self.request.headers["Access-Control-Request-Headers"]
        self.set_header("Access-Control-Allow-Headers", headers)

    def set_custom_default_headers(self) -> None:
        """
        override this to set custom headers without having to reimplement entire handler
        """
        raise NotImplementedError(
            "implement set_custom_default_headers in child class to automatically call it"
            + " while directing the request to Thing"
        )

    def get_execution_parameters(
        self,
    ) -> typing.Tuple[ServerExecutionContext, ThingExecutionContext, dict[str, typing.Any]]:
        """
        merges all arguments to a single JSON body and retrieves execution context (like oneway calls, fetching executing
        logs) and timeouts
        """
        arguments = dict()
        if len(self.request.query_arguments) >= 1:
            for key, value in self.request.query_arguments.items():
                if len(value) == 1:
                    try:
                        arguments[key] = Serializers.json.loads(value[0])
                    except:
                        arguments[key] = value[0].decode("utf-8")
                else:
                    final_value = []
                    for val in value:
                        try:
                            final_value.append(Serializers.json.loads(val))
                        except:
                            final_value.append(val.decode("utf-8"))
                    arguments[key] = final_value
            thing_execution_context = ThingExecutionContext(
                fetchExecutionLogs=bool(arguments.pop("fetchExecutionLogs", False))
            )
            server_execution_context = ServerExecutionContext(
                invokationTimeout=arguments.pop(
                    "invokationTimeout", default_server_execution_context.invokationTimeout
                ),
                executionTimeout=arguments.pop("executionTimeout", default_server_execution_context.executionTimeout),
                oneway=arguments.pop("oneway", default_server_execution_context.oneway),
            )
            additional_execution_context = dict(
                noblock=arguments.pop("noblock", None), messageID=arguments.pop("messageID", None), **arguments
            )
            # if timeout is not None and timeout < 0:
            #     timeout = None # reinstate logic soon
            # if self.resource.request_as_argument:
            #     arguments['request'] = self.request # find some way to pass the request object to the thing
            return (
                server_execution_context,
                thing_execution_context,
                additional_execution_context,
            )
        return default_server_execution_context, default_thing_execution_context, dict()

    @property
    def message_id(self) -> str:
        """
        retrieves the message id from the request headers.
        """
        try:
            return self._message_id
        except AttributeError:
            message_id = self.request.headers.get("X-Message-ID", None)
            if not message_id:
                _, _, additional_execution_context = self.get_execution_parameters()
                message_id = additional_execution_context.get("messageID", None)
            self._message_id = message_id
            return message_id

    def get_request_payload(self) -> typing.Tuple[SerializableData, PreserializedData]:
        """
        retrieves the payload from the request body and deserializes it.
        """
        payload = SerializableData(value=None)
        preserialized_payload = PreserializedData(value=b"")
        if self.request.body:
            if self.request.headers.get("Content-Type", "application/json") in Serializers.allowed_content_types:
                payload.value = self.request.body
                payload.content_type = self.request.headers.get("Content-Type", "application/json")
            elif global_config.ALLOW_UNKNOWN_SERIALIZATION:
                preserialized_payload.value = self.request.body
                preserialized_payload.content_type = self.request.headers.get("Content-Type", None)
            else:
                raise ValueError("Content-Type not supported")
                # NOTE that was assume that the content type is JSON even if unspecified in the header.
                # This error will be raised only when a specified content type is not supported.
        return payload, preserialized_payload

    def get_response_payload(self, zmq_response: ResponseMessage) -> PreserializedData | SerializableData:
        """
        cached return value of the last call to the method
        """
        # print("zmq_response - ", zmq_response)
        if zmq_response is None:
            raise RuntimeError("No last response available. Did you make an operation?")
        if zmq_response.preserialized_payload.value != EMPTY_BYTE:
            if zmq_response.payload.value:
                self.logger.warning(
                    "Multiple content types in response payload, only the latter will be written to the wire"
                )
            # multiple content types are not supported yet, so we return only one payload
            return zmq_response.preserialized_payload
            # return payload, preserialized_payload
        return zmq_response.payload  # dont deseriablize, there is no need, just pass it on to the client

    async def get(self) -> None:
        """
        runs property or action if accessible by 'GET' method. Default for property reads.
        """
        raise NotImplementedError("implement GET request method in child handler class")

    async def post(self) -> None:
        """
        runs property or action if accessible by 'POST' method. Default for action execution.
        """
        raise NotImplementedError("implement POST request method in child handler class")

    async def put(self) -> None:
        """
        runs property or action if accessible by 'PUT' method. Default for property writes.
        """
        raise NotImplementedError("implement PUT request method in child handler class")

    async def delete(self) -> None:
        """
        runs property or action if accessible by 'DELETE' method. Default for property deletes
        (not a valid operation as per web of things semantics).
        """
        raise NotImplementedError("implement DELETE request method in child handler class")

    def is_method_allowed(self, method: str) -> bool:
        """
        checks if the method is allowed for the property.
        """
        raise NotImplementedError("implement is_method_allowed in child handler class")


class RPCHandler(BaseHandler):
    """
    Handler for property read-write and method calls
    """

    def is_method_allowed(self, method: str) -> bool:
        """
        checks if the method is allowed for the property.
        """
        if not self.has_access_control:
            return False
        if self.message_id is not None and method.upper() == "GET":
            return True
        if method not in self.metadata.get("http_methods", []):
            self.set_status(405, "method not allowed")
            return False
        return True

    def set_custom_default_headers(self) -> None:
        """
        sets default headers for RPC (property read-write and action execution). The general headers are listed as follows:

        .. code-block:: yaml

            Content-Type: application/json
            Access-Control-Allow-Credentials: true
            Access-Control-Allow-Origin: <client>
        """
        self.set_header("Access-Control-Allow-Credentials", "true")
        if global_config.ALLOW_CORS or self.server.config.get("allow_cors", False):
            # For credential login, access control allow origin cannot be '*',
            # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#examples_of_access_control_scenarios
            self.set_header("Access-Control-Allow-Origin", "*")

    async def options(self) -> None:
        """
        Options for the resource. Main functionality is to inform the client is a specific HTTP method is supported by
        the property or the action (Access-Control-Allow-Methods).
        """
        if self.has_access_control:
            self.set_status(204)
            self.set_custom_default_headers()
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Methods", ", ".join(self.metadata.get("http_methods", [])))
        self.finish()

    async def handle_through_thing(self, operation: str) -> None:
        """
        handles the Thing operations and writes the reply to the HTTP client.
        """
        try:
            server_execution_context, thing_execution_context, additional_execution_context = (
                self.get_execution_parameters()
            )
            payload, preserialized_payload = self.get_request_payload()
        except Exception as ex:
            self.set_status(400, f"error while decoding request - {str(ex)}")
            self.set_custom_default_headers()
            return
        try:
            # TODO - add schema validation here, we are anyway validating at some point within the ZMQ server
            # if self.schema_validator is not None and global_config.VALIDATE_SCHEMA_ON_CLIENT:
            #     self.schema_validator.validate(payload)
            if server_execution_context.oneway or additional_execution_context.get("noblock", False):
                # if oneway, we do not expect a response, so we just return None
                message_id = await self.zmq_client_pool.async_send_request(
                    client_id=self.zmq_client_pool.get_client_id_from_thing_id(self.resource.thing_id),
                    thing_id=self.resource.thing_id,
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                response_payload = SerializableData(value=None)
                self.set_status(204, "ok")
                if additional_execution_context.get("noblock", False):
                    self.set_header("X-Message-ID", message_id)
            else:
                response_message = await self.zmq_client_pool.async_execute(
                    client_id=self.zmq_client_pool.get_client_id_from_thing_id(self.resource.thing_id),
                    thing_id=self.resource.thing_id,
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                response_payload = self.get_response_payload(response_message)
                self.set_status(200, "ok")
                self.set_header("Content-Type", response_payload.content_type or "application/json")
        except ConnectionAbortedError as ex:
            self.set_status(503, str(ex))
            # event_loop = asyncio.get_event_loop()
            # event_loop.call_soon(lambda : asyncio.create_task(self.server.update_router_with_thing(
            #                                                     self.zmq_client_pool[self.resource.instance_name])))
        # except ConnectionError as ex:
        #     await self.server.update_router_with_thing(self.zmq_client_pool[self.resource.instance_name])
        #     await self.handle_through_thing(operation) # reschedule
        #     return
        except Exception as ex:
            self.logger.error(f"error while scheduling RPC call - {str(ex)}")
            self.logger.debug(f"traceback - {ex.__traceback__}")
            self.set_status(500, "error while scheduling RPC call")
            response_payload = SerializableData(
                value=self.serializer.dumps({"exception": format_exception_as_json(ex)}),
                content_type="application/json",
            )
            response_payload.serialize()
        self.set_custom_default_headers()  # remaining headers are set here
        if response_payload.value:
            self.write(response_payload.value)

    async def handle_no_block_response(self) -> None:
        """handles the no-block response for the noblock calls"""
        try:
            response_message = await self.zmq_client_pool.async_recv_response(
                client_id=self.zmq_client_pool.get_client_id_from_thing_id(self.resource.thing_id),
                message_id=self.message_id,
                timeout=default_server_execution_context.invokationTimeout
                + default_server_execution_context.executionTimeout,
            )
            response_payload = self.get_response_payload(response_message)
            self.set_status(200, "ok")
            self.set_header("Content-Type", response_payload.content_type or "application/json")
            self.set_custom_default_headers()
            if response_payload.value:
                self.write(response_payload.value)
        except KeyError as ex:
            # if the message id is not found, it means that the response was not received in time
            self.logger.error(f"error while receiving no-block response - {str(ex)}")
            self.set_status(404, "message id not found")
        except TimeoutError as ex:
            self.logger.error(f"error while receiving no-block response - {str(ex)}")
            self.set_status(408, "timeout while waiting for response")
        except Exception as ex:
            self.logger.error(f"error while receiving no-block response - {str(ex)}")
            self.set_status(500, f"error while receiving no-block response - {str(ex)}")
            response_payload = SerializableData(
                value=self.serializer.dumps({"exception": format_exception_as_json(ex)}),
                content_type="application/json",
            )
            response_payload.serialize()
            self.write(response_payload.value)


class PropertyHandler(RPCHandler):
    async def get(self) -> None:
        """
        runs property or action if accessible by 'GET' method. Default for property reads.
        """
        if self.is_method_allowed("GET"):
            if self.message_id is not None:
                await self.handle_no_block_response()
            else:
                await self.handle_through_thing(Operations.readproperty)
        self.finish()

    async def post(self) -> None:
        """
        runs property or action if accessible by 'POST' method. Default for action execution.
        """
        if self.is_method_allowed("POST"):
            await self.handle_through_thing(Operations.writeproperty)
        self.finish()

    async def put(self) -> None:
        """
        runs property or action if accessible by 'PUT' method. Default for property writes.
        """
        if self.is_method_allowed("PUT"):
            await self.handle_through_thing(Operations.writeproperty)
        self.finish()

    async def delete(self) -> None:
        """
        runs property or action if accessible by 'DELETE' method. Default for property deletes.
        """
        if self.is_method_allowed("DELETE"):
            await self.handle_through_thing(Operations.deleteproperty)
        self.finish()


class ActionHandler(RPCHandler):
    async def get(self) -> None:
        """
        runs property or action if accessible by 'GET' method. Default for property reads.
        """
        if self.is_method_allowed("GET"):
            if self.message_id is not None:
                await self.handle_no_block_response()
            else:
                await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def post(self) -> None:
        """
        runs property or action if accessible by 'POST' method. Default for action execution.
        """
        if self.is_method_allowed("POST"):
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def put(self) -> None:
        """
        runs property or action if accessible by 'PUT' method. Default for property writes.
        """
        if self.is_method_allowed("PUT"):
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def delete(self) -> None:
        """
        runs property or action if accessible by 'DELETE' method. Default for property deletes.
        """
        if self.is_method_allowed("DELETE"):
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()


class EventHandler(BaseHandler):
    """
    handles events emitted by ``Thing`` and tunnels them as HTTP SSE.
    """

    def initialize(
        self,
        resource: InteractionAffordance | EventAffordance,
        owner_inst=None,
        metadata: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> None:
        super().initialize(resource, owner_inst, metadata)
        self.data_header = b"data: %s\n\n"

    def set_custom_default_headers(self) -> None:
        """
        sets default headers for event handling. The general headers are listed as follows:

        .. code-block:: yaml

            Content-Type: text/event-stream
            Cache-Control: no-cache
            Connection: keep-alive
            Access-Control-Allow-Credentials: true
            Access-Control-Allow-Origin: <client>
        """
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")
        self.set_header("Access-Control-Allow-Credentials", "true")

    async def get(self):
        """
        events are support only with GET method.
        """
        if self.has_access_control:
            self.set_custom_default_headers()
            await self.handle_datastream()
        self.finish()

    async def options(self):
        """
        options for the resource.
        """
        if self.has_access_control:
            self.set_status(204)
            self.set_custom_default_headers()
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Methods", "GET")
        self.finish()

    def receive_blocking_event(self, event_consumer: EventConsumer):
        """deprecated, but can make a blocking call in an async loop"""
        return event_consumer.receive(timeout=10000, deserialize=False)

    async def handle_datastream(self) -> None:
        """called by GET method and handles the event publishing"""
        try:
            # if not getattr(self.resource, 'zmq_socket_address', None) or not getattr(self.resource, 'zmq_unique_identifier', None):
            #     raise ValueError("Event resource is not initialized properly, missing socket address or unique identifier")
            if isinstance(self.resource, EventAffordance):
                form = self.resource.retrieve_form(Operations.subscribeevent)
            else:
                form = self.resource.retrieve_form(Operations.observeproperty)
            event_consumer = AsyncEventConsumer(
                id=f"{self.resource.name}|HTTPEventTunnel|{uuid.uuid4().hex[:8]}",
                event_unique_identifier=f"{self.resource.thing_id}/{self.resource.name}",
                access_point=form.href,  # no not acceptable, TODO
                context=global_config.zmq_context(),
                logger=self.logger,
            )
            event_consumer.subscribe()
            self.set_status(200)
        except Exception as ex:
            self.logger.error(f"error while subscribing to event - {str(ex)}")
            self.set_status(500, "could not subscribe to event source from thing")
            self.write(self.serializer.dumps({"exception": format_exception_as_json(ex)}))
            return

        while True:
            try:
                event_message = await event_consumer.receive(timeout=10000)
                if event_message:
                    payload = self.get_response_payload(event_message)
                    self.write(self.data_header % payload.value)
                    self.logger.debug(f"new data scheduled to flush - {self.resource.name}")
                else:
                    self.logger.debug(f"found no new data - {self.resource.name}")
                await self.flush()  # flushes and handles heartbeat - raises StreamClosedError if client disconnects
            except StreamClosedError:
                break
            except Exception as ex:
                self.logger.error(f"error while pushing event - {str(ex)}")
                self.write(self.data_header % self.serializer.dumps({"exception": format_exception_as_json(ex)}))
        event_consumer.exit()


class JPEGImageEventHandler(EventHandler):
    """
    handles events with images with image data header
    """

    def initialize(self, resource, validator: BaseSchemaValidator, owner_inst=None) -> None:
        super().initialize(resource, validator, owner_inst)
        self.data_header = b"data:image/jpeg;base64,%s\n\n"


class PNGImageEventHandler(EventHandler):
    """
    handles events with images with image data header
    """

    def initialize(self, resource, validator: BaseSchemaValidator, owner_inst=None) -> None:
        super().initialize(resource, validator, owner_inst)
        self.data_header = b"data:image/png;base64,%s\n\n"


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
        return root + path


class ThingsHandler(BaseHandler):
    """
    add or remove things
    """

    async def get(self):
        self.set_status(404)
        self.finish()

    async def post(self):
        if not self.has_access_control:
            self.set_status(401, "forbidden")
        else:
            try:
                instance_name = ""
                await self.zmq_client_pool.create_new(server_instance_name=instance_name)
                await self.server.update_router_with_thing(self.zmq_client_pool[instance_name])
                self.set_status(204, "ok")
            except Exception as ex:
                self.set_status(500, str(ex))
            self.set_custom_default_headers()
        self.finish()

    async def options(self):
        if self.has_access_control:
            self.set_status(204)
            self.set_custom_default_headers()
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Methods", "GET, POST")
        else:
            self.set_status(401, "forbidden")
        self.finish()


class StopHandler(BaseHandler):
    """Stops the tornado HTTP server"""

    def initialize(self, owner_inst=None) -> None:
        from . import HTTPServer

        assert isinstance(owner_inst, HTTPServer)
        self.server = owner_inst
        self.allowed_clients = self.server.allowed_clients
        self.security_schemes = self.server.security_schemes

    async def post(self):
        if not self.has_access_control:
            return
        try:
            # Stop the Tornado server
            run_callable_somehow(self.server.async_stop())  # creates a task in current loop
            # dont call it in sequence, its not clear whether its designed for that
            self.set_status(204, "ok")
            self.set_header("Access-Control-Allow-Credentials", "true")
        except Exception as ex:
            self.set_status(500, str(ex))
        self.finish()


class ThingDescriptionHandler(BaseHandler):
    def set_custom_default_headers(self):
        self.set_header("Access-Control-Allow-Credentials", "true")
        if global_config.ALLOW_CORS or self.server.config.get("allow_cors", False):
            # For credential login, access control allow origin cannot be '*',
            # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#examples_of_access_control_scenarios
            self.set_header("Access-Control-Allow-Origin", "*")

    async def get(self):
        if self.has_access_control:
            try:
                _, _, body = self.get_execution_parameters()

                response_message = await self.zmq_client_pool.async_execute(
                    client_id=self.zmq_client_pool.get_client_id_from_thing_id(self.resource.thing_id),
                    thing_id=self.resource.thing_id,
                    objekt=self.resource.name,
                    operation=Operations.invokeaction,
                    payload=SerializableData(
                        value=dict(
                            ignore_errors=body.get("ignore_errors", False), skip_names=body.get("skip_names", [])
                        ),
                    ),
                )

                payload = self.get_response_payload(response_message)
                TM = payload.deserialize()
                TD = self.generate_td(
                    TM, authority=body.get("authority", None), use_localhost=body.get("use_localhost", False)
                )

                self.set_status(200, "ok")
                self.set_header("Content-Type", "application/json")
                self.write(TD)
            except Exception as ex:
                self.set_status(500, str(ex).replace("\n", " "))
            self.set_custom_default_headers()
        self.finish()

    def generate_td(
        self, TM: dict[str, JSONSerializable], authority: str = None, use_localhost: bool = False
    ) -> dict[str, JSONSerializable]:
        from ...td.forms import Form

        TD = copy.deepcopy(TM)
        # sanitize some things
        TD["id"] = f"{self.server.router.get_basepath(authority=authority, use_localhost=use_localhost)}/{TD['id']}"
        # add forms
        for name in TM.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, TM)
            href = self.server.router.get_href_for_affordance(
                affordance, authority=authority, use_localhost=use_localhost
            )
            if not TD["properties"][name].get("forms", None):
                TD["properties"][name]["forms"] = []
            http_methods = (
                self.server.router.get_target_kwargs_for_affordance(affordance)
                .get("metadata", {})
                .get("http_methods", [])
            )
            for http_method in http_methods:
                if affordance.readOnly and http_method.upper() != "GET":
                    break
                if http_method.upper() == "DELETE":
                    # currently not in spec although we support it
                    continue
                form = Form()
                form.href = href
                form.htv_methodName = http_method
                form.op = Operations.readproperty if http_method.upper() == "GET" else Operations.writeproperty
                form.contentType = "application/json"
                TD["properties"][name]["forms"].append(form.json())
            if affordance.observable:
                form = Form()
                form.href = f"{href}/change-event"
                form.htv_methodName = "GET"
                form.contentType = "application/json"
                form.op = Operations.observeproperty
                form.subprotocol = "sse"
                TD["properties"][name]["forms"].append(form.json())
        for name in TM.get("actions", []):
            affordance = ActionAffordance.from_TD(name, TM)
            href = self.server.router.get_href_for_affordance(
                affordance, authority=authority, use_localhost=use_localhost
            )
            if not TD["actions"][name].get("forms", None):
                TD["actions"][name]["forms"] = []
            http_methods = (
                self.server.router.get_target_kwargs_for_affordance(affordance)
                .get("metadata", {})
                .get("http_methods", [])
            )
            for http_method in http_methods:
                form = Form()
                form.href = href
                form.htv_methodName = http_method
                form.op = Operations.invokeaction
                form.contentType = "application/json"
                TD["actions"][name]["forms"].append(form.json())
        for name in TM.get("events", []):
            affordance = EventAffordance.from_TD(name, TM)
            href = self.server.router.get_href_for_affordance(
                affordance, authority=authority, use_localhost=use_localhost
            )
            if not TD["events"][name].get("forms", None):
                TD["events"][name]["forms"] = []
            http_methods = (
                self.server.router.get_target_kwargs_for_affordance(affordance)
                .get("metadata", dict(http_methods=["GET"]))
                .get("http_methods", ["GET"])
            )
            for http_method in http_methods:
                form = Form()
                form.href = href
                form.htv_methodName = http_method
                form.op = Operations.subscribeevent
                form.contentType = "application/json"
                form.subprotocol = "sse"
                TD["events"][name]["forms"].append(form.json())
        self.add_security_definitions(TD)
        return TD

    def add_security_definitions(self, TD: dict[str, JSONSerializable]) -> None:
        from ...td.security_definitions import SecurityScheme

        TD["securityDefinitions"] = {}
        sec_names: list[str] = []

        schemes = getattr(self.server, "security_schemes", None)
        if schemes:
            for i, scheme in enumerate(schemes):
                if isinstance(scheme, (BcryptBasicSecurity, Argon2BasicSecurity)):
                    name = f"basic_sc_{i}"
                    TD["securityDefinitions"][name] = {
                        "scheme": "basic",
                        "in": "header",
                    }
                    sec_names.append(name)

        if not sec_names:
            nosec = SecurityScheme()
            nosec.build()
            TD["securityDefinitions"]["nosec"] = nosec.json()
            TD["security"] = ["nosec"]
        else:
            TD["security"] = sec_names
