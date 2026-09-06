"""ZeroMQ server exposing `Thing`s over IPC, TCP and INPROC transport."""

from __future__ import annotations

from functools import partial
from typing import Any

import structlog
import zmq.asyncio

from hololinked import Serializers

from ...config import global_config
from ...constants import ZMQ_TRANSPORTS, Operations
from ...core.eventloop import EventLoop, Operation, Reply, ReplyKind
from ...core.eventloop.operations import as_execution_kwargs, format_return_value
from ...core.exceptions import BreakLoop
from ...core.properties import ClassSelector
from ...core.thing import Thing
from ...utils import format_exception_as_json, get_current_async_loop
from ..server import BaseProtocolServer
from .brokers import AsyncZMQServer, EventPublisher
from .config import RuntimeConfig
from .message import ERROR, REPLY, RequestMessage
from .services import ThingDescriptionService


_ZMQ_MESSAGE_TYPE_FOR_REPLY = {
    ReplyKind.OK: REPLY,
    ReplyKind.ERROR: ERROR,
    ReplyKind.EXIT: None,  # let the broker decide, as it did before
}
"""How a `Reply` maps onto ZMQ's message-type vocabulary. The event loop does not know these."""


class ZMQServer(BaseProtocolServer):
    """ZeroMQ server exposing `Thing`s over IPC, TCP and INPROC transport."""

    context: zmq.asyncio.Context

    config = ClassSelector(
        class_=RuntimeConfig,
        default=None,
        allow_None=True,
    )  # type: RuntimeConfig
    """Runtime configuration for the ZMQ server. See `hololinked.server.zmq.config.RuntimeConfig` for details"""

    def __init__(
        self,
        *,
        id: str,
        access_points: ZMQ_TRANSPORTS | str | list[ZMQ_TRANSPORTS | str] = ZMQ_TRANSPORTS.IPC,
        things: list[Thing] | None = None,
        context: zmq.asyncio.Context | None = None,
        config: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """
        Initialize the ZeroMQ server.

        Parameters
        ----------
        id: str
            Unique identifier for the server instance. Required for routing.
        access_points: ZMQ_TRANSPORTS or list[ZMQ_TRANSPORTS], default ZMQ_TRANSPORTS.IPC
            Transport protocols for communication. Supported values are `ZMQ_TRANSPORTS.INPROC`,
            `ZMQ_TRANSPORTS.IPC`, `ZMQ_TRANSPORTS.TCP` or a TCP socket address `tcp://*:<port>`.
            Can be a single value or a list of values.
        things: list[Thing]
            List of `Thing` instances to be served.
        context: zmq.asyncio.Context, optional
            ZeroMQ context for socket management. If `None`, a global context is used.
        config: dict[str, Any], optional
            Additional runtime configuration, see `RuntimeConfig` under `hololinked.server.zmq.config`.
            Its attributes may also be given as keyword arguments.
        **kwargs
            Additional keyword arguments for server configuration. Usually:

            - `logger`: `structlog.stdlib.BoundLogger`, custom logger instance.
            - `poll_timeout`: `int`, polling timeout in milliseconds.

        Raises
        ------
        TypeError
            if `access_points` is neither a transport, a socket address, nor a list of them
        RuntimeError
            if a TCP server or event publisher was created without a socket address
        """
        self.inproc_server = self.ipc_server = self.tcp_server = None
        self.inproc_event_publisher = self.ipc_event_publisher = self.tcp_event_publisher = None
        tcp_socket_address = None

        logger = kwargs.get("logger", None)
        if not logger:
            logger = structlog.get_logger().bind(component="zmq-server")
            kwargs["logger"] = logger

        default_config: dict[str, Any] = dict(
            thing_description_service=kwargs.pop("thing_description_service", ThingDescriptionService),
        )
        default_config.update(config or dict())

        super().__init__(id=id, logger=logger, config=RuntimeConfig(**default_config))
        self.logger = logger

        self._published_event_ids = set()  # type: set[str]

        self.context = context or global_config.zmq_context()

        if isinstance(access_points, str):
            requested_access_points = [access_points]
        elif isinstance(access_points, list):
            requested_access_points = list(access_points)
        else:
            raise TypeError(f"unsupported transport type : {type(access_points)}")

        transports = []  # type: list[str]
        for transport in requested_access_points:
            if isinstance(transport, str) and len(transport) in [3, 6]:
                transports.append(transport.upper())
            elif transport.lower().startswith("tcp://"):
                transports.append("TCP")
                tcp_socket_address = transport
            else:
                transports.append(transport)

        if ZMQ_TRANSPORTS.INPROC in transports or "INPROC" in transports:
            self.inproc_server = AsyncZMQServer(
                id=self.id,
                context=self.context,
                access_point=ZMQ_TRANSPORTS.INPROC,
                poll_timeout=1000,
                **kwargs,
            )
            self.inproc_event_publisher = EventPublisher(
                id=f"{self.id}{EventPublisher._standard_address_suffix}",
                context=self.context,
                access_point=ZMQ_TRANSPORTS.INPROC,
                **kwargs,
            )
        if ZMQ_TRANSPORTS.TCP in transports or "TCP" in transports:
            self.tcp_server = AsyncZMQServer(
                id=self.id,
                context=self.context,
                access_point=tcp_socket_address or ZMQ_TRANSPORTS.TCP,
                **kwargs,
            )
            if not self.tcp_server.socket_address:
                raise RuntimeError("TCP server was created without a socket address")
            host, port = self.tcp_server.socket_address.rsplit(":", 1)
            new_port = int(port) + 1  # try the next port for the event publisher
            tcp_socket_address = f"{host}:{new_port}"
            self.tcp_event_publisher = EventPublisher(
                id=f"{self.id}{EventPublisher._standard_address_suffix}",
                context=self.context,
                transport=ZMQ_TRANSPORTS.TCP,
                access_point=tcp_socket_address,
                **kwargs,
            )
        if ZMQ_TRANSPORTS.IPC in transports or "IPC" in transports:
            self.ipc_server = AsyncZMQServer(
                id=self.id,
                context=self.context,
                access_point=ZMQ_TRANSPORTS.IPC,
                **kwargs,
            )
            self.ipc_event_publisher = EventPublisher(
                id=f"{self.id}{EventPublisher._standard_address_suffix}",
                context=self.context,
                access_point=ZMQ_TRANSPORTS.IPC,
                **kwargs,
            )

        # which transports are served is settled by now, and cannot change afterwards
        self.transport_servers = [
            server for server in (self.inproc_server, self.ipc_server, self.tcp_server) if server is not None
        ]  # type: list[AsyncZMQServer]
        """one request socket per served transport, each polled by its own coroutine."""
        self.event_publishers = [
            publisher
            for publisher in (self.inproc_event_publisher, self.ipc_event_publisher, self.tcp_event_publisher)
            if publisher is not None
        ]  # type: list[EventPublisher]
        """one PUB socket per served transport, each subscribed to every event of every served `Thing`."""

        self.add_things(*(things or []))

    @property
    def eventloop(self) -> EventLoop:
        """
        The event loop running the `Thing`s this server serves.

        Resolved from the `Thing`s rather than owned, as HTTP and MQTT do it - this server is one
        protocol in front of an event loop, not the thing that creates one.

        Returns
        -------
        EventLoop
            the event loop to submit this server's operations to

        Raises
        ------
        RuntimeError
            if no `Thing` was added, or the ones that were are not bound to an event loop
        """
        for thing in self.things or []:
            if thing.eventloop is not None:
                return thing.eventloop
        raise RuntimeError(
            f"no event loop for ZMQ server {self.id} - add a Thing that is already served by one, "
            + "with EventLoop(things=[...]) or run()"
        )

    def add_thing(self, thing: Thing) -> None:
        """
        Adds a thing to the list of things to serve.

        The `Thing` need not be bound to an event loop yet - `run()` is what requires that, so that a
        server can be built before the loop that will run it, which is what `parse_params()` does.
        """
        if self.things is None:
            self.things = []
        if thing not in self.things:
            self.things.append(thing)

    def extra_coroutines(self) -> list[Any]:
        """
        The request listeners, to be run on the event loop's own asyncio loop.

        Returns
        -------
        list[Coroutine]
            one polling coroutine per served transport
        """
        return [self.recv_requests_and_dispatch_jobs(server) for server in self.transport_servers]

    async def recv_requests_and_dispatch_jobs(self, server: AsyncZMQServer) -> None:
        """
        Poll a ZMQ socket, hand every request to the event loop and write each reply back.

        This is the ZMQ border: `RequestMessage` in, `Operation` to the event loop, `Reply` back,
        `ResponseMessage` out. Messages that need no job at all, like `HANDSHAKE` and `EXIT`, are
        already dealt with by `poll_requests()`.

        Parameters
        ----------
        server: AsyncZMQServer
            the server instance to poll for requests
        """
        self.logger.debug(f"started polling at socket {server.socket_address}")
        loop = get_current_async_loop()
        eventloop = self.eventloop
        while eventloop.is_running:
            try:
                request_messages = await server.poll_requests()
                # when stop poll is set, this will exit with an empty list
            except BreakLoop:
                break
            except Exception as ex:
                self.logger.error(f"exception occurred while polling for server - {ex!s}")
                self.logger.exception(str(ex))
                continue

            for request_message in request_messages:
                # a task per request, so that waiting for one reply never stalls the poller
                loop.create_task(self.serve_one_request(server, request_message))
        self.stop()
        self.logger.info(f"stopped polling at socket {server.socket_address.split(':')[0].upper()}")

    async def serve_one_request(self, server: AsyncZMQServer, request_message: RequestMessage) -> None:
        """
        Convert one ZMQ request, run it through the event loop and write the answer back.

        Parameters
        ----------
        server: AsyncZMQServer
            the server the request arrived on, and the one the response goes back out of
        request_message: RequestMessage
            the request, still in its wire format
        """
        try:
            # this is the border: the 5-frame layout, the header structs and the message types are
            # ZMQ artifacts and stop here, an Operation is all the event loop is told
            header = request_message.header
            operation = Operation.create(
                thing_id=header["thingID"],
                objekt=header["objekt"],
                operation=header["operation"],
                payload=request_message.body[0],  # ty: ignore[invalid-argument-type]
                preserialized_payload=request_message.body[1],  # ty: ignore[invalid-argument-type]
                id=request_message.id,
                sender_id=request_message.sender_id,
                **as_execution_kwargs(header["serverExecutionContext"]),
                **as_execution_kwargs(header["thingExecutionContext"]),
            )
            if operation.operation == Operations.invokeaction and operation.objekt == "get_thing_description":
                reply = await self.get_thing_description(operation)
            else:
                reply = await self.eventloop.execute(operation)
        except Exception as ex:
            self.logger.error(
                f"exception occurred for message - {ex!s}",
                sender_id=request_message.sender_id,
                msg_id=request_message.id,
            )
            self.logger.exception(str(ex))
            await server._handle_invalid_message(request_message=request_message, exception=ex)
            return

        if reply.timed_out:
            # the client is told which of the two timeouts it was, as it always has been
            await server._handle_timeout(
                request_message,
                "invokation" if reply.kind is ReplyKind.INVOKATION_TIMEOUT else "execution",
            )
            return
        if operation.scheduler_execution_context.oneway:
            return
        await server.async_send_response_with_message_type(
            request_message=request_message,
            message_type=_ZMQ_MESSAGE_TYPE_FOR_REPLY[reply.kind],  # ty: ignore[invalid-argument-type]
            payload=reply.payload,
            preserialized_payload=reply.preserialized_payload,
        )

    async def get_thing_description(self, operation: Operation) -> Reply:
        """
        Answer a Thing Description request here, rather than through the event loop.

        A Thing Description is mostly forms, and a form is an address on this server's own sockets,
        so only this server can build one. Submitting it would send it through a scheduler and the
        `Thing`'s thread - queued behind whatever that `Thing` is busy with - only to come back here.

        Parameters
        ----------
        operation: Operation
            the `get_thing_description` invocation the border has just decoded

        Returns
        -------
        Reply
            the description, or the error that generating it raised
        """
        instance = self.eventloop.things[operation.thing_id]
        try:
            kwargs = dict(operation.payload.deserialize() or {})
            args = kwargs.pop("__args__", ())
            thing_description = self.config.thing_description_service(server=self, logger=self.logger)
            return_value = await thing_description.generate(instance, *args, **kwargs)
            payload, preserialized_payload = format_return_value(
                return_value,
                serializer=Serializers.for_object(operation.thing_id, instance.__class__.__name__, operation.objekt),
                content_type_if_no_serializer=Serializers.get_content_type_for_object(
                    operation.thing_id, instance.__class__.__name__, operation.objekt
                ),
            )
            payload.require_serialized()
            return Reply(payload, preserialized_payload, ReplyKind.OK)
        except Exception as ex:
            # the same shape the event loop would have produced, so a bad `protocol=` argument still
            # comes back as an error reply rather than as an invalid-message response
            self.logger.error(f"error while generating the thing description - {ex!s}")
            self.logger.exception(ex)
            payload, preserialized_payload = format_return_value(
                dict(exception=format_exception_as_json(ex)), Serializers.default
            )
            return Reply(payload, preserialized_payload, ReplyKind.ERROR)

    def run(self) -> None:
        """
        Start & run the server, and the event loop its `Thing`s belong to. This method is blocking.

        The request listeners are handed to the event loop so they run on the same async loop as the
        drain loops that resolve their replies. Call `stop()` (threadsafe) to stop.

        Raises
        ------
        RuntimeError
            if the served `Thing`s are not bound to an event loop
        """
        self.logger.info("starting ZMQ server")
        # the loop this thread is given is the one `EventLoop.run()` picks up below, and setup has
        # nothing to await - it is a coroutine only because the protocol lifecycle says so
        get_current_async_loop().run_until_complete(self.setup())
        try:
            self.eventloop.run(extra_coroutines=self.extra_coroutines())
        finally:
            self.stop_polling()
        self.logger.info("ZMQ server stopped")

    def stop_polling(self) -> None:
        """Stop every request listener. Registered with the event loop, so stopping it stops these too."""
        for server in self.transport_servers:
            server.stop_polling()

    def stop(self) -> None:
        """Stop the server and the event loop behind it. This method is threadsafe."""
        self.eventloop.stop()

    def exit(self) -> None:
        """Stop, then close every socket and event publisher."""
        try:
            self.stop()
            for server in self.transport_servers:
                server.exit()
            for publisher in self.event_publishers:
                publisher.exit()
        except Exception as ex:
            self.logger.warning(f"Exception occurred while exiting the server - {ex!s}")

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if not isinstance(other, ZMQServer):
            return False
        return self.id == other.id

    def __str__(self):
        parts = [f"{self.__class__.__name__}(\n\tid: {self.id}"]
        for name in [
            "inproc_server",
            "ipc_server",
            "tcp_server",
            "inproc_event_publisher",
            "ipc_event_publisher",
            "tcp_event_publisher",
        ]:
            obj = getattr(self, name, None)
            if obj is not None:
                type_name = type(obj).__name__
                parts.append(f"{name}: {getattr(obj, 'socket_address', None)} ({type_name})")
            else:
                parts.append(f"{name}: None")
        paths = "\n\t".join(parts)
        paths += "\n)"
        return paths

    async def start(self) -> None:
        """
        Bind to the event loop its `Thing`s run on, without blocking.

        The request listeners are not started here - they are coroutines the event loop runs, handed
        over through `extra_coroutines()` before the loop starts. Use `run()` to start both at once.
        """
        await self.setup()

    async def setup(self) -> None:
        """
        Bind this server to the event loop its `Thing`s run on.

        Raises
        ------
        RuntimeError
            if the served `Thing`s are not bound to an event loop
        ValueError
            if they are not all bound to the same one - this server polls one set of sockets and
            hands every request to one loop, so it cannot straddle two
        """
        eventloop = self.eventloop
        for thing in self.things or []:
            if thing.eventloop is not eventloop:
                raise ValueError(
                    "every Thing served over ZMQ must be run by the same event loop, "
                    + f"but {thing.id} belongs to a different one"
                )
        eventloop.add_stop_hook(self.stop_polling)

        # Subscribes every publisher to every event
        event_bus = eventloop.event_bus
        for event_id in event_bus.event_ids - self._published_event_ids:
            event = event_bus.event_for(event_id)
            for publisher in self.event_publishers:
                event_bus.subscribe(partial(publisher.publish, event), event_id)
            self._published_event_ids.add(event_id)


__all__ = [ZMQServer.__name__]
