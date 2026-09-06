"""An in-process pubsub to forward events to protocols."""

from __future__ import annotations

import asyncio
import threading
import warnings

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from hololinked import Serializers


if TYPE_CHECKING:
    from hololinked.core.events import Event
    from hololinked.core.thing import Thing


class RegisteredEvent(NamedTuple):
    """A registered event, consisting of its descriptor, owner, and unique identifier."""

    descriptor: Event
    """the class level descriptor the event was declared as."""
    owner: Thing
    """the instance that pushes it."""
    unique_identifier: str
    """what the two of them are known by outside the `Thing`, as `<thing id>/<event name>`."""


class EventBus:
    """Registry of the events `Thing`s can push, and fan-out to whoever is listening."""

    def __init__(self) -> None:
        self._events = dict()  # type: dict[str, RegisteredEvent]
        self._subscribers = dict()  # type: dict[str, list[Callable[[Any], None]]]
        self._lock = threading.Lock()

    @property
    def event_ids(self) -> set[str]:
        """Unique identifiers of every registered event."""
        return set(self._events)

    def event_for(self, event_id: str) -> RegisteredEvent:
        """
        The event registered under an identifier.

        A subscriber that needs the event itself - to encode its payloads, say - asks for it once,
        when it subscribes, instead of being handed it with every push.

        Parameters
        ----------
        event_id: str
            unique identifier of the event, as `<thing id>/<event name>`

        Returns
        -------
        RegisteredEvent
            the descriptor and the owner registered under that identifier

        Raises
        ------
        KeyError
            if no such event is registered with this bus
        """
        with self._lock:
            if event_id not in self._events:
                raise KeyError(f"event {event_id} is not registered, nothing would ever be delivered")
            return self._events[event_id]

    def register(self, event: Event, owner: Thing) -> None:
        """
        Register an event specific to `Thing` instance.

        Parameters
        ----------
        event: Event
            the descriptor the event was declared as
        owner: Thing
            the instance that pushes the event
        """
        unique_identifier = event.get_unique_identifier(owner)
        with self._lock:
            self._events[unique_identifier] = RegisteredEvent(event, owner, unique_identifier)

    def unregister(self, event: Event, owner: Thing) -> None:
        """
        Unregister an event specific to a `Thing` instance, so that publishing it raises.

        Parameters
        ----------
        event: Event
            the descriptor the event was declared as
        owner: Thing
            the instance that will push the event
        """
        unique_identifier = event.get_unique_identifier(owner)
        with self._lock:
            if self._events.pop(unique_identifier, None) is None:
                warnings.warn(
                    f"event {unique_identifier} not found, did you mean to unregister another event?",
                    UserWarning,
                    stacklevel=2,
                )

    def subscribe(self, callback: Callable[[Any], None], event_id: str) -> None:
        """
        Subscribe to an event with a callback that will be invoked whenever the event is published.

        Parameters
        ----------
        callback: Callable[[Any], None]
            called synchronously, on whichever thread pushed the event - which is a `Thing`'s own
            thread, not the subscriber's. A subscriber that owns loop-bound state (a protocol
            server's connections, say) must hop to its loop itself, with `call_soon_threadsafe`.
        event_id: str
            unique identifier of the event to listen for, as `<thing id>/<event name>`
        """
        with self._lock:
            callbacks = self._subscribers.setdefault(event_id, [])
            if callback not in callbacks:
                callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[Any], None], event_id: str) -> None:
        """
        Unsubscribe from an event.

        Parameters
        ----------
        callback: Callable[[Any], None]
            a callback previously given to `subscribe()`. Unknown callbacks are ignored.
        event_id: str
            the event it was subscribed to. Unknown events are ignored.
        """
        with self._lock:
            callbacks = self._subscribers.get(event_id, None)
            if callbacks is None or callback not in callbacks:
                return
            callbacks.remove(callback)
            if not callbacks:
                del self._subscribers[event_id]  # a long-lived bus must not keep a bucket per past listener

    def publish(self, event_id: str, data: Any) -> None:
        """
        Hand one event's payload to its own subscribers, in subscription order.

        The lock is held for the whole fan-out, which is what serializes concurrent pushes from
        different `Thing` threads onto each subscriber's wire.

        Parameters
        ----------
        event_id: str
            unique identifier of the event being pushed, as `<thing id>/<event name>`
        data: Any
            its payload, unencoded

        Raises
        ------
        AttributeError
            if the event is not registered with this bus
        """
        with self._lock:
            if event_id not in self._events:
                raise AttributeError(f"event name {event_id} not registered")
            for callback in self._subscribers.get(event_id, ()):
                callback(data)


class EventSubscription:
    """
    One event's payloads, delivered onto the subscriber's own loop.

    Fans out synchronously on whichever thread pushed the event.
    """

    def __init__(
        self,
        bus: EventBus,
        unique_identifier: str,
        loop: asyncio.AbstractEventLoop | None = None,
        maxsize: int = 3,
    ) -> None:
        """
        Subscribe to one event.

        Parameters
        ----------
        bus: EventBus
            the bus to subscribe to
        unique_identifier: str
            the event to listen for, as `<thing id>/<event name>`
        loop: asyncio.AbstractEventLoop, optional
            the loop to deliver on. The running one by default.
        maxsize: int
            how many payloads to hold before dropping the oldest

        Raises
        ------
        KeyError
            if no such event is registered with the bus
        """
        self.event = bus.event_for(unique_identifier)
        self.bus = bus
        self.unique_identifier = unique_identifier
        self.loop = loop or asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=maxsize)  # type: asyncio.Queue
        self.dropped = 0
        bus.subscribe(self.event_callback_threadsafe, unique_identifier)

    def event_callback_threadsafe(self, data: Any) -> None:
        """Called on the pushing thread - hand the payload over and get out of the way."""
        try:
            self.loop.call_soon_threadsafe(self._handle_event_publish, data)
        except RuntimeError:
            pass  # the subscriber's loop is gone, so there is nobody left to deliver to

    def _handle_event_publish(self, data: Any) -> None:
        """Called on the subscriber's loop."""
        if self.queue.full():
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(data)

    async def receive(self, timeout: float | None = None) -> Any:
        """
        Wait for the next payload.

        Parameters
        ----------
        timeout: float, optional
            seconds to wait. Waits indefinitely when not given.

        Returns
        -------
        Any
            the payload, unencoded.

        Raises
        ------
        TimeoutError
            if nothing was pushed before the timeout elapsed.
        """
        if timeout is None:
            return await self.queue.get()
        return await asyncio.wait_for(self.queue.get(), timeout)

    def encode(self, data: Any) -> tuple[bytes, str]:
        """
        Encode one of this event's payloads the way its objekt is registered to be encoded.

        Parameters
        ----------
        data: Any
            a payload from `receive()`

        Returns
        -------
        tuple[bytes, str]
            the encoded body and the content type to declare for it
        """
        return encode_event(self.event, data)

    def unsubscribe(self) -> None:
        """Stop receiving. Safe to call more than once."""
        self.bus.unsubscribe(self.event_callback_threadsafe, self.unique_identifier)


def encode_event(event: RegisteredEvent, data: Any) -> tuple[bytes, str]:
    """
    Serialize the event payload based on the metadata of the event.

    Parameters
    ----------
    event: RegisteredEvent
        the event being published
    data: Any
        its payload

    Returns
    -------
    tuple[bytes, str]
        the encoded body and the content type to declare for it
    """
    owner, name = event.owner, event.descriptor.name
    if isinstance(data, bytes):
        content_type = Serializers.get_content_type_for_object(owner.id, owner.__class__.__name__, name)
        return data, content_type or "application/octet-stream"
    serializer = Serializers.for_object(owner.id, owner.__class__.__name__, name)
    return serializer.dumps(data), serializer.content_type


__all__ = [EventBus.__name__, EventSubscription.__name__, RegisteredEvent.__name__]
