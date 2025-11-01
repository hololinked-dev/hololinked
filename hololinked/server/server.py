import logging
from ..config import global_config
from ..param import Parameterized
from ..core.properties import ClassSelector, Integer, TypedList
from ..core.thing import Thing


class BaseProtocolServer(Parameterized):
    """Base class for protocol specific servers"""

    port = Integer(default=9000)
    """The protocol port"""

    logger = ClassSelector(class_=logging.Logger, default=global_config.logger())  # type: logging.Logger
    """Logger instance"""

    things = TypedList(default=None, allow_None=True, item_type=Thing)  # type: list[Thing]
    """List of things to serve"""

    def add_thing(self, thing):
        raise NotImplementedError("Not implemented for this protocol")

    def add_thing_instance_through_broker(self, server_id: str, access_point: str, thing_id: str):
        raise NotImplementedError("Not implemented for this protocol")

    def add_property(self, thing, prop):
        raise NotImplementedError("Not implemented for this protocol")

    def add_action(self, thing, action):
        raise NotImplementedError("Not implemented for this protocol")

    def add_event(self, thing, event):
        raise NotImplementedError("Not implemented for this protocol")

    def start(self):
        raise NotImplementedError("Not implemented for this protocol")

    def stop(self):
        raise NotImplementedError("Not implemented for this protocol")

    def run(self):
        raise NotImplementedError("Not implemented for this protocol")

    async def async_run(self):
        raise NotImplementedError("Not implemented for this protocol")
