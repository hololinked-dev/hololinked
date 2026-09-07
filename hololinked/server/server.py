"""Entry points to run and stop protocol servers."""

from __future__ import annotations

import threading
import warnings

from collections.abc import Sequence
from io import StringIO
from types import SimpleNamespace  # noqa: F401
from typing import Any

from hololinked.utils import (
    cancel_pending_tasks_in_current_loop,
    forkable,
    get_current_async_loop,
    uuid_hex,
)

from ..constants import ZMQ_TRANSPORTS
from ..core.eventloop import EventLoop
from ..core.interfaces import BaseProtocolServer
from ..core.utils import CrossLoopEvent


_runs = dict()  # type: dict[str, CrossLoopEvent]
"""Every run() currently serving, by id, so that stop() can name the one it means."""
_runs_lock = threading.Lock()
"""Guards `_runs` - a forked run() registers on its own thread while another may be stopping."""


@forkable
def run(
    *servers: BaseProtocolServer,
    forked: bool = False,
    print_welcome_message: bool = True,
    id: str | None = None,
) -> None:
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
    id: str, optional
        name this run, so that a `stop()` can be called `stop(id)`.

    Raises
    ------
    RuntimeError
        if a server cannot start - each protocol decides what it needs
    ValueError
        if the run ID is reused by another active run
    """
    loop = get_current_async_loop()  # initialize an event loop if it does not exist

    things = [thing for server in servers if server.things is not None for thing in server.things.values()]
    things = list(set(things))  # remove duplicates

    eventloops = list(dict.fromkeys(thing.eventloop for thing in things if thing.eventloop is not None))
    unbound = [thing for thing in things if thing.eventloop is None]
    if unbound or not eventloops:
        eventloops.append(EventLoop(things=unbound))

    for eventloop in eventloops:
        threading.Thread(target=eventloop.run, daemon=True).start()

    shutdown_event = CrossLoopEvent()
    run_id = id or f"run-{uuid_hex()}"
    with _runs_lock:
        if run_id in _runs:
            raise ValueError(f"a run with id {run_id!r} is already serving, give this one another id")
        _runs[run_id] = shutdown_event

    async def shutdown():
        await shutdown_event.wait()

    try:
        loop = get_current_async_loop()
        for server in servers:
            loop.create_task(server.start())

        if print_welcome_message:
            _print_welcome_message(servers)

        loop.run_until_complete(shutdown())
    finally:
        with _runs_lock:
            _runs.pop(run_id, None)
        for server in servers:
            try:
                server.stop()
            except Exception as ex:
                warnings.warn(f"could not stop {server} while shutting down - {ex!s}", category=UserWarning)
        for eventloop in eventloops:
            eventloop.stop()
        cancel_pending_tasks_in_current_loop()


def stop(id: str | None = None) -> None:
    """
    Shutdown the servers started by `run()`.

    Parameters
    ----------
    id: str, optional
        the id given to `run()`. Omit if unspecified.

    Raises
    ------
    ValueError
        if no id is given while more than one run is serving
    """
    with _runs_lock:
        if id is None:
            if len(_runs) > 1:
                raise ValueError(f"{len(_runs)} runs are serving - say which one to stop, one of {sorted(_runs)}")
            if not _runs:
                warnings.warn(
                    "No running servers found to shutdown or possibly no shutdown event available (cannot stop)",
                    category=UserWarning,
                )
                return
            id = next(iter(_runs))
        shutdown_event = _runs.pop(id, None)
        if shutdown_event is None:
            warnings.warn(f"no run with id {id!r} is serving (cannot stop)", category=UserWarning)
            return
    shutdown_event.set()


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
