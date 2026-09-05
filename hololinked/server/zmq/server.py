"""
ZeroMQ: the sockets, the wire format border, and the protocol server that owns them.

`ZMQServer` puts an `EventLoop` behind ZMQ. It owns every socket - `INPROC` for callers inside this
process, `IPC` and `TCP` for callers outside it - and converts, at its own border, between the
5-frame wire format and the transport-neutral `Operation`/`Reply` the event loop speaks.
"""

from __future__ import annotations

import copy
import socket

from typing import Any

import structlog
import zmq.asyncio

from hololinked import Serializers

from ...config import global_config
from ...constants import ZMQ_TRANSPORTS, Operations
from ...core.eventloop import EventLoop, ReplyKind
from ...core.exceptions import BreakLoop
from ...core.thing import Thing
from ...utils import get_current_async_loop
from ..server import BaseProtocolServer
from .brokers import AsyncZMQServer, EventPublisher
from .message import ERROR, REPLY, RequestMessage


_ZMQ_MESSAGE_TYPE_FOR_REPLY = {
    ReplyKind.OK: REPLY,
    ReplyKind.ERROR: ERROR,
    ReplyKind.EXIT: None,  # let the broker decide, as it did before
}
"""How a `Reply` maps onto ZMQ's message-type vocabulary. The event loop does not know these."""


class ZMQServer(BaseProtocolServer):
    """
    Serves `Thing`s over ZeroMQ, on any combination of the `INPROC`, `IPC` and `TCP` transports.

    The server owns the sockets; an `EventLoop` behind it owns the `Thing`s and runs the operations.
    Requests are polled off a socket, converted into an `Operation`, submitted, and the `Reply` that
    comes back is converted into a response message. Nothing below the border knows the wire format.

    `INPROC` is shared memory and is the fastest of the three, which is why other protocol servers in
    the same process reach a `Thing` through it. `IPC` reaches other processes on this machine, and
    `TCP` reaches the network. All three carry the same messaging contract.

    [UML Diagram](http://docs.hololinked.dev/UML/PDF/RPCServer.pdf)
    """

    context: zmq.asyncio.Context

    def __init__(
        self,
        *,
        id: str,
        access_points: ZMQ_TRANSPORTS | str | list[ZMQ_TRANSPORTS | str] = ZMQ_TRANSPORTS.IPC,
        things: list[Thing] | None = None,
        context: zmq.asyncio.Context | None = None,
        eventloop: EventLoop | None = None,
        **kwargs,
    ) -> None:
        """
        Initialize the ZeroMQ server.

        Parameters
        ----------
        id: str
            Unique identifier for the server instance. The event loop shares it, so that a `Thing` can
            report the address other protocols in this process should connect to.
        access_points: ZMQ_TRANSPORTS or list[ZMQ_TRANSPORTS], default ZMQ_TRANSPORTS.IPC
            Transport protocols for communication. Supported values are `ZMQ_TRANSPORTS.INPROC`,
            `ZMQ_TRANSPORTS.IPC`, `ZMQ_TRANSPORTS.TCP` or a TCP socket address `tcp://*:<port>`.
            Can be a single value or a list of values. `INPROC` is always served.
        things: list[Thing]
            List of `Thing` instances to be served.
        context: zmq.asyncio.Context, optional
            ZeroMQ context for socket management. If `None`, a global context is used.
        eventloop: EventLoop, optional
            An existing event loop to serve. A new one is created when none is given.
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
        self.ipc_server = self.tcp_server = None
        self.ipc_event_publisher = self.tcp_event_publisher = None
        tcp_socket_address = None

        logger = kwargs.get("logger", None)
        if not logger:
            logger = structlog.get_logger().bind(component="zmq-server")
            kwargs["logger"] = logger
        BaseProtocolServer.__init__(self, id=id, logger=logger)
        self.logger = logger

        self.eventloop = eventloop or EventLoop(
            logger=logger,
            thing_description_provider=self.get_thing_description,
        )
        self.eventloop.attach(self)
        self.eventloop.add_stop_hook(self.stop_polling)
        self.add_things(*(things or []))

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

        # INPROC is always served: it is how HTTP, MQTT and anything else in this process reach the
        # event loop, and it is the transport the internal clients assume
        self.req_rep_server = AsyncZMQServer(
            id=self.id,
            context=self.context,
            access_point=ZMQ_TRANSPORTS.INPROC,
            poll_timeout=1000,
            **kwargs,
        )
        self.event_publisher = EventPublisher(
            id=f"{self.id}{EventPublisher._standard_address_suffix}",
            context=self.context,
            access_point=ZMQ_TRANSPORTS.INPROC,
            **kwargs,
        )
        # one of possibly several protocols listening to the bus - ZMQ has no special standing here
        self.eventloop.event_bus.subscribe(self.event_publisher.publish)

        # then every externally visible transport that was asked for
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
            self.eventloop.event_bus.subscribe(self.tcp_event_publisher.publish)
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
            self.eventloop.event_bus.subscribe(self.ipc_event_publisher.publish)

    @property
    def is_running(self) -> bool:
        """Whether the event loop behind this server is running."""
        return self.eventloop.is_running

    @property
    def _run(self) -> bool:
        """The event loop's run flag, which the polling loops check."""
        return self.eventloop._run

    @property
    def event_bus(self):
        """The event loop's `EventBus`, which this server's publishers are subscribed to."""
        return self.eventloop.event_bus

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve."""
        self.eventloop.add_thing(thing)
        if self.things is None:
            self.things = []
        if thing not in self.things:
            self.things.append(thing)

    def _request_servers(self) -> list[AsyncZMQServer]:
        """
        Every socket this server polls for requests.

        Returns
        -------
        list[AsyncZMQServer]
            the INPROC server, plus IPC and TCP where those transports were asked for
        """
        return [server for server in (self.req_rep_server, self.ipc_server, self.tcp_server) if server is not None]

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
        while self._run:
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
                loop.create_task(self._serve_one_request(server, request_message))
        self.stop()
        self.logger.info(f"stopped polling at socket {server.socket_address.split(':')[0].upper()}")

    async def _serve_one_request(self, server: AsyncZMQServer, request_message: RequestMessage) -> None:
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
            operation = request_message.to_operation()
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
        if operation.server_execution_context.oneway:
            return
        await server.async_send_response_with_message_type(
            request_message=request_message,
            message_type=_ZMQ_MESSAGE_TYPE_FOR_REPLY[reply.kind],  # ty: ignore[invalid-argument-type]
            payload=reply.payload,
            preserialized_payload=reply.preserialized_payload,
        )

    def get_thing_description(
        self,
        instance: Thing,
        protocol: str,
        ignore_errors: bool = False,
        skip_names: list[str] = [],
    ) -> dict[str, Any]:
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

        Raises
        ------
        RuntimeError
            if the server does not serve the requested protocol
        ValueError
            if the protocol is not one of `INPROC`, `IPC` or `TCP`
        """
        TM = instance.get_thing_model(ignore_errors=ignore_errors, skip_names=skip_names).json()  # type: dict[str, Any]
        TD = copy.deepcopy(TM)
        from ...metadata.td import ActionAffordance, EventAffordance, PropertyAffordance
        from ...metadata.td.forms import Form

        if protocol.lower() == "inproc":
            req_rep_socket_address = self.req_rep_server.socket_address
            pub_sub_socket_address = self.event_publisher.socket_address
        elif protocol.lower() == "ipc":
            if self.ipc_server is None or self.ipc_event_publisher is None:
                raise RuntimeError(
                    "This server cannot generate TD for IPC protocol, consider using thing model directly."
                )
            req_rep_socket_address = self.ipc_server.socket_address
            pub_sub_socket_address = self.ipc_event_publisher.socket_address
        elif protocol.lower() == "tcp":
            if self.tcp_server is None or self.tcp_event_publisher is None:
                raise RuntimeError(
                    "This server cannot generate TD for TCP protocol, consider using thing model directly."
                )
            req_rep_socket_address = self.tcp_server.socket_address
            req_rep_socket_address = req_rep_socket_address.replace(
                "*", socket.gethostname()
            ).replace(
                "0.0.0.0", socket.gethostname()
            )  # SAST(id='hololinked.server.zmq.server.ZMQServer.get_thing_description.req_rep_socket_address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
            pub_sub_socket_address = self.tcp_event_publisher.socket_address
            pub_sub_socket_address = pub_sub_socket_address.replace(
                "*", socket.gethostname()
            ).replace(
                "0.0.0.0", socket.gethostname()
            )  # SAST(id='hololinked.server.zmq.server.ZMQServer.get_thing_description.pub_sub_socket_address', description='B104:hardcoded_bind_all_interfaces', tool='bandit')
        else:
            raise ValueError(f"Unsupported protocol '{protocol}' for ZMQ.")

        for name in TM.get("properties", []):
            try:
                affordance = PropertyAffordance.from_TD(name, TM)
                if not TD["properties"][name].get("forms", None):
                    TD["properties"][name]["forms"] = []

                form = Form()
                form.href = req_rep_socket_address
                form.op = Operations.readproperty

                content_type = Serializers.get_content_type_for_object(instance.id, instance.__class__.__name__, name)
                if not content_type:
                    content_type = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
                form.contentType = content_type

                TD["properties"][name]["forms"].append(form.json())

                if not affordance.readOnly:
                    form = Form()
                    form.href = req_rep_socket_address
                    form.op = Operations.writeproperty
                    content_type = Serializers.get_content_type_for_object(
                        instance.id,
                        instance.__class__.__name__,
                        name,
                    )
                    if not content_type:
                        content_type = Serializers.for_object(
                            instance.id,
                            instance.__class__.__name__,
                            name,
                        ).content_type
                    form.contentType = content_type
                    TD["properties"][name]["forms"].append(form.json())

                if affordance.observable:
                    form = Form()
                    form.href = pub_sub_socket_address
                    form.op = Operations.observeproperty
                    content_type = Serializers.get_content_type_for_object(
                        instance.id, instance.__class__.__name__, name
                    )
                    if not content_type:
                        content_type = Serializers.for_object(
                            instance.id,
                            instance.__class__.__name__,
                            name,
                        ).content_type
                    form.contentType = content_type
                    TD["properties"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                instance.logger.warning(
                    "error while generating TD forms for property",
                    name=name,
                    error=str(ex),
                )

        for name in TM.get("actions", []):
            try:
                affordance = ActionAffordance.from_TD(name, TM)
                if not TD["actions"][name].get("forms", None):
                    TD["actions"][name]["forms"] = []

                form = Form()
                form.href = req_rep_socket_address
                form.op = Operations.invokeaction
                content_type = Serializers.get_content_type_for_object(instance.id, instance.__class__.__name__, name)
                if not content_type:
                    content_type = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
                form.contentType = content_type
                TD["actions"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                instance.logger.warning(
                    "error while generating TD forms for action",
                    name=name,
                    error=str(ex),
                )

        for name in TM.get("events", []):
            try:
                affordance = EventAffordance.from_TD(name, TM)
                if not TD["events"][name].get("forms", None):
                    TD["events"][name]["forms"] = []

                form = Form()
                form.href = pub_sub_socket_address
                form.op = Operations.subscribeevent
                content_type = Serializers.get_content_type_for_object(instance.id, instance.__class__.__name__, name)
                if not content_type:
                    content_type = Serializers.for_object(instance.id, instance.__class__.__name__, name).content_type
                form.contentType = content_type
                TD["events"][name]["forms"].append(form.json())
            except Exception as ex:
                if not ignore_errors:
                    raise ex from None
                instance.logger.warning(
                    "error while generating TD forms for event",
                    name=name,
                    error=str(ex),
                )

        return TD

    def run(self) -> None:
        """
        Start & run the server, and the event loop behind it. This method is blocking.

        The request listeners are handed to the event loop so they run on the same async loop as the
        drain loops that resolve their replies. Call `stop()` (threadsafe) to stop.
        """
        self.logger.info("starting ZMQ server")
        try:
            self.eventloop.run(
                extra_coroutines=[self.recv_requests_and_dispatch_jobs(server) for server in self._request_servers()]
            )
        finally:
            self.stop_polling()
        self.logger.info("ZMQ server stopped")

    def stop_polling(self) -> None:
        """Stop every request listener. Registered with the event loop, so stopping it stops these too."""
        for server in self._request_servers():
            server.stop_polling()

    def stop(self) -> None:
        """Stop the server and the event loop behind it. This method is threadsafe."""
        self.eventloop.stop()

    def exit(self) -> None:
        """Stop, then close every socket and event publisher."""
        try:
            self.stop()
            for server in self._request_servers():
                server.exit()
            for publisher in (self.event_publisher, self.ipc_event_publisher, self.tcp_event_publisher):
                if publisher is not None:
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
            "req_rep_server",
            "ipc_server",
            "tcp_server",
            "event_publisher",
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
        Not supported for this server, use the blocking `run()` method instead.

        Raises
        ------
        NotImplementedError
            always, since the server is started through `run()`
        """
        raise NotImplementedError("Use the blocking run() method to start the ZMQServer.")

    async def setup(self) -> None:
        """
        Not supported for this server, `run()` performs the setup itself.

        Raises
        ------
        NotImplementedError
            always, since `run()` sets the server up
        """
        raise NotImplementedError("Use the blocking run() method to start the ZMQServer, no need to setup separately.")


class RPCServer(ZMQServer):
    """
    Deprecated. A `ZMQServer` serving `INPROC` only.

    The event loop it used to be now lives in `hololinked.core.eventloop.EventLoop`, and this
    is what is left: the ZMQ transport in front of one. Use `ZMQServer`, or `EventLoop` directly if
    no ZMQ is wanted at all.
    """

    def __init__(
        self,
        *,
        id: str,
        access_points: ZMQ_TRANSPORTS | str | list[ZMQ_TRANSPORTS | str] = ZMQ_TRANSPORTS.INPROC,
        **kwargs,
    ) -> None:
        """
        Initialize an INPROC-only ZeroMQ server. Arguments are those of `ZMQServer`.

        Parameters
        ----------
        id: str
            Unique identifier for the server instance.
        access_points: ZMQ_TRANSPORTS or list[ZMQ_TRANSPORTS], default ZMQ_TRANSPORTS.INPROC
            Transports to serve.
        """
        super().__init__(id=id, access_points=access_points, **kwargs)


def prepare_rpc_server(*args, **kwargs) -> None:
    """
    Removed.

    Raises
    ------
    NotImplementedError
        always
    """
    raise NotImplementedError("prepare_rpc_server function is deprecated, use ZMQServer class directly.")


__all__ = [RPCServer.__name__, ZMQServer.__name__]
