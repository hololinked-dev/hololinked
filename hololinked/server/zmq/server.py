"""ZeroMQ server exposing `Thing`s over IPC, TCP and INPROC transport."""

from __future__ import annotations

from functools import partial
from typing import Any, Self

import structlog
import zmq.asyncio

from hololinked import Serializers

from ...config import global_config
from ...constants import ZMQ_TRANSPORTS, Operations
from ...core.eventloop import Operation, Reply, ReplyKind
from ...core.eventloop.operations import as_execution_kwargs, format_return_value
from ...core.exceptions import BreakLoop
from ...core.interfaces import BaseProtocolServer
from ...core.properties import ClassSelector
from ...core.thing import Thing
from ...utils import format_exception_as_json, get_current_async_loop
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
        self.polling = False

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

    async def recv_requests(self, server: AsyncZMQServer) -> None:
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
        while self.polling:
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
                loop.create_task(self.process_request(server, request_message))
        self.stop()
        self.logger.info(f"stopped polling at socket {server.socket_address.split(':')[0].upper()}")

    async def process_request(self, server: AsyncZMQServer, request_message: RequestMessage) -> None:
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
                # setup() rejects any thing not bound to an event loop, so eventloop is never None here
                eventloop = self.things[operation.thing_id].eventloop
                reply = await eventloop.execute(operation)  # ty: ignore[unresolved-attribute]
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
        Create a Thing Description.

        Parameters
        ----------
        operation: Operation
            the `get_thing_description` invocation the border has just decoded

        Returns
        -------
        Reply
            the description, or the error that generating it raised
        """
        # TODO this method needs a signature update. Does not make sense to input operation and get a reply.
        instance = self.things[operation.thing_id]
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
            self.logger.error(f"error while generating the thing description - {ex!s}")
            self.logger.exception(ex)
            payload, preserialized_payload = format_return_value(
                dict(exception=format_exception_as_json(ex)), Serializers.default
            )
            return Reply(payload, preserialized_payload, ReplyKind.ERROR)

    def stop_polling(self) -> None:
        """Stop every request listener. The sockets stay open, use `exit()` to close them."""
        self.polling = False
        for server in self.transport_servers:
            server.stop_polling()

    def stop(self) -> None:
        """Stop serving."""
        self.stop_polling()

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

    @classmethod
    def from_params(cls, id: str, params: str | int | dict | list[str] | None) -> Self:
        # docstring already there in base
        protocol_params: dict[str, Any]
        if isinstance(params, int):
            protocol_params = dict(access_points=[f"tcp://*:{params}"])
        elif isinstance(params, (str, ZMQ_TRANSPORTS)):
            protocol_params = dict(access_points=[params])
        elif isinstance(params, list):
            protocol_params = dict(access_points=params)
        elif isinstance(params, dict):
            protocol_params = dict(params)
        else:
            raise ValueError(
                "ZMQ parameters must be supplied as a dict, a port, an access point or a list of access points."
            )
        access_points = protocol_params["access_points"]
        protocol_params["access_points"] = list(access_points) if isinstance(access_points, list) else [access_points]
        return cls(id=id, **protocol_params)

    async def start(self) -> None:
        """Start polling every served transport for requests. Returns without blocking."""
        await self.setup()
        self.polling = True
        loop = get_current_async_loop()
        for server in self.transport_servers:
            loop.create_task(self.recv_requests(server))

    async def setup(self) -> None:
        """
        Setup the server.

        Raises
        ------
        ValueError
            if a served `Thing` is not bound to an event loop
        """
        event_buses = {}
        for thing in self.things.values():
            if not thing.eventloop:
                raise ValueError(f"You need to expose thing {thing.id} via an EventLoop before trying to serve it")
            event_buses[thing.id] = thing.eventloop.event_bus

        for thing in self.things.values():
            event_bus = event_buses[thing.id]
            for event in thing.events.descriptors.values():
                event_id = event.get_unique_identifier(thing)
                if event_id in self._published_event_ids:
                    continue  # a second setup() must not subscribe a second time
                registered = event_bus.event_for(event_id)
                for publisher in self.event_publishers:
                    event_bus.subscribe(partial(publisher.publish, registered), event_id)
                self._published_event_ids.add(event_id)


__all__ = [ZMQServer.__name__]
