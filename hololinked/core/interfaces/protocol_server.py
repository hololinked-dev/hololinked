"""Interface class for protocol servers that expose a `Thing` on the network."""

from __future__ import annotations

import logging

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, Self

import structlog

from hololinked.param import Parameterized
from hololinked.param.parameters import ClassSelector, Integer, String, TypeConstrainedDict
from hololinked.utils import forkable


if TYPE_CHECKING:
    from hololinked.core.thing import Thing


class BaseProtocolServer(Parameterized):
    """
    Base class for protocol specific servers.

    Subclass from here to implement a new protocol.
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

    things: MutableMapping[str, Thing]
    """Every served `Thing`, by id. Sub-things are not served."""

    def __init__(self, things: list[Thing] | dict[str, Thing] | None = None, **kwargs) -> None:
        from hololinked.core.thing import Thing

        self.config: Any = None
        self.things = TypeConstrainedDict({}, key_type=str, item_type=Thing)
        super().__init__(**kwargs)
        self.add_things(*(things.values() if isinstance(things, dict) else things or []))

    @classmethod
    def from_params(cls, id: str, params: str | int | dict | list[str] | None) -> Self:
        """
        Create a server from the parameters given for its access point.

        Each protocol accepts some shorthand arguments, such as a port for HTTP, a broker hostname for MQTT etc.,
        which this method normalizes into constructor arguments.

        Parameters
        ----------
        id: str
            identifier for the server, used by the protocols that need one for routing
        params: str | int | dict | list[str] | None
            the parameters given for this protocol, either a protocol specific shorthand or a dict of keyword
            arguments for the constructor

        Returns
        -------
        Self
            the server, with no `Thing` added to it yet

        Raises
        ------
        ValueError
            if the parameters are not of a type this protocol supports
        """
        if not isinstance(params, dict):
            raise ValueError(f"{cls.__name__} parameters must be supplied as a dict, given : {type(params)}")
        return cls(**params)

    def add_thing(self, thing: Thing) -> None:
        """
        Adds a thing to the things being served.

        Sub-things are not served - see `EventLoop.add_thing`, which does not register them
        either.
        """
        self.things[thing.id] = thing

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to be served."""
        for thing in things:
            self.add_thing(thing)

    def add_property(self, *args, **kwargs) -> None:
        """
        Add a property to be served.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, *args, **kwargs) -> None:
        """
        Add an action to be served.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, *args, **kwargs) -> None:
        """
        Add an event to be served.

        Raises
        ------
        NotImplementedError
            if the protocol does not support this operation
        """
        raise NotImplementedError("Not implemented for this protocol")

    async def setup(self) -> None:
        """
        Prepare the protocol before it starts serving, creating side effects only without blocking.

        Raises
        ------
        NotImplementedError
            if the protocol does not implement a setup step
        """
        # This method should not block, just create side-effects
        raise NotImplementedError("Not implemented for this protocol")

    async def start(self) -> None:
        """
        Start serving the protocol, creating side effects only without blocking.

        Raises
        ------
        NotImplementedError
            if the protocol cannot be started this way
        """
        # This method should not block, just create side-effects
        # await self.setup()  # usually one should call setup() here
        raise NotImplementedError("Not implemented for this protocol")

    def welcome_lines(self) -> list[str]:
        """
        Lines announcing where this protocol can be reached (string), printed when a run starts.

        Returns
        -------
        list[str]
            the lines to print, without trailing newlines
        """
        return []

    @forkable
    def run(self, forked: bool = False, print_welcome_message: bool = True) -> None:
        """
        Run the server and serve your things.

        Use this method if this is the only running protocol. Blocks.

        Parameters
        ----------
        forked: bool, default False
            whether to run in a forked thread
        print_welcome_message: bool, default True
            whether to print a welcome message on startup, like the ports and access points
        """
        from hololinked.server import run

        run(self, print_welcome_message=print_welcome_message)

    def stop(self):
        """
        Stop serving the protocol.

        Stops this protocol only, the Thing still keeps running. To stop completely:

        ```python
        from hololinked.server import stop
        stop()
        ```

        Raises
        ------
        NotImplementedError
            if the protocol does not implement a stop step
        """
        raise NotImplementedError("Not implemented for this protocol")
