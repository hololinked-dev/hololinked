import asyncio
import threading
import uuid
import warnings

from ..config import global_config
from ..core.zmq.rpc_server import ZMQ_TRANSPORTS, RPCServer
from ..utils import (
    cancel_pending_tasks_in_current_loop,
    forkable,
    get_current_async_loop,
    uuid_hex,
)
from .server import BaseProtocolServer


@forkable
def run(*servers: BaseProtocolServer, forked: bool = False) -> None:
    """run servers and serve your things"""
    from .zmq import ZMQServer

    loop = get_current_async_loop()  # initialize an event loop if it does not exist

    things = [thing for server in servers if server.things is not None for thing in server.things]
    things = list(set(things))  # remove duplicates

    zmq_servers = [server for server in servers if isinstance(server, (ZMQServer, RPCServer))]
    rpc_server = None

    if len(zmq_servers) > 1:
        raise ValueError(
            "Only one ZMQServer or RPCServer instance to be run at a time, "
            + "please add all your things to one instance"
        )
    elif len(zmq_servers) == 1:
        rpc_server = zmq_servers[0]
    else:
        rpc_server = RPCServer(
            id=f"rpc-broker-{uuid_hex()}",
            things=things,
            context=global_config.zmq_context(),
        )

    threading.Thread(target=rpc_server.run).start()

    shutdown_future = asyncio.Event()
    run.shutdown_future = shutdown_future

    async def shutdown():
        shutdown_future = run.shutdown_future
        await shutdown_future.wait()

    loop = get_current_async_loop()
    for server in servers:
        if server == rpc_server:
            continue
        loop.create_task(server.start())

    loop.run_until_complete(shutdown())
    rpc_server.stop()
    cancel_pending_tasks_in_current_loop()


def stop():
    """shutdown all running servers started with run()"""
    if hasattr(run, "shutdown_future"):
        run.shutdown_future.set()
        return
    warnings.warn("No running servers found to shutdown", category=UserWarning)


def parse_params(id: str, access_points: list[tuple[str, str | int | dict | list[str]]]) -> list[BaseProtocolServer]:
    from .http import HTTPServer
    from .mqtt import MQTTPublisher
    from .zmq import ZMQServer

    if access_points is not None and not isinstance(access_points, list):
        raise TypeError("access_points must be provided as a list of tuples.")

    servers = []
    for protocol, params in access_points:
        if protocol.upper() == "HTTP":
            if isinstance(params, int):
                params = dict(port=params)
            if not isinstance(params, dict):
                raise ValueError("HTTP server parameters must be supplied as a dict or just the port as an integer.")
            http_server = HTTPServer(**params)
            servers.append(http_server)
        elif protocol.upper() == "ZMQ":
            if isinstance(params, int):
                params = dict(access_points=[f"tcp://*:{params}"])
            elif isinstance(params, (str, ZMQ_TRANSPORTS)):
                params = dict(access_points=[params])
            elif isinstance(params, list):
                params = dict(access_points=params)
            if not isinstance(params.get("access_points", None), list):
                params["access_points"] = [params["access_points"]]
            if not any(isinstance(ap, str) and ap.upper().startswith("INPROC") for ap in params["access_points"]):
                params["access_points"].append("INPROC")

            if len(params["access_points"]) == 1 and params["access_points"][0] == "INPROC":
                server = RPCServer(id=id, **params)
            else:
                server = ZMQServer(id=id, **params)
            servers.append(server)
        elif protocol.upper() == "MQTT":
            if isinstance(params, str):
                params = dict(hostname=params)
            if not isinstance(params, dict):
                raise ValueError("MQTT parameters must be supplied as a dictionary or the broker hostname as a string.")
            mqtt_publisher = MQTTPublisher(**params)
            servers.append(mqtt_publisher)
        else:
            warnings.warn(f"Unsupported protocol: {protocol}", category=UserWarning)
    return servers
