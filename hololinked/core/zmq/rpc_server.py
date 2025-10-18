import copy
import socket
import zmq
import zmq.asyncio
import asyncio
import typing
import threading
import logging
import tracemalloc
from collections import deque


from ...exceptions import BreakLoop, BreakInnerLoop
from ...constants import ZMQ_TRANSPORTS, Operations
from ...utils import (
    format_exception_as_json,
    get_all_sub_things_recusively,
    get_current_async_loop,
    get_default_logger,
    set_global_event_loop_policy,
)
from ...config import global_config
from ...serializers import Serializers, BaseSerializer
from .message import (
    EMPTY_BYTE,
    ERROR,
    REPLY,
    PreserializedData,
    RequestMessage,
    SerializableData,
)
from .brokers import AsyncZMQServer, BaseZMQServer, EventPublisher
from ..thing import Thing
from ..property import Property  # noqa: F401
from ..properties import TypedDict
from ..actions import BoundAction  # noqa: F401
from ..logger import LogHistoryHandler


if global_config.TRACE_MALLOC:
    tracemalloc.start()

set_global_event_loop_policy()

Undefined = NotImplemented


class RPCServer(BaseZMQServer):
    """
    The `RPCServer` implements a infinite loop where ZMQ sockets listen for messages, in any transport layer possible
    (`INPROC`, `IPC` or `TCP`). Once requests are received, jobs are dispatched to the `Thing` instances which are being served,
    with timeouts or any other execution requirements (called execution context). After being executed by a `Thing` instance,
    the results are then sent back to the client. Execution information include `Thing` ID, the property, action or
    event to be executed (events are usually PUB-SUB and are largely handled by the `EventPublisher` directly),
    what operation to do on them (i.e. `readproperty`, `invokeaction` etc.), the payload and the execution contexts (like timeouts).
    This is structured as a JSON.

    Jobs determine how to execute the operations on the `Thing` instance, whether in queued, async or threaded modes.
    This is their main function. Queued mode is the default as it is assumed that multiple physical operations in the physical world
    is not always practical.

    Default ZMQ transport layer is `INPROC`, but `IPC` or `TCP` can also be added simultaneously using `ZMQServer`
    instance instead of `RPCServer`. The purpose of `INPROC` being default is that, the `RPCServer` is the only server
    implementing the operations directly on the `Thing`
    instances. All other protocols like HTTP, MQTT, CoAP etc. will be used to redirect requests to the `RPCServer` only
    and do not directly operate on the `Thing` instances. Instead, the incoming requests in those protocols are converted
    to the above stated "Jobs" which are in JSON format.

    `INPROC` is the fastest and most efficient way to communicate between multiple independently running loops,
    whether the loop belongs to a specific protocol's request listener or the `RPCServer` itself, as it used shared memory.
    The same `INPROC` messaging contract is also used for `IPC` and `TCP`, thus eliminating the
    need to separately implement messaging contracts at different layers of communication for ZMQ.

    Therefore, if a `Thing` instance is to be served by a well known protocol, say HTTP, the server behaves like HTTP-RPC.

    [UML Diagram](http://docs.hololinked.dev/UML/PDF/RPCServer.pdf)
    """

    things = TypedDict(
        key_type=(str,),
        item_type=(Thing,),
        bounds=(0, 100),
        allow_None=True,
        default=None,
        doc="list of Things which are being executed",
        remote=False,
    )  # type: typing.Dict[str, Thing]

    def __init__(
        self,
        *,
        id: str,
        things: typing.List[Thing],
        context: zmq.asyncio.Context | None = None,
        access_point: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.INPROC,
        **kwargs: typing.Dict[str, typing.Any],
    ) -> None:
        """
        Parameters
        ----------
        id: str
            `id` of the server
        things: List[Thing]
            list of `Thing` instances to be served
        context: Optional, zmq.asyncio.Context
            ZeroMQ async Context object to use. Automatically created when None is supplied.
        access_point: ZMQ_TRANSPORTS
            transport layer to be used for the server, default is `INPROC`
        """
        super().__init__(id=id, **kwargs)
        self.things = dict()
        for thing in things:
            self.things[thing.id] = thing

        if isinstance(access_point, str):
            access_point = access_point.upper()

        if self.logger is None:
            self.logger = get_default_logger(
                "{}|{}|{}|{}".format(self.__class__.__name__, "RPC", "MIXED", self.id),
                kwargs.get("log_level", logging.INFO),
            )
            kwargs["logger"] = self.logger

        self._run = False  # flag to stop all the servers
        self.context = context or global_config.zmq_context()

        self.req_rep_server = AsyncZMQServer(
            id=self.id,
            context=self.context,
            access_point=access_point,
            poll_timeout=1000,
            **kwargs,
        )
        self.event_publisher = EventPublisher(
            id=f"{self.id}/event-publisher",
            context=self.context,
            access_point=access_point,
            **kwargs,
        )
        self.schedulers = dict()

        # setup scheduling requirements
        for instance in self.things.values():
            all_things = get_all_sub_things_recusively(instance)
            for instance in all_things:
                assert isinstance(instance, Thing), "instance must be of type Thing"
                instance.rpc_server = self
                for action in instance.actions.descriptors.values():
                    if action.execution_info.iscoroutine and not action.execution_info.synchronous:
                        self.schedulers[f"{instance.id}.{action.name}.invokeAction"] = AsyncScheduler
                    elif not action.execution_info.synchronous:
                        self.schedulers[f"{instance.id}.{action.name}.invokeAction"] = ThreadedScheduler
                    # else QueuedScheduler which is default
                # properties need not dealt yet, but may be in future

    schedulers: typing.Dict[str, "QueuedScheduler"]

    def __post_init__(self):
        super().__post_init__()
        self.logger.info("Server with name '{}' can be started using run().".format(self.id))

    @property
    def is_running(self) -> bool:
        """Check if the server is running or not."""
        return self._run

    async def recv_requests_and_dispatch_jobs(self, server: AsyncZMQServer) -> None:
        """
        Continuously receives messages from different clients and dispatches them as jobs according to the specific
        requirements of a how an object (property/action/event) must be executed (queued/threaded/async).
        Also handles messages that dont need separate jobs like `HANDSHAKE`, `EXIT`, timeouts etc.

        Parameters
        ----------
        server: AsyncZMQServer
            the server instance to poll for requests
        """
        self.logger.debug("started polling with server {} at socket {}".format(server.id, server.socket_address))
        eventloop = asyncio.get_event_loop()
        while self._run:
            try:
                request_messages = await server.poll_requests()
                # when stop poll is set, this will exit with an empty list
            except BreakLoop:
                break
            except Exception as ex:
                self.logger.error(f"exception occurred while polling for server '{server.id}' - {str(ex)}")
                continue

            for request_message in request_messages:
                try:
                    # handle invokation timeout
                    invokation_timeout = request_message.server_execution_context.get("invokation_timeout", None)

                    ready_to_process_event = None
                    timeout_task = None
                    if invokation_timeout is not None:
                        ready_to_process_event = asyncio.Event()
                        timeout_task = asyncio.create_task(
                            self._process_timeouts(
                                request_message=request_message,
                                ready_to_process_event=ready_to_process_event,
                                timeout=invokation_timeout,
                                origin_server=server,
                                timeout_type="invokation",
                            )
                        )
                        eventloop.call_soon(lambda: timeout_task)

                    # check object level scheduling requirements and schedule the message
                    # append to messages list - message, event, timeout task, origin socket
                    job = (
                        server,
                        request_message,
                        timeout_task,
                        ready_to_process_event,
                    )  # type: Scheduler.JobInvokationType
                    if request_message.qualified_operation in self.schedulers:
                        scheduler = self.schedulers[request_message.qualified_operation](
                            self.things[request_message.thing_id], self
                        )
                    else:
                        scheduler = self.schedulers[request_message.thing_id]
                    scheduler.dispatch_job(job)

                except Exception as ex:
                    # handle invalid message
                    self.logger.error(f"exception occurred for message id '{request_message.id}' - {str(ex)}")
                    invalid_message_task = asyncio.create_task(
                        server._handle_invalid_message(request_message=request_message, exception=ex)
                    )
                    eventloop.call_soon(lambda: invalid_message_task)
        self.stop()
        self.logger.info(f"stopped polling for server '{server.id}' {server.socket_address.split(':')[0].upper()}")

    async def tunnel_message_to_things(self, scheduler: "Scheduler") -> None:
        """message tunneler/coordinator between external sockets listening thread and `Thing` object executor thread"""
        eventloop = get_current_async_loop()
        while self._run and scheduler.run:
            # wait for message first
            if not scheduler.has_job:
                await scheduler.wait_for_job()
                # this means in next loop it wont be in this block as a message arrived
                continue

            # retrieve from messages list - message, execution context, event, timeout task, origin socket
            origin_server, request_message, timeout_task, ready_to_process_event = scheduler.next_job
            server_execution_context = request_message.server_execution_context

            # handle invokation timeout
            invokation_timed_out = True
            if ready_to_process_event is not None:
                ready_to_process_event.set()  # releases timeout task
                invokation_timed_out = await timeout_task
            if ready_to_process_event is not None and invokation_timed_out:
                # drop call to thing, timeout message was already sent in _process_timeouts()
                continue

            # handle execution through thing
            scheduler.last_operation_request = scheduler.extract_operation_tuple_from_request(request_message)

            # schedule an execution timeout
            execution_timeout = server_execution_context.get("execution_timeout", None)
            execution_completed_event = None
            execution_timeout_task = None
            execution_timed_out = True
            if execution_timeout is not None:
                execution_completed_event = asyncio.Event()
                execution_timeout_task = asyncio.create_task(
                    self._process_timeouts(
                        request_message=request_message,
                        ready_to_process_event=execution_completed_event,
                        timeout=execution_timeout,
                        origin_server=origin_server,
                        timeout_type="execution",
                    )
                )
                eventloop.call_soon(lambda: execution_timeout_task)

            # always wait for reply from thing, since this loop is asyncio task (& in its own thread in RPC server),
            # timeouts always reach client without truly blocking by the GIL. If reply does not arrive, all other requests
            # get invokation timeout.
            # await eventloop.run_in_executor(None, scheduler.wait_for_reply)
            await scheduler.wait_for_reply(eventloop)
            # check if reply is never undefined, Undefined is a sensible placeholder for NotImplemented singleton
            if scheduler.last_operation_reply is Undefined:
                # this is a logic error, as the reply should never be undefined
                await origin_server._handle_error_message(
                    request_message=request_message,
                    exception=RuntimeError("No reply from thing - logic error"),
                )
                continue
            payload, preserialized_payload, reply_message_type = scheduler.last_operation_reply
            scheduler.reset_operation_reply()

            # check if execution completed within time
            if execution_completed_event is not None:
                execution_completed_event.set()  # releases timeout task
                execution_timed_out = await execution_timeout_task
            if execution_timeout_task is not None and execution_timed_out:
                # drop reply to client as timeout was already sent
                continue
            if server_execution_context.get("oneway", False):
                # drop reply if oneway
                continue

            # send reply to client
            await origin_server.async_send_response_with_message_type(
                request_message=request_message,
                message_type=reply_message_type,
                payload=payload,
                preserialized_payload=preserialized_payload,
            )

        scheduler.cleanup()
        self.logger.info("stopped tunneling messages to things")

    async def run_thing_instance(self, instance: Thing, scheduler: typing.Optional["Scheduler"] = None) -> None:
        """
        run a single `Thing` instance in an infinite loop by allowing the scheduler to schedule operations on it.

        Parameters
        ----------
        instance: Thing
            instance of the `Thing`
        scheduler: Optional[Scheduler]
            scheduler that schedules operations on the `Thing` instance, a default is always available.
        """
        self.logger.info(
            "starting to run operations on thing {} of class {}".format(instance.id, instance.__class__.__name__)
        )
        if self.logger.level >= logging.ERROR:
            # sleep added to resolve some issue with logging related IO bound tasks in asyncio - not really clear what it is.
            # This loop crashes for log levels above ERROR without the following statement
            await asyncio.sleep(0.001)
            # TODO - investigate and fix it
        scheduler = scheduler or self.schedulers[instance.id]
        eventloop = get_current_async_loop()

        while self._run and scheduler.run:
            # print("starting to serve thing {}".format(instance.id))
            await scheduler.wait_for_operation(eventloop)
            # await scheduler.wait_for_operation()
            if scheduler.last_operation_request is Undefined:
                instance.logger.warning("No operation request found in thing '{}'".format(instance.id))
                continue

            try:
                # fetch operation_request which is a tuple of
                # (thing_id, objekt, operation, payload, preserialized_payload, execution_context)
                (
                    thing_id,
                    objekt,
                    operation,
                    payload,
                    preserialized_payload,
                    execution_context,
                ) = scheduler.last_operation_request

                # deserializing the payload required to execute the operation
                payload = payload.deserialize()
                preserialized_payload = preserialized_payload.value
                instance.logger.debug(
                    f"thing {instance.id} with {thing_id} starting execution of operation {operation} on {objekt}"
                )

                # start activities related to thing execution context
                fetch_execution_logs = execution_context.pop("fetch_execution_logs", False)
                if fetch_execution_logs:
                    list_handler = LogHistoryHandler([])
                    list_handler.setLevel(logging.DEBUG)
                    list_handler.setFormatter(instance.logger.handlers[0].formatter)
                    instance.logger.addHandler(list_handler)

                # execute the operation
                return_value = await self.execute_operation(instance, objekt, operation, payload, preserialized_payload)

                # handle return value
                serializer = Serializers.for_object(thing_id, instance.__class__.__name__, objekt)
                rpayload, rpreserialized_payload = self.format_return_value(return_value, serializer=serializer)

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value = dict(return_value=rpayload.value, execution_logs=list_handler.log_list)

                # raise any payload errors now
                rpayload.require_serialized()

                # set reply
                scheduler.last_operation_reply = (rpayload, rpreserialized_payload, REPLY)

            except BreakInnerLoop:
                # exit the loop and stop the thing
                instance.logger.info(
                    "Thing {} with id {} exiting event loop.".format(instance.__class__.__name__, instance.id)
                )

                # send a reply with None return value
                rpayload, rpreserialized_payload = self.format_return_value(None, Serializers.json)

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value = dict(return_value=rpayload.value, execution_logs=list_handler.log_list)

                # set reply, let the message broker decide
                scheduler.last_operation_reply = (rpayload, rpreserialized_payload, None)

                # quit the loop
                break

            except Exception as ex:
                # error occurred while executing the operation
                instance.logger.error(
                    "Thing {} with ID {} produced error : {} - {}.".format(
                        instance.__class__.__name__, instance.id, type(ex), ex
                    )
                )

                # send a reply with error
                rpayload, rpreserialized_payload = self.format_return_value(
                    dict(exception=format_exception_as_json(ex)), Serializers.json
                )

                # complete thing execution context
                if fetch_execution_logs:
                    rpayload.value["execution_logs"] = list_handler.log_list

                # set error reply
                scheduler.last_operation_reply = (rpayload, rpreserialized_payload, ERROR)

            finally:
                # cleanup
                if fetch_execution_logs:
                    instance.logger.removeHandler(list_handler)
                instance.logger.debug(
                    "thing {} with id {} completed execution of operation {} on {}".format(
                        instance.__class__.__name__, instance.id, operation, objekt
                    )
                )
        self.logger.info("stopped running thing {}".format(instance.id))

    async def execute_operation(
        self,
        instance: Thing,
        objekt: str,
        operation: str,
        payload: typing.Any,
        preserialized_payload: bytes,
    ) -> typing.Any:
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
        """
        if operation == Operations.readproperty:
            prop = instance.properties[objekt]  # type: Property
            return getattr(instance, prop.name)
        elif operation == Operations.writeproperty:
            prop = instance.properties[objekt]  # type: Property
            if preserialized_payload != EMPTY_BYTE:
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
            if preserialized_payload != EMPTY_BYTE:
                args = (preserialized_payload,) + args
            action = instance.actions[objekt]  # type: BoundAction
            if action.execution_info.iscoroutine:
                # the actual scheduling as a purely async task is done by the scheduler, not here,
                # this will be a blocking call
                return await action.external_call(*args, **payload)
            return action.external_call(*args, **payload)
        elif operation == Operations.readmultipleproperties or operation == Operations.readallproperties:
            if objekt is None:
                return instance.properties.get()
            return instance.properties.get(names=objekt)
        elif operation == Operations.writemultipleproperties or operation == Operations.writeallproperties:
            return instance.properties.set(payload)
        raise NotImplementedError(
            "Unimplemented execution path for Thing {} for operation {}".format(instance.id, operation)
        )

    def format_return_value(
        self,
        return_value: typing.Any,
        serializer: BaseSerializer,
    ) -> tuple[SerializableData, PreserializedData]:
        if (
            isinstance(return_value, tuple)
            and len(return_value) == 2
            and (isinstance(return_value[1], bytes) or isinstance(return_value[1], PreserializedData))
        ):
            payload = SerializableData(return_value[0], serializer=serializer, content_type=serializer.content_type)
            if isinstance(return_value[1], bytes):
                preserialized_payload = PreserializedData(return_value[1])
        elif isinstance(return_value, bytes):
            payload = SerializableData(None, content_type="application/json")
            preserialized_payload = PreserializedData(return_value)
        elif isinstance(return_value, PreserializedData):
            payload = SerializableData(None, content_type="application/json")
            preserialized_payload = return_value
        else:
            payload = SerializableData(return_value, serializer=serializer, content_type=serializer.content_type)
            preserialized_payload = PreserializedData(EMPTY_BYTE, content_type="text/plain")
        return payload, preserialized_payload

    async def _process_timeouts(
        self,
        request_message: RequestMessage,
        ready_to_process_event: asyncio.Event,
        origin_server: AsyncZMQServer,
        timeout: float | int | None,
        timeout_type: str,
    ) -> bool:
        """
        replies timeout to client if timeout occured along with returning `True` to indicate that.
        If timeout did not occur, the `ready_to_process_event` is set to indicate that the operation can be processed.
        `False` is returned in this case.
        """
        try:
            await asyncio.wait_for(ready_to_process_event.wait(), timeout)
            return False
        except TimeoutError:
            await origin_server._handle_timeout(request_message, timeout_type)
            return True

    def run_zmq_request_listener(self):
        """
        Runs ZMQ's socket polling in an async loop. This method is blocking and is automatically called by `run()`
        method. Please dont call this method when the async loop is already running.
        """
        self.logger.info("starting external message listener thread")
        eventloop = get_current_async_loop()
        existing_tasks = asyncio.all_tasks(eventloop)
        eventloop.run_until_complete(
            asyncio.gather(
                self.recv_requests_and_dispatch_jobs(self.req_rep_server),
                *[self.tunnel_message_to_things(scheduler) for scheduler in self.schedulers.values()],
                *existing_tasks,
            )
        )
        self.logger.info("exiting external listener event loop {}".format(self.id))
        eventloop.close()

    def run_things(self, things: typing.List[Thing]):
        """
        Run loop that executes operations on `Thing` instances. This method is blocking and is called by `run()` method.

        Parameters
        ----------
        things: List[Thing]
            list of `Thing` instances to be executed
        """
        thing_executor_loop = get_current_async_loop()
        self.logger.info(
            f"starting thing executor loop in thread {threading.get_ident()} for {[obj.id for obj in things]}"
        )
        thing_executor_loop.run_until_complete(
            asyncio.gather(*[self.run_thing_instance(instance) for instance in things])
        )
        self.logger.info(f"exiting event loop in thread {threading.get_ident()}")
        thing_executor_loop.close()

    def run(self):
        """
        Start & run the server. This method is blocking.
        Creates job schedulers for each `Thing`, dispatches each `Thing` to its own thread and starts the ZMQ sockets
        request polling loop. Call `stop()` (threadsafe) to stop the server.
        """
        self._run = True
        self.logger.info(f"starting RPC server {self.id}")
        for thing in self.things.values():
            self.schedulers[thing.id] = QueuedScheduler(thing, self)
        threads = dict()  # type: typing.Dict[int, threading.Thread]
        for thing in self.things.values():
            thread = threading.Thread(target=self.run_things, args=([thing],))
            thread.start()
            threads[thread.ident] = thread
        self.run_zmq_request_listener()
        for thread in threads.values():
            thread.join()
        self.logger.info(f"server stopped {self.id}")

    def stop(self):
        """Stop the server. This method is threadsafe."""
        self._run = False
        self.req_rep_server.stop_polling()
        for scheduler in self.schedulers.values():
            scheduler.cleanup()

    def exit(self):
        """Stop and try to clean up resources used by the server."""
        try:
            self.stop()
            if self.req_rep_server is not None:
                self.req_rep_server.exit()
            if self.event_publisher is not None:
                self.event_publisher.exit()
        except Exception as ex:
            self.logger.warning(f"Exception occurred while exiting the server - {str(ex)}")

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if not isinstance(other, RPCServer):
            return False
        return self.id == other.id

    def __str__(self):
        return f"RPCServer({self.id}, req-rep: {self.req_rep_server.socket_address}, pub-sub: {self.event_publisher.socket_address})"

    def get_thing_description(
        self,
        instance: Thing,
        protocol: str,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, typing.Any]:
        """
        Get the Thing Description (TD) for a specific Thing instance.

        Parameters
        ----------
        instance: Thing
            The Thing instance for which to retrieve the TD
        protocol: str
            The protocol for which to generate the TD - `INPROC`, `IPC` or `TCP`
        ignore_errors: bool
            Whether to ignore errors while generating the TD. Default is False.
        skip_names: List[str]
            List of property, action or event names to skip while generating the TD. Default is empty list.

        Returns
        -------
        JSON
            The Thing Description in JSON format.
        """
        TM = instance.get_thing_model(ignore_errors=ignore_errors, skip_names=skip_names).json()  # type: dict[str, typing.Any]
        TD = copy.deepcopy(TM)
        from ...td import PropertyAffordance, ActionAffordance, EventAffordance
        from ...td.forms import Form

        if protocol.lower() == "inproc":
            req_rep_socket_address = self.req_rep_server.socket_address
            pub_sub_socket_address = self.event_publisher.socket_address
        elif protocol.lower() == "ipc":
            if not hasattr(self, "ipc_server"):
                raise RuntimeError(
                    "This server cannot generate TD for IPC protocol, consider using thing model directly."
                )
            req_rep_socket_address = self.ipc_server.socket_address
            pub_sub_socket_address = self.ipc_event_publisher.socket_address
        elif protocol.lower() == "tcp":
            if not hasattr(self, "tcp_server"):
                raise RuntimeError(
                    "This server cannot generate TD for TCP protocol, consider using thing model directly."
                )
            req_rep_socket_address = self.tcp_server.socket_address  # type: str
            req_rep_socket_address = req_rep_socket_address.replace("*", socket.gethostname()).replace(
                "0.0.0.0", socket.gethostname()
            )
            pub_sub_socket_address = self.tcp_event_publisher.socket_address  # type: str
            pub_sub_socket_address = pub_sub_socket_address.replace("*", socket.gethostname()).replace(
                "0.0.0.0", socket.gethostname()
            )
        else:
            raise ValueError(f"Unsupported protocol '{protocol}' for ZMQ.")

        for name in TM.get("properties", []):
            affordance = PropertyAffordance.from_TD(name, TM)
            if not TD["properties"][name].get("forms", None):
                TD["properties"][name]["forms"] = []

            form = Form()
            form.href = req_rep_socket_address
            form.op = Operations.readproperty
            form.contentType = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
            TD["properties"][name]["forms"].append(form.json())

            if not affordance.readOnly:
                form = Form()
                form.href = req_rep_socket_address
                form.op = Operations.writeproperty
                form.contentType = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
                TD["properties"][name]["forms"].append(form.json())

            if affordance.observable:
                form = Form()
                form.href = pub_sub_socket_address
                form.op = Operations.observeproperty
                form.contentType = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
                TD["properties"][name]["forms"].append(form.json())

        for name in TM.get("actions", []):
            affordance = ActionAffordance.from_TD(name, TM)
            if not TD["actions"][name].get("forms", None):
                TD["actions"][name]["forms"] = []

            form = Form()
            form.href = req_rep_socket_address
            form.op = Operations.invokeaction
            form.contentType = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
            TD["actions"][name]["forms"].append(form.json())

        for name in TM.get("events", []):
            affordance = EventAffordance.from_TD(name, TM)
            if not TD["events"][name].get("forms", None):
                TD["events"][name]["forms"] = []

            form = Form()
            form.href = pub_sub_socket_address
            form.op = Operations.subscribeevent
            form.contentType = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
            TD["events"][name]["forms"].append(form.json())

        return TD


class Scheduler:
    """
    Scheduler class to schedule the operations of a thing either in queued mode, or a one-shot mode in either
    async or threaded loops.

    [UML Diagram](http://docs.hololinked.dev/UML/PDF/RPCServer.pdf)

    [UML Diagram subclasses](http://docs.hololinked.dev/UML/PDF/Scheduler.pdf)
    """

    OperationRequest = typing.Tuple[str, str, str, SerializableData, PreserializedData, typing.Dict[str, typing.Any]]
    OperationReply = typing.Tuple[SerializableData, PreserializedData, str]
    JobInvokationType = typing.Tuple[AsyncZMQServer, RequestMessage, asyncio.Task, asyncio.Event]
    # [UML Diagram](http://docs.hololinked.dev/UML/PDF/RPCServer.pdf)
    _operation_execution_complete_event: asyncio.Event | threading.Event
    _operation_execution_ready_event: asyncio.Event | threading.Event

    def __init__(self, instance: Thing, rpc_server: RPCServer) -> None:
        self.instance = instance  # type: Thing
        self.rpc_server = rpc_server  # type: RPCServer
        self.run = True  # type: bool
        self._one_shot = False  # type: bool
        self._last_operation_request = Undefined  # type: Scheduler.OperationRequest
        self._last_operation_reply = Undefined  # type: Scheduler.OperationRequest
        self._job_queued_event = asyncio.Event()  # type: asyncio.Event

    @property
    def last_operation_request(self) -> OperationRequest:
        return self._last_operation_request

    @last_operation_request.setter
    def last_operation_request(self, value: OperationRequest):
        self._last_operation_request = value
        self._operation_execution_ready_event.set()

    def reset_operation_request(self) -> None:
        self._last_operation_request = Undefined

    @property
    def last_operation_reply(self) -> OperationReply:
        return self._last_operation_reply

    @last_operation_reply.setter
    def last_operation_reply(self, value: OperationReply):
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

    async def wait_for_operation(self, eventloop: asyncio.AbstractEventLoop | None) -> None:
        # assert isinstance(self._operation_execution_ready_event, threading.Event), "not a threaded scheduler"
        if isinstance(self._operation_execution_ready_event, threading.Event):
            await eventloop.run_in_executor(None, self._operation_execution_ready_event.wait)
        else:
            await self._operation_execution_ready_event.wait()
        self._operation_execution_ready_event.clear()

    async def wait_for_reply(self, eventloop: asyncio.AbstractEventLoop | None) -> None:
        if isinstance(self._operation_execution_complete_event, threading.Event):
            await eventloop.run_in_executor(None, self._operation_execution_complete_event.wait)
        else:
            await self._operation_execution_complete_event.wait()
        self._operation_execution_complete_event.clear()

    @property
    def has_job(self) -> bool:
        raise NotImplementedError("has_job method must be implemented in the subclass")

    @property
    def next_job(self) -> JobInvokationType:
        raise NotImplementedError("next_job method must be implemented in the subclass")

    def dispatch_job(self, job: JobInvokationType) -> None:
        raise NotImplementedError("dispatch_job method must be implemented in the subclass")

    def cleanup(self):
        self.run = False
        self._job_queued_event.set()
        self._operation_execution_ready_event.set()
        self._operation_execution_complete_event.set()

    @classmethod
    def extract_operation_tuple_from_request(self, request_message: RequestMessage) -> OperationRequest:
        """thing execution info"""
        return (
            request_message.header["thingID"],
            request_message.header["objekt"],
            request_message.header["operation"],
            request_message.body[0],
            request_message.body[1],
            request_message.header["thingExecutionContext"],
        )

    @classmethod
    def format_reply_tuple(self, return_value: typing.Any) -> OperationReply:
        pass


class QueuedScheduler(Scheduler):
    """
    Scheduler class to schedule the operations of a thing in a queued loop.
    """

    def __init__(self, instance: Thing, rpc_server: RPCServer) -> None:
        super().__init__(instance, rpc_server)
        self.queue = deque()
        self._one_shot = False
        self._operation_execution_ready_event = threading.Event()
        self._operation_execution_complete_event = threading.Event()

    @property
    def has_job(self) -> bool:
        return len(self.queue) > 0

    @property
    def next_job(self) -> Scheduler.JobInvokationType:
        return self.queue.popleft()

    def dispatch_job(self, job: Scheduler.JobInvokationType) -> None:
        """
        append a request message to the queue after ticking the invokation timeout clock

        Parameters
        ----------
        job: Tuple[RequestMessage, asyncio.Event, asyncio.Task, AsyncZMQServer]
            tuple of request message, event to indicate if request message can be executed, invokation timeout task
            and originating server of the request
        """
        self.queue.append(job)
        self._job_queued_event.set()

    def cleanup(self):
        self.queue.clear()
        return super().cleanup()


class AsyncScheduler(Scheduler):
    """
    Scheduler class to schedule the operations of a thing in an async loop.
    """

    def __init__(self, instance: Thing, rpc_server: RPCServer) -> None:
        super().__init__(instance, rpc_server)
        self._job = None
        self._one_shot = True
        self._operation_execution_ready_event = asyncio.Event()
        self._operation_execution_complete_event = asyncio.Event()

    @property
    def has_job(self) -> bool:
        return self._job is not None

    @property
    def next_job(self) -> Scheduler.JobInvokationType:
        if self._job is None:
            raise RuntimeError("No job to execute")
        return self._job

    def dispatch_job(self, job: Scheduler.JobInvokationType) -> None:
        self._job = job
        eventloop = get_current_async_loop()
        eventloop.call_soon(lambda: asyncio.create_task(self.rpc_server.tunnel_message_to_things(self)))
        eventloop.call_soon(lambda: asyncio.create_task(self.rpc_server.run_thing_instance(self.instance, self)))
        self._job_queued_event.set()


class ThreadedScheduler(Scheduler):
    """
    Scheduler class to schedule the operations of a thing in a threaded loop.
    """

    def __init__(self, instance: Thing, rpc_server: RPCServer) -> None:
        super().__init__(instance, rpc_server)
        self._job = None
        self._execution_thread = None
        self._one_shot = True
        self._operation_execution_ready_event = threading.Event()
        self._operation_execution_complete_event = threading.Event()

    @property
    def has_job(self) -> bool:
        return self._job is not None

    @property
    def next_job(self) -> Scheduler.JobInvokationType:
        if self._job is None:
            raise RuntimeError("No job to execute")
        return self._job

    def dispatch_job(self, job: Scheduler.JobInvokationType) -> None:
        """"""
        self._job = job
        eventloop = get_current_async_loop()
        eventloop.call_soon(lambda: asyncio.create_task(self.rpc_server.tunnel_message_to_things(self)))
        self._execution_thread = threading.Thread(
            target=asyncio.run,
            args=(self.rpc_server.run_thing_instance(self.instance, self),),
        )
        self._execution_thread.start()
        self._job_queued_event.set()


def prepare_rpc_server(
    instance: Thing,
    access_points: str = ZMQ_TRANSPORTS.IPC,
    context: zmq.asyncio.Context | None = None,
    **kwargs,
) -> None:
    # expose_eventloop: bool, False
    #     expose the associated Eventloop which executes the object. This is generally useful for remotely
    #     adding more objects to the same event loop.
    # dont specify http server as a kwarg, as the other method run_with_http_server has to be used
    if context is not None and not isinstance(context, zmq.asyncio.Context):
        raise TypeError("context must be an instance of zmq.asyncio.Context")
    context = context or global_config.zmq_context()

    if access_points == "INPROC" or access_points == ZMQ_TRANSPORTS.INPROC:
        RPCServer(id=instance.id, things=[instance], context=context, logger=instance.logger)
    else:
        from ...server.zmq import ZMQServer

        ZMQServer(
            id=instance.id,
            things=[instance],
            context=context,
            access_points=access_points,
            logger=instance.logger,
        )


__all__ = [RPCServer.__name__]
