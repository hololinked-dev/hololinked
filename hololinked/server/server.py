"""Base class for protocol servers, along with the entry points to run and stop them."""

from __future__ import annotations

import asyncio
import logging
import threading
import warnings

from collections.abc import Sequence
from io import StringIO
from types import SimpleNamespace  # noqa: F401
from typing import Any

import structlog

from hololinked.utils import (
    cancel_pending_tasks_in_current_loop,
    forkable,
    get_current_async_loop,
    uuid_hex,
)

from ..config import global_config
from ..core import Thing
from ..core.properties import ClassSelector, Integer, TypedList
from ..core.zmq.rpc_server import ZMQ_TRANSPORTS, RPCServer
from ..param import Parameterized
from ..param.parameters import String
from .repository import (
    BrokerThing,
    consume_broker_pubsub,
    consume_broker_queue,
)


class BaseProtocolServer(Parameterized):
    """
    Base class for protocol specific servers.

    Protocol implementations follow a layered approach where each protocol server is split into their
    message handlers (controllers), services (important logic), and repository (for example, `Thing` repository allows
    execution of operations over the `Thing` class). This class (& its children) represent the protocol server itself
    and is responsible for starting and stopping the protocol, deciding which `Thing`s to serve etc.
    """

    id = String(default=None, allow_None=True)
    """Unique identifier for the server"""

    port = Integer(default=9000, bounds=(1, 65535))
    """The protocol port"""

    logger = ClassSelector(
        class_=(logging.Logger, structlog.stdlib.BoundLoggerBase),
        default=None,
        allow_None=True,
    )  # type: logging.Logger | structlog.stdlib.BoundLogger
    """Logger instance"""

    things = TypedList(default=None, allow_None=True, item_type=Thing)  # type: list[Thing] | None
    """List of things to be served"""

    def __init__(self, **kwargs) -> None:
        self.zmq_client_pool = None
        self.config: Any = None
        super().__init__(**kwargs)
        if self.things is None:
            self.things = []
        self._disconnected_things = []  # type: list[BrokerThing]

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        raise NotImplementedError("Not implemented for this protocol")

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to the list of things to serve."""
        for thing in things:
            self.add_thing(thing)

    def add_property(self, *args, **kwargs) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, *args, **kwargs) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, *args, **kwargs) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    async def _instantiate_broker(
        self,
        server_id: str,
        thing_id: str,
        access_point: str = "INPROC",
    ) -> None:
        try:
            broker_thing = BrokerThing(server_id=server_id, id=thing_id, access_point=access_point)

            self._disconnected_things.append(broker_thing)

            client, TD = await consume_broker_queue(
                id=f"{self.id}|client|{thing_id}",
                server_id=server_id,
                thing_id=thing_id,
                access_point=access_point,
            )

            event_consumer = consume_broker_pubsub(
                id=f"{self.id}|event-consumer|{thing_id}",
                access_point=f"{client.socket_address}/event-publisher",
            )

            self._disconnected_things.remove(broker_thing)

            broker_thing.set_req_rep_client(client)
            broker_thing.set_event_consumer(event_consumer)
            broker_thing.TD = TD
            broker_thing.logger = structlog.get_logger().bind(
                layer="repository",
                impl=broker_thing.__class__.__name__,
                thing_id=thing_id,
            )

            if self.zmq_client_pool:
                self.zmq_client_pool.register(client, thing_id)
                broker_thing.req_rep_client = self.zmq_client_pool

            self.config.thing_repository[thing_id] = broker_thing

        except ConnectionError:
            self.logger.warning(
                f"could not connect to {thing_id} on server {server_id} with access_point {access_point}"
            )
        except Exception as ex:
            self.logger.error(f"could not connect to {thing_id} on server {server_id} with access_point {access_point}")
            self.logger.exception(ex)

    async def setup(self) -> None:
        # This method should not block, just create side-effects
        raise NotImplementedError("Not implemented for this protocol")

    async def start(self) -> None:
        # This method should not block, just create side-effects
        # await self.setup()  # call setup() here, this is only an example
        raise NotImplementedError("Not implemented for this protocol")

    @forkable
    def run(self, forked: bool = False, print_welcome_message: bool = True) -> None:
        """
        Run the server and serve your things.

        Parameters
        ----------
        forked: bool, default False
            whether to run in a forked thread
        print_welcome_message: bool, default True
            whether to print a welcome message on startup, like the ports and access points
        """
        from . import run

        run(self, print_welcome_message=print_welcome_message)

    def stop(self):
        raise NotImplementedError("Not implemented for this protocol")


@forkable
def run(*servers: BaseProtocolServer, forked: bool = False, print_welcome_message: bool = True) -> None:
    """
    Run servers and serve your things.

    Parameters
    ----------
    servers: BaseProtocolServer
        one or more server instances to run
    forked: bool, default False
        whether to run in a forked thread
    print_welcome_message: bool, default True
        whether to print a welcome message on startup, like the ports and access points
    """
    from . import ZMQServer

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

    shutdown_event = asyncio.Event()
    run.shutdown_event = shutdown_event

    async def shutdown():
        shutdown_event = run.shutdown_event
        await shutdown_event.wait()

    loop = get_current_async_loop()
    for server in servers:
        if server == rpc_server:
            continue
        loop.create_task(server.start())

    if print_welcome_message:
        _print_welcome_message(servers)

    loop.run_until_complete(shutdown())
    rpc_server.stop()
    cancel_pending_tasks_in_current_loop()


def stop():
    """Shutdown all running servers started with run()."""
    if hasattr(run, "shutdown_event"):
        run.shutdown_event.set()
        return
    warnings.warn(
        "No running servers found to shutdown or possibly no shutdown event available (cannot stop)",
        category=UserWarning,
    )


def parse_params(id: str, access_points: list[tuple[str, str | int | dict | list[str]]]) -> list[BaseProtocolServer]:
    """
    Create one protocol server per requested access point.

    Parameters
    ----------
    id: str
        identifier given to the ZMQ server, when one is created
    access_points: list[tuple[str, str | int | dict | list[str]]]
        one tuple per protocol - `"HTTP"`, `"ZMQ"` or `"MQTT"` - paired with its parameters. The parameters may
        be the port, the broker hostname, the ZMQ access points, or a dict of keyword arguments for that server.

    Returns
    -------
    list[BaseProtocolServer]
        the created servers, in the order their access points were given

    Raises
    ------
    TypeError
        if `access_points` is not a list
    ValueError
        if the parameters given for a protocol are not of a supported type
    """
    from .http import HTTPServer
    from .mqtt import MQTTPublisher
    from .zmq import ZMQServer

    if access_points is not None and not isinstance(access_points, list):
        raise TypeError("access_points must be provided as a list of tuples.")

    servers = []

    for protocol, params in access_points:
        protocol_params: dict[str, Any] = {}
        if protocol.upper() == "HTTP":
            if isinstance(params, int):
                protocol_params = dict(port=params)
            elif isinstance(params, dict):
                protocol_params = params
            else:
                raise ValueError("HTTP server parameters must be supplied as a dict or just the port as an integer.")
            http_server = HTTPServer(**protocol_params)
            servers.append(http_server)
        elif protocol.upper() == "ZMQ":
            if isinstance(params, int):
                protocol_params = dict(access_points=[f"tcp://*:{params}"])
            elif isinstance(params, (str, ZMQ_TRANSPORTS)):
                protocol_params = dict(access_points=[params])
            elif isinstance(params, list):
                protocol_params = dict(access_points=params)
            else:
                protocol_params = dict(params)
            zmq_access_points = protocol_params.get("access_points", None)
            if not isinstance(zmq_access_points, list):
                zmq_access_points = [protocol_params["access_points"]]
            else:
                zmq_access_points = list(zmq_access_points)
            if not any(isinstance(ap, str) and ap.upper().startswith("INPROC") for ap in zmq_access_points):
                zmq_access_points.append("INPROC")
            protocol_params["access_points"] = zmq_access_points

            if len(zmq_access_points) == 1 and zmq_access_points[0] == "INPROC":
                server = RPCServer(id=id, **protocol_params)
            else:
                server = ZMQServer(id=id, **protocol_params)
            servers.append(server)
        elif protocol.upper() == "MQTT":
            if isinstance(params, str):
                protocol_params = dict(hostname=params)
            elif isinstance(params, dict):
                protocol_params = params
            else:
                raise ValueError("MQTT parameters must be supplied as a dictionary or the broker hostname as a string.")
            mqtt_publisher = MQTTPublisher(**protocol_params)
            servers.append(mqtt_publisher)
        else:
            warnings.warn(f"Unsupported protocol: {protocol}", category=UserWarning)

    return servers


def _print_welcome_message(servers: Sequence[BaseProtocolServer]) -> None:
    """Prints a welcome message to the console/log."""
    from . import HTTPServer, MQTTPublisher

    buffer = StringIO()
    buffer.write("\n" + "=" * 60 + "\n")
    buffer.write("🚀 Server Started!\n")
    buffer.write("=" * 60 + "\n")
    for server in servers:
        if isinstance(server, HTTPServer):
            buffer.write("\n📡 HTTP:\n")
            for thing in server.things:
                td_path = "/resources/wot-td?ignore_errors=true"
                buffer.write(f"   ➜ Local:   {server.router.get_basepath(use_localhost=True)}/{thing.id}{td_path}\n")
                buffer.write(f"   ➜ Network: {server.router.get_basepath()}/{thing.id}{td_path}\n")
        elif isinstance(server, MQTTPublisher):
            buffer.write("\n📡 MQTT:\n")
            buffer.write(f" • Broker:   {server.hostname}:{server.port}\n")
            for thing in server.things:
                buffer.write(f"   ➜ Topic tree: {thing.id}/thing-description\n")
    buffer.write("\n" + "=" * 60 + "\n")
    print(buffer.getvalue())
