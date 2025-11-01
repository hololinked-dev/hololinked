import uuid
import threading
import asyncio

from ..config import global_config
from ..utils import get_current_async_loop
from ..core.zmq.rpc_server import RPCServer
from .server import BaseProtocolServer, BrokerThing
from .zmq import ZMQServer


def run(*servers: BaseProtocolServer) -> None:
    """run servers and serve your things"""
    loop = get_current_async_loop()  # initialize an event loop if it does not exist

    things = [thing for server in servers if server.things is not None for thing in server.things]
    things = list(set(things))  # remove duplicates

    zmq_servers = [server for server in servers if isinstance(server, (ZMQServer, RPCServer))]
    if len(zmq_servers) > 1:
        raise ValueError(
            "Only one ZMQServer or RPCServer instance to be run at a time, "
            + "please add all your things to one instance"
        )

    rpc_server = None
    if not any(isinstance(server, (RPCServer, ZMQServer)) for server in servers):
        rpc_server = RPCServer(
            id=f"rpc-broker-{uuid.uuid4().hex[:8]}",
            things=things,
            context=global_config.zmq_context(),
            logger=global_config.logger(),
        )
    else:
        rpc_server = zmq_servers[0]

    threading.Thread(target=rpc_server.run).start()

    futures = []
    for server in servers:
        if server == rpc_server:
            continue
        server_specific_things = server.things
        server.things = []
        for thing in server_specific_things:
            server.things.append(
                BrokerThing(
                    server_id=rpc_server.id,
                    thing_id=thing.id,
                    access_point="INPROC",
                )
            )
        futures.append(server.async_run())

    loop.run_until_complete(asyncio.gather(*futures))
