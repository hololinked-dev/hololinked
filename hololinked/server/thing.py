from typing import Any, Optional

import structlog
import zmq.asyncio

from pydantic import BaseModel, model_validator

from ..config import global_config
from ..core import Thing
from ..core.zmq.brokers import (
    AsyncEventConsumer,
    AsyncZMQClient,
    EventConsumer,
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
from ..td.interaction_affordance import EventAffordance, PropertyAffordance
from ..utils import uuid_hex


class BrokerThing(BaseModel):
    """Abstraction of a Thing over internal message broker"""

    id: str
    server_id: str
    access_point: str

    TD: dict[str, Any] | None = None

    req_rep_client: AsyncZMQClient | MessageMappedZMQClientPool | None = None
    event_client: EventConsumer | None = None

    req_rep_socket_address: str = ""
    pub_sub_socket_address: str = ""

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
        if self.req_rep_client is None:
            raise RuntimeError("Not connected to broker")
        return self.req_rep_client.async_execute(
            thing_id=self.id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    def consume_broker_pubsub_per_event(self, resource: EventAffordance | PropertyAffordance) -> AsyncEventConsumer:
        return AsyncEventConsumer(
            id=f"{resource.name}|EventTunnel|{uuid_hex()}",
            event_unique_identifier=f"{resource.thing_id}/{resource.name}",
            access_point=self.pub_sub_socket_address or self.access_point,
            context=global_config.zmq_context(),
        )


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
    id : str
        Unique identifier for the client.
    server_id : str
        The server ID to connect to.
    thing_id : str
        The Thing ID whose Thing Description (TD) is to be fetched.
    access_point : str
        The access point (e.g., "TCP", "WS", or a specific address).
    context : Optional[zmq.asyncio.Context], optional
        ZMQ context to use for the connection. If None, uses the global context.
    logger : Optional[structlog.stdlib.BoundLogger], optional
        Logger instance for logging events. If None, no logging is performed.
    poll_timeout : int, optional
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


def consume_broker_pubsub(id: str = None, access_point: str = "INPROC") -> AsyncEventConsumer:
    """Consume all events from ZMQ (usually INPROC) pubsub"""
    return AsyncEventConsumer(
        id=id or f"event-proxy-{uuid_hex()}",
        event_unique_identifier="",
        access_point=access_point,
        context=global_config.zmq_context(),
    )
