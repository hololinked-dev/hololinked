"""
The transport-neutral half of pushing an event: who may push, and who wants to be told.

An `EventBus` belongs to one event loop. `Thing`s register their events with it and push
payloads through it; protocols subscribe to it and are handed the dispatcher and the raw payload.
Encoding that payload and getting it onto a wire is each subscriber's own business, which is what
lets one event reach a ZMQ PUB socket, an SSE stream and an MQTT topic without the event loop
knowing
that any of them exist.
"""

from __future__ import annotations

import asyncio
import threading
import warnings

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from hololinked import Serializers


if TYPE_CHECKING:
    from hololinked.core.events import EventDispatcher


class EventBus:
    """Registry of the events a set of `Thing`s can push, and fan-out to whoever is listening."""

    def __init__(self) -> None:
        # keyed by unique identifier rather than holding a set of dispatchers: `Event.__get__` builds
        # a fresh `EventDispatcher` on every attribute access, so a set of them would grow without
        # bound and any identity-based duplicate check would fire on the same event twice over
        self._events = dict()  # type: dict[str, EventDispatcher]
        self._subscribers = []  # type: list[Callable[[EventDispatcher, Any], None]]
        self._lock = threading.Lock()

    @property
    def event_ids(self) -> set[str]:
        """Unique identifiers of every registered event."""
        return set(self._events)

    def register(self, event: EventDispatcher) -> None:
        """
        Register an event, so that it may be published.

        Re-registering the same unique identifier replaces the entry rather than raising - a `Thing`
        hands over a newly built dispatcher for the same event each time the attribute is read.

        Parameters
        ----------
        event: EventDispatcher
            the event to register. Events created at `__init__()` of a `Thing` register themselves.
        """
        with self._lock:
            self._events[event._unique_identifier] = event

    def unregister(self, event: EventDispatcher) -> None:
        """
        Unregister an event, so that publishing it raises.

        Parameters
        ----------
        event: EventDispatcher
            the event to unregister
        """
        with self._lock:
            if self._events.pop(event._unique_identifier, None) is None:
                warnings.warn(
                    f"event {event._unique_identifier} not found, did you mean to unregister another event?",
                    UserWarning,
                    stacklevel=2,
                )

    def subscribe(self, callback: Callable[[EventDispatcher, Any], None]) -> None:
        """
        Ask to be called with `(event, data)` whenever any registered event is published.

        Parameters
        ----------
        callback: Callable[[EventDispatcher, Any], None]
            called synchronously, on whichever thread pushed the event - which is a `Thing`'s own
            thread, not the subscriber's. A subscriber that owns loop-bound state (a protocol
            server's connections, say) must hop to its loop itself, with `call_soon_threadsafe`.
        """
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[EventDispatcher, Any], None]) -> None:
        """
        Stop being called when events are published.

        Parameters
        ----------
        callback: Callable[[EventDispatcher, Any], None]
            a callback previously given to `subscribe()`. Unknown callbacks are ignored.
        """
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def publish(self, event: EventDispatcher, data: Any) -> None:
        """
        Hand one event's payload to every subscriber, in subscription order.

        The lock is held for the whole fan-out, which is what serializes concurrent pushes from
        different `Thing` threads onto each subscriber's wire.

        Parameters
        ----------
        event: EventDispatcher
            the event being pushed
        data: Any
            its payload, unencoded

        Raises
        ------
        AttributeError
            if the event is not registered with this bus
        """
        with self._lock:
            if event._unique_identifier not in self._events:
                raise AttributeError(f"event name {event._unique_identifier} not registered")
            for callback in self._subscribers:
                callback(event, data)


class EventSubscription:
    """
    One event's payloads, delivered onto the subscriber's own loop.

    `EventBus.publish()` fans out synchronously on whichever thread pushed the event - a `Thing`'s
    thread - so a subscriber that owns loop-bound state cannot be called directly. This parks each
    payload on a queue belonging to the subscriber's loop and lets it `await` them in its own time.

    Bounded on purpose: a client that stops reading must not grow the queue without limit, so the
    oldest payload is dropped once it is full, which is what a live stream wants.
    """

    def __init__(
        self,
        bus: EventBus,
        unique_identifier: str,
        loop: asyncio.AbstractEventLoop | None = None,
        maxsize: int = 100,
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
        """
        self._bus = bus
        self._unique_identifier = unique_identifier
        self._loop = loop or asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=maxsize)  # type: asyncio.Queue
        self.dropped = 0
        """how many payloads were dropped because the reader fell behind."""
        bus.subscribe(self._on_event)

    def _on_event(self, event: EventDispatcher, data: Any) -> None:
        """Called on the pushing thread - hand the payload over and get out of the way."""
        if event._unique_identifier != self._unique_identifier:
            return
        try:
            self._loop.call_soon_threadsafe(self._offer, event, data)
        except RuntimeError:
            pass  # the subscriber's loop is gone, so there is nobody left to deliver to

    def _offer(self, event: EventDispatcher, data: Any) -> None:
        """Called on the subscriber's loop."""
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait((event, data))

    async def receive(self, timeout: float | None = None) -> tuple[EventDispatcher, Any] | None:
        """
        Wait for the next payload.

        Parameters
        ----------
        timeout: float, optional
            seconds to wait. Waits indefinitely when not given.

        Returns
        -------
        tuple[EventDispatcher, Any] | None
            the event and its payload, or `None` if the timeout elapsed first
        """
        if timeout is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None

    def unsubscribe(self) -> None:
        """Stop receiving. Safe to call more than once."""
        self._bus.unsubscribe(self._on_event)


def encode_event(event: EventDispatcher, data: Any) -> tuple[bytes, str]:
    """
    Encode one event's payload the way its objekt is registered to be encoded.

    Every protocol needs this and none of them should be reimplementing the registry lookup.
    `bytes` are passed through untouched, which is the escape hatch for anything a serializer would
    only get in the way of.

    Parameters
    ----------
    event: EventDispatcher
        the event being published
    data: Any
        its payload

    Returns
    -------
    tuple[bytes, str]
        the encoded body and the content type to declare for it
    """
    owner, name = event._owner_inst, event._descriptor.name
    if isinstance(data, bytes):
        content_type = Serializers.get_content_type_for_object(owner.id, owner.__class__.__name__, name)
        return data, content_type or "application/octet-stream"
    serializer = Serializers.for_object(owner.id, owner.__class__.__name__, name)
    return serializer.dumps(data), serializer.content_type


__all__ = [EventBus.__name__, EventSubscription.__name__]
