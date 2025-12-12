import logging

import structlog

from ..core import Action, Event, Property, Thing
from ..core.properties import ClassSelector, Integer, TypedDict, TypedList
from ..param import Parameterized
from ..td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ..utils import forkable
from .thing import BrokerThing


class BaseProtocolServer(Parameterized):
    """Base class for protocol specific servers"""

    port = Integer(default=9000, bounds=(1, 65535))
    """The protocol port"""

    logger = ClassSelector(
        class_=(logging.Logger, structlog.stdlib.BoundLoggerBase),
        default=None,
        allow_None=True,
    )  # type: logging.Logger | structlog.stdlib.BoundLogger
    """Logger instance"""

    things = TypedDict(default=None, allow_None=True, item_type=BrokerThing, key_type=str)  # type: dict[str, BrokerThing]
    """List of things to be served through broker connections"""

    _things = TypedList(default=None, allow_None=True, item_type=Thing)  # type: list[Thing] | None
    """Internal list of things"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if self.things is None:
            self.things = {}
            self._things = []

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        # Post additional to the server, just when the the servers are started, an RPC server must be available.
        # The following code needs to be implemented:
        # if not thing.rpc_server:
        #     raise ValueError("Thing must have an RPC server to be added to the protocol server")
        # self.things[thing.id] = BrokerThing(
        #     server_id=thing.rpc_server.id,
        #     thing_id=thing.id,
        #     access_point=thing.rpc_server.access_point,
        # )
        self._things.append(thing)

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to the list of things to serve."""
        for thing in things:
            self.add_thing(thing)

    def add_thing_instance_through_broker(self, server_id: str, access_point: str, thing_id: str):
        """internal method, exposes a thing via the broker"""
        if self._broker_things is None:
            self._broker_things = []
        self._broker_things.append(BrokerThing(server_id=server_id, thing_id=thing_id, access_point=access_point))

    def add_property(self, property: PropertyAffordance | Property) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, action: ActionAffordance | Action) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, event: EventAffordance | Event) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    async def setup(self) -> None:
        # This method should not block, just create side-effects
        raise NotImplementedError("Not implemented for this protocol")

    async def start(self) -> None:
        # This method should not block, just create side-effects
        # await self.setup()  # call setup() here, this is only an example
        raise NotImplementedError("Not implemented for this protocol")

    @forkable
    def run(self, forked: bool = False) -> None:
        from . import run

        run(self)

    def stop(self):
        raise NotImplementedError("Not implemented for this protocol")
