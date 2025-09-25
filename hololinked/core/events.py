import typing
import jsonschema

from ..param.parameterized import Parameterized, ParameterizedMetaclass
from ..constants import JSON
from ..config import global_config


class Event:
    """
    Asynchronously push arbitrary messages to clients. Apart from default events created by the package (like state
    change event, observable properties etc.), events are supposed to be created at class level or at `__init__`
    as a instance attribute, otherwise their publishing socket is unbound and will lead to `AttributeError`.
    """

    # security: Any
    #     security necessary to access this event.

    __slots__ = ["name", "_internal_name", "_publisher", "_observable", "doc", "schema", "security", "label", "owner"]

    def __init__(
        self,
        doc: typing.Optional[str] = None,
        schema: typing.Optional[JSON] = None,
        label: typing.Optional[str] = None,
    ) -> None:
        """
        Parameters
        ----------
        doc: str
            docstring for the event
        schema: JSON
            schema of the event, if the event is JSON complaint. HTTP clients can validate the data with this schema. There
            is no validation on server side.
        label: str
            a descriptive label for the event, to be shown in a GUI for example.
        """

        self.doc = doc
        if global_config.VALIDATE_SCHEMAS and schema:
            jsonschema.Draft7Validator.check_schema(schema)
        self.schema = schema
        # self.security = security
        self.label = label
        self._observable = False

    def __set_name__(self, owner: ParameterizedMetaclass, name: str) -> None:
        self.name = name
        self.owner = owner

    @typing.overload
    def __get__(self, obj, objtype) -> "EventDispatcher": ...

    def __get__(self, obj: Parameterized, objtype: ParameterizedMetaclass = None):
        try:
            if not obj:
                return self
            # uncomment for type hinting
            # from .thing import Thing
            # assert isinstance(obj, Thing)
            return EventDispatcher(
                unique_identifier=f"{obj._qualified_id}/{self.name}",
                publisher=obj.rpc_server.event_publisher if obj.rpc_server else None,
                owner_inst=obj,
                descriptor=self,
            )
        except KeyError:
            raise AttributeError(
                "Event object not yet initialized, please dont access now." + " Access after Thing is running."
            )

    def to_affordance(self, owner_inst=None):
        """
        Generates a `EventAffordance` TD fragment for this Event

        Parameters
        ----------
        owner_inst: Thing, optional
            The instance of the owning `Thing` object. If not supplied, the class is used.

        Returns
        -------
        EventAffordance
            the affordance TD fragment for this event
        """
        from ..td import EventAffordance

        return EventAffordance.generate(self, owner_inst or self.owner)


class EventDispatcher:
    """
    The worker that pushes an event. The separation is necessary between `Event` and
    `EventDispatcher` to allow class level definitions of the `Event`
    """

    __slots__ = ["_unique_identifier", "_publisher", "_owner_inst", "_descriptor"]

    def __init__(
        self, unique_identifier: str, publisher: "EventPublisher", owner_inst: ParameterizedMetaclass, descriptor: Event
    ) -> None:
        self._unique_identifier = unique_identifier
        self._owner_inst = owner_inst
        self._descriptor = descriptor
        self.publisher = publisher

    @property
    def publisher(self) -> "EventPublisher":
        """Event publishing PUB socket owning object"""
        return self._publisher

    @publisher.setter
    def publisher(self, value: "EventPublisher") -> None:
        if not hasattr(self, "_publisher"):
            self._publisher = value
        elif not isinstance(value, EventPublisher):
            raise AttributeError("Publisher must be of type EventPublisher. Given type: " + str(type(value)))
        if self._publisher is not None:
            self._publisher.register(self)

    def push(self, data: typing.Any) -> None:
        """
        publish the event.

        Parameters
        ----------
        data: Any
            payload of the event
        """
        self.publisher.publish(self, data=data)

    def receive_acknowledgement(self, timeout: typing.Union[float, int, None]) -> bool:
        """
        Unimplemented.

        Receive acknowledgement for an event that was just pushed.
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        return self._synchronize_event.wait(timeout=timeout)

    def _set_acknowledgement(self, *args, **kwargs) -> None:
        """
        Method to be called by RPC server when an acknowledgement is received. Not for user to be set.
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        self._synchronize_event.set()


from .zmq.brokers import EventPublisher  # noqa: E402

__all__ = [
    Event.__name__,
]
