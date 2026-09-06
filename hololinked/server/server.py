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
)

from ..constants import ZMQ_TRANSPORTS
from ..core import Thing
from ..core.eventloop import EventLoop
from ..core.properties import ClassSelector, Integer, TypedDict
from ..core.utils import get_all_sub_things_recusively
from ..param import Parameterized
from ..param.parameters import String


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

    things = TypedDict(default=None, allow_None=True, key_type=str, item_type=Thing)  # type: dict[str, Thing]
    """Every served `Thing`, sub-things included."""

    def __init__(self, **kwargs) -> None:
        self.config: Any = None
        super().__init__(**kwargs)
        if self.things is None:
            self.things = dict()

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the things being served, along with its sub-things."""
        for instance in get_all_sub_things_recusively(thing):
            self.things[instance.id] = instance

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to be served."""
        for thing in things:
            self.add_thing(thing)

    def add_property(self, *args, **kwargs) -> None:
        """
        Add a property to be served, the arguments being specific to the protocol.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, *args, **kwargs) -> None:
        """
        Add an action to be served, the arguments being specific to the protocol.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, *args, **kwargs) -> None:
        """
        Add an event to be served, the arguments being specific to the protocol.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    async def setup(self) -> None:
        # This method should not block, just create side-effects
        """
        Prepare the protocol before it starts serving, creating side effects only without blocking.

        Raises
        ------
        NotImplementedError
            if the protocol does not implement a setup step
        """
        raise NotImplementedError("Not implemented for this protocol")

    async def start(self) -> None:
        # This method should not block, just create side-effects
        # await self.setup()  # call setup() here, this is only an example
        """
        Start serving the protocol, creating side effects only without blocking.

        Raises
        ------
        NotImplementedError
            if the protocol cannot be started this way
        """
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
        """
        Stop serving the protocol.

        Raises
        ------
        NotImplementedError
            if the protocol does not implement a stop step
        """
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

    Raises
    ------
    RuntimeError
        if a server cannot start - each protocol decides what it needs
    """
    loop = get_current_async_loop()  # initialize an event loop if it does not exist

    things = [thing for server in servers if server.things is not None for thing in server.things.values()]
    things = list(set(things))  # remove duplicates

    # a Thing brings the event loop it is already bound to, and each distinct one gets a thread of
    # its own - no protocol runs one. Things not bound to any loop yet share a new one.
    eventloops = list(dict.fromkeys(thing.eventloop for thing in things if thing.eventloop is not None))
    unbound = [thing for thing in things if thing.eventloop is None]
    if unbound or not eventloops:
        eventloops.append(EventLoop(things=unbound))

    for eventloop in eventloops:
        threading.Thread(target=eventloop.run).start()

    shutdown_event = asyncio.Event()
    run.shutdown_event = shutdown_event

    async def shutdown():
        shutdown_event = run.shutdown_event
        await shutdown_event.wait()

    loop = get_current_async_loop()
    for server in servers:
        loop.create_task(server.start())

    if print_welcome_message:
        _print_welcome_message(servers)

    loop.run_until_complete(shutdown())
    for eventloop in eventloops:
        eventloop.stop()
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
            protocol_params["access_points"] = zmq_access_points

            servers.append(ZMQServer(id=id, **protocol_params))
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
            for thing in server.things.values():
                td_path = "/resources/wot-td?ignore_errors=true"
                buffer.write(f"   ➜ Local:   {server.router.get_basepath(use_localhost=True)}/{thing.id}{td_path}\n")
                buffer.write(f"   ➜ Network: {server.router.get_basepath()}/{thing.id}{td_path}\n")
        elif isinstance(server, MQTTPublisher):
            buffer.write("\n📡 MQTT:\n")
            buffer.write(f" • Broker:   {server.hostname}:{server.port}\n")
            for thing in server.things.values():
                buffer.write(f"   ➜ Topic tree: {thing.id}/thing-description\n")
    buffer.write("\n" + "=" * 60 + "\n")
    print(buffer.getvalue())
