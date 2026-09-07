"""Entry points to run and stop protocol servers, knowing no protocol in particular."""

from __future__ import annotations

import threading
import warnings

from collections.abc import Sequence

from hololinked.core.eventloop import EventLoop
from hololinked.core.interfaces import BaseProtocolServer
from hololinked.core.utils import CrossLoopEvent
from hololinked.injection import ProtocolServers
from hololinked.utils import (
    cancel_pending_tasks_in_current_loop,
    forkable,
    get_current_async_loop,
    uuid_hex,
)


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
        identifier given to the servers that need one for routing, currently only ZMQ
    access_points: list[tuple[str, str | int | dict | list[str]]]
        one tuple per protocol - `"HTTP"`, `"ZMQ"` or `"MQTT"` by default - paired with its parameters. The
        parameters may be the port, the broker hostname, the ZMQ access points, or a dict of keyword arguments
        for that server. Each protocol normalizes its own, see `BaseProtocolServer.from_params()`.

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
    if access_points is not None and not isinstance(access_points, list):
        raise TypeError("access_points must be provided as a list of tuples.")

    servers = []
    for protocol, params in access_points:
        server = ProtocolServers.for_protocol(protocol)
        if server is None:
            warnings.warn(f"Unsupported protocol: {protocol}", category=UserWarning)
            continue
        servers.append(server.from_params(id, params))

    return servers


def _print_welcome_message(servers: Sequence[BaseProtocolServer]) -> None:
    """Prints a welcome message to the console/log."""
    lines = ["", "=" * 60, "🚀 Server Started!", "=" * 60]
    for server in servers:
        lines.extend(server.welcome_lines())
    lines += ["", "=" * 60, ""]
    print("\n".join(lines))
