from typing import Any, Optional
import uuid
import zmq.asyncio
import logging

from ..config import global_config
from ..constants import Operations
from ..core import Thing, Action
from ..core.zmq import AsyncZMQClient, AsyncEventConsumer
from ..td.interaction_affordance import EventAffordance


async def consume_broker_queue(
    id: str,
    server_id: str,
    thing_id: str,
    access_point: str,
    context: Optional[zmq.asyncio.Context] = None,
    logger: Optional[logging.Logger] = None,
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
    logger : Optional[logging.Logger], optional
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
    assert isinstance(Thing.get_thing_model, Action)  # type definition
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


def consume_broker_pubsub_per_event(resource: EventAffordance) -> AsyncEventConsumer:
    if isinstance(resource, EventAffordance):
        form = resource.retrieve_form(Operations.subscribeevent)
    else:
        form = resource.retrieve_form(Operations.observeproperty)
    return AsyncEventConsumer(
        id=f"{resource.name}|EventTunnel|{uuid.uuid4().hex[:8]}",
        event_unique_identifier=f"{resource.thing_id}/{resource.name}",
        access_point=form.href,
        context=global_config.zmq_context(),
        logger=global_config.logger(),
    )
