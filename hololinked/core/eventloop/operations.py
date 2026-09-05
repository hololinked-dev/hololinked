"""
The transport-neutral unit of work that the event loop schedules on a `Thing`.

A protocol receives a request in a shape its own wire format defines - a ZMQ multipart frame, a
HTTP request, an MQTT payload - and converts it, at its own border, into an `Operation`. The
event loop never sees the wire format. It answers with a `Reply`, which the protocol converts back.

Keeping the two apart is what lets a wire format be a protocol's private business. It also gives one
spelling for the execution parameters.
"""

from __future__ import annotations

import asyncio

from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import msgspec

from hololinked.core.eventloop.payloads import PreserializedData, SerializableData
from hololinked.core.interfaces import BaseSerializer
from hololinked.core.utils import CrossLoopEvent


class SchedulerExecutionContext(msgspec.Struct, rename="camel"):
    """Additional context for the serving side while executing an operation."""

    invokation_timeout: float | None
    """
    Max seconds to wait for the operation to *start*, `None` to wait indefinitely. 
    Please dont use `None` if unnecessary."""
    execution_timeout: float | None
    """
    Max seconds to wait for the operation to *finish*, `None` to wait indefinitely. 
    Please dont use `None` if unnecessary.
    """
    oneway: bool
    """whether the caller wants no reply, if not, the event loop's answer is discarded."""


class ThingExecutionContext(msgspec.Struct, rename="camel"):
    """Additional context for the thing while executing an operation."""

    fetch_execution_logs: bool
    """whether to collect the `Thing`'s log records during execution and return them with the reply."""


default_scheduler_execution_context = SchedulerExecutionContext(invokation_timeout=5, execution_timeout=5, oneway=False)

default_thing_execution_context = ThingExecutionContext(fetch_execution_logs=False)

SerializableNone = SerializableData(None, content_type="application/json")
PreserializedEmptyByte = PreserializedData(b"", content_type="text/plain")


@dataclass(init=False)
class Operation:
    """
    The eventloop's operation model - One operation to perform on one interaction affordance of one `Thing`.

    The transport-neutral unit of work.
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

    scheduler_execution_context: SchedulerExecutionContext
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
        Initialize an operation with the given parameters.

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
        self.scheduler_execution_context = SchedulerExecutionContext(
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
            oneway=oneway,
        )
        self.thing_execution_context = ThingExecutionContext(fetch_execution_logs=fetch_execution_logs)
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
    """the `Thing` was asked to stop; there is no meaningful return value."""
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
    """The operation wrapped around its lifecycle within the event loop."""

    operation: Operation
    """what to do."""
    future: Future
    """Resolved with a `Reply`"""
    # A `concurrent.futures.Future` rather than an `asyncio` one: it is created by whoever submitted
    # and resolved by whichever thread the `Thing` ran on, and only this kind is safe across that gap.
    # An async caller wraps it onto its own loop - see `EventLoop.execute()`.
    started: CrossLoopEvent
    """set when the operation started. The invokation timeout races against this."""
    completed: CrossLoopEvent
    """set when the operation has completed. The execution timeout races against this."""
    invokation_timeout_task: Future | None = None
    """The timeout racing `started`. Awaited once `started` is set, to settle the race."""
    execution_timeout_task: asyncio.Task | None = None
    """The timeout racing `completed`. Awaited once `completed` is set, to settle the race."""

    def answer(self, reply: Reply) -> None:
        """
        Resolve the caller's future, unless a timeout already answered for us.

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


def format_return_value(
    return_value: Any,
    serializer: BaseSerializer,
    content_type_if_no_serializer: str = "",
) -> tuple[SerializableData, PreserializedData]:
    """
    Cast whatever a `Thing` returned into a multipart return value. Not ideal format. WIP.

    Parameters
    ----------
    return_value: Any
        what the `Thing` method returned
    serializer: BaseSerializer
        the serializer registered for the objekt, used for the serializable half
    content_type_if_no_serializer: str
        content type to stamp on the raw half, which no serializer touches

    Returns
    -------
    tuple[SerializableData, PreserializedData]
        the two payloads a `Reply` carries
    """
    if (
        isinstance(return_value, tuple)
        and len(return_value) == 2
        and (isinstance(return_value[1], bytes) or isinstance(return_value[1], PreserializedData))
    ):
        payload = SerializableData(
            return_value[0],
            serializer=serializer,
            content_type=serializer.content_type,
        )
        if isinstance(return_value[1], bytes):
            preserialized_payload = PreserializedData(return_value[1], content_type=content_type_if_no_serializer)
    elif isinstance(return_value, bytes):
        payload = SerializableData(None, content_type="application/json")
        preserialized_payload = PreserializedData(return_value, content_type=content_type_if_no_serializer)
    elif isinstance(return_value, PreserializedData):
        payload = SerializableData(None, content_type="application/json")
        preserialized_payload = return_value
    else:
        payload = SerializableData(
            return_value,
            serializer=serializer,
            content_type=serializer.content_type,
        )
        preserialized_payload = PreserializedData(b"", content_type="text/plain")
    return payload, preserialized_payload


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


__all__ = [
    Job.__name__,
    Operation.__name__,
    Reply.__name__,
    ReplyKind.__name__,
    format_return_value.__name__,
    qualified_operation_key.__name__,
]
