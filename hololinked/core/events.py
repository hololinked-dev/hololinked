"""Concrete definition of an Event."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, overload

from pydantic import BaseModel

from hololinked import SchemaValidators
from hololinked.config import global_config
from hololinked.constants import JSON
from hololinked.core.interfaces.metadata import EventMetadata


if TYPE_CHECKING:
    from hololinked.core.meta import ThingMeta
    from hololinked.core.thing import Thing
    from hololinked.core.zmq.brokers import EventPublisher


class Event:
    """
    Asynchronously push arbitrary messages to clients without the client requesting the data every time.

    Asynchronous as-in messages that cannot be properly timed, not necessary `async`. Events are pushed from the server
    to the clients that have subscribed to them.
    """

    __slots__ = [
        "name",
        "_internal_name",
        "_publisher",
        "_observable",
        "doc",
        "schema",
        "label",
        "owner",
    ]

    def __init__(
        self,
        doc: str | None = None,
        schema: JSON | type[BaseModel] | None = None,
        label: str | None = None,
    ) -> None:
        """
        Initialize an event.

        Parameters
        ----------
        doc: str
            docstring for the event
        schema: JSON | type[BaseModel]
            schema of the event data, either a JSON schema or a pydantic model. Any other kind of schema is
            accepted as well, as long as a validator that matches it is registered with `SchemaValidators`.
        label: str
            a descriptive label for the event, to be shown in a GUI for example.
        """
        self.doc = doc
        if global_config.VALIDATE_SCHEMAS and schema:
            SchemaValidators.check_schema(schema)
        self.schema = schema
        self.label = label
        self._observable = False

    def __set_name__(self, owner: ThingMeta, name: str) -> None:
        self.name = name
        self.owner = owner

    @overload
    def __get__(self, obj: None, objtype: ThingMeta | None = None) -> "Event": ...

    @overload
    def __get__(self, obj: Thing, objtype: ThingMeta | None = None) -> "EventDispatcher": ...

    def __get__(self, obj: Thing | None, objtype: ThingMeta | None = None):
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

    def to_metadata(self, owner_inst: Thing | None = None, format: str = "wot") -> EventMetadata:
        """
        Generates a `EventAffordance` TD fragment for this Event.

        Parameters
        ----------
        owner_inst: Thing, optional
            The instance of the owning `Thing` object. If not supplied, the class is used.

        Returns
        -------
        EventAffordance
            the affordance TD fragment for this event
        """
        from hololinked.ddl import MetadataFormats

        return MetadataFormats.get(format).event.from_descriptor(self, owner_inst or self.owner)


class EventDispatcher:
    """
    The worker that pushes an event.

    The separation is necessary between `Event` and `EventDispatcher` to allow class level definitions of the `Event`
    """

    __slots__ = ["_unique_identifier", "_publisher", "_owner_inst", "_descriptor"]

    def __init__(
        self,
        unique_identifier: str,
        publisher: EventPublisher | None,
        owner_inst: Thing,
        descriptor: Event,
    ) -> None:
        self._unique_identifier = unique_identifier
        self._owner_inst = owner_inst
        self._descriptor = descriptor
        self.publisher = publisher

    @property
    def publisher(self) -> EventPublisher:
        """Event publishing PUB socket owning object."""
        return self._publisher  # ty: ignore[invalid-return-type]

    @publisher.setter
    def publisher(self, value: EventPublisher | None) -> None:
        # TODO fix this once the architecture is resolved
        from .zmq.brokers import EventPublisher  # noqa: E402

        if not hasattr(self, "_publisher"):
            self._publisher = value
        elif not isinstance(value, EventPublisher):
            raise AttributeError("Publisher must be of type EventPublisher. Given type: " + str(type(value)))
        if self._publisher is not None:
            self._publisher.register(self)

    def push(self, data: Any) -> None:
        """
        Publish the event.

        Multipart payloads are not supported. Supply either a serializable object or a
        bytes object for binary data, not both.

        Parameters
        ----------
        data: Any
            payload of the event
        """
        self.publisher.publish(self, data=data)

    def receive_acknowledgement(self, timeout: float | int | None) -> bool:
        """
        Receive acknowledgement for an event that was just pushed.

        Not Implemented.

        Parameters
        ----------
        timeout: float | int | None
            timeout for receiving the acknowledgement, in seconds. If None, wait indefinitely.

        Returns
        -------
        bool
            True if acknowledgement is received, False if timeout is reached.
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        return self._synchronize_event.wait(timeout=timeout)

    def _set_acknowledgement(self, *args, **kwargs) -> None:
        """
        Once an acknowledgement is received from the client, this function is called to set the event.

        Not Implemented.
        """
        raise NotImplementedError("Event acknowledgement is not implemented yet.")
        self._synchronize_event.set()


__all__ = [
    Event.__name__,
]
