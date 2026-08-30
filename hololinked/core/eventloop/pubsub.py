"""
The transport-neutral half of pushing an event: who may push, and who wants to be told.

An `EventBus` belongs to one execution engine. `Thing`s register their events with it and push
payloads through it; protocols subscribe to it and are handed the dispatcher and the raw payload.
Encoding that payload and getting it onto a wire is each subscriber's own business, which is what
lets one event reach a ZMQ PUB socket, an SSE stream and an MQTT topic without the engine knowing
that any of them exist.
"""

from __future__ import annotations

import threading
import warnings

from collections.abc import Callable
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from ..events import EventDispatcher


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
            called synchronously, on whichever thread pushed the event
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


__all__ = [EventBus.__name__]
