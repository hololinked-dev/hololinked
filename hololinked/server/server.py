import logging

import structlog

from pydantic import BaseModel, model_validator

from ..core import Action, Event, Property, Thing
from ..core.properties import ClassSelector, Integer, TypedList
from ..param import Parameterized
from ..td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ..utils import forkable


class BrokerThing(BaseModel):
    server_id: str
    thing_id: str
    access_point: str

    @model_validator(mode="before")
    def validate_access_point(cls, values):
        """Validates the access point format before setting."""
        access_point = values.get("access_point")
        if access_point is not None and access_point.upper() not in ["TCP", "IPC", "INPROC"]:
            raise ValueError("Access point must be 'TCP', 'IPC', or 'INPROC'")
        return values


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

    things = TypedList(default=None, allow_None=True, item_type=Thing)  # type: list[Thing]
    """List of things to serve"""

    _broker_things = TypedList(default=None, allow_None=True, item_type=BrokerThing)  # type: list[BrokerThing]
    """List of things to be served through broker connections"""

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        if self.things is None:
            self.things = []
            self._broker_things = []
        self.things.append(thing)

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to the list of things to serve."""
        if self.things is None:
            self.things = []
            self._broker_things = []
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
