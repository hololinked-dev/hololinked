from typing import Any, Optional

import structlog
import zmq.asyncio

from pydantic import BaseModel, ConfigDict, model_validator

from ..config import global_config
from ..core import Thing
from ..core.zmq.brokers import (
    AsyncEventConsumer,
    AsyncZMQClient,
    MessageMappedZMQClientPool,
    PreserializedData,
    PreserializedEmptyByte,
    ResponseMessage,
    SerializableData,
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)
from ..core.zmq.message import EMPTY_BYTE
from ..td.interaction_affordance import EventAffordance, PropertyAffordance
from ..utils import uuid_hex


class BrokerThing(BaseModel):
    """Repository Layer of a Thing over the internal message broker"""

    id: str
    """Thing ID"""
    server_id: str
    """ZMQ Server ID"""
    access_point: str
    """ZMQ Access Point"""

    TD: dict[str, Any] | None = None
    """ZMQ Thing Description"""

    req_rep_client: MessageMappedZMQClientPool | None = None
    """req-rep queue client"""
    event_client: AsyncEventConsumer | None = None
    """pub-sub queue client"""
    req_rep_socket_address: str = ""
    """req-rep socket address"""
    pub_sub_socket_address: str = ""
    """pub-sub socket address"""
    logger: structlog.stdlib.BoundLogger | None = None
    """Logger instance"""

    @model_validator(mode="before")
    def validate_access_point(cls, values):
        """Validates the access point format before setting."""
        access_point = values.get("access_point")
        if access_point is not None and access_point.upper() not in ["TCP", "IPC", "INPROC"]:
            raise ValueError("Access point must be 'TCP', 'IPC', or 'INPROC'")
        return values

    async def execute(
        self,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> ResponseMessage:
        """
        Executes a request-response operation on a `Thing`.

        Parameters
        ----------
        objekt: str
            The target object of the operation - name of property or action.
        operation: str
            The operation to perform (e.g., "readproperty", "writeproperty", "invokeaction")
        payload: SerializableData, optional
            The payload to send with the request
        preserialized_payload: PreserializedData, optional
            The preserialized payload to send with the request
        server_execution_context: ServerExecutionContext, optional
            The server execution context
        thing_execution_context: ThingExecutionContext, optional
            The thing execution context
        """
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        return await self.req_rep_client.async_execute(
            thing_id=self.id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def schedule(
        self,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> str:
        """
        Schedules a request-response operation on a `Thing` and returns a message ID.

        Parameters
        ----------
        objekt: str
            The target object of the operation - name of property or action.
        operation: str
            The operation to perform (e.g., "readproperty", "writeproperty", "invokeaction")
        payload: SerializableData, optional
            The payload to send with the request
        preserialized_payload: PreserializedData, optional
            The preserialized payload to send with the request
        server_execution_context: ServerExecutionContext, optional
            The server execution context
        thing_execution_context: ThingExecutionContext, optional
            The thing execution context

        Returns
        -------
        str
            The message ID of the scheduled request
        """
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        return await self.req_rep_client.async_send_request(
            thing_id=self.id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def oneway(
        self,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> None:
        """
        Sends a oneway request(no-response) operation on a `Thing`.

        Parameters
        ----------
        objekt: str
            The target object of the operation - name of property or action.
        operation: str
            The operation to perform (e.g., "readproperty", "writeproperty", "invokeaction")
        payload: SerializableData, optional
            The payload to send with the request
        preserialized_payload: PreserializedData, optional
            The preserialized payload to send with the request
        server_execution_context: ServerExecutionContext, optional
            The server execution context
        thing_execution_context: ThingExecutionContext, optional
            The thing execution context
        """
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        await self.req_rep_client.async_send_request(
            thing_id=self.id,
            objekt=objekt,
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
        """
        Receives a response for a previously scheduled request.

        Parameters
        ----------
        message_id: str
            The message ID of the scheduled request
        timeout: int, optional
            The timeout in milliseconds to wait for the response (default is 10000)

        Returns
        -------
        ResponseMessage
            The response message received
        """
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        return await self.req_rep_client.async_recv_response(
            thing_id=self.id,
            message_id=message_id,
            timeout=timeout,
        )

    def subscribe_event(self, resource: EventAffordance | PropertyAffordance) -> AsyncEventConsumer:
        """
        Subscribe to events from a `Thing` through the internal pub-sub broker.

        Parameters
        ----------
        resource: EventAffordance | PropertyAffordance
            The event or observable property to subscribe to

        Returns
        -------
        AsyncEventConsumer
            The event consumer for the subscribed events
        """
        event_consumer = AsyncEventConsumer(
            id=f"{resource.name}|EventTunnel|{uuid_hex()}",
            event_unique_identifier=f"{resource.thing_id}/{resource.name}",
            access_point=self.pub_sub_socket_address,
            context=global_config.zmq_context(),
        )
        event_consumer.subscribe()
        return event_consumer

    def set_req_rep_client(self, client: AsyncZMQClient | MessageMappedZMQClientPool) -> None:
        """Sets the req-rep client for this broker thing."""
        self.req_rep_client = client
        self.req_rep_socket_address = client.socket_address

    def set_event_consumer(self, client: AsyncEventConsumer) -> None:
        """Sets the pub-sub client for this broker thing."""
        self.event_client = client
        self.pub_sub_socket_address = client.socket_address

    def get_response_payload(self, zmq_response: ResponseMessage) -> PreserializedData | SerializableData:
        """
        Retrieves the payload from the ZMQ response message, does not necessarily deserialize it.
        Use this method to extract the payload from a response message.
        Multipart responses are not supported yet for protocol controllers (except ZMQ), so only one payload is returned.

        Parameters
        ----------
        zmq_response: ResponseMessage
            The ZMQ response message to extract the payload from

        Returns
        -------
        PreserializedData | SerializableData
            The extracted payload, either preserialized or serialized
        """
        # print("zmq_response - ", zmq_response)
        if zmq_response is None:
            raise RuntimeError("No last response available. Did you make an operation?")
        if zmq_response.preserialized_payload.value != EMPTY_BYTE:
            if zmq_response.payload.value != b"null":
                # our None return value comes like this, sufficient to check against that
                self.logger.warning(
                    "Multiple content types in response payload (multipart payloads) are currently not supported,"
                    + " only the preserialized payload will be written to the wire",
                    content_type=zmq_response.payload.content_type,
                    binary_value=zmq_response.payload.value,
                )
            # multiple content types are not supported yet, so we return only one payload
            return zmq_response.preserialized_payload
            # return payload, preserialized_payload
        return zmq_response.payload  # dont deseriablize, there is no need, just pass it on to the client

    model_config = ConfigDict(arbitrary_types_allowed=True)


thing_repository = dict()  # type: dict[str, BrokerThing]


async def consume_broker_queue(
    id: str,
    server_id: str,
    thing_id: str,
    access_point: str,
    context: Optional[zmq.asyncio.Context] = None,
    logger: Optional[structlog.stdlib.BoundLogger] = None,
    poll_timeout: int = 1000,
) -> tuple[AsyncZMQClient, dict[str, Any]]:
    """
    Connect to a running Thing via ZMQ INPROC and fetch its Thing Description.

    Parameters
    ----------
    id: str
        Unique identifier for the client.
    server_id: str
        The server ID to connect to.
    thing_id: str
        The Thing ID whose Thing Description (TD) is to be fetched.
    access_point: str
        The access point (e.g., "TCP", "WS", or a specific address).
    context: Optional[zmq.asyncio.Context], optional
        ZMQ context to use for the connection. If None, uses the global context.
    logger: Optional[structlog.stdlib.BoundLogger], optional
        Logger instance for logging events. If None, no logging is performed.
    poll_timeout: int, optional
        Poll timeout in milliseconds (default is 1000).

    Returns
    -------
    tuple[AsyncZMQClient, dict[str, Any]]
        A tuple containing the connected AsyncZMQClient and the fetched Thing Description as a dictionary.
    """
    from ..client.zmq.consumed_interactions import ZMQAction

    # create client
    client = AsyncZMQClient(
        id=id,
        server_id=server_id,
        access_point=access_point,
        context=context or global_config.zmq_context(),
        handshake=False,
        logger=logger,
        poll_timeout=poll_timeout,
    )
    # connect client
    client.handshake(10000)
    await client.handshake_complete(10000)

    # fetch ZMQ INPROC TD
    Thing.get_thing_model  # type: Action
    FetchTMAffordance = Thing.get_thing_model.to_affordance()
    FetchTMAffordance.override_defaults(thing_id=thing_id, name="get_thing_description")
    fetch_td = ZMQAction(
        resource=FetchTMAffordance,
        sync_client=None,
        async_client=client,
        logger=logger,
        owner_inst=None,
    )
    if isinstance(access_point, str) and len(access_point) in [3, 6]:
        access_point = access_point.upper()
    elif access_point.lower().startswith("tcp://"):
        access_point = "TCP"
    TD = await fetch_td.async_call(ignore_errors=True, protocol=access_point)  # type: dict[str, Any]
    return client, TD


def consume_broker_pubsub(id: str, access_point: str) -> AsyncEventConsumer:
    """
    Consume all events from the broker's pub-sub queue.

    Parameters
    ----------
    id: str
        Unique identifier for the event consumer
    access_point: str
        The qualified ZMQ address (`tcp://`, `ipc://`, `inproc://`) of the pub-sub broker
    """
    return AsyncEventConsumer(
        id=id or f"EventTunnel|{uuid_hex()}",
        event_unique_identifier="",
        access_point=access_point,
        context=global_config.zmq_context(),
    )
