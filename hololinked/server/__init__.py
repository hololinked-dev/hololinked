import uuid
import threading

from ..config import global_config
from ..utils import get_current_async_loop
from ..core.zmq.rpc_server import RPCServer
from .server import BaseProtocolServer
from .zmq import ZMQServer


def run(*servers: BaseProtocolServer) -> None:
    """Run the server module."""
    loop = get_current_async_loop()  # initialize an event loop if it does not exist

    things = [thing for server in servers if server.things is not None for thing in server.things]

    rpc_server = None
    if not any(isinstance(server, (RPCServer, ZMQServer)) for server in servers):
        rpc_server = RPCServer(
            id=f"srpc-broker-{uuid.uuid4().hex[:8]}",
            things=things,
            context=global_config.zmq_context(),
            logger=global_config.logger(),
        )

    for server in servers:
        if isinstance(server, (RPCServer, ZMQServer)):
            rpc_server = server
        else:
            loop.create_task(server.async_run())

    threading.Thread(target=rpc_server.run).start()
    loop.run_forever()
