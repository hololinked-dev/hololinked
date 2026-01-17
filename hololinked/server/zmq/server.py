import structlog
import zmq
import zmq.asyncio

from ...constants import ZMQ_TRANSPORTS
from ...core.thing import Thing
from ...core.zmq.brokers import AsyncEventConsumer, AsyncZMQServer, EventPublisher
from ...core.zmq.rpc_server import RPCServer
from ...utils import get_current_async_loop
from ..server import BaseProtocolServer


class ZMQServer(RPCServer, BaseProtocolServer):
    """Server to expose `Thing` over `ZeroMQ` protocol. Extends `RPCServer` to support `IPC` & `TCP`"""

    def __init__(
        self,
        *,
        id: str,
        access_points: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC,
        things: list["Thing"] = None,
        context: zmq.asyncio.Context | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            Unique identifier for the server instance.
        things: list["Thing"]
            List of `Thing` instances to be managed by the server.
        context: zmq.asyncio.Context, optional
            ZeroMQ context for socket management. If `None`, a global context is used.
        access_points: ZMQ_TRANSPORTS or list[ZMQ_TRANSPORTS], default ZMQ_TRANSPORTS.IPC
            Transport protocols for communication. Supported values are `ZMQ_TRANSPORTS.IPC`, `ZMQ_TRANSPORTS.TCP` or
            a TCP socket address `tcp://*:<port>`. Can be a single value or a list of values.
        **kwargs
            Additional keyword arguments for server configuration. Usually:

            - `logger`: `structlog.stdlib.BoundLogger`, custom logger instance.
            - `poll_timeout`: `int`, polling timeout in milliseconds.
        """
        self.ipc_server = self.tcp_server = None
        self.ipc_event_publisher = self.tcp_event_publisher = self.inproc_events_proxy = None
        tcp_socket_address = None

        logger = kwargs.get("logger", None)
        if not logger:
            logger = structlog.get_logger().bind(component="zmq-server")
            kwargs["logger"] = logger
        super().__init__(id=id, things=things, context=context, **kwargs)
        # note for later refactoring - we dont use add_things method here, be careful if that method becomes overloaded
        # at any point in future

        if isinstance(access_points, str):
            access_points = [access_points]
        elif not isinstance(access_points, list):
            raise TypeError(f"unsupported transport type : {type(access_points)}")
        for index, transport in enumerate(access_points):
            if isinstance(transport, str) and len(transport) in [3, 6]:
                access_points[index] = transport.upper()
            elif transport.lower().startswith("tcp://"):
                access_points[index] = "TCP"
                tcp_socket_address = transport
            else:
                access_points[index] = transport

        # initialise every externally visible protocol
        if ZMQ_TRANSPORTS.TCP in access_points or "TCP" in access_points:
            self.tcp_server = AsyncZMQServer(
                id=self.id,
                context=self.context,
                access_point=tcp_socket_address or ZMQ_TRANSPORTS.TCP,
                **kwargs,
            )
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
        if ZMQ_TRANSPORTS.IPC in access_points or "IPC" in access_points:
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
        if self.ipc_event_publisher is not None or self.tcp_event_publisher is not None:
            self.inproc_events_proxy = AsyncEventConsumer(
                id=f"{self.id}/event-proxy",
                event_unique_identifier="",
                access_point=self.event_publisher.socket_address,
                context=self.context,
                **kwargs,
            )

    def add_thing(self, thing: Thing) -> None:
        """Adds a thing to the list of things to serve"""
        return RPCServer.add_thing(self, thing)

    def run_zmq_request_listener(self) -> None:
        # doc in parent class
        eventloop = get_current_async_loop()
        if self.ipc_server is not None:
            eventloop.create_task(self.recv_requests_and_dispatch_jobs(self.ipc_server))
        if self.tcp_server is not None:
            eventloop.create_task(self.recv_requests_and_dispatch_jobs(self.tcp_server))
        if self.inproc_events_proxy is not None:
            eventloop.create_task(self.tunnel_events_from_inproc())
        super().run_zmq_request_listener()

    async def tunnel_events_from_inproc(self) -> None:
        if not self.inproc_events_proxy:
            return
        self.logger.info("starting to tunnel events from inproc to external publishers")
        self.inproc_events_proxy.subscribe()
        while self._run:
            try:
                event = await self.inproc_events_proxy.receive(raise_interrupt_as_exception=True)
                if not event:
                    continue
                if self.ipc_event_publisher is not None:
                    self.ipc_event_publisher.socket.send_multipart(event.byte_array)
                    # print(f"sent event to ipc publisher {event.byte_array}")
                if self.tcp_event_publisher is not None:
                    self.tcp_event_publisher.socket.send_multipart(event.byte_array)
                    # print(f"sent event to tcp publisher {event.byte_array}")
            except ConnectionAbortedError:
                break
            except Exception as e:
                self.logger.error(f"error in tunneling events from inproc: {e}")
        self.logger.info("stopped tunneling events from inproc")

    def stop(self) -> None:
        # doc in parent class
        if self.ipc_server is not None:
            self.ipc_server.stop_polling()
        if self.tcp_server is not None:
            self.tcp_server.stop_polling()
        if self.inproc_events_proxy is not None:
            self.inproc_events_proxy.stop()
        super().stop()

    def exit(self) -> None:
        # doc in parent class
        try:
            self.stop()
            if self.ipc_server is not None:
                self.ipc_server.exit()
                self.ipc_event_publisher.exit()
            if self.tcp_server is not None:
                self.tcp_server.exit()
                self.tcp_event_publisher.exit()
            if self.req_rep_server is not None:
                self.req_rep_server.exit()
            if self.event_publisher is not None:
                self.event_publisher.exit()
            if self.inproc_events_proxy is not None:
                self.inproc_events_proxy.exit()
        except Exception as ex:
            self.logger.warning(f"Exception occurred while exiting the server - {str(ex)}")

    def __str__(self):
        parts = [f"ZMQServer(\n\tid: {self.id}"]
        for name in [
            "ipc_server",
            "tcp_server",
            "req_rep_server",
            "ipc_event_publisher",
            "tcp_event_publisher",
            "event_publisher",
            "inproc_events_proxy",
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
        raise NotImplementedError("Use the blocking run() method to start the ZMQServer.")

    async def setup(self) -> None:
        raise NotImplementedError("Use the blocking run() method to start the ZMQServer, no need to setup separately.")
