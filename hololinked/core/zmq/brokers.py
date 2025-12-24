from __future__ import annotations

import asyncio
import os
import threading
import time
import warnings

from enum import Enum
from typing import Any, Iterator

import structlog
import zmq
import zmq.asyncio

from zmq.utils.monitor import parse_monitor_message

from ...config import global_config
from ...constants import ZMQ_EVENT_MAP, ZMQ_TRANSPORTS
from ...serializers.serializers import Serializers
from ...utils import (
    format_exception_as_json,
    get_current_async_loop,
    get_sanitized_filename_from_random_string,
    get_socket_type_name,
    run_callable_somehow,
    uuid_hex,
)
from ..exceptions import BreakLoop
from .message import (
    ERROR,
    EXIT,
    HANDSHAKE,
    INVALID_MESSAGE,
    REPLY,
    SERVER_DISCONNECTED,
    TIMEOUT,
    EventMessage,
    PreserializedData,
    PreserializedEmptyByte,
    RequestMessage,
    ResponseMessage,
    SerializableData,
    SerializableNone,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
    default_thing_execution_context,
)


class BaseZMQ:
    """
    Base class for all ZMQ message brokers. Implements socket creation & logger config,
    which are common to all server and client implementations.
    """

    def __init__(self, id: str, **kwargs) -> None:
        """
        id: str
            unique ID of the server/client. This is used as the identity of the ZMQ socket.
        logger: logging.Logger, optional
            logger instance to use. If None, a default logger is created.
        """
        super().__init__()
        self.id = id  # type: str
        self.context = self.context if hasattr(self, "context") and self.context else None  # type: zmq.Context | zmq.asyncio.Context
        self.socket = self.socket if hasattr(self, "socket") and self.socket else None  # type: zmq.Socket | None
        self.socket_address = self.socket_address if hasattr(self, "socket_address") and self.socket_address else None  # type: str | None

    def exit(self) -> None:
        """
        Cleanup method to terminate ZMQ sockets and contexts before quitting. Called by `__del__()`
        automatically. Each subclass server/client should implement their version of exiting if necessary.
        """
        if not hasattr(self, "logger") or not self.logger:
            self.logger = structlog.get_logger().bind(component="broker", impl=self.__class__.__name__, id=self.id)

    def __del__(self) -> None:
        self.exit()

    @classmethod
    def get_socket(
        cls,
        *,
        server_id: str,
        socket_id: str,
        node_type: str,
        context: zmq.asyncio.Context | zmq.Context,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        socket_type: zmq.SocketType = zmq.ROUTER,
        **kwargs,
    ) -> tuple[zmq.Socket, str]:
        """
        Create a socket with certain specifications. Supported ZeroMQ transports are TCP, IPC & INPROC.
        For IPC sockets, a file is created under TEMP_DIR of global configuration.

        Parameters
        ----------
        server_id: str
            Used to create socket address
        socket_id: str
            Each ROUTER socket require unique identity to correctly route the messages, usually same as `server_id`
        node_type: str
            server or client? i.e. whether to bind (server) or connect (client) as per ZMQ definition
        context: zmq.Context or zmq.asyncio.Context
            ZeroMQ Context object that creates the socket
        access_point: Enum
            `TCP`, `IPC` or `INPROC`. Message crafting-passing-routing is transport-invariant as suggested by ZMQ.
            Speed relationship - `INPROC` > `IPC` > `TCP`. For client side `TCP`, specify the TCP address - `tcp://<host>:<port>`
            or a random port will be chosen.
        socket_type: zmq.SocketType, default zmq.ROUTER
            Usually a ROUTER socket is implemented for both client-server and peer-to-peer communication. But other sockets
            like PAIR, DEALER, etc. can also be used as per the use-case.
        kwargs: dict
            Additional arguments:

            - `socket_class`: `zmq.Socket` class to use, default is `zmq.Socket` for sync and `zmq.asyncio.Socket` for async.

        Returns
        -------
        socket: zmq.Socket
            created socket
        socket_address: str
            qualified address of the socket created for any transport type

        Raises
        ------
        NotImplementedError
            if transport other than `TCP`, `IPC` or `INPROC` is used
        RuntimeError
            if transport is `TCP` and a socket connection from client side is requested but a socket address is not supplied
        """
        if node_type.lower() not in ["server", "client"]:
            raise ValueError(f"Invalid node_type: {node_type}")
        bind = node_type.lower() == "server"
        if len(access_point) == 3 or len(access_point) == 6 or isinstance(access_point, Enum):
            transport = access_point
            socket_address = None
        else:
            transport = access_point.split("://")[0].upper()
            socket_address = access_point

        socket = context.socket(socket_type, socket_class=kwargs.get("socket_class", None))
        socket.setsockopt_string(zmq.IDENTITY, socket_id)

        if transport == ZMQ_TRANSPORTS.IPC or transport.lower() == "ipc":
            if socket_address is None or not socket_address.endswith(".ipc"):
                if not socket_address:
                    filename = get_sanitized_filename_from_random_string(server_id, "ipc")
                elif not socket_address.endswith(".ipc"):
                    filename = get_sanitized_filename_from_random_string(socket_address, "ipc")
                # re-compute for IPC because it looks for a file in a directory
                filename = filename.replace(
                    EventPublisher._standard_address_suffix.replace("/", "_"),
                    f".{EventPublisher._standard_address_suffix_filename_replacement}",
                )
                socket_address = "ipc://{}{}{}".format(global_config.TEMP_DIR_SOCKETS, os.sep, filename)
            if bind:
                socket.bind(socket_address)
            else:
                socket.connect(socket_address)
        elif transport == ZMQ_TRANSPORTS.TCP or transport.lower() == "tcp":
            if bind:
                failed = False
                if socket_address:
                    try:
                        socket.bind(socket_address)
                    except zmq.error.ZMQError as ex:
                        if not ex.strerror.startswith("Address in use"):
                            raise ex from None
                        failed = True
                if failed or not socket_address:
                    for i in range(
                        global_config.TCP_SOCKET_SEARCH_START_PORT,
                        global_config.TCP_SOCKET_SEARCH_END_PORT,
                    ):
                        socket_address = "tcp://0.0.0.0:{}".format(i)
                        try:
                            socket.bind(socket_address)
                            break
                        except zmq.error.ZMQError as ex:
                            if not ex.strerror.startswith("Address in use"):
                                raise ex from None
            elif socket_address:
                socket.connect(socket_address)
            else:
                raise RuntimeError(f"Socket address not supplied for TCP connection to identity - {socket_id}")
        elif transport == ZMQ_TRANSPORTS.INPROC or transport.lower() == "inproc":
            # inproc_id = id.replace('/', '_').replace('-', '_')
            if socket_address is None:
                socket_address = f"inproc://{server_id}"
            elif not socket_address.startswith("inproc://"):
                socket_address = f"inproc://{socket_address}"
            if bind:
                socket.bind(socket_address)
            else:
                socket.connect(socket_address)
        else:
            raise NotImplementedError(
                "transports other than IPC, TCP & INPROC are not implemented now for {}.".format(cls.__name__)
                + f" Given transport {transport}."
            )
        return socket, socket_address


class BaseAsyncZMQ(BaseZMQ):
    """
    Base class for all async ZMQ servers and clients.
    """

    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(
        self,
        *,
        server_id: str,
        socket_id: str,
        node_type: str = "server",
        context: zmq.asyncio.Context | None = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        socket_type: zmq.SocketType = zmq.ROUTER,
        **kwargs,
    ) -> None:
        """
        Overloads `create_socket()` to create, bind/connect an async socket. A global context is used if
        none is supplied.
        """
        if context and not isinstance(context, zmq.asyncio.Context):
            raise TypeError(
                "async ZMQ message broker accepts only async ZMQ context. supplied type {}".format(type(context))
            )
        self.context = context or global_config.zmq_context()
        self.socket, self.socket_address = BaseZMQ.get_socket(
            server_id=server_id,
            socket_id=socket_id,
            node_type=node_type,
            context=self.context,
            access_point=access_point,
            socket_type=socket_type,
            **kwargs,
        )
        self.logger.info(
            "created socket type: {} with address: {} & identity: {} and {}".format(
                get_socket_type_name(socket_type),
                self.socket_address,
                socket_id,
                "bound" if node_type == "server" else "connected",
            )
        )


class BaseSyncZMQ(BaseZMQ):
    """Base class for all sync ZMQ servers and clients"""

    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(
        self,
        *,
        server_id: str,
        socket_id: str,
        node_type: str = "server",
        context: zmq.Context | None = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        socket_type: zmq.SocketType = zmq.ROUTER,
        **kwargs,
    ) -> None:
        """
        Overloads `create_socket()` to create, bind/connect a synchronous socket. A global context is used if
        none is supplied.
        """
        self.context = context or global_config.zmq_context()
        self.socket, self.socket_address = BaseZMQ.get_socket(
            server_id=server_id,
            socket_id=socket_id,
            node_type=node_type,
            context=self.context,
            access_point=access_point,
            socket_type=socket_type,
            socket_class=zmq.Socket,
            **kwargs,
        )
        self.logger.info(
            "created socket type: {} with address: {} & identity: {} and {}".format(
                get_socket_type_name(socket_type),
                self.socket_address,
                socket_id,
                "bound" if node_type == "server" else "connected",
            )
        )


class BaseZMQServer(BaseZMQ):
    """Base class for all ZMQ servers irrespective of sync and async"""

    def __init__(self, id: str, logger: structlog.stdlib.BoundLogger | None = None, **kwargs) -> None:
        super().__init__(id=id, **kwargs)
        if not logger:
            logger = structlog.get_logger()
        self.logger = logger.bind(component="broker", impl=self.__class__.__name__, id=self.id)

    def handshake(self, request_message: RequestMessage) -> None:
        """
        Pass a handshake message to client. Absolutely mandatory to handshake with all clients to ensure initial messages
        do not get lost because of ZMQ's tiny but significant initial delay after creating socket.

        Parameters
        ----------
        request_message: RequestMessage
            the client message for which the handshake is being sent
        """
        run_callable_somehow(self._handshake(request_message))

    def _handshake(self, request_message: RequestMessage) -> None:
        raise NotImplementedError(
            f"handshake cannot be handled - implement _handshake in {self.__class__} to handshake."
        )

    def handle_invalid_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Pass an invalid message to the client when an exception occurred while parsing the message from the client
        (in `handled_default_message_types()`)

        Parameters
        ----------
        request_message: RequestMessage
            the client message for which the parsing exception occurred
        exception: Exception
            exception object raised
        """
        run_callable_somehow(self._handle_invalid_message(request_message, exception))

    def _handle_invalid_message(self, message: RequestMessage, exception: Exception) -> None:
        raise NotImplementedError(
            "invalid message cannot be handled"
            + f" - implement _handle_invalid_message in {self.__class__} to handle invalid messages."
        )

    def handle_timeout(self, request_message: RequestMessage, timeout_type: str) -> None:
        """
        Pass timeout message to the client when the operation could not be executed within specified timeouts

        Parameters
        ----------
        request_message: RequestMessage
            the client message which could not executed within the specified timeout. timeout value is
            generally specified within the execution context values.
        """
        run_callable_somehow(self._handle_timeout(request_message, timeout_type=timeout_type))

    def _handle_timeout(self, request_message: RequestMessage, timeout_type: str) -> None:
        raise NotImplementedError(
            "timeouts cannot be handled ",
            f"- implement _handle_timeout in {self.__class__} to handle timeout.",
        )

    def handle_error_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Pass an exception message to the client when an exception occurred while executing the operation

        Parameters
        ----------
        request_message: RequestMessage
            the client message for which the exception occurred
        exception: Exception
            exception object raised
        """
        run_callable_somehow(self._handle_error_message(request_message, exception))

    def _handle_error_message(self, request_message: RequestMessage, exception: Exception) -> None:
        raise NotImplementedError(
            "exceptions cannot be handled ",
            f"- implement _handle_error_message in {self.__class__} to handle exceptions.",
        )

    def handled_default_message_types(self, request_message: RequestMessage) -> bool:
        """
        Handle default cases for the server without further processing of the request (for example, `HANDSHAKE`).
        This method is called once/supposed to be called when the message is received or popped out of the socket.

        Parameters
        ----------
        request_message: RequestMessage
            the client message to handle
        """
        if request_message.type == HANDSHAKE:
            self.handshake(request_message)
            return True
        elif request_message.type == EXIT:
            # self.send response with message type EXIT
            raise BreakLoop(f"exit message received from {request_message.sender_id} with msg-ID {request_message.id}")
        elif request_message.length != len(request_message.byte_array):
            self.handle_invalid_message(
                request_message,
                exception=ValueError(
                    f"message length {request_message.length} does not match "
                    + f"the number of message parts {len(request_message.byte_array)}"
                ),
            )
            return True
        return False


class AsyncZMQServer(BaseZMQServer, BaseAsyncZMQ):
    """
    An async ZMQ server that can handle multiple clients. Implements both blocking (non-polled) and
    non-blocking/polling form of receiving messages and sending replies. This server can be stopped from server side
    by calling `stop_polling()`.
    """

    def __init__(
        self,
        *,
        id: str,
        context: zmq.asyncio.Context | None = None,
        socket_type: zmq.SocketType = zmq.ROUTER,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        poll_timeout: int = 25,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            `id` of the server, also used as the identity of the ZMQ socket
        context: Optional, zmq.asyncio.Context
            ZeroMQ Context object to use. If None, a global context is used.
        socket_type: zmq.SocketType, default zmq.ROUTER
            socket type of ZMQ socket, default is ROUTER (enables address based routing of messages)
        access_point: Enum | str, default ZMQ_TRANSPORTS.IPC
            Use `TCP` or `tcp://*:<port>` for network access, `IPC` for multi-process applications,
            and `INPROC` for multi-threaded applications.
        poll_timeout: int, default 25
            time in milliseconds to poll the sockets specified under `procotols`. Useful for calling `stop_polling()`
            where the max delay to stop polling will be `poll_timeout`.
        kwargs: dict
            Additional arguments for `BaseZMQ` and `BaseAsyncZMQ` classes.

            - `logger`: logger instance to use. If None, a default logger is created.
        """

        super().__init__(id=id, **kwargs)
        self.create_socket(
            server_id=id,
            socket_id=id,
            node_type="server",
            context=context,
            access_point=access_point,
            socket_type=socket_type,
            **kwargs,
        )  # for server the server ID and socket ID is the same, only for clients they differ
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self.poll_timeout = poll_timeout

    @property
    def poll_timeout(self) -> int:
        """socket polling timeout in milliseconds greater than 0"""
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(
                f"polling period must be an integer greater than 0, not {value}. "
                + "Value is considered in milliseconds."
            )
        self._poll_timeout = value

    async def async_recv_request(self) -> RequestMessage:
        """
        Receive one message in a blocking form. There is no polling, therefore this method blocks until a message is
        received.

        Returns
        -------
        message: RequestMessage
            received message
        """
        while True:
            raw_message = await self.socket.recv_multipart()
            request_message = RequestMessage(raw_message)
            if not self.handled_default_message_types(request_message) and raw_message:
                self.logger.debug(
                    "received message from client",
                    client_id=request_message.sender_id,
                    msg_id=request_message.id,
                    message_type=request_message.type,
                )
                return request_message

    async def async_recv_requests(self) -> list[RequestMessage]:
        """
        Receive all currently available messages in blocking form. There is no polling, therefore this method
        blocks until at least one message is received.

        Returns
        -------
        messages: list[RequestMessage]
            list of received messages
        """
        messages = [await self.async_recv_request()]
        while True:
            try:
                raw_message = await self.socket.recv_multipart(zmq.NOBLOCK)
                request_message = RequestMessage(raw_message)
                if not self.handled_default_message_types(request_message) and raw_message:
                    self.logger.debug(
                        "received message from client",
                        client_id=request_message.sender_id,
                        msg_id=request_message.id,
                        message_type=request_message.type,
                    )
                    messages.append(request_message)
            except zmq.Again:
                break
        return messages

    async def async_send_response(
        self,
        request_message: RequestMessage,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> None:
        """
        Send response message for a request message.

        Parameters
        ----------
        request_message: RequestMessage
            original message based on which the response message can be automatically crafted and routed
        payload: SerializableData
            serializable data to be sent as response
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        """
        response_message = ResponseMessage.craft_reply_from_request(
            request_message=request_message,
            payload=payload,
            preserialized_payload=preserialized_payload,
        )
        await self.socket.send_multipart(response_message.byte_array)
        self.logger.debug(
            "sent response to client",
            receiver_id=response_message.receiver_id,
            msg_id=response_message.id,
            message_type=response_message.type,
        )

    async def async_send_response_with_message_type(
        self,
        request_message: RequestMessage,
        message_type: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> None:
        """
        Send a specific response message apart from `REPLY` for a request message.

        Parameters
        ----------
        request_message: RequestMessage
            original message based on which the response message can be automatically crafted and routed
        payload: SerializableData
            serializable data to be sent as response
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        """
        response_message = ResponseMessage.craft_from_arguments(
            receiver_id=request_message.sender_id,
            sender_id=self.id,
            message_type=message_type or REPLY,
            message_id=request_message.id,
            payload=payload,
            preserialized_payload=preserialized_payload,
        )
        await self.socket.send_multipart(response_message.byte_array)
        self.logger.debug(
            "sent response to client",
            receiver_id=response_message.receiver_id,
            msg_id=response_message.id,
            message_type=response_message.type,
        )

    async def poll_requests(self) -> list[RequestMessage]:
        """
        poll for messages with specified timeout (`poll_timeout`) and return if any messages are available.
        This method can be stopped from another method in a different thread or asyncio task (not in the same thread though).

        Returns
        -------
        messages: list[RequestMessage]
            list of received messages
        """
        self.stop_poll = False
        messages = []
        while not self.stop_poll:
            sockets = await self.poller.poll(self._poll_timeout)  # type hints dont work in this line
            for socket, _ in sockets:
                while True:
                    try:
                        raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    else:
                        request_message = RequestMessage(raw_message)
                        if not self.handled_default_message_types(request_message) and raw_message:
                            self.logger.debug(
                                "received message from client",
                                sender_id=request_message.sender_id,
                                receiver_id=request_message.receiver_id,
                                msg_id=request_message.id,
                                message_type=request_message.type,
                            )
                            messages.append(request_message)
            if len(messages) > 0:
                break
        return messages

    def stop_polling(self) -> None:
        """stop polling and unblock `poll_messages()` method"""
        self.stop_poll = True

    async def _handshake(self, request_message: RequestMessage) -> None:
        """
        Inner method that handles handshake. Scheduled by `handshake()` method, signature same as `handshake()`.
        """
        # Note that for ROUTER sockets, once the message goes through the sending socket, the address of the receiver
        # is replaced by the address of the sender once received
        handshake_message = ResponseMessage.craft_from_arguments(
            receiver_id=request_message.sender_id,
            sender_id=self.id,
            message_type=HANDSHAKE,
            message_id=request_message.id,
        )
        await self.socket.send_multipart(handshake_message.byte_array)
        self.logger.info(
            "sent handshake to client",
            receiver_id=handshake_message.receiver_id,
            msg_id=handshake_message.id,
        )

    async def _handle_timeout(self, request_message: RequestMessage, timeout_type: str) -> None:
        """
        Inner method that handles timeout. Scheduled by `handle_timeout()`, signature same as `handle_timeout`.
        """
        timeout_message = ResponseMessage.craft_from_arguments(
            receiver_id=request_message.sender_id,
            sender_id=self.id,
            message_type=TIMEOUT,
            message_id=request_message.id,
            payload=SerializableData(timeout_type, content_type="application/json"),
        )
        await self.socket.send_multipart(timeout_message.byte_array)
        self.logger.warning(
            f"sent {timeout_type} timeout to client",
            receiver_id=timeout_message.receiver_id,
            msg_id=timeout_message.id,
        )

    async def _handle_invalid_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Inner method that handles invalid messages. Scheduled by `handle_invalid_message()`,
        signature same as `handle_invalid_message()`.
        """
        invalid_message = ResponseMessage.craft_from_arguments(
            receiver_id=request_message.sender_id,
            sender_id=self.id,
            message_type=INVALID_MESSAGE,
            message_id=request_message.id,
            payload=SerializableData(
                dict(exception=format_exception_as_json(exception)),
                content_type="application/json",
            ),
        )
        await self.socket.send_multipart(invalid_message.byte_array)
        self.logger.warning(
            f"informed client about invalid message due to exception - {str(exception)}",
            receiver_id=invalid_message.receiver_id,
            msg_id=invalid_message.id,
        )

    async def _handle_error_message(self, request_message: RequestMessage, exception: Exception) -> None:
        error_message = ResponseMessage.craft_with_message_type(
            request_message=request_message,
            message_type=ERROR,
            payload=SerializableData(
                dict(exception=format_exception_as_json(exception)),
                content_type="application/json",
            ),
        )
        await self.socket.send_multipart(error_message.byte_array)
        self.logger.warning(
            f"sent error message to client for exception - {str(exception)}",
            receiver_id=error_message.receiver_id,
            msg_id=error_message.id,
        )

    def exit(self) -> None:
        """unregister socket from poller and terminate socket. context is not terminated as it may be shared."""
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
            self.socket.close(0)
            self.logger.info("terminated socket of server")
        except Exception as ex:
            self.logger.warning(f"error while closing socket - {str(ex)}")


class ZMQServerPool(BaseZMQServer):
    """Implements pool of async ZMQ servers (& their sockets)"""

    def __init__(self, *, ids: list[str] | None = None, **kwargs) -> None:
        """
        ids: List[str], optional
            list of server IDs to create the server pool. If None, an empty pool is created and servers can be
            registered later using `register_server()`.
        kwargs: dict
            Additional arguments for `BaseZMQ` and `BaseAsyncZMQ` classes.

            - `logger`: logger instance to use. If None, a default logger is created.
        """
        self.context = global_config.zmq_context()
        self.poller = zmq.asyncio.Poller()
        self.pool = dict()  # type: dict[str, AsyncZMQServer]
        if ids:
            for id in ids:
                self.pool[id] = AsyncZMQServer(id=id, context=self.context, **kwargs)
            for server in self.pool.values():
                self.poller.register(server.socket, zmq.POLLIN)
        super().__init__(id=f"pool-{uuid_hex()}", **kwargs)

    def create_socket(
        self,
        *,
        id: str,
        bind: bool,
        context: zmq.asyncio.Context | zmq.Context,
        access_point: str,
        socket_type: zmq.SocketType = zmq.ROUTER,
        **kwargs,
    ) -> None:
        raise NotImplementedError("create socket not supported by ZMQServerPool")
        # we override this method to prevent socket creation. id set to pool is simply a filler
        # return super().create_socket()

    def register_server(self, server: AsyncZMQServer) -> None:
        if not isinstance(server, (AsyncZMQServer)):
            raise TypeError(f"registration possible only for subclass of AsyncZMQServer. Given type {type(server)}")
        self.pool[server.id] = server
        self.poller.register(server.socket, zmq.POLLIN)

    def deregister_server(self, server: AsyncZMQServer) -> None:
        self.poller.unregister(server.socket)
        self.pool.pop(server.id)

    @property
    def poll_timeout(self) -> int:
        """socket polling timeout in milliseconds greater than 0"""
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(
                "polling period must be an integer greater than 0, not {}.".format(value)
                + " Value is considered in milliseconds."
            )
        self._poll_timeout = value

    async def async_recv_request(self, id: str) -> RequestMessage:
        """
        receive message for server specified by id

        Parameters
        ----------
        id: str
            id of the ZMQ server

        Returns
        -------
        RequestMessage
            received message
        """
        return await self.pool[id].async_recv_request()

    async def async_recv_requests(self, id: str) -> list[RequestMessage]:
        """
        receive all available messages for server specified by id

        Parameters
        ----------
        id: str
            id of the ZMQ server

        Returns
        -------
        list[RequestMessage]
            list of received messages
        """
        return await self.pool[id].async_recv_requests()

    async def async_send_response(
        self,
        *,
        id: str,
        request_message: RequestMessage,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> None:
        """
        send response for a request message for server specified by id

        Parameters
        ----------
        id: str
            id of the ZMQ server
        request_message: RequestMessage
            request message for which response is being given
        payload: SerializableData
            serializable data to be sent as response
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        """
        await self.pool[id].async_send_response(
            request_message=request_message,
            payload=payload,
            preserialized_payload=preserialized_payload,
        )

    async def poll(self) -> list[RequestMessage]:
        """
        Pool for messages in the entire server pool. Use the message to identify the server by using `receiver_id` of
        the message header.

        Returns
        -------
        list[RequestMessage]
            list of received messages across all servers in the pool
        """
        self.stop_poll = False
        messages = []
        while not self.stop_poll:
            sockets = await self.poller.poll(self._poll_timeout)
            for socket, _ in sockets:
                while True:
                    try:
                        raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    else:
                        if raw_message:
                            request_message = RequestMessage(raw_message)
                            self.logger.debug(
                                "received message from client",
                                sender_id=request_message.sender_id,
                                receiver_id=request_message.receiver_id,
                                msg_id=request_message.id,
                            )
                            messages.append(request_message)
        return messages

    def stop_polling(self) -> None:
        """stop polling method `poll()`"""
        self.stop_poll = True

    def __getitem__(self, key) -> AsyncZMQServer:
        return self.pool[key]

    def __iter__(self) -> Iterator[str]:
        return self.pool.__iter__()

    def __contains__(self, name: str) -> bool:
        return name in self.pool.keys()

    def exit(self) -> None:
        for server in self.pool.values():
            try:
                self.poller.unregister(server.socket)
            except Exception as ex:
                self.logger.warning(f"could not unregister poller - {str(ex)}")
            server.exit()


class BaseZMQClient(BaseZMQ):
    """Base class for all ZMQ clients irrespective of sync and async"""

    def __init__(
        self,
        *,
        id: str,
        server_id: str,
        logger: structlog.BoundLogger | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            Unique id of the client to receive messages from the server. Each client connecting to same server must
            still have unique ID.
        server_id: str
            The server id to connect to
        logger: Optional[logging.Logger]
            logger instance to use. If None, a default logger is created.
        kwargs: dict
            Additional arguments:

            - `poll_timeout`: `int`, time in milliseconds to poll the socket for messages, default is 1000 ms.
        """
        super().__init__(id=id, **kwargs)
        if not logger:
            logger = structlog.get_logger()
        self.logger = logger.bind(component="broker", impl=self.__class__.__name__, id=id, server_id=server_id)
        self.server_id = server_id
        self.socket: zmq.Socket | zmq.asyncio.Socket
        self.poller: zmq.Poller | zmq.asyncio.Poller
        self._monitor_socket = None  # type: zmq.Socket | zmq.asyncio.Socket | None
        self._response_cache = dict()
        self._poll_timeout = kwargs.get("poll_timeout", 1000)  # default to 1000 ms
        self._stop = False  # in general, stop any loop with this variable

    @property
    def poll_timeout(self) -> int:
        """socket polling timeout in milliseconds greater than 0"""
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError(
                f"polling period must be an integer greater than 0, not {value}. Value is considered in milliseconds."
            )
        self._poll_timeout = value

    def exit(self) -> None:
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
            # TODO - there is some issue here while quitting
            if self._monitor_socket is not None:
                self.poller.unregister(self._monitor_socket)
        except Exception as ex:  # noqa
            # TODO log message and undo noqa
            # raises a weird key error for some reason
            # unable to deregister from poller - <zmq.asyncio.Socket(zmq.PAIR) at 0x1c9e5028830> - KeyError
            # unable to deregister from poller - <zmq.asyncio.Socket(zmq.PAIR) at 0x1c9e502a350> - KeyError
            # unable to deregister from poller - <zmq.asyncio.Socket(zmq.PAIR) at 0x1c9e5080750> - KeyError
            # unable to deregister from poller - <zmq.asyncio.Socket(zmq.PAIR) at 0x1c9e5082430> - KeyError
            self.logger.warning(f"unable to deregister socket from poller - {str(ex)} - {type(ex).__name__}")
        try:
            if self._monitor_socket is not None:
                self._monitor_socket.close(0)
            self.socket.close(0)
            self.logger.info("terminated socket of client")
        except Exception as ex:
            self.logger.warning(
                "could not properly terminate socket or attempted to terminate an already terminated,"
                + f" exception message: {str(ex)}"
            )

    def handled_default_message_types(self, response_message: ResponseMessage) -> bool:
        """
        Handle default cases for the client. This method is called once/supposed to be called when the message
        is received or popped out of the socket.

        Parameters
        ----------
        response_message: List[ResponseMessage]
            the server message to handle
        """
        if len(response_message.byte_array) == 2:  # socket monitor message, not our message
            try:
                if ZMQ_EVENT_MAP[parse_monitor_message(response_message.byte_array)["event"]] == SERVER_DISCONNECTED:
                    raise ConnectionAbortedError("server disconnected")
                return True  # True should simply continue polling
            except RuntimeError:
                self.logger.warning(
                    "message received from monitor socket cannot be deserialized, "
                    + f"assuming its irrelevant and skipping, {response_message.byte_array}"
                )
                return True
        elif len(response_message.byte_array) != ResponseMessage.length:  # either an error or not our message
            self.logger.warning(
                f"received unknown message from server, message length: {len(response_message.byte_array)}, "
                + f"message: {response_message.byte_array}"
            )
            return True
        if response_message.type == HANDSHAKE:
            return True
        return False

    def stop(self) -> None:
        """Stop polling for messages from server. Automatically reset when polling starts again."""
        self._stop = True


class SyncZMQClient(BaseZMQClient, BaseSyncZMQ):
    """Sync ZMQ client (as-in not asyncio compatible) that connect with a ZMQ server. Implements REQ-REP pattern."""

    def __init__(
        self,
        id: str,
        server_id: str,
        context: zmq.Context | None = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        handshake: bool = True,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            Unique id of the client to receive messages from the server. Each client connecting to same server must
            still have unique ID.
        server_id: str
            The server id to connect to
        context: Optional, zmq.Context
            ZeroMQ Context object to use. If None, a global context is used.
        access_point: Enum | str, default ZMQ_TRANSPORTS.IPC
            Use `TCP` or `tcp://<host>:<port>` for network access, `IPC` for multi-process applications,
            and `INPROC` for multi-threaded applications.
        handshake: bool
            When true, handshake with the server first before receiving any other message and block until that handshake was
            accomplished, highly recommended.
        kwargs: dict[str, Any]
            Additional arguments:

            - `poll_timeout`: `int`. The timeout for polling the socket (in milliseconds)
            - `handshake_timeout`: `int`. The timeout for the handshake process (in milliseconds) to complete.
                If handshake does not complete within this time, an exception is raised. Only relevant if `handshake` is True.
            - `logger`: `logging.Logger`. logger instance to use. If None, a default logger is created.
        """
        super().__init__(id=id, server_id=server_id, **kwargs)
        self.create_socket(
            server_id=server_id,
            socket_id=id,
            node_type="client",
            context=context,
            access_point=access_point,
            **kwargs,
        )
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self._poller_lock = threading.Lock()
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))

    def send_request(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> bytes:
        """
        send request message to server.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        bytes
            a message id in bytes
        """
        request_message = RequestMessage.craft_from_arguments(
            receiver_id=self.server_id,
            sender_id=self.id,
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        self.socket.send_multipart(request_message.byte_array)
        self.logger.debug(
            "sent message to server",
            msg_id=request_message.id,
            message_type=request_message.type,
            thing_id=thing_id,
            operation=operation,
            objekt=objekt,
        )
        return request_message.id

    def recv_response(self, message_id: bytes) -> ResponseMessage:
        """
        Receives response from server. Messages are identified by message id, and out of order messages are sent to
        a cache which may be popped later. This method blocks until the expected message is received or `stop_polling()`
        is called from another thread.

        Parameters
        ----------
        message_id: bytes
            the message id of the expected response message
        """
        self._stop = False
        while not self._stop:
            if message_id in self._response_cache:
                return self._response_cache.pop(message_id)
            try:
                if not self._poller_lock.acquire(timeout=self.poll_timeout / 1000 if self.poll_timeout else -1):
                    continue
                sockets = self.poller.poll(self.poll_timeout)
                response_message = None  # type: ResponseMessage
                for socket, _ in sockets:
                    try:
                        raw_message = socket.recv_multipart(zmq.NOBLOCK)
                        response_message = ResponseMessage(raw_message)
                    except zmq.Again:
                        pass
                    if response_message:
                        if self.handled_default_message_types(response_message):
                            continue
                        if message_id != response_message.id:
                            self._response_cache[response_message.id] = response_message
                            self.logger.debug(
                                "cached response as it does not corresponding to expected ID",
                                msg_id=response_message.id,
                                expected_msg_id=message_id,
                            )
                        else:
                            self.logger.debug(
                                "received response",
                                msg_id=response_message.id,
                                message_type=response_message.type,
                            )
                            return response_message
            finally:
                try:
                    self._poller_lock.release()
                except Exception as ex:  # noqa
                    # TODO log exception message and undo noqa
                    # 1. no need to release an unacquired lock, which can happen if another thread polling
                    # put the expected message in response message cache
                    # 2. also release the lock in every iteration because a message may be added in response cache
                    # and may not return the method, which means the loop will run again and the lock needs to reacquired
                    self.logger.warning(f"could not release poller lock for recv_response - {str(ex)}")

    def execute(
        self,
        thing_id: bytes,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> ResponseMessage:
        """
        send an operation and receive the response for it.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        ResponseMessage
            response message from server after completing the operation
        """
        message_id = self.send_request(
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        return self.recv_response(message_id=message_id)

    def handshake(self, timeout: float | int = 60000) -> None:
        """
        handshake with server before sending first message

        Parameters
        ----------
        timeout: float | int
            timeout in milliseconds to wait for handshake to complete. If handshake does not complete within this time,
            a `ConnectionError` is raised. If None, wait indefinitely until handshake completes.
        """
        self._stop = False
        start_time = time.time_ns()
        while not self._stop:
            if timeout is not None and (time.time_ns() - start_time) / 1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.server_id}' from client '{self.id}'")
            handshake_message = RequestMessage.craft_with_message_type(self.id, self.server_id, HANDSHAKE)
            self.socket.send_multipart(handshake_message.byte_array)
            self.logger.info("sent Handshake to server")
            if self.poller.poll(500):
                try:
                    raw_message = self.socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass
                else:
                    if response_message.type == HANDSHAKE:
                        self.logger.info("client handshook with server")
                        break
                    elif self.handled_default_message_types(response_message):
                        continue
                    else:
                        self._response_cache[response_message.id] = response_message
            else:
                self.logger.info("got no response for handshake")
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN)
        # sufficient to know when server dies only while receiving messages, not continuous polling


class AsyncZMQClient(BaseZMQClient, BaseAsyncZMQ):
    """Async ZMQ client (asyncio compatible) that connect with a ZMQ server. Implements REQ-REP pattern."""

    def __init__(
        self,
        id: str,
        server_id: str,
        context: zmq.asyncio.Context | None = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        handshake: bool = True,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            Unique id of the client to receive messages from the server. Each client connecting to same server must
            still have unique ID.
        server_id: str
            The server id to connect to
        context: Optional, zmq.Context
            ZeroMQ Context object to use. If None, a global context is used.
        access_point: Enum | str, default ZMQ_TRANSPORTS.IPC
            Use `TCP` or `tcp://<host>:<port>` for network access, `IPC` for multi-process applications,
            and `INPROC` for multi-threaded applications.
        handshake: bool
            When true, handshake with the server first before receiving any other message and block until that handshake was
            accomplished, highly recommended.
        kwargs: dict[str, Any]
            Additional arguments:

            - `poll_timeout`: `int`. The timeout for polling the socket (in milliseconds)
            - `handshake_timeout`: `int`. The timeout for the handshake process (in milliseconds) to complete.
                If handshake does not complete within this time, an exception is raised. Only relevant if `handshake` is True.
            - `logger`: `logging.Logger`. logger instance to use. If None, a default logger is created.
        """
        super().__init__(id=id, server_id=server_id, **kwargs)
        self.create_socket(
            server_id=server_id,
            socket_id=id,
            node_type="client",
            context=context,
            access_point=access_point,
            **kwargs,
        )
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self.poller.register(self._monitor_socket, zmq.POLLIN)
        self._poller_lock = asyncio.Lock()
        self._handshake_event = asyncio.Event()
        self._handshake_event.clear()
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))

    def handshake(self, timeout: int | None = 60000) -> None:
        """
        schedules a handshake coroutine in the running event loop
        or completes handshake synchronously if no event loop is running.
        Use `handshake_complete()` async method to check if handshake is complete.

        Parameters
        ----------
        timeout: float | int
            timeout in milliseconds to wait for handshake to complete. If handshake does not complete within this time,
            a `ConnectionError` is raised. If None, wait indefinitely until handshake completes.
        """
        run_callable_somehow(self._handshake(timeout))

    async def _handshake(self, timeout: float | int | None = 60000) -> None:
        """handshake with server before sending first message"""
        self._stop = False
        if self._monitor_socket is not None and self._monitor_socket in self.poller:
            self.poller.unregister(self._monitor_socket)
        self._handshake_event.clear()
        start_time = time.time_ns()
        while not self._stop:
            if timeout is not None and (time.time_ns() - start_time) / 1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.server_id}' from client '{self.id}'")
            handshake_message = RequestMessage.craft_with_message_type(self.id, self.server_id, HANDSHAKE)
            await self.socket.send_multipart(handshake_message.byte_array)
            self.logger.info("sent Handshake to server")
            if await self.poller.poll(500):
                try:
                    raw_message = await self.socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass
                else:
                    if response_message.type == HANDSHAKE:  # type: ignore
                        self.logger.info("client handshook with server")
                        break
                    elif self.handled_default_message_types(response_message):
                        continue
                    else:
                        self._response_cache[response_message.id] = response_message
            else:
                self.logger.info("got no response for handshake")
        self.poller.register(self._monitor_socket, zmq.POLLIN)
        self._handshake_event.set()

    async def handshake_complete(self, timeout: float | int = 60000) -> None:
        """
        wait for handshake to complete

        Parameters
        ----------
        timeout: float | int
            timeout in milliseconds to wait for handshake to complete. If handshake does not complete within this time,
            a `TimeoutError` is raised.
        """
        await asyncio.wait_for(self._handshake_event.wait(), int(timeout / 1000) if timeout else None)
        if not self._handshake_event.is_set():
            raise TimeoutError(f"Handshake with server timed out after {timeout} ms")

    async def async_send_request(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: dict[str, Any] = default_thing_execution_context,
    ) -> str:
        """
        send request message to server.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        bytes
            a message id in bytes
        """
        request_message = RequestMessage.craft_from_arguments(
            receiver_id=self.server_id,
            sender_id=self.id,
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        await self.socket.send_multipart(request_message.byte_array)
        self.logger.debug(
            "sent message to server",
            msg_id=request_message.id,
            message_type=request_message.type,
            thing_id=thing_id,
            operation=operation,
            objekt=objekt,
        )
        return request_message.id

    async def async_recv_response(self, message_id: str) -> list[ResponseMessage]:
        """
        Receives response from server. Messages are identified by message id, and out of order messages are sent to
        a cache which may be popped later. This method blocks until the expected message is received or `stop_polling()`
        is called from another thread.

        Parameters
        ----------
        message_id: bytes
            the message id of the expected response message
        """
        self._stop = False
        while not self._stop:
            if message_id in self._response_cache:
                return self._response_cache.pop(message_id)
            try:
                try:
                    await asyncio.wait_for(
                        self._poller_lock.acquire(),
                        timeout=self.poll_timeout / 1000 if self.poll_timeout else None,
                    )
                except TimeoutError:
                    continue
                sockets = await self.poller.poll(self._poll_timeout)
                response_message = None
                for socket, _ in sockets:
                    try:
                        raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                        response_message = ResponseMessage(raw_message)
                    except zmq.Again:
                        continue
                    if response_message:
                        if self.handled_default_message_types(response_message):
                            continue
                        if message_id != response_message.id:
                            self._response_cache[response_message.id] = response_message
                            self.logger.debug(
                                "cached response as it does not corresponding to expected ID",
                                msg_id=response_message.id,
                                expected_msg_id=message_id,
                            )
                        else:
                            self.logger.debug(
                                "received response",
                                msg_id=response_message.id,
                                message_type=response_message.type,
                            )
                            return response_message
            finally:
                try:
                    self._poller_lock.release()
                except Exception as ex:
                    self.logger.warning(f"could not release poller lock for async_recv_response - {str(ex)}")

    async def async_execute(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> ResponseMessage:
        """
        send an operation and receive the response for it.

        Parameters
        ----------
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        ResponseMessage
            response message from server after completing the operation
        """
        message_id = await self.async_send_request(
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        return await self.async_recv_response(message_id)


class MessageMappedZMQClientPool(BaseZMQClient):
    """
    Pool of async ZMQ clients, to be primarily used within protocol bindings where multiple things may be served.
    Use message ID to track responses.
    """

    def __init__(
        self,
        id: str,
        client_ids: list[str],
        server_ids: list[str],
        handshake: bool = True,
        context: zmq.asyncio.Context = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        poll_timeout: int = 25,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            ID of the pool, must be unique.
        client_ids: List[str]
            list of id's of clients in the pool, must be unique. Clients are created with these ID's.
            For pre-existing clients, use `register` method instead and leave this list empty.
        server_ids: List[str]
            list of id's of servers to connect to, must be same length as client_ids. For pre-existing clients that
            are connected to servers, use `register` method instead and leave this list empty.
        handshake: bool
            when true, handshake with the server first before allowing first message and block until that handshake was
            accomplished.
        context: zmq.asyncio.Context
            ZMQ context to use, if None, a global context is used.
        access_point: Enum | str, default ZMQ_TRANSPORTS.IPC
            Default access point for all clients in the pool, usually not helpful except `INPROC` transport.
            Use `TCP` or `tcp://<host>:<port>` for network access, `IPC` for multi-process applications,
            and `INPROC` for multi-threaded applications.
        poll_timeout: int
            socket polling timeout in milliseconds greater than 0.
        **kwargs:
            Additional arguments:

            - `logger`: `logging.Logger`, logger instance to use. If None, a default logger is created.
        """
        super().__init__(id=id, server_id=None, **kwargs)
        if len(client_ids) != len(server_ids):
            raise ValueError("client_ids and server_ids must have same length")
        # this class does not call create_socket method
        self.context = context or global_config.zmq_context()
        self.pool = dict()  # type: dict[str, AsyncZMQClient]
        self.poller = zmq.asyncio.Poller()
        for client_id, server_id in zip(client_ids, server_ids):
            client = AsyncZMQClient(
                id=client_id,
                server_id=server_id,
                handshake=handshake,
                context=self.context,
                access_point=access_point,
                logger=self.logger,
            )
            self.register(client)
        # Both the client pool as well as the individual client get their serializers and client_types
        # This is required to implement pool level sending and receiving messages like polling of pool of sockets
        self.event_pool = AsyncioEventPool(len(server_ids))
        self.events_map = dict()  # type: dict[bytes, asyncio.Event]
        self.message_map = dict()
        self.cancelled_messages = []
        self.poll_timeout = poll_timeout
        self.stop_poll = False
        self._thing_to_client_map = dict()  # type: dict[str, AsyncZMQClient]
        self._client_to_thing_map = dict()  # type: dict[str, str]

    def create_new(self, id: str, server_id: str, access_point: str = ZMQ_TRANSPORTS.IPC) -> None:
        """
        Create new server with specified transport & add it to the pool.
        Other arguments are taken from pool default specifications.

        Parameters
        ----------
        id: str
            id of the new client to be created
        server_id: str
            id of the server to connect to
        access_point: str
            transport method used by the server - `IPC`, `INPROC` or `tcp://<host>:<port>`
        """
        if server_id not in self.pool.keys():
            client = AsyncZMQClient(
                id=id,
                server_id=server_id,
                handshake=True,
                context=self.context,
                access_point=access_point,
                logger=self.logger,
            )
            client._monitor_socket = client.socket.get_monitor_socket()
            self.poller.register(client._monitor_socket, zmq.POLLIN)
            self.pool[id] = client
        else:
            raise ValueError(f"client for instance name '{server_id}' already present in pool")

    def register(self, client: AsyncZMQClient, thing_id: str | None = None) -> None:
        """
        Register a pre-existing client with the pool.

        Parameters
        ----------
        client: AsyncZMQClient
            client to be registered
        thing_id: Optional, str
            thing_id to which this client is mapped, especially when the client is connected to a server that serves
            only one `Thing`.
        """
        if not isinstance(client, AsyncZMQClient):
            raise TypeError(
                "registration possible for clients only subclass of AsyncZMQClient." + f" Given type {type(client)}"
            )
        if client.id not in self.pool:
            self.pool[client.id] = client
            self.poller.register(client.socket, zmq.POLLIN)
            self.poller.register(client._monitor_socket, zmq.POLLIN)
        elif self.pool[client.id] != client:
            warnings.warn(
                f"client with id '{client.id}' already present in pool. Replacing with {client}",
                category=UserWarning,
            )
        if thing_id:
            self._thing_to_client_map[thing_id] = client.id
            self._client_to_thing_map[client.id] = thing_id

    def get_client_id_from_thing_id(self, thing_id: str) -> str:
        """
        Retrieve client mapped to a `thing_id`. The value must have been previously set using `register` method.

        Parameters
        ----------
        thing_id: str
            the `thing_id` for which the client is to be retrieved
        """
        if thing_id not in self._thing_to_client_map:
            raise ValueError(f"client for thing_id '{thing_id}' not present in pool")
        return self._thing_to_client_map.get(thing_id, None)

    def get_thing_id_from_client_id(self, client_id: str) -> str:
        """
        Retrieve `thing_id` mapped to a client. The value must have been previously set using `register` method.

        Parameters
        ----------
        client_id: str
            the client id for which the `thing_id` is to be retrieved
        """
        if client_id not in self._client_to_thing_map:
            raise ValueError(f"thing_id for client_id '{client_id}' not present in pool")
        return self._client_to_thing_map.get(client_id, None)

    def get_client_protocol(self, thing_id: str) -> str:
        """
        Retrieve protocol used by a client in the pool.

        Parameters
        ----------
        client_id: str
            the client id for which the protocol is to be retrieved
        """
        if thing_id not in self._thing_to_client_map:
            raise ValueError(f"client_id '{thing_id}' not present in pool")
        client_id = self._thing_to_client_map[thing_id]
        return self.pool[client_id].socket_address.split("://")[0].upper()

    @property
    def poll_timeout(self) -> int:
        """socket polling timeout in milliseconds greater than 0"""
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(
                "polling period must be an integer greater than 0, not {}. Value is considered in milliseconds".format(
                    value
                )
            )
        self._poll_timeout = value

    async def handshake_complete(self) -> None:
        """wait for handshake to complete for all clients in the pool"""
        for client in self.pool.values():
            await client.handshake_complete()  # sufficient to wait serially

    def handshake(self, timeout: int | None = 60000) -> None:
        """
        schedules handshake coroutines for each client in the running event loop
        or completes handshake synchronously if no event loop is running.
        Use `handshake_complete()` async method to check if handshake is complete.

        Parameters
        ----------
        timeout: float | int
            timeout in milliseconds to wait for handshake to complete. If handshake does not complete within this time,
            a `ConnectionError` is raised. If None, wait indefinitely until handshake completes.
        """
        for client in self.pool.values():
            client.handshake(timeout)

    async def poll_responses(self) -> None:
        """
        Poll for replies from server.This method should be independently started in the event loop by calling `start_polling()`.
        Sending message requests and retrieving a response is still carried out by other methods.
        Do not duplicate this method call as there are no checks how many pollers exist and messages will become malformed
        if multiple pollers are active.
        """
        self.logger.info("client polling started for sockets for {}".format(list(self.pool.keys())))
        self.stop_poll = False
        event_loop = asyncio.get_event_loop()
        while not self.stop_poll:
            sockets = await self.poller.poll(self.poll_timeout)  # type hints dont work in this line
            for socket, _ in sockets:
                while True:
                    try:
                        raw_response = await socket.recv_multipart(zmq.NOBLOCK)
                        response_message = ResponseMessage(raw_response)
                    except zmq.Again:
                        # errors in handle_message should reach the client.
                        break
                    except ConnectionAbortedError:
                        for client in self.pool.values():
                            if client.socket.get_monitor_socket() == socket:
                                self.poller.unregister(client.socket)  # leave the monitor in the pool
                                client.handshake(timeout=None)
                                self.logger.error(
                                    f"client {client.id} disconnected from server."
                                    + " Unregistering from poller temporarily until server comes back."
                                )
                                break
                    else:
                        if self.handled_default_message_types(response_message):
                            continue
                        message_id = response_message.id
                        self.logger.debug(
                            "received response from server",
                            sender_id=response_message.sender_id,
                            receiver_id=response_message.receiver_id,
                            msg_id=response_message.id,
                            message_type=response_message.type,
                        )
                        if message_id in self.cancelled_messages:
                            self.cancelled_messages.remove(message_id)
                            self.logger.debug("dropping a cancelled message", msg_id=message_id)
                            continue
                        self.message_map[message_id] = response_message
                        event = self.events_map.get(message_id, None)
                        if event:
                            event.set()
                        else:
                            event_loop.create_task(self._resolve_response(message_id, response_message))

    async def _resolve_response(self, message_id: str, data: Any) -> None:
        """
        This method is called when there is no asyncio Event available for a message ID. This can happen only
        when the server replied before the client created a asyncio.Event object. check `async_execute()` for details.

        Parameters
        ----------
        message_id: bytes
            the message for which the event was not created
        data: ResponseMessage
            the response message received from server
        """
        max_number_of_retries = 100
        for i in range(max_number_of_retries):
            await asyncio.sleep(0.025)
            try:
                event = self.events_map[message_id]
            except KeyError:
                if message_id in self.cancelled_messages:
                    # Only for safety, likely should never reach here
                    self.cancelled_messages.remove(message_id)
                    self.logger.debug("message cancelled, not retrieving response", msg_id=message_id)
                    return
                if i >= max_number_of_retries - 1:
                    self.logger.error("unknown message id without corresponding event object", msg_id=message_id)
                    return
            else:
                self.message_map[message_id] = data
                event.set()
                break

    def assert_client_ready(self, client: AsyncZMQClient):
        if not client._handshake_event.is_set():
            raise ConnectionAbortedError(f"{client.id} is currently not alive")
        if client.socket not in self.poller._map:
            raise ConnectionError(
                "handshake complete, server is alive but client socket not yet ready to be polled."
                + "Application using MessageMappedClientPool should register the socket manually for polling."
                + "If using hololinked.server.HTTPServer, socket is waiting until HTTP Server updates its "
                "routing logic as the server has just now come alive, please try again soon."
            )

    async def async_send_request(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> str:
        """
        send request message to server.

        Parameters
        ----------
        client_id: str
            id of the client in the pool to be used to send the message
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        bytes
            a message id in bytes
        """
        client_id = self.get_client_id_from_thing_id(thing_id)
        self.assert_client_ready(self.pool[client_id])
        message_id = await self.pool[client_id].async_send_request(
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        event = self.event_pool.pop()
        self.events_map[message_id] = event
        return message_id

    async def async_recv_response(
        self, thing_id: str, message_id: bytes, timeout: float | int | None = None
    ) -> ResponseMessage:
        """
        Receive response for specified message ID.

        Parameters
        ----------
        client_id: str
            id of the client in the pool to be used to receive the message
        message_id: bytes
            the message id for which response needs to be fetched
        timeout: float | int | None
            Client side timeout, not the same as timeout passed to server. Recommended to be None in general cases.
            The reply is dropped if this timeout occurs. Usually the server always replies when either of invokation or
            execution timeout occurs. This timeout ensures that the protocol binding does not wait indefinitely for a message
            that may never arrive.

        Returns
        -------
        response: ResponseMessage
            response message from server corresponding to the message id

        Raises
        ------
        ValueError
            if supplied message id is not valid
        TimeoutError
            if timeout is not None and response did not arrive
        """
        try:
            client_id = self.get_client_id_from_thing_id(thing_id)
            event = self.events_map[message_id]
        except KeyError:
            raise KeyError(f"message id {message_id} unknown.") from None
        while True:
            try:
                await asyncio.wait_for(event.wait(), timeout)
                # default 5 seconds because we want to check if server is also dead
                if event.is_set():  # i.e. if timeout is not None, check if event is set
                    break
                self.assert_client_ready(self.pool[client_id])
            except TimeoutError:
                self.cancelled_messages.append(message_id)
                self.logger.error("message added to list of cancelled messages", msg_id=message_id)
                raise TimeoutError(f"Execution not completed within {timeout} seconds") from None
        self.events_map.pop(message_id)
        self.event_pool.completed(event)
        response = self.message_map.pop(message_id)
        return response

    async def async_execute(
        self,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> ResponseMessage:
        """
        send an operation and receive the response for it.

        Parameters
        ----------
        client_id: str
            id of the client in the pool to be used to send the message
        thing_id: str
            `id` of the `Thing` on which an operation is to be performed
        objekt: str
            name of property, action or event (usually only property or action)
        operation: str
            operation to be performed, like `readproperty`, `writeproperty`, `invokeaction` etc.
        payload: SerializableData
            serializable data to be sent as payload
        preserialized_payload: PreserializedData
            pre-encoded data to be sent as payload, generally used for large or custom data that is already serialized
        server_execution_context: dict[str, Any]
            Specify server level execution context like `invokationTimeout`, `executionTimeout`, `oneway` operation etc.
        thing_execution_context: dict[str, Any]
            Specify thing level execution context like `fetchExecutionLogs` etc.

        Returns
        -------
        ResponseMessage
            response message from server after completing the operation
        """
        message_id = await self.async_send_request(
            thing_id=thing_id,
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )
        return await self.async_recv_response(
            thing_id=thing_id,
            message_id=message_id,
        )

    def start_polling(self) -> None:
        """register the server message polling loop in the asyncio event loop"""
        get_current_async_loop().create_task(self.poll_responses())

    def stop_polling(self):
        """
        stop polling for replies from server
        """
        self.stop_poll = True
        for client in self.pool.values():
            client.stop()

    async def async_execute_in_all(
        self,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        thing_ids: list[str] | None = None,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> dict[str, ResponseMessage]:
        if not thing_ids:
            thing_ids = self._client_to_thing_map.values()

        gathered_replies = await asyncio.gather(
            *[
                self.async_execute(
                    thing_id=id,
                    objekt=objekt,
                    operation=operation,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                )
                for id in thing_ids
            ]
        )
        replies = dict()
        for id, response in zip(thing_ids, gathered_replies):
            replies[id] = response
        return replies

    async def async_execute_in_all_things(
        self,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: ServerExecutionContext = default_server_execution_context,
        thing_execution_context: ThingExecutionContext = default_thing_execution_context,
    ) -> dict[str, ResponseMessage]:
        """execute the same operation in all `Thing`s"""
        return await self.async_execute_in_all(
            objekt=objekt,
            operation=operation,
            payload=payload,
            preserialized_payload=preserialized_payload,
            server_execution_context=server_execution_context,
            thing_execution_context=thing_execution_context,
        )

    async def ping_all_servers(self):
        return await self.async_execute_in_all()  # operation='invokeAction', objekt=CommonRPC.PING)

    def __contains__(self, name: str) -> bool:
        return name in self.pool

    def __getitem__(self, key) -> AsyncZMQClient:
        return self.pool[key]

    def __iter__(self) -> Iterator[AsyncZMQClient]:
        return iter(self.pool.values())

    def exit(self) -> None:
        try:
            BaseZMQ.exit(self)
            for client in self.pool.values():
                self.poller.unregister(client.socket)
                self.poller.unregister(client.socket.get_monitor_socket())
                client.exit()
            self.logger.info("all client socket unregistered")
        except Exception as ex:
            self.logger.warning(
                "could not properly terminate context or attempted to terminate an already terminated context."
                + f" Exception message: {str(ex)}"
            )

    """
    Inheritance tree:

    BaseZMQ
    BaseAsyncZMQ
    BaseSyncZMQ
    BaseZMQClient
    SyncZMQClient
    AsyncZMQClient
    MessageMappedClientPool
    """


class AsyncioEventPool:
    """
    creates a pool of asyncio Events to be used as a synchronisation object for MessageMappedClientPool

    Parameters
    ----------
    initial_number_of_events: int
        initial pool size of events
    """

    def __init__(self, initial_number_of_events: int) -> None:
        self.pool = [asyncio.Event() for i in range(initial_number_of_events)]
        self.size = initial_number_of_events

    def pop(self) -> asyncio.Event:
        """
        pop an event, new one is created if nothing left in pool
        """
        try:
            event = self.pool.pop(0)
        except IndexError:
            self.size += 1
            event = asyncio.Event()
        event.clear()
        return event

    def completed(self, event: asyncio.Event) -> None:
        """
        put an event back into the pool
        """
        self.pool.append(event)


class EventPublisher(BaseZMQServer, BaseSyncZMQ):
    """Event publisher for broadcasting messages to all connected clients. Implements PUB-SUB pattern."""

    _standard_address_suffix = "/event-publisher"
    _standard_address_suffix_filename_replacement = "event-publisher"

    def __init__(
        self,
        id: str,
        context: zmq.Context | None = None,
        access_point: str = ZMQ_TRANSPORTS.IPC,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            unique identifier of the publisher
        context: zmq.Context
            ZMQ context to use, if None, a global context is used.
        access_point: Enum | str, default ZMQ_TRANSPORTS.IPC
            access point for the publisher to bind to, usually `INPROC`
        """
        super().__init__(id=id, **kwargs)
        self.create_socket(
            server_id=id,
            socket_id=id,
            node_type="server",
            context=context,
            access_point=access_point,
            socket_type=zmq.PUB,
            **kwargs,
        )
        self.events = set()  # type is set[EventDispatcher]
        self.event_ids = set()  # type: set[str]
        self._send_lock = threading.Lock()

    def register(self, event: "EventDispatcher") -> None:
        """
        register event with a specific (unique) name

        Parameters
        ----------
        event: `EventDispatcher`
            `Event` object that needs to be registered. Events created at `__init__()` of `Thing` are
            automatically registered.
        """
        if event._unique_identifier in self.events and event not in self.events:
            raise AttributeError(f"event {event._unique_identifier} already registered, please use another name.")
        self.event_ids.add(event._unique_identifier)
        self.events.add(event)

    def unregister(self, event: "EventDispatcher") -> None:
        """
        unregister event with a specific (unique) name

        Parameters
        ----------
        event: `EventDispatcher`
            `Event` object that needs to be unregistered.
        """
        if event in self.events:
            self.events.remove(event)
            self.event_ids.remove(event._unique_identifier)
        else:
            warnings.warn(
                f"event {event._unique_identifier} not found, did you mean to unregister another event?",
                UserWarning,
            )

    def publish(self, event, data: Any) -> None:
        """
        publish an event with given unique name.

        Parameters
        ----------
        event: `EventDispatcher`
            `Event` object that needs to be published.
        data: Any
            data to be sent as payload of the event
        """
        # uncomment for type definitions
        # from ...core.events import EventDispatcher
        # assert isinstance(event, EventDispatcher), "event must be an instance of EventDispatcher"

        try:
            self._send_lock.acquire()
            if event._unique_identifier in self.event_ids:
                serializer = Serializers.for_object(
                    event._owner_inst.id,
                    event._owner_inst.__class__.__name__,
                    event._descriptor.name,
                )
                content_type_if_no_serializer = Serializers.get_content_type_for_object(
                    event._owner_inst.id,
                    event._owner_inst.__class__.__name__,
                    event._descriptor.name,
                )
                if not isinstance(data, bytes):
                    payload = SerializableData(data, serializer=serializer)
                    preserialized_payload = PreserializedEmptyByte
                else:
                    payload = SerializableNone
                    preserialized_payload = PreserializedData(data, content_type=content_type_if_no_serializer)

                event_message = EventMessage.craft_from_arguments(
                    event._unique_identifier,
                    self.id,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
                )
                self.socket.send_multipart(event_message.byte_array)
                self.logger.debug(f"published event with unique identifier {event._unique_identifier}")
                # print("published event with unique identifier {}".format(event._unique_identifier))
                return
            raise AttributeError(f"event name {event._unique_identifier} not registered")
        finally:
            try:
                self._send_lock.release()
            except Exception as ex:
                self.logger.warning(f"could not release publish lock for event publisher - {str(ex)}")

    def exit(self):
        try:
            BaseZMQ.exit(self)
            self.socket.close(0)
            self.logger.info("terminated event publishing socket")
        except Exception as ex:
            self.logger.warning(
                "could not properly terminate context or attempted to terminate an already terminated context."
                + f" Exception message: {str(ex)}"
            )


class BaseEventConsumer(BaseZMQClient):
    """Consumes events published at PUB sockets using SUB socket"""

    def __init__(
        self,
        id: str,
        event_unique_identifier: str,
        access_point: str,
        context: zmq.Context | None = None,
        **kwargs,
    ) -> None:
        """
        Parameters
        ----------
        id: str
            unique identity for the consumer
        event_unique_identifier: str
            unique identifier of the event registered at the PUB socket
        access_point: str
            socket address of the event publisher (`EventPublisher`), properly qualified with transport method
        context: zmq.Context
            ZMQ context to use, if None, a global context is used.
        **kwargs:
            additional arguments:

            - `logger`: `logging.Logger`, logger instance to use. If None, a default
            - `poll_timeout`: `int`, socket polling timeout in milliseconds greater than 0.
            - `server_id`: `str`, id of the PUB socket server, usually not necessary as `access_point` is sufficient.
        """

        if isinstance(self, BaseSyncZMQ):
            self.context = context or global_config.zmq_context()
            self.poller = zmq.Poller()
            socket_class = zmq.Socket
            self._poller_lock = threading.Lock()
        elif isinstance(self, BaseAsyncZMQ):
            self.context = context or global_config.zmq_context()
            self.poller = zmq.asyncio.Poller()
            socket_class = zmq.asyncio.Socket
            self._poller_lock = asyncio.Lock()
        else:
            raise TypeError("BaseEventConsumer must be subclassed by either BaseSyncZMQ or BaseAsyncZMQ")
        super().__init__(id=id, server_id=kwargs.get("server_id", None), **kwargs)
        logger = kwargs.get("logger", None)
        if not logger:
            logger = structlog.get_logger().bind(
                component="broker",
                impl=self.__class__.__name__,
                id=id,
                event_id=event_unique_identifier,
            )
        self.logger = logger  # type: structlog.stdlib.BoundLogger
        self.create_socket(
            server_id=id,
            socket_id=id,
            node_type="client",
            context=self.context,
            socket_type=zmq.SUB,
            access_point=access_point,
            **kwargs,
        )
        self.event_unique_identifier = bytes(event_unique_identifier, encoding="utf-8")
        short_uuid = uuid_hex()
        self.interruptor = self.context.socket(zmq.PAIR, socket_class=socket_class)
        self.interruptor.setsockopt_string(zmq.IDENTITY, f"interrupting-server-{short_uuid}")
        self.interrupting_peer = self.context.socket(zmq.PAIR, socket_class=socket_class)
        self.interrupting_peer.setsockopt_string(zmq.IDENTITY, f"interrupting-client-{short_uuid}")
        self.interruptor.bind(f"inproc://{self.id}-{short_uuid}/interruption")
        self.interrupting_peer.connect(f"inproc://{self.id}-{short_uuid}/interruption")
        self._stop = False

    def subscribe(self) -> None:
        """subscribe to the event at the PUB socket"""
        self.socket.setsockopt(zmq.SUBSCRIBE, self.event_unique_identifier)
        # pair sockets cannot be polled unforunately, so we use router
        # if self.socket in self.poller._map:
        #     self.poller.unregister(self.socket)
        # if self.interruptor in self.poller._map:
        #     self.poller.unregister(self.interruptor)
        self.poller.register(self.socket, zmq.POLLIN)
        self.poller.register(self.interruptor, zmq.POLLIN)

    def stop_polling(self) -> None:
        """stop polling for events when `receive()` is called"""
        self._stop = True

    @property
    def interrupt_message(self) -> EventMessage:
        """
        craft an interrupt message to be sent to the interruptor socket, if `stop_polling()` is not sufficient as
        the poll timeout is infinite. Used internally by `interrupt()` method.
        """
        return EventMessage.craft_from_arguments(
            event_id=f"{self.id}/interrupting-server",
            sender_id=self.id,
            payload=SerializableData("INTERRUPT", content_type="application/json"),
        )

    def exit(self):
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
            self.poller.unregister(self.interruptor)
        except Exception as ex:  # noqa
            # TODO - log message and undo noqa
            self.logger.warning(f"could not unregister sockets from poller for event consumer - {str(ex)}")
        try:
            self.socket.close(0)
            self.interruptor.close(0)
            self.interrupting_peer.close(0)
            self.logger.info(f"terminated event consuming socket {self.socket_address}")
        except Exception as ex:
            self.logger.warning(f"could not terminate sockets. exception message - {str(ex)}")


class EventConsumer(BaseEventConsumer, BaseSyncZMQ):
    """Sync Event Consumer to used outside of async loops"""

    def receive(self, timeout: float | None = 1000, raise_interrupt_as_exception: bool = False) -> EventMessage | None:
        """
        receive event with given timeout

        Parameters
        ----------
        timeout: float, int, None
            timeout in milliseconds, None for blocking
        raise_interrupt_as_exception: bool
            if True, raises BreakLoop exception when interrupted, otherwise returns None
        """
        self._stop = False
        while not self._stop:
            try:
                if not self._poller_lock.acquire(timeout=timeout / 1000 if timeout else -1):
                    continue
                sockets = self.poller.poll(timeout)  # list[tuple[zmq.Socket, int]]
                if len(sockets) > 1:
                    # if there is an interrupt message as well as an event,
                    # give preference to interrupt message.
                    if sockets[0][0] == self.interrupting_peer:
                        sockets = [sockets[0]]  # we still need the socket, poll event  tuple
                    elif sockets[1][0] == self.interrupting_peer:
                        sockets = [sockets[1]]
                for socket, _ in sockets:
                    try:
                        raw_message = socket.recv_multipart(zmq.NOBLOCK)
                        message = EventMessage(raw_message)
                        if socket == self.interrupting_peer:
                            if message.payload.deserialize() == "INTERRUPT":
                                self.stop_polling()
                                if raise_interrupt_as_exception:
                                    raise BreakLoop("event consumer interrupted")
                                return
                        return message
                    except zmq.Again:
                        pass
                    # if not self.handled_default_message_types(event_message):
            finally:
                try:
                    self._poller_lock.release()
                except Exception as ex:
                    self.logger.warning(f"could not release poller lock for event receive - {str(ex)}")

    def interrupt(self):
        """
        interrupts the event consumer. Generally should be used for exiting this object if there is no poll
        period/infinite polling. Otherwise please use stop_polling().
        """
        self.interrupting_peer.send_multipart(self.interrupt_message.byte_array)


class AsyncEventConsumer(BaseEventConsumer, BaseAsyncZMQ):
    """Async Event Consumer to be used inside async loops"""

    async def receive(
        self,
        timeout: float | None = 1000,
        raise_interrupt_as_exception: bool = False,
    ) -> EventMessage | None:
        """
        receive event with given timeout

        Parameters
        ----------
        timeout: float, int, None
            timeout in milliseconds, None for blocking
        raise_interrupt_as_exception: bool
            if True, raises BreakLoop exception when interrupted, otherwise returns None
        """
        # TODO - use raise_interrupt_as_exception
        self._stop = False
        while not self._stop:
            try:
                try:
                    await asyncio.wait_for(
                        self._poller_lock.acquire(),
                        timeout=timeout / 1000 if timeout else None,
                    )
                except TimeoutError:
                    continue
                sockets = await self.poller.poll(timeout)
                if len(sockets) > 1:
                    # if there is an interrupt message as well as an event,
                    # give preference to interrupt message.
                    if sockets[0][0] == self.interrupting_peer:
                        sockets = [sockets[0]]
                    elif sockets[1][0] == self.interrupting_peer:
                        sockets = [sockets[1]]
                for socket, _ in sockets:
                    try:
                        raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                        message = EventMessage(raw_message)
                        if socket == self.interrupting_peer:
                            if message.payload.deserialize() == "INTERRUPT":
                                self.stop_polling()
                                if raise_interrupt_as_exception:
                                    raise BreakLoop("event consumer interrupted")
                                return
                        return message
                    except zmq.Again:
                        pass
            finally:
                try:
                    self._poller_lock.release()
                except Exception as ex:
                    self.logger.warning(f"could not release poller lock for event receive - {str(ex)}")

    async def interrupt(self):
        """
        interrupts the event consumer. Generally should be used for exiting this object if there is no poll
        period/infinite polling. Otherwise please use stop_polling().
        """
        await self.interrupting_peer.send_multipart(self.interrupt_message.byte_array)


from ...core.events import EventDispatcher  # noqa

__all__ = [
    AsyncZMQServer.__name__,
    ZMQServerPool.__name__,
    SyncZMQClient.__name__,
    AsyncZMQClient.__name__,
    MessageMappedZMQClientPool.__name__,
    AsyncEventConsumer.__name__,
    EventConsumer.__name__,
]
