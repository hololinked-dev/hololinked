"""
The implementation of an eventloop and how it executes operations.

The execution of operations is independent of the protocols or transport mechanisams,
and all protocols must instantiate an event loop object and simply submit their executions to it.

This would also mean that the protocol simply implement some parsing of incoming/outgoing messages
and comply them to a standard operation that we understand.

Schedulers control how event loop executes the submitted operations, queued, thread, async etc.
"""

from hololinked.core.eventloop.eventloop import EventLoop  # noqa: F401
from hololinked.core.eventloop.operations import (  # noqa: F401
    Job,
    Operation,
    Reply,
    ReplyKind,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)
from hololinked.core.eventloop.pubsub import EventBus, EventSubscription, encode_event  # noqa: F401
from hololinked.core.eventloop.scheduler import (  # noqa: F401
    AsyncScheduler,
    QueuedScheduler,
    Scheduler,
    ThreadedScheduler,
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
