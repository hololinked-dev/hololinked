import asyncio
import functools

from typing import Any, Optional

import msgspec

from aiocoap import Message
from aiocoap.numbers import Code, ContentFormat
from aiocoap.numbers import types as mtypes
from aiocoap.resource import Resource
from structlog.stdlib import BoundLogger

from hololinked.config import global_config
from hololinked.core.zmq.message import (
    PreserializedData,
    SerializableData,
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)
from hololinked.serializers import Serializers
from hololinked.server.coap.utils import (
    CoAPCodeToContentTypeStr,
    ContentTypeStrToCoAPCode,
)
from hololinked.td import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from hololinked.utils import format_exception_as_json


class LocalExecutionContext(msgspec.Struct):
    noblock: Optional[bool] = None
    messageID: Optional[str] = None
    presend_ack: Optional[bool] = None


method_not_allowed_message = Message(
    code=Code.METHOD_NOT_ALLOWED,
    content_format=ContentFormat.TEXT,
    mtype=mtypes.ACK,
)


def handle_render_exceptions(func):
    """Decorator to handle exceptions in render methods and return appropriate error messages"""

    @functools.wraps(func)
    async def wrapper(self, request: Message) -> Message:
        try:
            return await func(self, request)
        except Exception as ex:
            if hasattr(self, "logger") and self.logger:
                self.logger.error(f"error in {func.__name__} - {str(ex)}")
            return Message(
                code=Code.INTERNAL_SERVER_ERROR,
                payload=Serializers.json.dumps({"exception": format_exception_as_json(ex)}),
                content_format=ContentFormat.JSON,
                mtype=mtypes.ACK,
            )

    return wrapper


class RPCResource(Resource):
    """
    Base class for properties and action resources.
    The path of the resource is determined by the `name` field of the affordance.
    """

    def __init__(
        self,
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance,
        config: Any,
        logger: BoundLogger,
        metadata: Any,
    ) -> None:
        from .config import ResourceMetadata, RuntimeConfig  # noqa: F401

        super().__init__()
        self.resource = resource
        self.config = config  # type: RuntimeConfig
        self.logger = logger
        self.thing = None  # we need to postpone evaluation as CoAP resource needs to be passed in an initialized
        self.metadata = metadata  # type: ResourceMetadata
        # cache to store the execution parameters for each request to avoid parsing them multiple times
        # self._request_parameters_cache = dict()

    render_get_operation = None
    render_post_operation = None
    render_put_operation = None
    render_delete_operation = None

    @handle_render_exceptions
    async def render_get(self, request: Message) -> Message:
        message_id = self.message_id(request)
        if message_id is not None:
            return await self.handle_no_block_response(message_id=message_id)
        if request.code.name not in self.metadata.coap_methods or not self.render_get_operation:
            return method_not_allowed_message
        return await self.execute_operation(request, operation=self.render_get_operation)

    @handle_render_exceptions
    async def render_post(self, request: Message) -> Message:
        if request.code.name not in self.metadata.coap_methods or not self.render_post_operation:
            return method_not_allowed_message
        return await self.execute_operation(request, operation=self.render_post_operation)

    @handle_render_exceptions
    async def render_put(self, request: Message) -> Message:
        if request.code.name not in self.metadata.coap_methods or not self.render_put_operation:
            return method_not_allowed_message
        return await self.execute_operation(request, operation=self.render_put_operation)

    @handle_render_exceptions
    async def render_delete(self, request: Message) -> Message:
        if request.code.name not in self.metadata.coap_methods or not self.render_delete_operation:
            return method_not_allowed_message
        return await self.execute_operation(request, operation=self.render_delete_operation)

    def get_execution_parameters(
        self,
        request: Message,
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
        coap://127.0.0.1:8080/property/temperature?oneway=true&invokationTimeout=5&value=42
        ```

        server execution context would have `oneway` set to true & `invokationTimeout` set to 5 seconds,
        local execution context would be empty as no such arguments were passed,
        and additional payload would have `{"value": 42}` as its value.

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
        # Note that the message ID is an ID per message, not an ID per full-cycle of request and response (which is called token).
        # We will cache with the MID for now.
        # if self._request_parameters_cache.get(request.mid, None):
        #     return self._request_parameters_cache[request.mid]
        arguments = dict()
        if len(request.opt.uri_query) == 0:
            return (
                default_server_execution_context,
                default_thing_execution_context,
                LocalExecutionContext(),
                SerializableNone,
            )

        for query in request.opt.uri_query:
            key, value = query.split("=", 1)
            try:
                arguments[key] = Serializers.json.loads(value)
            except Exception:
                if isinstance(value, str):
                    arguments[key] = value
                elif isinstance(value, bytes):
                    arguments[key] = value.decode()
                else:
                    raise ValueError(
                        f"query parameter value {value} is not a valid JSON or string,"
                        + " only JSON or plain string is supported for query parameters"
                    )
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
            presend_ack=arguments.pop("presend_ack", False),
        )
        additional_payload = SerializableNone if not arguments else SerializableData(arguments)  # application/json
        # self._request_parameters_cache[request.mid] = (
        #     server_execution_context,
        #     thing_execution_context,
        #     local_execution_context,
        #     additional_payload,
        # )
        return server_execution_context, thing_execution_context, local_execution_context, additional_payload

    def get_request_payload(self, request: Message) -> tuple[SerializableData, PreserializedData]:
        payload = SerializableData(value=None)
        preserialized_payload = PreserializedData(value=b"")
        if request.payload:
            if (
                CoAPCodeToContentTypeStr.supports(request.opt.content_format)
                and CoAPCodeToContentTypeStr.get(request.opt.content_format) in Serializers.allowed_content_types
            ):
                payload.value = request.payload
                payload.content_type = CoAPCodeToContentTypeStr.get(request.opt.content_format)
            elif global_config.ALLOW_UNKNOWN_SERIALIZATION:
                preserialized_payload.value = request.payload
                preserialized_payload.content_type = request.opt.content_format
            else:
                raise ValueError("Content-Type not supported")
                # NOTE that was assume that the content type is JSON even if unspecified in the header.
                # This error will be raised only when a specified content type is not supported.
        return payload, preserialized_payload

    async def execute_operation(self, request: Message, operation: str):
        """Handle the request through the associated `Thing` and return the response"""
        from ..repository import BrokerThing  # noqa: F401

        try:
            server_execution_context, thing_execution_context, local_execution_context, additional_payload = (
                self.get_execution_parameters(request=request)
            )
            payload, preserialized_payload = self.get_request_payload(request)
            payload = payload if payload.value else additional_payload
        except Exception as ex:
            return Message(
                code=Code.BAD_REQUEST,
                payload=f"error while decoding request - {str(ex)}".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.RST,
            )
        try:
            if not self.thing:
                if self.config.thing_repository.get(self.resource.thing_id) is None:
                    return Message(
                        code=Code.SERVICE_UNAVAILABLE,
                        payload=f"thing with id {self.resource.thing_id} not found".encode(),
                        content_format=ContentFormat.TEXT,
                        mtype=mtypes.ACK,
                    )
                self.thing = self.config.thing_repository[self.resource.thing_id]  # type: BrokerThing
            if server_execution_context.oneway:
                await self.thing.oneway(
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                return Message(
                    code=Code.CREATED,
                    content_format=ContentFormat.TEXT,
                    mtype=mtypes.ACK,
                )
            elif local_execution_context.noblock:
                message_id = await self.thing.schedule(
                    objekt=self.resource.name,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                return Message(
                    code=Code.CREATED,
                    payload=message_id.encode(),
                    content_format=ContentFormat.TEXT,
                    mtype=mtypes.ACK,
                )
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
                if not response_payload.value:
                    return Message(
                        code=Code.CREATED,
                        mtype=mtypes.ACK,
                        content_format=ContentFormat.TEXT,
                    )
                if not ContentTypeStrToCoAPCode.supports(response_payload.content_type):
                    return Message(
                        code=Code.UNSUPPORTED_CONTENT_FORMAT,
                        payload=f"Content-Type {response_payload.content_type} not supported by CoAP server".encode(),
                        content_format=ContentFormat.TEXT,
                        mtype=mtypes.ACK,
                    )
                return Message(
                    code=Code.CONTENT,
                    payload=response_payload.value,
                    mtype=mtypes.ACK,
                    content_format=ContentTypeStrToCoAPCode.get(response_payload.content_type),
                )
        except ConnectionAbortedError as ex:
            self.logger.error(f"lost connection to thing - {str(ex)}")
            return Message(
                code=Code.SERVICE_UNAVAILABLE,
                payload=f"lost connection to thing - {str(ex)}".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        except Exception as ex:
            self.logger.error(f"error while scheduling RPC call - {str(ex)}")
            return Message(
                code=Code.INTERNAL_SERVER_ERROR,
                payload=Serializers.json.dumps({"exception": format_exception_as_json(ex)}),
                content_format=ContentFormat.JSON,
                mtype=mtypes.ACK,
            )

    def message_id(self, request: Message) -> str | None:
        """retrieves the message id from the request headers"""
        _, _, local_execution_context, _ = self.get_execution_parameters(request)
        # TODO avoid calling get_execution_parameters twice in the same request
        return local_execution_context.messageID

    async def handle_no_block_response(self, message_id: str) -> Message:
        """handles the no-block response for the noblock calls"""
        try:
            self.logger.info("waiting for no-block response", message_id=message_id)
            response_message = await self.thing.recv_response(
                message_id=message_id,
                timeout=default_server_execution_context.invokationTimeout
                + default_server_execution_context.executionTimeout,
            )
            response_payload = self.thing.get_response_payload(response_message)
            if not response_payload.value:
                return Message(
                    code=Code.CHANGED,
                    mtype=mtypes.ACK,
                    content_format=ContentFormat.TEXT,
                )
            if not ContentTypeStrToCoAPCode.supports(response_payload.content_type):
                return Message(
                    code=Code.UNSUPPORTED_CONTENT_FORMAT,
                    payload=f"Content-Type {response_payload.content_type} not supported by CoAP server".encode(),
                    content_format=ContentFormat.TEXT,
                    mtype=mtypes.ACK,
                )
            return Message(
                code=Code.CONTENT,
                payload=response_payload.value,
                mtype=mtypes.ACK,
                content_format=ContentTypeStrToCoAPCode.get(response_payload.content_type),
            )
        except KeyError as ex:
            # if the message id is not found, it means that the response was not received in time
            self.logger.error(f"message ID not found for no-block response - {str(ex)}")
            return Message(
                code=Code.NOT_FOUND,
                payload=f"message ID {message_id} not found".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        except TimeoutError as ex:
            self.logger.error(f"timeout while waiting for no-block response - {str(ex)}")
            return Message(
                code=Code.NOT_FOUND,
                payload="timeout while waiting for response, ask later".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        except Exception as ex:
            self.logger.error(f"error while receiving no-block response - {str(ex)}")
            return Message(
                code=Code.INTERNAL_SERVER_ERROR,
                payload=Serializers.json.dumps({"exception": format_exception_as_json(ex)}),
                content_format=ContentFormat.JSON,
                mtype=mtypes.ACK,
            )


class PropertyResource(RPCResource):
    """Resource class for property interactions"""

    render_get_operation = "readproperty"
    render_post_operation = "writeproperty"
    render_put_operation = "writeproperty"
    render_delete_operation = "deleteproperty"  # not standard WoT


class ActionResource(RPCResource):
    """Resource class for action interactions"""

    render_get_operation = "invokeaction"
    render_post_operation = "invokeaction"
    render_put_operation = "invokeaction"
    render_delete_operation = "invokeaction"


class RWMultiplePropertiesResource(RPCResource):
    """Resource class for read/write multiple properties interactions"""

    render_get_operation = "read_multiple_properties"
    render_post_operation = "write_multiple_properties"
    render_put_operation = "write_multiple_properties"
    render_delete_operation = None

    def __init__(
        self,
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance,
        config: Any,
        logger: BoundLogger,
        metadata: Any,
        read_properties_resource,
        write_properties_resource,
    ) -> None:
        super().__init__(resource, config, logger, metadata)
        self.read_properties_resource = read_properties_resource
        self.write_properties_resource = write_properties_resource
        self.lock = asyncio.Lock()  # to prevent concurrent read/write multiple properties interactions

    @handle_render_exceptions
    async def render_get(self, request: Message):
        try:
            server_execution_context, _, _, _ = self.get_execution_parameters(request=request)
            await asyncio.wait_for(self.lock.acquire(), timeout=server_execution_context.invokationTimeout)
            self.resource = self.read_properties_resource
            return await super().render_get(request)
        except asyncio.TimeoutError:
            return Message(
                code=Code.SERVICE_UNAVAILABLE,
                payload="resource is busy, try again later".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        finally:
            self.lock.release()

    @handle_render_exceptions
    async def render_post(self, request: Message):
        try:
            server_execution_context, _, _, _ = self.get_execution_parameters(request=request)
            await asyncio.wait_for(self.lock.acquire(), timeout=server_execution_context.invokationTimeout)
            self.resource = self.write_properties_resource
            return await super().render_post(request)
        except asyncio.TimeoutError:
            return Message(
                code=Code.SERVICE_UNAVAILABLE,
                payload="resource is busy, try again in a few seconds".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        finally:
            self.lock.release()

    @handle_render_exceptions
    async def render_put(self, request: Message):
        try:
            server_execution_context, _, _, _ = self.get_execution_parameters(request=request)
            await asyncio.wait_for(self.lock.acquire(), timeout=server_execution_context.invokationTimeout)
            self.resource = self.write_properties_resource
            return await super().render_put(request)
        except asyncio.TimeoutError:
            return Message(
                code=Code.SERVICE_UNAVAILABLE,
                payload="resource is busy, try again in a few seconds".encode(),
                content_format=ContentFormat.TEXT,
                mtype=mtypes.ACK,
            )
        finally:
            self.lock.release()


class ThingDescriptionResource(RPCResource):
    """Resource class for thing description interactions"""

    def __init__(
        self,
        resource: InteractionAffordance | PropertyAffordance | ActionAffordance | EventAffordance,
        config: Any,
        logger: BoundLogger,
        metadata: Any,
        owner_inst=None,
    ) -> None:
        super().__init__(
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

    @handle_render_exceptions
    async def render_get(self, request: Message):
        _, _, _, body = self.get_execution_parameters(request=request)
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

        return Message(
            code=Code.CONTENT,
            payload=Serializers.json.dumps(TD),
            content_format=ContentFormat.JSON,
            mtype=mtypes.ACK,
        )


class LivenessProbeResource:
    """Resource class for liveness probe interactions"""

    @handle_render_exceptions
    async def render_get(self, request: Message):
        return Message(
            code=Code.CONTENT,
            payload=b"alive",
            content_format=ContentFormat.TEXT,
            mtype=mtypes.ACK,
        )


class ReadinessProbeResource:
    """Resource class for readiness probe interactions"""

    def __init__(self, server):
        self.server = server
        super().__init__()

    @handle_render_exceptions
    async def render_get(self, request: Message):
        return Message(
            code=Code.CREATED,
            content_format=ContentFormat.TEXT,
            mtype=mtypes.ACK,
        )


class StopResource(RPCResource):
    """Resource class for stopping server interactions"""

    def __init__(self, server):
        self.server = server
        super().__init__()

    @handle_render_exceptions
    async def render_post(self, request: Message):
        self.server.stop()  # creates a task in the running loop
        return Message(
            code=Code.CREATED,
            payload=b"shutting down, use liveness probe to check when shutdown is complete",
            content_format=ContentFormat.TEXT,
            mtype=mtypes.ACK,
        )
