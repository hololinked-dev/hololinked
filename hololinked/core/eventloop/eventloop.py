"""
The event loop: what actually runs an operation on a `Thing`.

`EventLoop` accepts `Operation`s through `submit()` and answers with `Reply`s. It owns the `Thing`
threads, the schedulers that decide whether an operation queues or runs at once, and the `EventBus`
that events are pushed onto. It owns no sockets and knows no wire format - a protocol server sits in
front of it and converts, at its own border, in both directions.

[UML Diagram](http://docs.hololinked.dev/UML/PDF/RPCServer.pdf)
"""

from __future__ import annotations

import asyncio
import logging
import threading

from collections.abc import Callable, Coroutine, Sequence
from concurrent.futures import Future
from typing import Any

import structlog

from hololinked import Serializers
from hololinked.constants import Operations
from hololinked.core.interfaces import BaseSerializer
from hololinked.utils import (
    format_exception_as_json,
    get_current_async_loop,
)

from ..actions import BoundAction
from ..exceptions import BreakInnerLoop
from ..logger import LogHistoryHandler
from ..property import Property
from ..thing import Thing
from ..utils import CrossLoopEvent, get_all_sub_things_recusively
from .operations import TIMED_OUT_REPLY, Job, Operation, Reply, ReplyKind, qualified_operation_key
from .payloads import PreserializedData, SerializableData
from .pubsub import EventBus
from .scheduler import (
    AsyncScheduler,
    QueuedScheduler,
    Scheduler,
    ThreadedScheduler,
    Undefined,
)


class EventLoop:
    """
    Runs operations on the `Thing` instances.

    Instantiate, use the `Operation` model and the submit() method in a protocol runtime to serve requests.
    These create `Job`s that go through schedulers, complete them and return `Reply`s.
    """

    things: dict[str, Thing]
    """Every served `Thing`, sub-things included, keyed by id. What `submit()` resolves against."""

    per_job_scheduler_types: dict[str, type[Scheduler]]
    """
    Scheduler class constructed fresh for every operation.

    `AsyncScheduler` and `ThreadedScheduler` live here: they run their operation concurrently and
    each carries its own reply.
    """

    per_thing_schedulers: dict[str, Scheduler]
    """
    Long-lived scheduler shared by every queued operation on that `Thing`.

    `QueuedScheduler` lives here: it owns the queue that serializes operations, so there can only
    be one of it per `Thing`.
    """

    def __init__(
        self,
        *,
        id: str,
        things: list[Thing] | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
        thing_description_provider: Callable[..., dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the event loop.

        Parameters
        ----------
        id: str
            `id` of the event loop, usually shared with the protocol server that owns it
        things: list[Thing]
            list of `Thing` instances to be served
        logger: structlog.stdlib.BoundLogger, optional
            logger instance to use. A default is created when none is given.
        thing_description_provider: Callable, optional
            the owning protocol server's TD generator - see `get_thing_description()`
        """
        self.id = id
        if not logger:
            logger = structlog.get_logger()
        self.logger = logger.bind(component="eventloop", impl=self.__class__.__name__, id=self.id)
        # all four must exist before add_things(): it writes to two of them, and a `Thing` reads the
        # bus as soon as one of its events is first accessed
        self.things = dict()
        self.per_job_scheduler_types = dict()
        self.per_thing_schedulers = dict()
        self.event_bus = EventBus()
        self.protocol_servers = []  # type: list[Any]
        self._stop_hooks = []  # type: list[Callable[[], None]]
        self._loop = None  # type: asyncio.AbstractEventLoop | None
        self._thing_description_provider = thing_description_provider
        self._run = False  # flag to stop the event loop and everything hooked onto it
        self.add_things(*(things or []))

    def add_thing(self, thing: Thing) -> None:
        """
        Adds a thing to the list of things to serve.

        Parameters
        ----------
        thing: Thing
            the `Thing` to serve, along with its sub-things

        Raises
        ------
        RuntimeError
            if the event loop is already running - the registries it writes to are read without a lock
            by every submission, on the understanding that they stop changing once things are served
        """
        if self._run:
            raise RuntimeError(
                f"cannot add thing {thing.id} while the event loop is running - add every thing before run()"
            )
        # setup scheduling requirements
        all_things: list[Thing] = get_all_sub_things_recusively(thing)
        for instance in all_things:
            instance.eventloop = self
            self.things[instance.id] = instance
            for action in instance.actions.descriptors.values():
                if action.synchronous:
                    continue  # QueuedScheduler, which is the default and is shared per Thing
                key = qualified_operation_key(instance.id, action.name, Operations.invokeaction)
                self.per_job_scheduler_types[key] = AsyncScheduler if action.iscoroutine else ThreadedScheduler
            # properties need not dealt yet, but may be in future)

    def add_things(self, *things: Thing) -> None:
        """Adds multiple things to serve."""
        for thing in things:
            self.add_thing(thing)

    @property
    def is_running(self) -> bool:
        """Check if the server is running or not."""
        return self._run

    def run_coro_threadsafe(self, coro: Coroutine[Any, Any, Any]) -> Future:
        """
        Run a coroutine on this `EventLoop`'s own asyncio loop, from whichever thread is asking.

        Parameters
        ----------
        coro: Coroutine
            the coroutine to schedule

        Returns
        -------
        concurrent.futures.Future
            resolved with the coroutine's result

        Raises
        ------
        RuntimeError
            if the event loop is not running, so there is no asyncio loop to schedule onto
        """
        if self._loop is None:
            coro.close()
            raise RuntimeError("the event loop is not running, call run() before submitting operations")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def submit(self, operation: Operation) -> Future:
        """
        Schedule an operation on its `Thing` and return the promise of its reply.

        Non-blocking, and safe to call from any thread, with or without a running asyncio event loop of your
        own. To complete the operation, use `execute()` instead.

        Parameters
        ----------
        operation: Operation
            what to do, on which `Thing`

        Returns
        -------
        concurrent.futures.Future
            resolved with a `Reply`, the timeout kinds included

        Raises
        ------
        KeyError
            if no `Thing` with that id is being served
        RuntimeError
            if the event loop is not running
        """
        if not self._run:
            raise RuntimeError("the event loop is not running, call run() before submitting operations")
        thing = self.things[operation.thing_id]
        job = Job(operation=operation, future=Future(), started=CrossLoopEvent())
        if operation.invokation_timeout is not None:
            # races against the job leaving the queue - whichever gets there first answers the caller
            job.invokation_timeout_task = self.run_coro_threadsafe(
                self._answer_if_never_started(job, operation.invokation_timeout)
            )

        scheduler_type = self.per_job_scheduler_types.get(operation.qualified_operation)
        if scheduler_type is not None:
            # async/threaded: a fresh scheduler per job, since they run concurrently
            scheduler = scheduler_type(thing, self)
        else:
            # queued (the default): the one scheduler shared by this Thing
            scheduler = self.per_thing_schedulers[operation.thing_id]
        scheduler.dispatch_job(job)
        return job.future

    async def execute(self, operation: Operation) -> Reply:
        """
        Schedule an operation and wait for its reply, on the calling coroutine's own loop.

        The async face of `submit()`. Whichever loop calls this is the loop the wait is parked on,
        so a protocol server never blocks, nor borrows, the `EventLoop`'s own asyncio loop.

        Parameters
        ----------
        operation: Operation
            what to do, on which `Thing`

        Returns
        -------
        Reply
            how the operation finished, including the two timeout kinds

        Raises
        ------
        KeyError
            if no `Thing` with that id is being served
        RuntimeError
            if the event loop is not running
        """
        return await asyncio.wrap_future(self.submit(operation))

    async def _answer_if_never_started(self, job: Job, timeout: float) -> bool:
        """
        Answer the caller with an invokation timeout if the job has not left the queue in time.

        Returns
        -------
        bool
            `True` if it timed out and answered, `False` if the job started first
        """
        try:
            await asyncio.wait_for(job.started.wait(), timeout)
            return False
        except TimeoutError:
            job.answer(TIMED_OUT_REPLY[ReplyKind.INVOKATION_TIMEOUT])
            return True

    async def _answer_if_overdue(self, job: Job, timeout: float) -> None:
        """
        Answer the caller with an execution timeout once the operation has run out of time.

        The operation is not cancelled - it cannot be - and its eventual reply is still drained by
        `tunnel_message_to_things()`, then dropped. Whether this ran at all is what that loop reads
        back out of the task to decide, which is why it answers rather than returning an outcome.
        """
        await asyncio.sleep(timeout)
        job.answer(TIMED_OUT_REPLY[ReplyKind.EXECUTION_TIMEOUT])

    async def tunnel_message_to_things(self, scheduler: Scheduler) -> None:
        """
        Drain one scheduler's queue, handing each operation to its `Thing` and answering the caller.

        Runs on the loop that submitted, never on the `Thing`'s - that separation is the whole point,
        and is what keeps the request side responsive however long an operation takes.

        Parameters
        ----------
        scheduler: Scheduler
            the scheduler whose jobs are to be drained
        """
        self.logger.info("started schedulers")
        loop = get_current_async_loop()
        while self._run and scheduler.run:
            # wait for a job first
            if not scheduler.has_job:
                await scheduler.wait_for_job()
                # this means in next loop it wont be in this block as a job arrived
                continue

            invokation_timed_out = False
            job = scheduler.next_job
            job.started.set()  # releases the invokation timeout
            if job.invokation_timeout_task is not None:
                # conditional because sometimes some operations dont ask for an invocation timeout
                # and simply wait arbitrarily long
                invokation_timed_out = await asyncio.wrap_future(job.invokation_timeout_task)
            if invokation_timed_out:
                # the timeout already answered the caller, drop operation
                continue

            # hand the operation to the thing
            scheduler.last_operation_request = job.operation

            # schedule an execution timeout, which answers the caller early but would
            # still unable to interrupt the thing's execution
            execution_timed_out = False
            overdue = None
            if job.operation.execution_timeout is not None:
                overdue = loop.create_task(self._answer_if_overdue(job, job.operation.execution_timeout))

            # always drain the reply, even once a timeout has answered. Abandoning the wait leaves
            # the thing's answer sitting in the scheduler for the next job to pick up as its own.
            await scheduler.wait_for_reply()
            if overdue is not None:
                # cancel() refuses only when the task already ran, i.e. it answered a timeout
                execution_timed_out = not overdue.cancel()

            # check the reply is never undefined, Undefined is a sensible placeholder for the
            # NotImplemented singleton
            if scheduler.last_operation_reply is Undefined:
                # this is a logic error, as the reply should never be undefined
                payload, preserialized_payload = self.format_return_value(
                    dict(exception=format_exception_as_json(RuntimeError("No reply from thing - logic error"))),
                    Serializers.default,
                )
                job.answer(Reply(payload, preserialized_payload, ReplyKind.ERROR))
                continue

            reply = scheduler.last_operation_reply
            scheduler.reset_operation_reply()
            if execution_timed_out:
                # drop the thing's late reply
                continue
            job.answer(reply)

        scheduler.cleanup()
        self.logger.info("stopped schedulers")

    async def run_thing_instance(self, instance: Thing, scheduler: Scheduler | None = None) -> None:
        """
        Run a single `Thing` instance in an infinite loop by allowing the scheduler to schedule operations on it.

        Parameters
        ----------
        instance: Thing
            instance of the `Thing`
        scheduler: Optional[Scheduler]
            scheduler that schedules operations on the `Thing` instance, a default is always available.
        """
        logger = self.logger.bind(cls=instance.__class__.__name__, thing_id=instance.id)
        logger.info("starting to run operations on thing")
        instance.logger.info("waiting to receive operations now")
        # if logger.level >= logging.ERROR:
        # sleep added to resolve some issue with logging related IO bound tasks in asyncio - not really clear what it is.
        # This loop crashes for log levels above ERROR without the following statement
        await asyncio.sleep(0.001)
        # TODO - investigate and fix it
        scheduler = scheduler or self.per_thing_schedulers[instance.id]

        while self._run and scheduler.run:
            # print("starting to serve thing {}".format(instance.id))
            await scheduler.wait_for_operation()
            if scheduler.last_operation_request is Undefined:
                logger.warning("No operation request found although an interruption to wait was made, continuing...")
                continue

            try:
                request: Operation = scheduler.last_operation_request
                thing_id, objekt, operation = request.thing_id, request.objekt, request.operation

                # deserializing the payload required to execute the operation
                payload = request.payload.deserialize()
                preserialized_payload = request.preserialized_payload.value
                instance.logger.debug(f"starting execution of operation {operation} on {objekt}")

                # start activities related to thing execution context
                fetch_execution_logs = request.fetch_execution_logs
                if fetch_execution_logs:
                    list_handler = LogHistoryHandler([])
                    list_handler.setLevel(logging.DEBUG)
                    if isinstance(instance.logger, structlog.stdlib.BoundLoggerBase):
                        stdlib_logger = instance.logger._logger
                    else:
                        stdlib_logger = instance.logger
                    list_handler.setFormatter(stdlib_logger.handlers[0].formatter)
                    stdlib_logger.addHandler(list_handler)

                # execute the operation
                return_value = await self.execute_operation(instance, objekt, operation, payload, preserialized_payload)

                # handle return value
                serializer = Serializers.for_object(thing_id, instance.__class__.__name__, objekt)
                content_type_if_no_serializer = Serializers.get_content_type_for_object(
                    thing_id,
                    instance.__class__.__name__,
                    objekt,
                )
                rpayload, rpreserialized_payload = self.format_return_value(
                    return_value,
                    serializer=serializer,
                    content_type_if_no_serializer=content_type_if_no_serializer,
                )

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value = dict(
                        return_value=rpayload.value,
                        execution_logs=list_handler.log_list,
                    )

                # raise any payload errors now
                rpayload.require_serialized()

                # set reply
                scheduler.last_operation_reply = Reply(rpayload, rpreserialized_payload, ReplyKind.OK)

            except BreakInnerLoop:
                # exit the loop and stop the thing
                instance.logger.info("exiting event loop")

                # send a reply with None return value
                rpayload, rpreserialized_payload = self.format_return_value(None, Serializers.default)

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value = dict(
                        return_value=rpayload.value,
                        execution_logs=list_handler.log_list,
                    )

                # set reply, let the protocol at the border decide how to signal an exit
                scheduler.last_operation_reply = Reply(rpayload, rpreserialized_payload, ReplyKind.EXIT)

                # quit the loop
                break

            except Exception as ex:
                # error occurred while executing the operation
                instance.logger.error(f"error while executing operation - {ex!s}")
                instance.logger.exception(ex)

                # send a reply with error
                rpayload, rpreserialized_payload = self.format_return_value(
                    dict(exception=format_exception_as_json(ex)), Serializers.default
                )

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value["execution_logs"] = list_handler.log_list

                # set error reply
                scheduler.last_operation_reply = Reply(rpayload, rpreserialized_payload, ReplyKind.ERROR)

            finally:
                # cleanup
                if fetch_execution_logs:
                    if isinstance(instance.logger, structlog.stdlib.BoundLoggerBase):
                        stdlib_logger = instance.logger._logger
                    else:
                        stdlib_logger = instance.logger
                    stdlib_logger.removeHandler(list_handler)
                instance.logger.debug(f"completed execution of operation {operation} on {objekt}")
        logger.info("stopped running thing")

    async def execute_operation(
        self,
        instance: Thing,
        objekt: str,
        operation: str,
        payload: Any,
        preserialized_payload: bytes,
    ) -> Any:
        """
        Execute a given operation on a thing instance.

        Parameters
        ----------
        instance: Thing
            instance of the thing
        objekt: str
            name of the property, action or event
        operation: str
            operation to be executed on the property, action or event
        payload: Any
            payload to be used for the operation
        preserialized_payload: bytes
            preserialized payload to be used for the operation

        Returns
        -------
        Any
            the result of the operation on the thing instance
        """
        if operation == Operations.readproperty:
            prop = instance.properties[objekt]  # type: Property
            return getattr(instance, prop.name)
        elif operation == Operations.writeproperty:
            prop: Property = instance.properties[objekt]  # ty: ignore[invalid-assignment]
            if preserialized_payload != b"":
                prop_value = preserialized_payload
            else:
                prop_value = payload
            return prop.external_set(instance, prop_value)
        elif operation == Operations.deleteproperty:
            prop = instance.properties[objekt]  # type: Property
            del prop  # raises NotImplementedError when deletion is not implemented which is mostly the case
        elif operation == Operations.invokeaction and objekt == "get_thing_description":
            # special case
            if payload is None:
                payload = dict()
            args = payload.pop("__args__", tuple())
            return self.get_thing_description(instance, *args, **payload)
        elif operation == Operations.invokeaction:
            if payload is None:
                payload = dict()
            args = payload.pop("__args__", tuple())
            # payload then become kwargs
            if preserialized_payload != b"":
                args = (preserialized_payload,) + args
            action: BoundAction = instance.actions[objekt]  # ty: ignore[invalid-assignment]
            if action.descriptor.iscoroutine:
                # the actual scheduling as a purely async task is done by the scheduler, not here,
                # this will be a blocking call
                return await action.external_call(*args, **payload)
            return action.external_call(*args, **payload)
        elif operation == Operations.readmultipleproperties or operation == Operations.readallproperties:
            if objekt is None:
                return instance.properties.get()
            return instance.properties.get(names=objekt)
        elif operation == Operations.writemultipleproperties or operation == Operations.writeallproperties:
            return instance.properties.set(**payload)
        raise NotImplementedError(f"Unimplemented execution path for Thing {instance.id} for operation {operation}")

    def format_return_value(
        self,
        return_value: Any,
        serializer: BaseSerializer,
        content_type_if_no_serializer: str = "",
    ) -> tuple[SerializableData, PreserializedData]:
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

    def run_things(self, things: list[Thing]):
        """
        Run loop that executes operations on `Thing` instances. This method is blocking and is called by `run()` method.

        Parameters
        ----------
        things: List[Thing]
            list of `Thing` instances to be executed
        """
        thing_executor_loop = get_current_async_loop()
        self.logger.info(f"starting thing in thread {threading.get_ident()} for {[obj.id for obj in things]}")
        thing_executor_loop.run_until_complete(
            asyncio.gather(*[self.run_thing_instance(instance) for instance in things])
        )
        self.logger.info(f"exiting event loop in thread {threading.get_ident()}")
        thing_executor_loop.close()

    def get_thing_model(
        self,
        thing_id: str,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
        """
        Describe one served `Thing` in the only terms the event loop has: affordances, and no forms.

        A Thing Model is a Thing Description without the forms, and forms are the part that names a
        protocol's wire. Every protocol server builds its own description on top of this.

        Read-only introspection of descriptors, so it is answered directly rather than queued behind
        whatever the `Thing` happens to be doing.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` to describe
        ignore_errors: bool
            whether to skip affordances whose metadata cannot be generated
        skip_names: list[str]
            property, action or event names to leave out

        Returns
        -------
        dict[str, Any]
            the Thing Model

        Raises
        ------
        KeyError
            if no `Thing` with that id is being served
        """
        instance = self.things[thing_id]
        return instance.get_thing_model(ignore_errors=ignore_errors, skip_names=skip_names).json()

    def get_thing_description(
        self,
        instance: Thing,
        protocol: str,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
        """
        Get the Thing Description for one served `Thing`.

        An `EventLoop` cannot produce one on its own: a TD is largely forms, and a form is an address on
        some protocol's wire. Whichever protocol server owns this event loop supplies the generator.

        Parameters
        ----------
        instance: Thing
            the `Thing` to describe
        protocol: str
            the protocol to generate forms for, as that protocol names its transports
        ignore_errors: bool
            whether to skip affordances whose forms cannot be generated
        skip_names: list[str]
            property, action or event names to leave out

        Returns
        -------
        dict[str, Any]
            the Thing Description

        Raises
        ------
        NotImplementedError
            if no protocol server is attached to generate the forms
        """
        if self._thing_description_provider is None:
            raise NotImplementedError(
                "this event loop has no protocol server attached, so it cannot generate forms. "
                + "Use the thing model directly, or serve the Thing over a protocol."
            )
        return self._thing_description_provider(
            instance,
            protocol,
            ignore_errors=ignore_errors,
            skip_names=skip_names,
        )

    def attach(self, server: Any) -> None:
        """
        Note that a protocol server is serving this event loop.

        The event loop never calls into a protocol server - it answers futures and leaves the rest alone.
        The list is here so that a `Thing` can find out how it is reachable, which is a question only
        the protocols in front can answer.

        Parameters
        ----------
        server: Any
            a protocol server, typically a `BaseProtocolServer`
        """
        if server not in self.protocol_servers:
            self.protocol_servers.append(server)

    def add_stop_hook(self, callback: Callable[[], None]) -> None:
        """
        Ask to be called when the event loop stops.

        A protocol server registers its socket teardown here, so that stopping the event loop - which
        is what `Thing.exit()` reaches - also stops whatever is sitting in front of it.

        Parameters
        ----------
        callback: Callable[[], None]
            called from `stop()`, on whichever thread stopped the event loop
        """
        if callback not in self._stop_hooks:
            self._stop_hooks.append(callback)

    def run(self, extra_coroutines: Sequence[Coroutine[Any, Any, Any]] = ()) -> None:
        """
        Start & run the event loop. This method is blocking.

        Creates the shared scheduler for each `Thing`, gives each `Thing` a thread of its own, then
        runs the drain loops - along with whatever coroutines a protocol server hands over, which is
        how a socket poller ends up on the same loop the replies are resolved on. Call `stop()`
        (threadsafe) to stop.

        Parameters
        ----------
        extra_coroutines: Sequence[Coroutine]
            coroutines to run beside the drain loops, usually a protocol server's request listeners
        """
        self._run = True
        # recorded before anything can submit, since submissions from other threads land here
        self._loop = get_current_async_loop()
        self.logger.info("starting event loop")
        # only the `Thing`s added directly get a scheduler and a thread; a sub-thing runs within
        # its owner's, which is also why `Thing.exit()` refuses on a composed object
        top_level_things = [thing for thing in self.things.values() if not thing._owners]
        for thing in top_level_things:
            self.per_thing_schedulers[thing.id] = QueuedScheduler(thing, self)
        threads = dict()  # type: dict[int, threading.Thread]
        for thing in top_level_things:
            thread = threading.Thread(target=self.run_things, args=([thing],))
            thread.start()
            threads[thread.ident] = thread
        try:
            loop = self._loop
            existing_tasks = asyncio.all_tasks(loop)
            loop.run_until_complete(
                asyncio.gather(
                    # only the shared per-Thing schedulers exist at startup, the one-shot ones are
                    # created on demand and arrange their own drain loop
                    *[self.tunnel_message_to_things(scheduler) for scheduler in self.per_thing_schedulers.values()],
                    *extra_coroutines,
                    *existing_tasks,
                )
            )
            loop.close()
        finally:
            self._loop = None  # nothing may be scheduled onto a closed loop
            self.stop()
        for thread in threads.values():
            thread.join()
        self.logger.info("event loop stopped")

    def stop(self) -> None:
        """Stop the event loop, and everything hooked onto it. This method is threadsafe."""
        self._run = False
        for hook in self._stop_hooks:
            try:
                hook()
            except Exception as ex:
                self.logger.warning(f"stop hook raised while stopping the event loop - {ex!s}")
        for scheduler in self.per_thing_schedulers.values():
            scheduler.cleanup()

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if not isinstance(other, EventLoop):
            return False
        return self.id == other.id

    def __str__(self):
        return f"EventLoop({self.id}, things: {list(self.things)})"


__all__ = [EventLoop.__name__]
