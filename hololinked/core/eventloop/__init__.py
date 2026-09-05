"""
The implementation of an eventloop and how it executes operations.

The execution of operations is independent of the protocols or transport mechanisams,
and all protocols must instantiate an event loop object and simply submit their executions to it.

This would also mean that the protocol simply implement some parsing of incoming/outgoing messages
and comply them to a standard operation that we understand.

Schedulers control how event loop executes the submitted operations, queued, thread, async etc.
"""

from .eventloop import EventLoop  # noqa: F401
from .operations import (  # noqa: F401
    TIMED_OUT_REPLY,
    Job,
    Operation,
    PreserializedEmptyByte,
    Reply,
    ReplyKind,
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    as_execution_kwargs,
    default_server_execution_context,
    default_thing_execution_context,
    qualified_operation_key,
)
from .pubsub import EventBus, EventSubscription, encode_event  # noqa: F401
from .scheduler import (  # noqa: F401
    AsyncScheduler,
    QueuedScheduler,
    Scheduler,
    ThreadedScheduler,
    Undefined,
)


__all__ = [
    "AsyncScheduler",
    "EventBus",
    "EventSubscription",
    "EventLoop",
    "Job",
    "Operation",
    "QueuedScheduler",
    "Reply",
    "ServerExecutionContext",
    "ThingExecutionContext",
    "ReplyKind",
    "Scheduler",
    "ThreadedScheduler",
    "encode_event",
]
