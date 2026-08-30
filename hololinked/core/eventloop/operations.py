"""
The transport-neutral unit of work that the execution engine schedules on a `Thing`.

A protocol receives a request in whatever shape its wire format defines - a ZMQ multipart frame, an
HTTP request, an MQTT payload - and converts it, at its own border, into an `Operation`. The engine
never sees the wire format. It answers with a `Reply`, which the protocol converts back.

Keeping the two apart is what lets a wire format be a protocol's private business. It also gives one
spelling for the execution parameters: the ZMQ header has historically declared them as
`invokationTimeout` while the engine looked up `invokation_timeout`, and that only worked because
clients bypassed the typed header and sent a raw dict.
"""

from __future__ import annotations

from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import msgspec

from ..payloads import PreserializedData, SerializableData
from ..utils import CrossLoopEvent


# The execution context a caller asks for, in the camelCase the ZMQ header declares. It lives here
# rather than with that header because it is what a caller wants, not how one protocol spells it -
# `as_execution_kwargs()` reads both spellings onto the `Operation` fields below.


class ServerExecutionContext(msgspec.Struct):
    """Additional context for the server while executing an operation."""

    invokationTimeout: float
    executionTimeout: float
    oneway: bool


class ThingExecutionContext(msgspec.Struct):
    """Additional context for the thing while executing an operation."""

    fetchExecutionLogs: bool


default_server_execution_context = ServerExecutionContext(invokationTimeout=5, executionTimeout=5, oneway=False)

default_thing_execution_context = ThingExecutionContext(fetchExecutionLogs=False)

SerializableNone = SerializableData(None, content_type="application/json")
PreserializedEmptyByte = PreserializedData(b"", content_type="text/plain")


@dataclass
class Operation:
    """One operation to perform on one interaction affordance of one `Thing`."""

    thing_id: str
    """`id` of the `Thing` the operation is for."""
    objekt: str
    """name of the property, action or event."""
    operation: str
    """what to do with it - an `Operations` member such as `readproperty` or `invokeaction`."""

    payload: SerializableData = field(default_factory=lambda: SerializableData(None))
    """the operation's argument, still encoded until the executing `Thing` deserializes it."""
    preserialized_payload: PreserializedData = field(default_factory=lambda: PreserializedData(b""))
    """binary argument that bypasses serialization entirely."""

    invokation_timeout: float | None = None
    """seconds to wait for the operation to *start*, `None` to wait indefinitely."""
    execution_timeout: float | None = None
    """seconds to wait for the operation to *finish*, `None` to wait indefinitely."""
    oneway: bool = False
    """whether the caller wants no reply, in which case the engine's answer is discarded."""
    fetch_execution_logs: bool = False
    """whether to collect the `Thing`'s log records during execution and return them with the reply."""

    id: str = ""
    """identifier of the originating request. Correlation and logging only - the engine never routes on it."""
    sender_id: str = ""
    """identifier of whoever asked. Logging only."""

    @property
    def qualified_operation(self) -> str:
        """A key identifying this operation on this affordance of this `Thing`."""
        return f"{self.thing_id}.{self.objekt}.{self.operation}"


class ReplyKind(StrEnum):
    """How an operation finished, in engine terms rather than in any protocol's vocabulary."""

    OK = "ok"
    """completed, `payload` carries the return value."""
    ERROR = "error"
    """raised, `payload` carries the formatted exception."""
    EXIT = "exit"
    """the `Thing` was asked to stop serving; there is no meaningful return value."""
    INVOKATION_TIMEOUT = "invokation_timeout"
    """never started - it was still queued when `invokation_timeout` elapsed."""
    EXECUTION_TIMEOUT = "execution_timeout"
    """started but did not finish within `execution_timeout`. It may still be running."""


@dataclass
class Reply:
    """The engine's answer to one `Operation`."""

    payload: SerializableData
    """the return value, encoded with whatever serializer the objekt is registered against."""
    preserialized_payload: PreserializedData
    """binary part of the return value, if the operation produced one."""
    kind: ReplyKind = ReplyKind.OK
    """how it finished."""

    @property
    def is_error(self) -> bool:
        """Whether the operation raised."""
        return self.kind is ReplyKind.ERROR

    @property
    def timed_out(self) -> bool:
        """Whether the operation never started, or started and did not finish in time."""
        return self.kind in (ReplyKind.INVOKATION_TIMEOUT, ReplyKind.EXECUTION_TIMEOUT)


TIMED_OUT_REPLY = {
    kind: Reply(
        payload=SerializableData(None),
        preserialized_payload=PreserializedData(b""),
        kind=kind,
    )
    for kind in (ReplyKind.INVOKATION_TIMEOUT, ReplyKind.EXECUTION_TIMEOUT)
}
"""Prebuilt empty replies for the two timeout outcomes - a timeout carries no value."""


@dataclass
class Job:
    """
    One submitted operation on its way to a `Thing`, with the promise that answers the caller.

    Whoever called `submit()` holds the other end of `future` and neither knows nor cares which
    scheduling policy the operation ended up under.
    """

    operation: Operation
    """what to do."""
    future: Future
    """
    Resolved with a `Reply`, the timeout kinds included, so the caller can tell them apart.

    A `concurrent.futures.Future` rather than an `asyncio` one: it is created by whoever submitted
    and resolved by whichever thread the `Thing` ran on, and only this kind is safe across that gap.
    An async caller wraps it onto its own loop - see `EventLoop.submit_and_wait()`.
    """
    started: CrossLoopEvent
    """set when the operation leaves the queue. The invokation timeout races against this."""
    invokation_timeout_task: Future | None = None
    """
    The racing timeout, if one was armed, as returned by `asyncio.run_coroutine_threadsafe`.

    Awaited once `started` is set, to settle the race before deciding whether to run the operation.
    """

    def answer(self, reply: Reply) -> None:
        """
        Resolve the caller's future, unless a timeout already answered for us.

        Safe to call from any thread, and safe to call twice - the loser is dropped rather than
        raising, which is what lets a timeout and a real reply race without coordination.

        Parameters
        ----------
        reply: Reply
            the outcome to hand back to whoever submitted
        """
        try:
            self.future.set_result(reply)
        except InvalidStateError:
            pass  # somebody got there first: a timeout, or a second answer for the same job


def qualified_operation_key(thing_id: str, objekt: str, operation: str) -> str:
    """
    A unique string representing one operation on one interaction affordance of one `Thing`.

    Can be used as a key in dictionaries as a unique identifier for an operation.

    Parameters
    ----------
    thing_id: str
        `id` of the `Thing`
    objekt: str
        name of the property, action or event
    operation: str
        the operation, like `Operations.invokeaction`

    Returns
    -------
    str
        the qualified operation key
    """
    return f"{thing_id}.{objekt}.{operation}"


def as_execution_kwargs(context: Any) -> dict[str, Any]:
    """
    Read the execution parameters out of whatever shape a protocol handed over.

    Accepts a mapping, an object with the attributes, or `None`, and tolerates both the snake_case
    spelling the engine uses and the camelCase spelling the ZMQ header declares.

    Parameters
    ----------
    context: Any
        a server or thing execution context - mapping, struct, or `None`

    Returns
    -------
    dict[str, Any]
        the recognised parameters, keyed as `Operation` fields, omitting anything absent
    """
    aliases = {
        "invokation_timeout": ("invokation_timeout", "invokationTimeout"),
        "execution_timeout": ("execution_timeout", "executionTimeout"),
        "oneway": ("oneway",),
        "fetch_execution_logs": ("fetch_execution_logs", "fetchExecutionLogs"),
    }
    if context is None:
        return {}
    found = {}  # type: dict[str, Any]
    for name, spellings in aliases.items():
        for spelling in spellings:
            if isinstance(context, dict):
                if spelling in context:
                    found[name] = context[spelling]
                    break
            elif hasattr(context, spelling):
                found[name] = getattr(context, spelling)
                break
    return found


__all__ = [Job.__name__, Operation.__name__, Reply.__name__, ReplyKind.__name__, qualified_operation_key.__name__]
