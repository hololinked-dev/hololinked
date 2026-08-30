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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .payloads import PreserializedData, SerializableData


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


__all__ = [Operation.__name__, Reply.__name__, ReplyKind.__name__]
