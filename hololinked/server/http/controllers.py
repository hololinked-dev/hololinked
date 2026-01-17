from typing import Any, Optional

import msgspec
import structlog

from msgspec import DecodeError as MsgspecJSONDecodeError
from tornado.iostream import StreamClosedError
from tornado.web import RequestHandler

from ...config import global_config
from ...constants import Operations
from ...core.zmq.brokers import EventConsumer
from ...core.zmq.message import (
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)
from ...serializers import Serializers
from ...serializers.payloads import PreserializedData, SerializableData
from ...td import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from ...utils import format_exception_as_json, get_current_async_loop
from ..repository import BrokerThing  # noqa: F401


try:
    from ..security import BcryptBasicSecurity
except ImportError:
    BcryptBasicSecurity = None

try:
    from ..security import APIKeySecurity, Argon2BasicSecurity
except ImportError:
    Argon2BasicSecurity = None
    APIKeySecurity = None


class LocalExecutionContext(msgspec.Struct):
    noblock: Optional[bool] = None
    messageID: Optional[str] = None


class BaseHandler(RequestHandler):
    """Base request handler for running operations on the `Thing`"""

    # Would be a Controller in layered architecture.

    def initialize(
        self,
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        metadata: Any = None,
    ) -> None:
        """
        Parameters
        ----------
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance
            dataclass representation of `Thing`'s exposed object that can quickly convert to a ZMQ Request object
        owner_inst: HTTPServer
            owning `hololinked.server.HTTPServer` instance
        metadata: HandlerMetadata | None,
            additional metadata about the resource, like allowed HTTP methods
        """
        from .config import HandlerMetadata, RuntimeConfig  # noqa: F401

        self.resource = resource  # type: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance
        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(
            resource=resource.name,
            what=resource.what,
            thing_id=resource.thing_id,
            path=self.request.path,
            layer="controller",
            impl=self.__class__.__name__,
        )
        self.thing = self.config.thing_repository[self.resource.thing_id]  # type: BrokerThing
        self.allowed_clients = self.config.allowed_clients
        self.security_schemes = self.config.security_schemes
        self.metadata = metadata or HandlerMetadata()  # type: HandlerMetadata

    @property
    def has_access_control(self) -> bool:
        """
        Checks if a client is an allowed client and enforces security schemes.
        Custom web request handlers can use this property to check if a client has access control on the server or `Thing`
        and let this property automatically generate a 401/403.
        """
        if not self.allowed_clients and not self.security_schemes:
            return True
        # First check if the client is allowed to access the server
        origin = self.request.headers.get("Origin")
        if (
            self.allowed_clients
            and origin is not None
            and (origin not in self.allowed_clients and origin + "/" not in self.allowed_clients)
        ):
            self.set_status(401, "Unauthorized")
            return False
        # Then check an authentication scheme either if the client is allowed
        # or if there is no such list of allowed clients
        if not self.security_schemes:
            self.logger.debug("no security schemes defined, allowing access")
            return True
        if self.is_authenticated:
            self.logger.info("client authenticated successfully")
            return True
        self.set_status(401, "Unauthorized")
        self.logger.info("client authentication failed or is not authorized to proceed")
        return False  # keep False always at the end

    @property
    def is_authenticated(self) -> bool:
        """enforces authentication using the defined security schemes, freshly computed everytime"""
        authenticated = False
        # 1. Basic Authentication
        authorization_header = self.request.headers.get("Authorization", None)  # type: str
        if authorization_header and "basic " in authorization_header.lower():
            for security_scheme in self.security_schemes:
                if isinstance(security_scheme, (BcryptBasicSecurity, Argon2BasicSecurity)):
                    try:
                        self.logger.info(
                            "authenticating client",
                            origin=self.request.headers.get("Origin"),
                            security_scheme=security_scheme.__class__.__name__,
                        )
                        if security_scheme.expect_base64:
                            authenticated = security_scheme.validate_base64(authorization_header.split()[1])
                        else:
                            authenticated = security_scheme.validate_input(
                                username=authorization_header.split()[1].split(":", 1)[0],
                                password=authorization_header.split()[1].split(":", 1)[1],
                            )
                    except Exception as ex:
                        self.logger.error(f"error while authenticating client - {str(ex)}")
                    if authenticated:
                        return True
        # 2. API Key Authentication
        apikey = self.request.headers.get("X-API-Key", None)  # type: str
        if apikey:
            for security_scheme in self.security_schemes:
                if isinstance(security_scheme, APIKeySecurity):
                    try:
                        self.logger.info(
                            "authenticating client with API key",
                            origin=self.request.headers.get("Origin"),
                            security_scheme=security_scheme.__class__.__name__,
                        )
                        authenticated = security_scheme.validate_input(apikey)
                    except Exception as ex:
                        self.logger.error(f"error while authenticating client with API key - {str(ex)}")
                    if authenticated:
                        return True
        return authenticated

    def set_access_control_allow_headers(self) -> None:
        """
        For credential login, access control allow headers cannot be a wildcard '*'.
        Some requests require exact list of allowed headers for the client to access the response.
        """
        headers = ", ".join(self.request.headers.keys())
        if self.request.headers.get("Access-Control-Request-Headers", None):
            headers += ", " + self.request.headers["Access-Control-Request-Headers"]
        self.set_header("Access-Control-Allow-Headers", headers)

    def set_custom_default_headers(self) -> None:
        """
        sets general default headers, override in child classes to add more headers.

        ```yaml
        Content-Type: application/json
        Access-Control-Allow-Origin: <client>
        ```
        """
        # Access-Control-Allow-Credentials: true # only for cookie auth
        if self.config.cors:
            # For credential login, access control allow origin cannot be '*',
            # See: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS#examples_of_access_control_scenarios
            self.set_header("Access-Control-Allow-Origin", "*")

    def get_execution_parameters(
        self,
    ) -> tuple[
        ServerExecutionContext,
        ThingExecutionContext,
        LocalExecutionContext,
        SerializableData,
    ]:
        """
        Aggregates all arguments to a standard dataclasses from the query parameters.
        Retrieves execution context (like oneway calls, fetching executing
        logs), timeouts, etc. Non recognized arguments are passed as additional payload to the `Thing`.

        An example would be the following URL:

        ```
        http://localhost:8080/property/temperature?oneway=true&invokationTimeout=5&some_arg=42
        ```

        server execution context would have `oneway` set to true & `invokationTimeout` set to 5 seconds,
        local execution context would be empty as no such arguments were passed,
        and additional payload would have `{"some_arg": 42}` as its value.

        Returns
        -------
        tuple[
            ServerExecutionContext,
            ThingExecutionContext,
            LocalExecutionContext,
            SerializableData,
        ]
            server execution context, thing execution context, local execution context and payload (if any)
        """
        arguments = dict()
        if len(self.request.query_arguments) == 0:
            return (
                default_server_execution_context,
                default_thing_execution_context,
                LocalExecutionContext(),
                SerializableNone,
            )
        for key, value in self.request.query_arguments.items():
            if len(value) == 1:
                try:
                    arguments[key] = Serializers.json.loads(value[0])
                except MsgspecJSONDecodeError:
                    arguments[key] = value[0].decode("utf-8")
            else:
                final_value = []
                for val in value:
                    try:
                        final_value.append(Serializers.json.loads(val))
                    except MsgspecJSONDecodeError:
                        final_value.append(val.decode("utf-8"))
                arguments[key] = final_value
        # if self.resource.request_as_argument:
        #     arguments['request'] = self.request # find some way to pass the request object to the thing
        thing_execution_context = ThingExecutionContext(
            fetchExecutionLogs=bool(arguments.pop("fetchExecutionLogs", False))
        )
        server_execution_context = ServerExecutionContext(
            invokationTimeout=arguments.pop("invokationTimeout", default_server_execution_context.invokationTimeout),
            executionTimeout=arguments.pop("executionTimeout", default_server_execution_context.executionTimeout),
            oneway=arguments.pop("oneway", default_server_execution_context.oneway),
        )
        local_execution_context = LocalExecutionContext(
            noblock=arguments.pop("noblock", None),
            messageID=arguments.pop("messageID", None),
        )
        additional_payload = SerializableNone if not arguments else SerializableData(arguments)  # application/json
        return server_execution_context, thing_execution_context, local_execution_context, additional_payload

    @property
    def message_id(self) -> str:
        """retrieves the message id from the request headers"""
        try:
            return self._message_id
        except AttributeError:
            message_id = self.request.headers.get("X-Message-ID", None)
            if not message_id:
                _, _, local_execution_context, _ = self.get_execution_parameters()
                # TODO avoid calling get_execution_parameters twice in the same request
                message_id = local_execution_context.messageID
            self._message_id = message_id
            return message_id

    def get_request_payload(self) -> tuple[SerializableData, PreserializedData]:
        """retrieves the payload from the request body, does not necessarily deserialize it"""
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

    async def get(self) -> None:
        """runs property or action if accessible by 'GET' method. Default for property reads"""
        raise NotImplementedError("implement GET request method in child handler class")

    async def post(self) -> None:
        """runs property or action if accessible by 'POST' method. Default for action execution"""
        raise NotImplementedError("implement POST request method in child handler class")

    async def put(self) -> None:
        """runs property or action if accessible by 'PUT' method. Default for property writes"""
        raise NotImplementedError("implement PUT request method in child handler class")

    async def delete(self) -> None:
        """
        runs property or action if accessible by 'DELETE' method. Default for property deletes
        (not a valid operation as per web of things semantics).
        """
        raise NotImplementedError("implement DELETE request method in child handler class")

    def is_method_allowed(self, method: str) -> bool:
        """checks if the method is allowed for the property"""
        raise NotImplementedError("implement is_method_allowed in child handler class")


class RPCHandler(BaseHandler):
    """
    Handler for property read-write and method calls.

    Subclassed from controller for reducing boilerplate code as the service layer is too thin when implemented separately.
    Uses Repository layer directly.
    """

    # Merges both Controller and Service layer in layered architecture. Repository layer is used directly.

    def is_method_allowed(self, method: str) -> bool:
        """
        Checks if the method is allowed for the property:

        - Access control (authentication & authorization)
        - if the HTTP method is allowed for the resource.
        - if its GET method with message id for no-block response.
        """
        if not self.has_access_control:
            return False
        if self.message_id is not None and method.upper() == "GET":
            return True
        if method in self.metadata.http_methods:
            return True
        self.set_status(405, "method not allowed")
        return False

    async def options(self) -> None:
        """
        Options for the resource. Main functionality is to inform the client is a specific HTTP method is supported by
        the property or the action (Access-Control-Allow-Methods).
        """
        if self.has_access_control:
            self.set_status(204)
            self.set_custom_default_headers()
            self.set_access_control_allow_headers()
            self.set_header("Access-Control-Allow-Methods", ", ".join(self.metadata.http_methods))
        self.finish()

    async def handle_through_thing(self, operation: str) -> None:
        """
        handles the `Thing` operations and writes the reply to the HTTP client.

        Parameters
        ----------
        operation: str
            operation to be performed on the Thing, like `readproperty`,
            `writeproperty`, `invokeaction`, `deleteproperty`
        """
        try:
            server_execution_context, thing_execution_context, local_execution_context, additional_payload = (
                self.get_execution_parameters()
            )
            payload, preserialized_payload = self.get_request_payload()
            payload = payload if payload.value else additional_payload
        except Exception as ex:
            self.set_status(400, f"error while decoding request - {str(ex)}")
            self.logger.error(f"error while decoding request - {str(ex)}")
            return
        try:
            if server_execution_context.oneway:
                # if oneway, we do not expect a response, so we just return None
                await self.thing.oneway(
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                self.set_status(204, "ok")
            elif local_execution_context.noblock:
                message_id = await self.thing.schedule(
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                self.set_status(204, "ok")
                self.set_header("X-Message-ID", message_id)
            else:
                response_message = await self.thing.execute(
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                response_payload = self.thing.get_response_payload(response_message)
                self.set_status(200, "ok")
                self.set_header("Content-Type", response_payload.content_type or "application/json")
                if response_payload.value:
                    self.write(response_payload.value)
        except ConnectionAbortedError as ex:
            self.set_status(503, f"lost connection to thing - {str(ex)}")
            # TODO handle reconnection
        except Exception as ex:
            self.logger.error(f"error while scheduling RPC call - {str(ex)}")
            self.set_status(500, f"error while scheduling RPC call - {str(ex)}")
            self.set_header("Content-Type", "application/json")
            response_payload = SerializableData(
                value=Serializers.json.dumps({"exception": format_exception_as_json(ex)}),
                content_type="application/json",
            )
            response_payload.serialize()
            self.write(response_payload.value)

    async def handle_no_block_response(self) -> None:
        """handles the no-block response for the noblock calls"""
        try:
            self.logger.info("waiting for no-block response", message_id=self.message_id)
            response_message = await self.thing.recv_response(
                message_id=self.message_id,
                timeout=default_server_execution_context.invokationTimeout
                + default_server_execution_context.executionTimeout,
            )
            response_payload = self.thing.get_response_payload(response_message)
            self.set_status(200, "ok")
            self.set_header("Content-Type", response_payload.content_type or "application/json")
            if response_payload.value:
                self.write(response_payload.value)
        except KeyError as ex:
            # if the message id is not found, it means that the response was not received in time
            self.logger.error(f"message ID not found for no-block response - {str(ex)}")
            self.set_status(404, "message id not found")
        except TimeoutError as ex:
            self.logger.error(f"timeout while waiting for no-block response - {str(ex)}")
            self.set_status(408, "timeout while waiting for response, ask later")
        except Exception as ex:
            self.logger.error(f"error while receiving no-block response - {str(ex)}")
            self.set_status(500, f"error while receiving no-block response - {str(ex)}")
            self.set_header("Content-Type", "application/json")
            response_payload = SerializableData(
                value=Serializers.json.dumps({"exception": format_exception_as_json(ex)}),
                content_type="application/json",
            )
            response_payload.serialize()
            self.write(response_payload.value)


class PropertyHandler(RPCHandler):
    """handles property requests"""

    async def get(self) -> None:
        if self.is_method_allowed("GET"):
            self.set_custom_default_headers()
            if self.message_id is not None:
                await self.handle_no_block_response()
            else:
                await self.handle_through_thing(Operations.readproperty)
        self.finish()

    async def post(self) -> None:
        if self.is_method_allowed("POST"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.writeproperty)
        self.finish()

    async def put(self) -> None:
        if self.is_method_allowed("PUT"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.writeproperty)
        self.finish()

    async def delete(self) -> None:
        if self.is_method_allowed("DELETE"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.deleteproperty)
        self.finish()


class ActionHandler(RPCHandler):
    """handles action requests"""

    async def get(self) -> None:
        if self.is_method_allowed("GET"):
            self.set_custom_default_headers()
            if self.message_id is not None:
                await self.handle_no_block_response()
            else:
                await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def post(self) -> None:
        if self.is_method_allowed("POST"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def put(self) -> None:
        if self.is_method_allowed("PUT"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def delete(self) -> None:
        if self.is_method_allowed("DELETE"):
            self.set_custom_default_headers()
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()


class RWMultiplePropertiesHandler(ActionHandler):
    """handles read-write of multiple properties via an action"""

    def initialize(
        self,
        resource: ActionAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        metadata: Any = None,
        **kwargs,
    ) -> None:
        self.read_properties_resource = kwargs.get("read_properties_resource", None)
        self.write_properties_resource = kwargs.get("write_properties_resource", None)
        return super().initialize(resource, config, logger, metadata)

    async def get(self) -> None:
        if self.is_method_allowed("GET"):
            self.set_custom_default_headers()
            self.resource = self.read_properties_resource
            if self.message_id is not None:
                await self.handle_no_block_response()
            else:
                await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def post(self) -> None:
        if self.is_method_allowed("POST"):
            self.set_status(405, "method not allowed, PUT instead")
        self.finish()

    async def put(self) -> None:
        if self.is_method_allowed("PUT"):
            self.set_custom_default_headers()
            self.resource = self.write_properties_resource
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()

    async def patch(self) -> None:
        if self.is_method_allowed("PATCH"):
            self.set_custom_default_headers()
            self.resource = self.write_properties_resource
            await self.handle_through_thing(Operations.invokeaction)
        self.finish()


class EventHandler(BaseHandler):
    """handles events emitted by `Thing` and tunnels them as HTTP SSE"""

    def initialize(
        self,
        resource: InteractionAffordance | EventAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        metadata: Any = None,
    ) -> None:
        super().initialize(resource, config, logger, metadata)
        self.data_header = b"data: %s\n\n"

    def set_custom_default_headers(self) -> None:
        """
        sets default headers for event handling. The general headers are listed as follows:

        ```yaml
        Content-Type: text/event-stream
        Cache-Control: no-cache
        Connection: keep-alive
        Access-Control-Allow-Credentials: true # Possibly for cookie auth
        Access-Control-Allow-Origin: <client> # if CORS is enabled
        ```
        """
        self.set_header("Content-Type", "text/event-stream")
        self.set_header("Cache-Control", "no-cache")
        self.set_header("Connection", "keep-alive")
        super().set_custom_default_headers()

    async def get(self):
        """events are support only with GET method"""
        if self.has_access_control:
            self.set_custom_default_headers()
            await self.handle_datastream()
        self.finish()

    async def options(self):
        """options for the resource"""
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
            event_consumer = self.thing.subscribe_event(self.resource)
            self.set_status(200)
        except Exception as ex:
            self.logger.error(f"error while subscribing to event - {str(ex)}")
            self.set_status(500, f"could not subscribe to event source from thing - {str(ex)}")
            self.write(Serializers.json.dumps({"exception": format_exception_as_json(ex)}))
            return

        while True:
            try:
                event_message = await event_consumer.receive(timeout=10000)
                if event_message:
                    payload = self.thing.get_response_payload(event_message)
                    self.write(self.data_header % payload.value)
                    self.logger.debug(f"new data scheduled to flush - {self.resource.name}")
                else:
                    self.logger.debug(f"found no new data - {self.resource.name}")
                await self.flush()  # flushes and handles heartbeat - raises StreamClosedError if client disconnects
            except StreamClosedError:
                break
            except Exception as ex:
                self.logger.error(f"error while pushing event - {str(ex)}")
                self.write(self.data_header % Serializers.json.dumps({"exception": format_exception_as_json(ex)}))


class JPEGImageEventHandler(EventHandler):
    """handles events with images with JPEG image data header"""

    def initialize(
        self,
        resource: InteractionAffordance | EventAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        metadata: Any = None,
    ) -> None:
        super().initialize(resource, config, logger, metadata)
        self.data_header = b"data:image/jpeg;base64,%s\n\n"


class PNGImageEventHandler(EventHandler):
    """handles events with images with PNG image data header"""

    def initialize(
        self,
        resource: InteractionAffordance | EventAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        metadata: Any = None,
    ) -> None:
        super().initialize(resource, config, logger, metadata)
        self.data_header = b"data:image/png;base64,%s\n\n"


class StopHandler(BaseHandler):
    """Stops the tornado HTTP server"""

    def initialize(
        self,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any,
    ) -> None:
        from . import HTTPServer  # noqa: F401
        from .config import RuntimeConfig  # noqa: F401

        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(path=self.request.path)
        self.allowed_clients = self.config.allowed_clients
        self.security_schemes = self.config.security_schemes
        self.server = owner_inst  # type: HTTPServer

    async def post(self):
        if not self.has_access_control:
            return
        try:
            self.set_custom_default_headers()
            # Stop the Tornado server
            origin = self.request.headers.get("Origin")
            self.logger.info(f"stopping HTTP server as per client request from {origin}, scheduling a stop message...")
            # create a task in current loop
            eventloop = get_current_async_loop()
            eventloop.create_task(self.server.async_stop())
            # dont call it in sequence, its not clear whether its designed for that
            self.set_status(204, "ok")
        except Exception as ex:
            self.logger.error(f"error while stopping HTTP server - {str(ex)}")
            self.set_status(500, f"error while stopping HTTP server - {str(ex)}")
        self.finish()


class LivenessProbeHandler(BaseHandler):
    """Liveness probe handler"""

    def initialize(
        self,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any = None,
    ) -> None:
        from . import HTTPServer  # noqa: F401
        from .config import RuntimeConfig  # noqa: F401

        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(path=self.request.path)
        self.server = owner_inst  # type: HTTPServer

    async def get(self):
        self.set_status(200, "ok")
        self.set_custom_default_headers()
        self.finish()


class ReadinessProbeHandler(BaseHandler):
    """Readiness probe handler"""

    def initialize(
        self,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any = None,
    ) -> None:
        from . import HTTPServer  # noqa: F401
        from .config import RuntimeConfig  # noqa: F401

        self.config = config  # type: RuntimeConfig
        self.logger = logger.bind(path=self.request.path)
        self.server = owner_inst  # type: HTTPServer

    async def get(self):
        self.set_custom_default_headers()
        try:
            if len(self.server._disconnected_things) > 0:
                raise RuntimeError("some things are disconnected, retry later")
            replies = await self.server.zmq_client_pool.async_execute_in_all_things(
                objekt="ping",
                operation="invokeaction",
            )
            if not all(reply.body[0].deserialize() is None for thing_id, reply in replies.items()):
                self.set_status(500, "not all things are ready")
            else:
                self.set_status(200, "ok")
                # self.write({id: "ready" for id in replies.keys()})
        except Exception as ex:
            self.logger.error(f"error while checking readiness - {str(ex)}")
            self.set_status(500, f"error while checking readiness - {str(ex)}")
        self.finish()


class ThingDescriptionHandler(BaseHandler):
    """Thing Description handler"""

    def initialize(
        self,
        resource: InteractionAffordance | PropertyAffordance,
        config: Any,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any = None,
        metadata: Any = None,
    ) -> None:
        super().initialize(
            resource=resource,
            config=config,
            logger=logger,
            metadata=metadata,
        )
        self.thing_description = self.config.thing_description_service(
            resource=resource,
            config=config,
            logger=logger,
            server=owner_inst,
        )

    async def get(self):
        if not self.has_access_control:
            self.finish()
            return

        try:
            self.set_custom_default_headers()
            _, _, _, body = self.get_execution_parameters()
            body = body.deserialize() or dict()
            if not isinstance(body, dict):
                raise ValueError("request body must be or convertable to JSON when supplied as path parameters")

            ignore_errors = body.get("ignore_errors", False)
            skip_names = body.get("skip_names", [])
            authority = body.get("authority", None)
            use_localhost = body.get("use_localhost", False)

            TD = await self.thing_description.generate(
                ignore_errors=ignore_errors,
                skip_names=skip_names,
                use_localhost=use_localhost,
                authority=authority,
            )

            self.set_status(200, "ok")
            self.set_header("Content-Type", "application/json")
            self.write(TD)
        except Exception as ex:
            self.set_status(500, str(ex).replace("\n", " "))
        self.finish()
