from typing import Any, Optional

import msgspec

from aiocoap import Message
from aiocoap.numbers import Code, ContentFormat
from aiocoap.numbers import types as mtypes
from aiocoap.resource import Resource
from msgspec import DecodeError as MsgspecJSONDecodeError
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
        from ..repository import BrokerThing  # noqa: F401
        from .config import HandlerMetadata, RuntimeConfig  # noqa: F401

        super().__init__()
        self.resource = resource
        self.config = config  # type: RuntimeConfig
        self.logger = logger
        self.thing = self.config.thing_repository[resource.thing_id]  # type: BrokerThing
        self.metadata = metadata  # type: HandlerMetadata

    async def render_get(self, request: Message):
        raise NotImplementedError("GET method is not implemented for this resource")

    async def render_post(self, request: Message):
        raise NotImplementedError("POST method is not implemented for this resource")

    async def render_put(self, request: Message):
        raise NotImplementedError("PUT method is not implemented for this resource")

    async def render_delete(self, request: Message):
        raise NotImplementedError("DELETE method is not implemented for this resource")

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
        http://localhost:8080/property/temperature?oneway=true&invokationTimeout=5&value=42
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
        arguments = dict()
        if len(request.opt) == 0:
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
            presend_ack=arguments.pop("presend_ack", False),
        )
        additional_payload = SerializableNone if not arguments else SerializableData(arguments)  # application/json
        return server_execution_context, thing_execution_context, local_execution_context, additional_payload

    def get_request_payload(self, request: Message) -> tuple[Any, Any]:
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

    async def execute_operation(self, request: Message, operation: str):
        """Handle the request through the associated `Thing` and return the response"""
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
                if response_payload.value:
                    return Message(
                        code=Code.CONTENT,
                        payload=response_payload.value,
                        mtype=mtypes.ACK,
                        content_format=response_payload.content_type,
                    )
                else:
                    return Message(
                        code=Code.CREATED,
                        mtype=mtypes.ACK,
                        content_format=ContentFormat.TEXT,
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
                payload={"exception": format_exception_as_json(ex)},
                content_format=ContentFormat.JSON,
                mtype=mtypes.ACK,
            )


class PropertyResource(RPCResource):
    """Resource class for property interactions"""

    method_not_allowed_message = Message(
        code=Code.METHOD_NOT_ALLOWED,
        content_format=ContentFormat.TEXT,
        mtype=mtypes.ACK,
    )

    async def render_get(self, request: Message):
        if request.code.name not in self.metadata.coap_methods:
            return self.method_not_allowed_message
        return await self.execute_operation(request, operation="readproperty")

    async def render_post(self, request: Message):
        if request.code.name not in self.metadata.coap_methods:
            return self.method_not_allowed_message
        return await self.execute_operation(request, operation="writeproperty")

    async def render_put(self, request: Message):
        if request.code.name not in self.metadata.coap_methods:
            return self.method_not_allowed_message
        return await self.execute_operation(request, operation="writeproperty")

    async def render_delete(self, request: Message):
        if request.code.name not in self.metadata.coap_methods:
            return self.method_not_allowed_message
        return await self.execute_operation(request, operation="deleteproperty")  # not standard WoT


class ActionResource(RPCResource):
    """Resource class for action interactions"""

    method_not_allowed_message = Message(
        code=Code.METHOD_NOT_ALLOWED,
        content_format=ContentFormat.TEXT,
        mtype=mtypes.ACK,
    )

    async def render_post(self, request: Message):
        if request.code.name not in self.metadata.coap_methods:
            return self.method_not_allowed_message
        return await self.execute_operation(request, operation="invokeaction")
