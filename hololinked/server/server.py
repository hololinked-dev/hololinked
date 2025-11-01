import logging
from pydantic import BaseModel, model_validator

from ..utils import get_current_async_loop
from ..config import global_config
from ..param import Parameterized
from ..core.properties import ClassSelector, Integer, TypedList
from ..core import Thing, Property, Action, Event
from ..td.interaction_affordance import PropertyAffordance, ActionAffordance, EventAffordance


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

    port = Integer(default=9000)
    """The protocol port"""

    logger = ClassSelector(class_=logging.Logger, default=global_config.logger())  # type: logging.Logger
    """Logger instance"""

    things = TypedList(default=None, allow_None=True, item_type=(Thing, BrokerThing))  # type: list[Thing | BrokerThing]
    """List of things to serve"""

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        self.things.append(thing)

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to the list of things to serve."""
        for thing in things:
            self.add_thing(thing)

    def add_thing_instance_through_broker(self, server_id: str, access_point: str, thing_id: str):
        """Adds a thing to the list of things to publish events from."""
        self.things.append(BrokerThing(server_id, thing_id, access_point))

    def add_property(self, property: PropertyAffordance | Property) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, action: ActionAffordance | Action) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, event: EventAffordance | Event) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def start(self):
        raise NotImplementedError("Not implemented for this protocol")

    def stop(self):
        raise NotImplementedError("Not implemented for this protocol")

    def run(self):
        loop = get_current_async_loop()
        loop.run_until_complete(self.async_run())

    async def async_run(self):
        raise NotImplementedError("Not implemented for this protocol")
