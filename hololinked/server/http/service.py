from ...core.zmq.message import (
    PreserializedEmptyByte,
    ResponseMessage,
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)
from ...serializers.payloads import PreserializedData, SerializableData
from ...td import (  # noqa: F401
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)


class Thing:
    def __init__(
        self,
        resource,
        owner_inst,
    ) -> None:
        from . import HTTPServer  # noqa: F401

        self.resource = resource  # type: InteractionAffordance
        self.server = owner_inst  # type: HTTPServer
        self.thing = self.server._broker_things[self.resource.thing_id]
        self.logger = self.server.logger.bind(
            resource=self.resource.name,
            what=self.resource.what,
            thing_id=self.resource.thing_id,
            layer="service",
        )

    async def execute(
        self,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> ResponseMessage:
        return await self.thing.execute(
            objekt=self.resource.name,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def schedule(
        self,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> str:
        return await self.thing.schedule(
            objekt=self.resource.name,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def oneway(
        self,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> None:
        await self.thing.schedule(
            objekt=self.resource.name,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def recv_response(
        self,
        message_id: str,
        timeout: int = 10000,
    ) -> ResponseMessage:
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        return await self.req_rep_client.async_recv_response(
            thing_id=self.id,
            message_id=message_id,
            timeout=timeout,
        )
