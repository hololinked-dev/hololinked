"""
The transport-neutral unit of work that the event loop schedules on a `Thing`.

A protocol receives a request in whatever shape its wire format defines - a ZMQ multipart frame, an
HTTP request, an MQTT payload - and converts it, at its own border, into an `Operation`. The
event loop
never sees the wire format. It answers with a `Reply`, which the protocol converts back.

Keeping the two apart is what lets a wire format be a protocol's private business. It also gives one
spelling for the execution parameters: the ZMQ header has historically declared them as
`invokationTimeout` while the event loop looked up `invokation_timeout`, and that only worked because
clients bypassed the typed header and sent a raw dict.
"""

from __future__ import annotations

import asyncio

from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import msgspec

from ..utils import CrossLoopEvent
from .payloads import PreserializedData, SerializableData


# The execution context a caller asks for, in the camelCase the ZMQ header declares. It lives here
# rather than with that header because it is what a caller wants, not how one protocol spells it -
# `as_execution_kwargs()` reads both spellings onto the flat keywords `Operation.__init__` takes.


class ServerExecutionContext(msgspec.Struct):
    """Additional context for the server while executing an operation."""

    invokationTimeout: float | None
    """seconds to wait for the operation to *start*, `None` to wait indefinitely."""
    executionTimeout: float | None
    """seconds to wait for the operation to *finish*, `None` to wait indefinitely."""
    oneway: bool
    """whether the caller wants no reply, in which case the event loop's answer is discarded."""


class ThingExecutionContext(msgspec.Struct):
    """Additional context for the thing while executing an operation."""

    fetchExecutionLogs: bool
    """whether to collect the `Thing`'s log records during execution and return them with the reply."""


default_server_execution_context = ServerExecutionContext(invokationTimeout=5, executionTimeout=5, oneway=False)

default_thing_execution_context = ThingExecutionContext(fetchExecutionLogs=False)

SerializableNone = SerializableData(None, content_type="application/json")
PreserializedEmptyByte = PreserializedData(b"", content_type="text/plain")


@dataclass(init=False)
class Operation:
    """
    One operation to perform on one interaction affordance of one `Thing`.

    The execution parameters live in the two contexts a caller actually asks for, which is also the
    shape every wire format declares them in. `__init__` accepts them flat, as `invokation_timeout=`,
    `oneway=` and the rest, because that is how a border has them to hand; reading them goes through
    the context they belong to, so which parameter is the server's business and which is the
    `Thing`'s stays visible at every use.
    """

    thing_id: str
    """`id` of the `Thing` the operation is for."""
    objekt: str
    """name of the property, action or event."""
    operation: str
    """what to do with it - an `Operations` member such as `readproperty` or `invokeaction`."""

    payload: SerializableData
    """the operation's argument, still encoded until the executing `Thing` deserializes it."""
    preserialized_payload: PreserializedData
    """binary argument that bypasses serialization entirely."""

    server_execution_context: ServerExecutionContext
    """the timeouts, and whether a reply is wanted at all."""
    thing_execution_context: ThingExecutionContext
    """what the `Thing` should do beside running the operation."""

    id: str
    """identifier of the originating request. Correlation and logging only - never routed on."""
    sender_id: str
    """identifier of whoever asked. Logging only."""

    def __init__(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData | None = None,
        preserialized_payload: PreserializedData | None = None,
        invokation_timeout: float | None = None,
        execution_timeout: float | None = None,
        oneway: bool = False,
        fetch_execution_logs: bool = False,
        id: str = "",
        sender_id: str = "",
    ) -> None:
        """
        Build an operation from flat parameters, gathering the execution ones into their contexts.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` the operation is for
        objekt: str
            name of the property, action or event
        operation: str
            what to do with it, an `Operations` member
        payload: SerializableData, optional
            the operation's argument, still encoded
        preserialized_payload: PreserializedData, optional
            binary argument that bypasses serialization
        invokation_timeout: float, optional
            seconds to wait for the operation to start, `None` to wait indefinitely
        execution_timeout: float, optional
            seconds to wait for the operation to finish, `None` to wait indefinitely
        oneway: bool
            whether to discard the reply
        fetch_execution_logs: bool
            whether to return the `Thing`'s log records with the reply
        id: str
            identifier of the originating request
        sender_id: str
            identifier of whoever asked
        """
        self.thing_id = thing_id
        self.objekt = objekt
        self.operation = operation
        self.payload = SerializableData(None) if payload is None else payload
        self.preserialized_payload = PreserializedData(b"") if preserialized_payload is None else preserialized_payload
        self.server_execution_context = ServerExecutionContext(
            invokationTimeout=invokation_timeout,
            executionTimeout=execution_timeout,
            oneway=oneway,
        )
        self.thing_execution_context = ThingExecutionContext(fetchExecutionLogs=fetch_execution_logs)
        self.id = id
        self.sender_id = sender_id

    @property
    def qualified_name(self) -> str:
        """A key identifying this operation on this affordance of this `Thing`."""
        return qualified_operation_key(self.thing_id, self.objekt, self.operation)


class ReplyKind(StrEnum):
    """How an operation finished, in event loop terms rather than in any protocol's vocabulary."""

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
    """The event loop's answer to one `Operation`."""

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
    An async caller wraps it onto its own loop - see `EventLoop.execute()`.
    """
    started: CrossLoopEvent
    """set when the operation leaves the queue. The invokation timeout races against this."""
    completed: CrossLoopEvent
    """set when the `Thing` has produced a reply. The execution timeout races against this."""
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

    async def answer_if_never_started(self, timeout: float) -> bool:
        """
        Answer the caller with an invokation timeout if this job has not left the queue in time.

        Parameters
        ----------
        timeout: float
            seconds to wait for `started`

        Returns
        -------
        bool
            `True` if it timed out and answered, `False` if the job started first
        """
        try:
            await asyncio.wait_for(self.started.wait(), timeout)
            return False
        except TimeoutError:
            self.answer(TIMED_OUT_REPLY[ReplyKind.INVOKATION_TIMEOUT])
            return True

    async def answer_if_overdue(self, timeout: float) -> bool:
        """
        Answer the caller with an execution timeout if the operation has not finished in time.

        The operation is not cancelled - it cannot be - so its eventual reply is still drained by
        `EventLoop.tunnel_message_to_things()`, then dropped.

        Parameters
        ----------
        timeout: float
            seconds to wait for `completed`

        Returns
        -------
        bool
            `True` if it timed out and answered, `False` if the operation finished first
        """
        try:
            await asyncio.wait_for(self.completed.wait(), timeout)
            return False
        except TimeoutError:
            self.answer(TIMED_OUT_REPLY[ReplyKind.EXECUTION_TIMEOUT])
            return True


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
    spelling the event loop uses and the camelCase spelling the ZMQ header declares.

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
