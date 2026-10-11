"""Concrete definition of an Event."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, overload

from pydantic import BaseModel

from hololinked import SchemaValidators
from hololinked.config import global_config
from hololinked.constants import JSON
from hololinked.core.interfaces.metadata import EventMetadata


if TYPE_CHECKING:
    from hololinked.core.eventloop import EventBus
    from hololinked.core.meta import ThingMeta
    from hololinked.core.thing import Thing


class Event:
    """
    Asynchronously push arbitrary messages to clients without the client requesting the data every time.

    Asynchronous as-in messages that cannot be properly timed, not necessary `async`. Events are pushed from the server
    to the clients that have subscribed to them.
    """

    __slots__ = [
        "_internal_name",
        "_observable",
        "_publisher",
        "doc",
        "label",
        "name",
        "owner",
        "schema",
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
    def __get__(self, obj: None, objtype: ThingMeta | None = None) -> Event: ...

    @overload
    def __get__(self, obj: Thing, objtype: ThingMeta | None = None) -> EventDispatcher: ...

    def __get__(self, obj: Thing | None, objtype: ThingMeta | None = None):
        try:
            if not obj:
                return self
            return EventDispatcher(
                unique_identifier=self.get_unique_identifier(obj),
                publisher=obj.eventloop.event_bus if obj.eventloop else None,
                owner_inst=obj,
                descriptor=self,
            )
        except KeyError:
            raise AttributeError(
                "Event object not yet initialized, please dont access now." + " Access after Thing is running."
            )

    def get_unique_identifier(self, owner_inst: Thing) -> str:
        """
        An instance bound unique identifier string of the event.

        Parameters
        ----------
        owner_inst: Thing
            the instance whose copy of this event is meant

        Returns
        -------
        str
            the identifier, as `<thing id>/<event name>`
        """
        return f"{owner_inst._qualified_id}/{self.name}"

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
        from hololinked import MetadataFormats

        return MetadataFormats.get(format).event.from_descriptor(self, owner_inst or self.owner)


class EventDispatcher:
    """
    The worker that pushes an event.

    The separation is necessary between `Event` and `EventDispatcher` to allow class level definitions of the `Event`
    """

    __slots__ = ["_descriptor", "_owner_inst", "_publisher", "unique_identifier"]

    def __init__(
        self,
        unique_identifier: str,
        publisher: EventBus | None,
        owner_inst: Thing,
        descriptor: Event,
    ) -> None:
        self.unique_identifier = unique_identifier
        self._owner_inst = owner_inst
        self._descriptor = descriptor
        self.publisher = publisher

    @property
    def publisher(self) -> EventBus:
        """The `EventBus` this event is registered with, through which it reaches every protocol."""
        return self._publisher  # ty: ignore[invalid-return-type]

    @publisher.setter
    def publisher(self, value: EventBus | None) -> None:
        from hololinked.core.eventloop import EventBus

        if not hasattr(self, "_publisher"):
            self._publisher = value
        elif not isinstance(value, EventBus):
            raise AttributeError("Publisher must be of type EventBus. Given type: " + str(type(value)))

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
        self.publisher.publish(self.unique_identifier, data)

    def receive_acknowledgement(self, timeout: float | None) -> bool:
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


class EventDelegate:
    """
    Pushes an event of a `Thing` for another object, such as a driver serving a Thing Model.

    Set on that object so it can push the event without holding the `Thing`. The `Thing` is set once it exists;
    pushes are dropped until then and while it is not served, since there is no publisher and no subscriber yet.
    """

    __slots__ = ("name", "thing")

    thing: Thing | None
    """the `Thing` owning the event, None until it is created"""

    def __init__(self, name: str, thing: Thing | None = None) -> None:
        """
        Initialize the delegate.

        Parameters
        ----------
        name: str
            name of the event on the `Thing`
        thing: Thing, optional
            the `Thing` owning the event, set later if it does not exist yet
        """
        self.name = name
        self.thing = thing

    def push(self, data: Any) -> None:
        """
        Publish the event, or drop it while the `Thing` is not served.

        Parameters
        ----------
        data: Any
            payload of the event
        """
        if self.thing is None:
            return
        dispatcher = getattr(self.thing, self.name)  # type: EventDispatcher
        if dispatcher.publisher is not None:
            dispatcher.push(data)

    def __repr__(self) -> str:
        owner = type(self.thing).__name__ if self.thing is not None else "no Thing"
        return f"<EventDelegate({owner}.{self.name})>"


__all__ = [
    Event.__name__,
    EventDelegate.__name__,
]
