import logging

import structlog

from ..core import Action, Event, Property, Thing
from ..core.properties import ClassSelector, Integer, TypedList
from ..param import Parameterized
from ..td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ..utils import forkable
from .thing import BrokerThing, consume_broker_pubsub, consume_broker_queue, thing_repository


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

    things = TypedList(default=None, allow_None=True, item_type=Thing)  # type: list[Thing] | None
    """List of things to be served"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        if self.things is None:
            self.things = []
        self._disconnected_things = []  # type: list[BrokerThing]
        self.zmq_client_pool = None

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        raise NotImplementedError("Not implemented for this protocol")

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to the list of things to serve."""
        for thing in things:
            self.add_thing(thing)

    def add_property(self, property: PropertyAffordance | Property) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, action: ActionAffordance | Action) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, event: EventAffordance | Event) -> None:
        raise NotImplementedError("Not implemented for this protocol")

    async def _instantiate_broker(
        self,
        server_id: str,
        thing_id: str,
        access_point: str = "INPROC",
    ) -> BrokerThing:
        try:
            broker_thing = BrokerThing(server_id=server_id, id=thing_id, access_point=access_point)
            self._disconnected_things.append(broker_thing)

            client, TD = await consume_broker_queue(
                id=self._IP,
                server_id=server_id,
                thing_id=thing_id,
                access_point=access_point,
            )

            event_consumer = consume_broker_pubsub(
                id=self._IP,
                access_point=f"{client.socket_address}/event-publisher",
            )

            self._disconnected_things.remove(broker_thing)

            broker_thing.set_req_rep_client(client)
            broker_thing.set_event_consumer(event_consumer)
            broker_thing.TD = TD

            thing_repository[thing_id] = broker_thing
            if self.zmq_client_pool:
                self.zmq_client_pool.register(client, thing_id)
                broker_thing.req_rep_client = self.zmq_client_pool

            return broker_thing
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
    def run(self, forked: bool = False) -> None:
        from . import run

        run(self)

    def stop(self):
        raise NotImplementedError("Not implemented for this protocol")
