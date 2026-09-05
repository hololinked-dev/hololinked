"""
How an operation waits its turn.

A scheduler sits between the loop that accepts requests and the thread the `Thing` runs on.

There are three in built types of schedulers:
- `QueuedScheduler` serializes everything on a `Thing` and is the default
- `AsyncScheduler` and `ThreadedScheduler` start their operation at once.
- `AsyncScheduler` runs concurrently operations async
- `ThreadedScheduler` runs concurrently operations in a thread

[UML Diagram](http://docs.hololinked.dev/UML/PDF/Scheduler.pdf)
"""

from __future__ import annotations

import asyncio
import threading

from collections import deque
from typing import TYPE_CHECKING, Any

from hololinked.core.eventloop.operations import Job, Operation, Reply
from hololinked.core.thing import Thing
from hololinked.core.utils import CrossLoopEvent


if TYPE_CHECKING:
    from hololinked.core.eventloop.eventloop import EventLoop


Undefined = NotImplemented
"""Placeholder for "nothing here yet", distinct from a legitimately `None` request or reply."""


class Scheduler:
    """
    Scheduler class to schedule the operations of a thing either in queued mode, or a one-shot mode in either async or threaded loops.

    [UML Diagram subclasses](http://docs.hololinked.dev/UML/PDF/Scheduler.pdf)
    """

    _operation_execution_complete_event: CrossLoopEvent
    _operation_execution_ready_event: CrossLoopEvent

    def __init__(self, instance: Thing, eventloop: EventLoop) -> None:
        self.instance = instance  # type: Thing
        self.eventloop = eventloop  # type: EventLoop
        self.run = True  # type: bool
        self._one_shot = False  # type: bool
        self._last_operation_request = Undefined  # type: Operation
        self._last_operation_reply = Undefined  # type: Reply
        self._job_queued_event = CrossLoopEvent()  # type: CrossLoopEvent

    @property
    def last_operation_request(self) -> Operation:
        return self._last_operation_request

    @last_operation_request.setter
    def last_operation_request(self, value: Operation):
        self._last_operation_request = value
        self._operation_execution_ready_event.set()

    def reset_operation_request(self) -> None:
        self._last_operation_request = Undefined

    @property
    def last_operation_reply(self) -> Reply:
        return self._last_operation_reply

    @last_operation_reply.setter
    def last_operation_reply(self, value: Reply):
        self._last_operation_request = Undefined
        self._last_operation_reply = value
        self._operation_execution_complete_event.set()
        if self._one_shot:
            self.run = False

    def reset_operation_reply(self) -> None:
        self._last_operation_reply = Undefined

    async def wait_for_job(self) -> None:
        await self._job_queued_event.wait()
        self._job_queued_event.clear()

    async def wait_for_operation(self) -> None:
        """Wait, on the `Thing`'s loop, until an operation has been handed over for execution."""
        await self._operation_execution_ready_event.wait()
        self._operation_execution_ready_event.clear()

    async def wait_for_reply(self) -> None:
        """Wait, on the listener loop, until the `Thing` has finished and produced a reply."""
        await self._operation_execution_complete_event.wait()
        self._operation_execution_complete_event.clear()

    @property
    def has_job(self) -> bool:
        raise NotImplementedError("has_job method must be implemented in the subclass")

    @property
    def next_job(self) -> Job:
        raise NotImplementedError("next_job method must be implemented in the subclass")

    def dispatch_job(self, job: Job) -> None:
        raise NotImplementedError("dispatch_job method must be implemented in the subclass")

    def cleanup(self):
        self.run = False
        self._job_queued_event.set()
        self._operation_execution_ready_event.set()
        self._operation_execution_complete_event.set()

    @classmethod
    def format_reply_tuple(self, return_value: Any) -> Reply:
        raise NotImplementedError("Implement format_reply_tuple in subclass")


class QueuedScheduler(Scheduler):
    """Scheduler class to schedule the operations of a thing in a queued loop."""

    def __init__(self, instance: Thing, eventloop: EventLoop) -> None:
        super().__init__(instance, eventloop)
        self.queue = deque()
        self._one_shot = False
        self._operation_execution_ready_event = CrossLoopEvent()
        self._operation_execution_complete_event = CrossLoopEvent()

    @property
    def has_job(self) -> bool:
        return len(self.queue) > 0

    @property
    def next_job(self) -> Job:
        return self.queue.popleft()

    def dispatch_job(self, job: Job) -> None:
        """
        Append a job to the queue, to be run once everything ahead of it has finished.

        Parameters
        ----------
        job: Job
            the operation to run, and the future that answers whoever submitted it
        """
        # `deque.append` is atomic and the drain loop is the only consumer, so no lock is needed
        # here however many threads submit at once
        self.queue.append(job)
        self._job_queued_event.set()

    def cleanup(self):
        self.queue.clear()
        return super().cleanup()


class AsyncScheduler(Scheduler):
    """Scheduler class to schedule the operations of a thing in an async loop."""

    def __init__(self, instance: Thing, eventloop: EventLoop) -> None:
        super().__init__(instance, eventloop)
        self._job = None
        self._one_shot = True
        self._operation_execution_ready_event = CrossLoopEvent()
        self._operation_execution_complete_event = CrossLoopEvent()

    @property
    def has_job(self) -> bool:
        return self._job is not None

    @property
    def next_job(self) -> Job:
        if self._job is None:
            raise RuntimeError("No job to execute")
        return self._job

    def dispatch_job(self, job: Job) -> None:
        """
        Store the job and start both halves of it as tasks on the `EventLoop`'s own asyncio loop.

        Onto that loop, never the caller's: a submission from a protocol server's thread
        must not end up running a `Thing`'s coordination on that server's loop.

        Parameters
        ----------
        job: Job
            the operation to run, and the future that answers whoever submitted it
        """
        self._job = job
        self.eventloop.run_coro_threadsafe(self.eventloop.tunnel_message_to_things(self))
        self.eventloop.run_coro_threadsafe(self.eventloop.run_thing_instance(self.instance, self))
        self._job_queued_event.set()


class ThreadedScheduler(Scheduler):
    """Scheduler class to schedule the operations of a thing in a threaded loop."""

    def __init__(self, instance: Thing, eventloop: EventLoop) -> None:
        super().__init__(instance, eventloop)
        self._job = None
        self._execution_thread = None
        self._one_shot = True
        self._operation_execution_ready_event = CrossLoopEvent()
        self._operation_execution_complete_event = CrossLoopEvent()

    @property
    def has_job(self) -> bool:
        return self._job is not None

    @property
    def next_job(self) -> Job:
        if self._job is None:
            raise RuntimeError("No job to execute")
        return self._job

    def dispatch_job(self, job: Job) -> None:
        """
        Store the job and start a thread to execute it on the `Thing` instance.

        The drain half goes onto the `EventLoop`'s own asyncio loop, not the caller's - see `AsyncScheduler`.

        Parameters
        ----------
        job: Job
            the operation to run, and the future that answers whoever submitted it
        """
        self._job = job
        self.eventloop.run_coro_threadsafe(self.eventloop.tunnel_message_to_things(self))
        self._execution_thread = threading.Thread(
            target=asyncio.run,
            args=(self.eventloop.run_thing_instance(self.instance, self),),
        )
        self._execution_thread.start()
        self._job_queued_event.set()


__all__ = [
    AsyncScheduler.__name__,
    QueuedScheduler.__name__,
    Scheduler.__name__,
    ThreadedScheduler.__name__,
]
