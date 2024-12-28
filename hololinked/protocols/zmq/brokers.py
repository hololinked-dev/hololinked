import os
import time
import warnings
import zmq
import zmq.asyncio
import asyncio
import logging
import typing
from uuid import uuid4
from zmq.utils.monitor import parse_monitor_message


from ...utils import *
from ...config import global_config
from ...constants import ZMQ_TRANSPORTS, ZMQSocketType, ZMQ_EVENT_MAP, CommonRPC, ServerTypes, get_socket_type_name
from ...serializers import JSONSerializer
from ...exceptions import BreakLoop
from .message import (EMPTY_BYTE, EXIT, HANDSHAKE, INVALID_MESSAGE, SERVER_DISCONNECTED, TIMEOUT, EventMessage, 
                    RequestMessage, ResponseMessage, SerializableData, PreserializedData, 
                    ServerExecutionContext, ThingExecutionContext, default_server_execution_context, default_thing_execution_context)


   
class BaseZMQ: 
    """
    Base class for all ZMQ message brokers. Implements socket creation & logger
    which is common to all server and client implementations. 
    """

    def __init__(self, id: str, logger: logging.Logger | None, **kwargs) -> None:
        super().__init__()
        self.id = id # type: str
        self.logger = None
        if not logger:
            logger = get_default_logger('{}|{}'.format(self.__class__.__name__, self.id), 
                                                kwargs.get('log_level', logging.INFO))
        self.logger = logger


    def exit(self) -> None:
        """
        Cleanup method to terminate ZMQ sockets and contexts before quitting. Called by `__del__()`
        automatically. Each subclass server/client should implement their version of exiting if necessary.
        """
        if not self.logger:
            logger = get_default_logger('{}|{}'.format(self.__class__.__name__, self.id), logging.INFO)

    def __del__(self) -> None:
        self.exit()
    

    @classmethod
    def get_socket(cls, *, id: str, node_type: str, context: zmq.asyncio.Context | zmq.Context, 
                    transport: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC, socket_type: zmq.SocketType = zmq.ROUTER, 
                    **kwargs) -> typing.Tuple[zmq.Socket, str]:
        """
        Create a socket with certain specifications. Supported ZeroMQ transports are TCP, IPC & INPROC. 
        For IPC sockets, a file is created under TEMP_DIR of global configuration.

        Parameters
        ----------
        id: str
            Each ROUTER socket require unique identity to correctly route the messages. 
        node_type: str
            server or client? i.e. whether to bind (server) or connect (client) as per ZMQ definition
        context: zmq.Context or zmq.asyncio.Context
            ZeroMQ Context object that creates the socket
        transport: Enum
            TCP, IPC or INPROC. Message crafting/passing/routing is transport invariant as suggested by ZMQ.
            Speed relationship - INPROC > IPC > TCP.
        socket_type: zmq.SocketType, default zmq.ROUTER
            Usually a ROUTER socket is implemented for both client-server and peer-to-peer communication
        **kwargs: dict
            - socket_address: str,
                applicable only for TCP socket to find the correct socket to connect 

        Returns
        -------
        socket: zmq.Socket
            created socket
        socket_address: str
            qualified address of the socket created for any transport type

        Raises
        ------
        NotImplementedError
            if transport other than TCP, IPC or INPROC is used
        RuntimeError
            if transport is TCP and a socket connect from client side is requested but a socket address is not supplied
        """
       
        socket = context.socket(socket_type)
        socket.setsockopt_string(zmq.IDENTITY, id)
        socket_address = kwargs.get('socket_address', None)
        bind = node_type == 'server'
        if transport == ZMQ_TRANSPORTS.IPC or transport.lower() == "ipc":
            if socket_address is None or not socket_address.endswith('.ipc'):
                if not socket_address:
                    split_id = id.split('/')
                elif not socket_address.endswith('.ipc'):
                    split_id = socket_address.split('/')
                socket_dir = os.sep  + os.sep.join(split_id[:-1]) if len(split_id) > 1 else ''
                directory = global_config.TEMP_DIR + socket_dir
                if not os.path.exists(directory):
                    os.makedirs(directory)
                # re-compute for IPC because it looks for a file in a directory
                socket_address = "ipc://{}{}{}.ipc".format(directory, os.sep, split_id[-1])
            if bind:
                socket.bind(socket_address)
            else:
                socket.connect(socket_address)
        elif transport == ZMQ_TRANSPORTS.TCP or transport.lower() == "tcp":
            if bind:
                if not socket_address:
                    for i in range(global_config.TCP_SOCKET_SEARCH_START_PORT, global_config.TCP_SOCKET_SEARCH_END_PORT):
                        socket_address = "tcp://0.0.0.0:{}".format(i)
                        try:
                            socket.bind(socket_address)
                            break 
                        except zmq.error.ZMQError as ex:
                            if not ex.strerror.startswith('Address in use'):
                                raise ex from None
                else:                   
                    socket.bind(socket_address)
            elif socket_address: 
                socket.connect(socket_address)
            else:
                raise RuntimeError(f"Socket address not supplied for TCP connection to identity - {id}")
        elif transport == ZMQ_TRANSPORTS.INPROC or transport.lower() == "inproc":
            # inproc_id = id.replace('/', '_').replace('-', '_')
            if socket_address is None:
                socket_address = f'inproc://{id}'
            elif not socket_address.startswith('inproc://'):
                socket_address = f'inproc://{socket_address}'
            if bind:
                socket.bind(socket_address)
            else:
                socket.connect(socket_address)
        else:
            raise NotImplementedError("transports other than IPC, TCP & INPROC are not implemented now for {}.".format(cls.__name__) + 
                                            f" Given transport {transport}.")
        
        return socket, socket_address
       

  
class BaseAsyncZMQ(BaseZMQ):
    """
    Base class for all async ZMQ servers and clients.
    """
    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(self, *, id: str, node_type: str = 'server', context: zmq.asyncio.Context | None = None, 
                        transport: str = "IPC", socket_type: zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        """
        Overloads ``create_socket()`` to create, bind/connect an async socket. A async context is created if none is supplied. 
        """
        if context and not isinstance(context, zmq.asyncio.Context):
            raise TypeError("async ZMQ message broker accepts only async ZMQ context. supplied type {}".format(type(context)))
        self.context = context or zmq.asyncio.Context()
        self.socket, self.socket_address = BaseZMQ.get_socket(id=id, node_type=node_type, context=self.context, 
                                                transport=transport, socket_type=socket_type, **kwargs)
        self.logger.info("created socket {} with address {} & identity {} and {}".format(get_socket_type_name(socket_type), 
                                                        self.socket_address, id, "bound" if node_type == 'server' else "connected"))
       
        
class BaseSyncZMQ(BaseZMQ):
    """
    Base class for all sync ZMQ servers and clients.
    """
    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(self, *, id: str, node_type: str = 'server', context: zmq.Context | None = None, 
                    transport: str = "IPC", socket_type: zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        """
        Overloads ``create_socket()`` to create, bind/connect a synchronous socket. A synchronous context is created 
        if none is supplied. 
        """
        if context: 
            if not isinstance(context, zmq.Context):
                raise TypeError("sync ZMQ message broker accepts only sync ZMQ context. supplied type {}".format(type(context)))
            if isinstance(context, zmq.asyncio.Context):
                raise TypeError("sync ZMQ message broker accepts only sync ZMQ context. supplied type {}".format(type(context)))
        self.context = context or zmq.Context()
        self.socket, self.socket_address = BaseZMQ.get_socket(id=id, node_type=node_type, context=self.context, 
                                                transport=transport, socket_type=socket_type, **kwargs)
        self.logger.info("created socket {} with address {} & identity {} and {}".format(get_socket_type_name(socket_type), 
                                                        self.socket_address, id, "bound" if node_type == 'server' else "connected"))
      


class BaseZMQServer(BaseZMQ):
   
   
    def handshake(self, request_message: RequestMessage) -> None:
        """
        Pass a handshake message to client. Absolutely mandatory to ensure initial messages do not get lost 
        because of ZMQ's very tiny but significant initial delay after creating socket.

        Parameters
        ----------
        request_message: List[bytes]
            the client message for which the handshake is being sent

        Returns
        -------
        None 
        """
        run_callable_somehow(self._handshake(request_message))

    def _handshake(self, request_message: RequestMessage) -> None:
        raise NotImplementedError(f"handshake cannot be handled - implement _handshake in {self.__class__} to handshake.")


    def handle_invalid_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Pass an invalid message to the client when an exception occurred while parsing the message from the client 
        (``parse_client_message()``)

        Parameters
        ----------
        request_message: List[bytes]
            the client message parsing which the exception occurred
        exception: Exception
            exception object raised

        Returns
        -------
        None
        """
        run_callable_somehow(self._handle_invalid_message(request_message, exception))

    def _handle_invalid_message(self, message: RequestMessage, exception: Exception) -> None:
        raise NotImplementedError("invalid message cannot be handled" +
                f" - implement _handle_invalid_message in {self.__class__} to handle invalid messages.")
            

    def handle_timeout(self, request_message: RequestMessage) -> None:
        """
        Pass timeout message to the client when the operation could not be executed within specified timeouts

        Parameters
        ----------
        request_message: List[bytes]
            the client message which could not executed within the specified timeout. timeout value is 
            generally specified within the execution context values.
        
        Returns
        -------
        None
        """
        run_callable_somehow(self._handle_timeout(request_message))

    def _handle_timeout(self, request_message: RequestMessage) -> None:
        raise NotImplementedError("timeouts cannot be handled ",
                f"- implement _handle_timeout in {self.__class__} to handle timeout.")
    

    def handle_error_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Pass an exception message to the client when an exception occurred while executing the operation

        Parameters
        ----------
        request_message: List[bytes]
            the client message for which the exception occurred
        exception: Exception
            exception object raised

        Returns
        -------
        None
        """
        run_callable_somehow(self._handle_error_message(request_message, exception))

    def _handle_error_message(self, request_message: RequestMessage, exception: Exception) -> None:
        raise NotImplementedError("exceptions cannot be handled ",
                f"- implement _handle_error_message in {self.__class__} to handle exceptions.")
    

    def handled_default_message_types(self, request_message: RequestMessage) -> bool:
        """
        Handle default cases for the server. This method is called when the message type is not recognized 
        or the message is not a valid message. 

        Parameters
        ----------
        request_message: List[bytes]
            the client message which could not executed within the specified timeout. timeout value is 
            generally specified within the execution context values.
        receiver_socket: zmq.Socket
            the socket to which the response must be sent. 

        Returns
        -------
        None
        """
        if request_message.type == HANDSHAKE:
            self.handshake(request_message)
            return True
        elif request_message.type == EXIT:
            # self.send response with message type EXIT
            raise BreakLoop(f"exit message received from {request_message.sender_id} with msg-ID {request_message.id}")
        return False 
    

    
class AsyncZMQServer(BaseZMQServer, BaseAsyncZMQ):
    """
    Implements both blocking (non-polled) and non-blocking/polling form of receive messages and send replies
    This server can be stopped from server side by calling ``stop_polling()`` unlike ``AsyncZMQServer`` which 
    cannot be stopped manually unless a message arrives.

    Parameters
    ----------
    id: str
        ``id`` of the Thing which the server serves
    server_type: str
        server type metadata - currently not useful/important
    context: Optional, zmq.asyncio.Context
        ZeroMQ Context object to use. All sockets share this context. Automatically created when None is supplied.
    socket_type: zmq.SocketType, default zmq.ROUTER
        socket type of ZMQ socket, default is ROUTER (enables address based routing of messages)
    transport: Enum, default ZMQ_TRANSPORTS.IPC
        Use TCP for network access, IPC for multi-process applications, and INPROC for multi-threaded applications.  
    poll_timeout: int, default 25
        time in milliseconds to poll the sockets specified under ``procotols``. Useful for calling ``stop_polling()``
        where the max delay to stop polling will be ``poll_timeout``
    """

    def __init__(self, *, id: str, context: typing.Union[zmq.asyncio.Context, None] = None, 
                socket_type: zmq.SocketType = zmq.ROUTER, transport: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC, 
                poll_timeout = 25, **kwargs) -> None:
        super().__init__(id=id, **kwargs)
        self.create_socket(id=id, node_type='server', context=context, transport=transport, 
                        socket_type=socket_type, **kwargs) 
        self._terminate_context = context == None # terminate if it was created by instance
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self.poll_timeout = poll_timeout


    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"polling period must be an integer greater than 0, not {value}. Value is considered in milliseconds.")
        self._poll_timeout = value 


    async def async_recv_request(self) -> RequestMessage:
        """
        Receive one message in a blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``.   

        Returns
        -------
        message: RequestMessage
            received message with important content (operation, arguments, thing execution context) deserialized. 
        """
        while True:
            raw_message = await self.socket.recv_multipart()
            request_message = RequestMessage(raw_message)
            if not self.handled_default_message_types(request_message) and raw_message:
                self.logger.debug(f"received message from client '{request_message.sender_id}' with msg-ID '{request_message.id}'")
                return request_message
        

    async def async_recv_requests(self) -> typing.List[RequestMessage]:
        """
        Receive all currently available messages in blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``. 

        Returns
        -------
        messages: typing.List[RequestMessage]
            list of received messages with important content (operation, arguments, execution context) deserialized.
        """
        messages = [await self.async_recv_request()]
        while True:
            try:
                raw_message = await self.socket.recv_multipart(zmq.NOBLOCK)
                request_message = RequestMessage(raw_message)
                if not self.handled_default_message_types(request_message) and raw_message:
                    self.logger.debug(f"received message from client '{request_message.sender_id}' with msg-ID '{request_message.id}'")
                    messages.append(request_message)
            except zmq.Again: 
                break 
        return messages
    

    async def async_send_response(self, 
                    request_message: RequestMessage, 
                    payload: SerializableData = SerializableData(None, 'application/json'), 
                    preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain')
                ) -> None:
        """
        Send response message for a request message. 

        Parameters
        ----------
        request_message: List[bytes]
            original message so that the response can be properly crafted and routed
        data: Any
            serializable data to be sent as response
        pre_encoded_data: bytes
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        None
        """
        await self.socket.send_multipart(
            ResponseMessage.craft_reply_from_request(
                request_message=request_message,
                payload=payload,
                preserialized_payload=preserialized_payload                
            ).byte_array
        )
        self.logger.debug(f"sent response to client '{request_message.sender_id}' with msg-ID '{request_message.id}'")
        
    
    async def async_send_response_with_message_type(self, 
                                        request_message: RequestMessage, 
                                        message_type: str,
                                        payload: SerializableData = SerializableData(None, 'application/json'),
                                        preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain')
                                    ) -> None:
        """
        Send response message for a request message. 

        Parameters
        ----------
        request_message: List[bytes]
            original message so that the response can be properly crafted and routed
        data: Any
            serializable data to be sent as response

        Returns
        -------
        None
        """
        await self.socket.send_multipart(
            ResponseMessage.craft_from_arguments(
                receiver_id=request_message.sender_id,
                sender_id=self.id, 
                message_type=message_type,
                message_id=request_message.id,
                payload=payload,
                preserialized_payload=preserialized_payload
            ).byte_array
        )
        self.logger.debug(f"sent response to client '{request_message.sender_id}' with msg-ID '{request_message.id}'")


    async def poll_requests(self) -> typing.List[RequestMessage]:
        """
        poll for messages with specified timeout (``poll_timeout``) and return if any messages are available.
        This method blocks, so make sure other methods are scheduled which can stop polling. 

        Returns
        -------
        messages: List[List[bytes]]
            list of received messages with important content (operation, arguments, thing execution context) deserialized.
        """
        self.stop_poll = False
        messages = []
        while not self.stop_poll:
            sockets = await self.poller.poll(self._poll_timeout) # type hints dont work in this line
            for socket, _ in sockets:
                while True:
                    try:
                        raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    else:
                        request_message = RequestMessage(raw_message)
                        if not self.handled_default_message_types(request_message) and raw_message:
                            self.logger.debug(f"received message from client '{request_message.sender_id}' with msg-ID '{request_message.id}'")
                            messages.append(request_message)
            if len(messages) > 0:
                break
        return messages
    
    def stop_polling(self) -> None:
        """
        stop polling and unblock ``poll_messages()`` method
        """
        self.stop_poll = True 

    
    async def _handshake(self, request_message: RequestMessage) -> None:
        """
        Inner method that handles handshake. Scheduled by ``handshake()`` method, signature same as ``handshake()``.
        """
        # Note that for ROUTER sockets, once the message goes through the sending socket, the address of the receiver 
        # is replaced by the address of the sender once received 
        await self.socket.send_multipart(
            ResponseMessage.craft_from_arguments(
                receiver_id=request_message.sender_id,
                sender_id=self.id,
                message_type=HANDSHAKE, 
                message_id=request_message.id
            ).byte_array
        )
        self.logger.info(f"sent handshake to client '{request_message.sender_id}'")


    async def _handle_timeout(self, request_message: RequestMessage, timeout_type: str) -> None:
        """
        Inner method that handles timeout. Scheduled by ``handle_timeout()``, signature same as ``handle_timeout``.
        """
        await self.socket.send_multipart(
            ResponseMessage.craft_from_arguments(
                receiver_id=request_message.sender_id,
                sender_id=self.id,
                message_type=TIMEOUT,
                message_id=request_message.id,
                payload=SerializableData(timeout_type, 'text/plain')
            ).byte_array   
        )
        self.logger.info(f"sent timeout to client '{request_message.sender_id}'")

    
    async def _handle_invalid_message(self, request_message: RequestMessage, exception: Exception) -> None:
        """
        Inner method that handles invalid messages. Scheduled by ``handle_invalid_message()``, 
        signature same as ``handle_invalid_message()``.
        """
        await self.socket.send_multipart(
            ResponseMessage.craft_from_arguments(
                receiver_id=request_message.sender_id,
                sender_id=self.id,
                message_type=INVALID_MESSAGE,
                message_id=request_message.id,
            ).byte_array
        )         
        self.logger.info(f"sent invalid message to client '{request_message.sender_id}'." +
                            f" exception - {str(exception)}") 	
        
    
    async def _handle_error_message(self, 
                                request_message: RequestMessage,
                                exception: Exception
                            ) -> None:
        response_message = ResponseMessage.craft_with_message_type(
                                                            request_message=request_message,
                                                            message_type=logging.ERROR,
                                                            payload=exception
                                                        )
        await self.socket.send_multipart(response_message.byte_array)    
        self.logger.info(f"sent exception message to client '{response_message.receiver_id}'." +
                            f" exception - {str(exception)}")


    def exit(self) -> None:
        """
        unregister socket from poller and terminate socket and context.
        """
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
            self.socket.close(0)
            self.logger.info(f"terminated socket of server '{self.id}' of type {self.__class__}")
        except Exception as ex:
            self.logger.warning(f"could not unregister socket {self.id} from polling - {str(ex)}")
        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of socket '{}' of type '{}'".format(self.id, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated " +
                            f" context '{self.id}'. Exception message: {str(ex)}")
    
   


class ZMQServerPool(BaseZMQServer):
    """
    Implements pool of async ZMQ servers (& their sockets)
    """

    def __init__(self, *, ids: typing.List[str] | None = None, **kwargs) -> None:
        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.pool = dict() # type: typing.Dict[str, AsyncZMQServer]
        if ids:
            for id in ids:
                self.pool[id] = AsyncZMQServer(id=id, context=self.context, **kwargs)
            for server in self.pool.values():
                self.poller.register(server.socket, zmq.POLLIN)
        super().__init__(id="pool", **kwargs)
  

    def create_socket(self, *, id: str, bind: bool, context: typing.Union[zmq.asyncio.Context, zmq.Context], 
                transport: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.IPC, socket_type: zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        raise NotImplementedError("create socket not supported by ZMQServerPool")
        # we override this method to prevent socket creation. id set to pool is simply a filler 
        return super().create_socket(id=id, node_type=node_type, context=context, transport=transport, 
                                    socket_type=socket_type, **kwargs)

    def register_server(self, server: AsyncZMQServer) -> None:
        if not isinstance(server, (AsyncZMQServer)):
            raise TypeError("registration possible for servers only subclass of AsyncZMQServer." +
                           f" Given type {type(server)}")
        self.pool[server.id] = server 
        self.poller.register(server.socket, zmq.POLLIN)

    def deregister_server(self, server: AsyncZMQServer) -> None:
        self.poller.unregister(server.socket)
        self.pool.pop(server.id)

    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError("polling period must be an integer greater than 0, not {}. Value is considered in milliseconds.".format(value))
        self._poll_timeout = value 

    async def async_recv_request(self, id: str) -> RequestMessage:
        """
        receive message for server instance name

        Parameters
        ----------
        id: str
            instance name of the ZMQ server. 
        """
        return await self.pool[id].async_recv_request()
     
    async def async_recv_requests(self, id: str) -> typing.List[RequestMessage]:
        """
        receive all available messages for server instance name

        Parameters
        ----------
        id: str
            instance name of the ZMQ server. 
        """
        return await self.pool[id].async_recv_requests()
   
    async def async_send_response(self, *, 
                                id: str, 
                                request_message: RequestMessage,  
                                payload: SerializableData = SerializableData(None, 'application/json'),
                                preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain')
                            ) -> None:
        """
        send response for instance name

        Parameters
        ----------
        id: str
            instance name of the ``Thing`` or in this case, the ZMQ server. 
        request_message: List[bytes]
            request message for which response is being given
        data: Any
            data to be given as response
        """
        await self.pool[id].async_send_response(
            request_message=request_message, 
            payload=payload,
            preserialized_payload=preserialized_payload
        )
         
    async def poll(self) -> typing.List[typing.List[typing.Any]]:
        """
        Pool for messages in the entire server pool. User of this method may map the message to the correct instance 
        using the 0th index of the message.  
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
                            self.logger.debug(f"received message from client '{request_message.sender_id}' with msg-ID '{request_message.id}'")
                            messages.append(request_message)
        return messages
        
    def stop_polling(self) -> None:
        """
        stop polling method ``poll()``
        """
        self.stop_poll = True 

    def __getitem__(self, key) -> AsyncZMQServer:
        return self.pool[key]
    
    def __iter__(self) -> typing.Iterator[str]:
        return self.pool.__iter__()
    
    def __contains__(self, name: str) -> bool:
        return name in self.pool.keys()
    
    def exit(self) -> None:
        for server in self.pool.values():       
            try:
                self.poller.unregister(server.socket)
                server.exit()
            except Exception as ex:
                self.logger.warning(f"could not unregister poller and exit server {server.id} - {str(ex)}")
        try:
            self.context.term()
            self.logger.info("context terminated for {}".format(self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context " +
                            f" Exception message: {str(ex)}")

    
    
    
class BaseZMQClient(BaseZMQ):
    """    
    Base class for all ZMQ clients irrespective of sync and async.

    server's response to client
    ::

        [address, bytes(), server_type, message_type, message id, data, pre encoded data]|br|
        [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6         ]|br|

    Parameters
    ----------
    server_id: str
        The instance name of the server (or ``Thing``)
    client_type: str
        ZMQ or HTTP Server
    server_type: str    
        server type metadata
    zmq_serializer: BaseSerializer
        custom implementation of ZMQ serializer if necessary
    http_serializer: JSONSerializer
        custom implementation of JSON serializer if necessary
    """

    def __init__(self, *,
                id: str,
                server_id: str, 
                logger: typing.Optional[logging.Logger] = None,
                **kwargs
            ) -> None:
        super().__init__(id=id, logger=logger, **kwargs)
        self.server_id = server_id 
        self._monitor_socket = None
        self._response_cache = dict()
        self._terminate_context = False
        self.poller: zmq.Poller | zmq.asyncio.Poller 
        self.socket: zmq.Socket | zmq.asyncio.Socket
        self._poll_timeout = kwargs.get('poll_timeout', 1000)  # default to 1000 ms

    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0.
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value: int) -> None:
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"polling period must be an integer greater than 0, not {value}. Value is considered in milliseconds.")
        self._poll_timeout = value

    def exit(self) -> None:
        BaseZMQ.exit(self)
        try:
            self.poller.unregister(self.socket)
            # TODO - there is some issue here while quitting 
            # print("poller exception did not occur 1")
            if self._monitor_socket is not None:
                # print("poller exception did not occur 2")
                self.poller.unregister(self._monitor_socket)
                # print("poller exception did not occur 3")
        except Exception as ex:
            self.logger.warning(f"unable to deregister from poller - {str(ex)}")

        try:
            if self._monitor_socket is not None:
                self._monitor_socket.close(0)
            self.socket.close(0)
            self.logger.info("terminated socket of server '{}' of type '{}'".format(self.id, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated " +
                             f"socket '{self.id}' of type '{self.__class__}'. Exception message: {str(ex)}")
        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of socket '{}' of type '{}'".format(self.id, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context" +
                            "'{}'. Exception message: {}".format(self.id, str(ex)))



class SyncZMQClient(BaseZMQClient, BaseSyncZMQ):
    """
    Synchronous ZMQ client that connect with sync or async server based on ZMQ transport. Works like REQ-REP socket. 
    Each request is blocking until response is received. Suitable for most purposes. 

    Parameters
    ----------
    server_id: str
        The instance name of the server (or ``Thing``)
    id: str 
        Unique id of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID. 
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    transport: str | Enum, TCP, IPC or INPROC, default IPC 
        transport implemented by the server 
    **kwargs:
        socket_address: str
            socket address for connecting to TCP server
    """

    def __init__(self, 
                id: str,
                server_id: str, 
                handshake: bool = True, 
                transport: str = ZMQ_TRANSPORTS.IPC, 
                context: zmq.Context | None = None,
                **kwargs
            ) -> None:
        super().__init__(id=id, server_id=server_id, **kwargs)
        self.create_socket(id=id, 
                        node_type='client', 
                        socket_address=server_id if str(transport) in ["IPC", "INPROC"] else kwargs.pop('socket_address', None),
                        context=context, 
                        transport=transport, 
                        **kwargs)
        self._terminate_context = context == None
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        # print("context on client", self.context)
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))
    
    def send_request(self, 
                    thing_id: bytes, 
                    objekt: str, 
                    operation: str, 
                    payload: SerializableData = SerializableData(None, 'application/json'),
                    preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                    server_execution_context: ServerExecutionContext = default_server_execution_context,
                    thing_execution_context: ThingExecutionContext = default_thing_execution_context
                ) -> bytes:
        """
        send message to server. 

        Parameters
        ----------
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        server_execution_context: Dict[str, Any]
            see execution context definitions
        thing_execution_context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message id: bytes
            a byte representation of message id
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
                                            thing_execution_context=thing_execution_context
                                        )
        self.socket.send_multipart(request_message.byte_array)
        self.logger.debug(f"sent operation '{operation}' on thing '{thing_id}' to server '{self.server_id}' with msg-id '{request_message.id}'")
        return request_message.id
    
    def recv_response(self, message_id: bytes) -> ResponseMessage:
        """
        Receives response from server. Messages are identified by message id, so call this method immediately after 
        calling ``send_request()`` to avoid receiving messages out of order. Or, use other methods like
        ``execute()``, ``read_attribute()`` or ``write_attribute()``.

        Parameters
        ----------
        raise_client_side_exception: bool, default False
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
            See docs of ``raise_local_exception()`` for info on exception 
        """
        while True:
            if message_id in self._response_cache:
                return self._response_cache.pop(message_id)
            sockets = self.poller.poll(self.poll_timeout)
            response_message = None # type: ResponseMessage
            for socket, _ in sockets:
                try:    
                    raw_message = socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass 
            if response_message: 
                if message_id != response_message.id:
                    self._response_cache[message_id] = response_message
                    self.logger.debug("cached response with msg-id {}".format(response_message.id))
                else:
                    self.logger.debug("received response with msg-id {}".format(response_message.id))
                    return response_message
           
          
    def execute(self, 
            thing_id: bytes, 
            objekt: str,
            operation: str, 
            payload: SerializableData = SerializableData(None, 'application/json'),
            preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
            server_execution_context: ServerExecutionContext = default_server_execution_context,
            thing_execution_context: ThingExecutionContext = default_thing_execution_context,
        ) -> ResponseMessage:
        """
        send an operation and receive the response for it. 

        Parameters
        ----------
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        server_execution_context: Dict[str, Any]
            see execution context definitions
        thing_execution_context: Dict[str, Any]
            see execution context definitions
        raise_client_side_exception: bool, default False
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
            See docs of ``raise_local_exception()`` for info on exception
        deserialize_response: bool, default True
            if True, deserializes the response from server

        Returns
        -------
        message id: bytes
            a byte representation of message id
        """
        message_id = self.send_request(
                                thing_id=thing_id, 
                                objekt=objekt, 
                                operation=operation, 
                                payload=payload,
                                preserialized_payload=preserialized_payload,
                                server_execution_context=server_execution_context, 
                                thing_execution_context=thing_execution_context
                            )
        return self.recv_response(message_id=message_id)
     

    def handshake(self, timeout: typing.Union[float, int] = 60000) -> None: 
        """
        hanshake with server before sending first message
        """
        start_time = time.time_ns()
        while True:
            if timeout is not None and (time.time_ns() - start_time)/1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.server_id}' from client '{self.id}'")
            self.socket.send_multipart(RequestMessage.craft_with_message_type(self.id, self.server_id, HANDSHAKE).byte_array)
            self.logger.info(f"sent Handshake to server '{self.server_id}'")
            if self.poller.poll(500):
                try:
                    raw_message = self.socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass 
                else:
                    if response_message.type == HANDSHAKE:  
                        self.logger.info(f"client '{self.id}' handshook with server '{self.server_id}'")
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with '{self.server_id}'." + 
                                                    "Another message arrived before handshake complete.")
            else:
                self.logger.info('got no response for handshake')
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN) 
        # sufficient to know when server dies only while receiving messages, not continuous polling
 
    

class AsyncZMQClient(BaseZMQClient, BaseAsyncZMQ):
    """ 
    Asynchronous client to talk to a ZMQ server where the server is identified by the instance name. The identity 
    of the client needs to be different from the server, unlike the ZMQ Server. The client will also perform handshakes 
    if necessary.

    Parameters
    ----------
    server_id: str
        The instance name of the server (or ``Thing``)  
    id: str
        Unique identity of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID.
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    transport: str | Enum, TCP, IPC or INPROC, default IPC
        transport implemented by the server
    **kwargs:
        socket_address: str
            socket address for connecting to TCP server
        zmq_serializer:
            custom implementation of ZMQ serializer if necessary
        http_serializer:
            custom implementation of JSON serializer if necessary
    """

    def __init__(self, 
                id: str,
                server_id: str, 
                handshake: bool = True, 
                transport: str = "IPC", 
                context: zmq.asyncio.Context | None = None, 
                **kwargs
            ) -> None:
        super().__init__(id=id, server_id=server_id, **kwargs)
        self.create_socket(id=id, 
                        node_type='client', 
                        socket_address=server_id if str(transport) in ["IPC", "INPROC"] else kwargs.pop('socket_address', None),
                        context=context, 
                        transport=transport, 
                        **kwargs)
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self._terminate_context = context == None
        self._handshake_event = asyncio.Event()
        self._handshake_event.clear()
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))
    
    def handshake(self, timeout: int | None = 60000) -> None:
        """
        automatically called when handshake argument at init is True. When not automatically called, it is necessary
        to call this method before awaiting ``handshake_complete()``.
        """
        run_callable_somehow(self._handshake(timeout))

    async def _handshake(self, timeout: float | int | None = 60000) -> None:
        """
        hanshake with server before sending first message
        """
        if self._monitor_socket is not None and self._monitor_socket in self.poller:
            self.poller.unregister(self._monitor_socket)
        self._handshake_event.clear()
        start_time = time.time_ns()    
        while True:
            if timeout is not None and (time.time_ns() - start_time)/1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.server_id}' from client '{self.id}'")
            await self.socket.send_multipart(RequestMessage.craft_with_message_type(self.id, self.server_id, HANDSHAKE).byte_array)
            self.logger.info(f"sent Handshake to server '{self.server_id}'")
            if await self.poller.poll(500):
                try:
                    raw_message = await self.socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass 
                else:
                    if response_message.type == HANDSHAKE: # type: ignore
                        self.logger.info(f"client '{self.id}' handshook with server '{self.server_id}'")               
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with server '{self.server_id}'." + 
                                                    " Another message arrived before handshake complete.")
            else:
                self.logger.info('got no response for handshake')
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN) 
        self._handshake_event.set()

    async def handshake_complete(self):
        """
        wait for handshake to complete
        """
        await self._handshake_event.wait()
       
    async def async_send_request(self, 
                                thing_id: str, 
                                objekt: str, 
                                operation: str, 
                                payload: SerializableData = SerializableData(None, 'application/json'),
                                preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                                server_execution_context: ServerExecutionContext = default_server_execution_context,
                                thing_execution_context: typing.Dict[str, typing.Any] = default_thing_execution_context
                            ) -> str:
        """
        send message to server. 

        client's message to server:
        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
                
            server execution context, operation, arguments, thing execution context] 
                5                   ,      6   ,     7    ,       8                ]

        Server Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "invokation_timeout" - time in seconds to wait for server to start executing the operation
            - "execution_timeout" - time in seconds to wait for server to complete the operation
            - "oneway" - if True, server will not send a response back
        
        Thing Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "fetch_execution_logs" - fetches logs that were accumulated while execution

        Parameters
        ----------
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        server_execution_context: Dict[str, Any]
            see execution context definitions
        thing_execution_context: Dict[str, Any]
            see execution context definitions
            
        Returns
        -------
        message id: bytes
            a byte representation of message id
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
                                                        thing_execution_context=thing_execution_context
                                                    ) 
        await self.socket.send_multipart(request_message.byte_array)
        self.logger.debug(f"sent operation '{operation}' to server '{self.id}' with msg-id '{request_message.id}'")
        return request_message.id
    
    async def async_recv_response(self, message_id: str) -> typing.List[ResponseMessage]:
        """
        Receives response from server. Messages are identified by message id, so call this method immediately after 
        calling ``send_request()`` to avoid receiving messages out of order. Or, use other methods like
        ``execute()``.

        Parameters
        ----------
        message_id: bytes
            message id of the message sent to server
        timeout: int
            time in milliseconds to wait for response
        raise_client_side_exception: bool, default False
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
            See docs of ``raise_local_exception()`` for info on exception 
        deserialize_response: bool
            deserializes the data field of the message
        """
        while True:
            if message_id in self._response_cache:
                return self._response_cache.pop(message_id)
            sockets = await self.poller.poll(self._poll_timeout)
            response_message = None
            for socket, _ in sockets:
                try:    
                    raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                    response_message = ResponseMessage(raw_message)
                except zmq.Again:
                    pass 
            if response_message: 
                if message_id != response_message.id:
                    self._response_cache[response_message.id] = response_message
                    self.logger.debug("cached response with msg-id {}".format(response_message.id))
                else:
                    self.logger.debug(f"received response with msg-id {response_message.id}")
                    return response_message
            
            

    async def async_execute(self, 
                        thing_id: str, 
                        objekt: str, 
                        operation: str, 
                        payload: SerializableData = SerializableData(None, 'application/json'),
                        preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                        server_execution_context: ServerExecutionContext = default_server_execution_context, 
                        thing_execution_context: ThingExecutionContext = default_thing_execution_context
                    ) -> ResponseMessage: 
        """
        send an operation and receive the response for it. 

        Parameters
        ----------
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        server_execution_context: Dict[str, Any]
            see execution context definitions
        thing_execution_context: Dict[str, Any]
            see execution context definitions
        raise_client_side_exception: bool
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
        deserialize_response: bool
            deserializes the data field of the message        

        Returns
        -------
        message id: bytes
            a byte representation of message id
        """
       
        message_id = await self.async_send_request(
                                        thing_id=thing_id, 
                                        objekt=objekt, 
                                        operation=operation, 
                                        payload=payload,
                                        preserialized_payload=preserialized_payload,
                                        server_execution_context=server_execution_context, 
                                        thing_execution_context=thing_execution_context
                                    )
        return await self.async_recv_response(message_id)
       
   

        
class MessageMappedZMQClientPool(BaseZMQClient):
    """
    Pool of clients where message ID can track the replies irrespective of order of arrival. 

    Parameters
    ----------
    server_ids: List[str]
        list of instance names of servers to connect to
    id: str
        Unique identity of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID.
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    poll_timeout: int
        socket polling timeout in milliseconds greater than 0.
    transport: str
        transport implemented by ZMQ server
    context: zmq.asyncio.Context
        ZMQ context
    deserialize_server_messages: bool
        deserializes the data field of the message
    **kwargs:
        zmq_serializer: BaseSerializer
            custom implementation of ZMQ serializer if necessary
        http_serializer: JSONSerializer
            custom implementation of JSON serializer if necessary
    """

    def __init__(self, 
                client_ids: typing.List[str], 
                server_ids: typing.List[str], 
                handshake: bool = True, 
                poll_timeout: int = 25, 
                transport: str = 'IPC',  
                context: zmq.asyncio.Context = None, 
                **kwargs
            ) -> None:
        super().__init__(id='pool', server_id=None, **kwargs)
        if len(client_ids) != len(server_ids):
            raise ValueError("client_ids and server_ids must have same length")
        # this class does not call create_socket method
        self.context = context or zmq.asyncio.Context()
        self.pool = dict() # type: typing.Dict[str, AsyncZMQClient]
        self.poller = zmq.asyncio.Poller()
        for client_id, server_id in zip(client_ids, server_ids):
            client = AsyncZMQClient(
                            id=client_id,
                            server_id=server_id,
                            handshake=handshake, 
                            transport=transport, 
                            context=self.context, 
                            logger=self.logger
                        )
            client._monitor_socket = client.socket.get_monitor_socket()
            self.poller.register(client._monitor_socket, zmq.POLLIN)
            self.pool[id] = client
        # Both the client pool as well as the individual client get their serializers and client_types
        # This is required to implement pool level sending and receiving messages like polling of pool of sockets
        self.event_pool = AsyncioEventPool(len(server_ids))
        self.events_map = dict() # type: typing.Dict[bytes, asyncio.Event]
        self.message_map = dict()
        self.cancelled_messages = []
        self.poll_timeout = poll_timeout
        self.stop_poll = False 
       

    def create_new(self, id: str, server_id: str, transport: str = 'IPC') -> None:
        """
        Create new server with specified transport. other arguments are taken from pool specifications. 
        
        Parameters
        ----------
        id: str
            instance name of server 
        transport: str
            transport implemented by ZMQ server
        """
        if server_id not in self.pool.keys():
            client = AsyncZMQClient(
                        id=id,
                        server_id=server_id,
                        handshake=True, 
                        transport=transport, 
                        context=self.context, 
                        logger=self.logger
                    )
            client._monitor_socket = client.socket.get_monitor_socket()
            self.poller.register(client._monitor_socket, zmq.POLLIN)
            self.pool[server_id] = client
        else: 
            raise ValueError(f"client for instance name '{server_id}' already present in pool")


    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError("polling period must be an integer greater than 0, not {}. Value is considered in milliseconds".format(value))
        self._poll_timeout = value 


    async def handshake_complete(self) -> None:
        """
        wait for handshake to complete for all clients in the pool
        """
        for client in self.pool.values():
            await client.handshake_complete() # sufficient to wait serially


    def handshake(self, timeout: int | None = 60000) -> None:
        """
        automatically called when handshake argument at init is True. When not automatically called, it is necessary
        to call this method before awaiting ``handshake_complete()``.
        """
        for client in self.pool.values():
            run_callable_somehow(client._handshake(timeout))


    async def poll_responses(self) -> None:
        """
        Poll for replies from server. Since the client is message mapped, this method should be independently started
        in the event loop. Sending message and retrieving a message mapped is still carried out by other methods.
        """
        self.logger.info("client polling started for sockets for {}".format(list(self.pool.keys())))
        self.stop_poll = False 
        event_loop = asyncio.get_event_loop()
        while not self.stop_poll:
            sockets = await self.poller.poll(self.poll_timeout) # type hints dont work in this line
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
                                self.poller.unregister(client.socket) # leave the monitor in the pool
                                client.handshake(timeout=None)
                                self.logger.error(f"{client.id} disconnected." +
                                    " Unregistering from poller temporarily until server comes back.")
                                break
                    else:
                        message_id = response_message.id
                        self.logger.debug(f"received response from server '{response_message.sender_id}' with msg-ID '{message_id}'")
                        if message_id in self.cancelled_messages:
                            self.cancelled_messages.remove(message_id)
                            self.logger.debug(f"msg-ID '{message_id}' cancelled")
                            continue
                        event = self.events_map.get(message_id, None) 
                        final_data = response_message.body
                        # if len(response_message.pre_encoded_payload ) > 0 and response_message.payload:
                        #     final_data = tuple(response_message.body)
                        # elif len(response_message.pre_encoded_payload) > 0:
                        #     final_data = response_message.pre_encoded_payload
                        # else:
                        #     final_data = response_message.payload
                        if event:
                            event.set()
                        else:    
                            invalid_event_task = asyncio.create_task(self._resolve_response(message_id, final_data))
                            event_loop.call_soon(lambda: invalid_event_task)


    async def _resolve_response(self, message_id: str, data: typing.Any) -> None:
        """
        This method is called when there is an asyncio Event not available for a message ID. This can happen only 
        when the server replied before the client created a asyncio.Event object. check ``async_execute()`` for details.

        Parameters
        ----------
        message_id: bytes 
            the message for which the event was not created
        data: bytes
            the data given by the server which needs to mapped to the message
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
                    self.logger.debug(f'message_id {message_id} cancelled')
                    return 
                if i >= max_number_of_retries - 1:
                    self.logger.error("unknown message id {} without corresponding event object".format(message_id)) 
                    return
            else:    
                self.message_map[message_id] = data
                event.set()
                break

    def assert_client_ready(self, client: AsyncZMQClient):
        if not client._handshake_event.is_set():
            raise ConnectionAbortedError(f"{client.id} is currently not alive")
        if not client.socket in self.poller._map:
            raise ConnectionError("handshake complete, server is alive but client socket not yet ready to be polled." +
                                "Application using MessageMappedClientPool should register the socket manually for polling." +
                                "If using hololinked.server.HTTPServer, socket is waiting until HTTP Server updates its "
                                "routing logic as the server has just now come alive, please try again soon.")

    async def async_send_request(self, 
                            client_id: str, 
                            thing_id: str, 
                            objekt: str, 
                            operation: str,
                            payload: SerializableData = SerializableData(None, 'application/json'), 
                            preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                            server_execution_context: ServerExecutionContext = default_server_execution_context,
                            thing_execution_context: ThingExecutionContext  = default_thing_execution_context
                        ) -> bytes:
        """
        Send operation to server with instance name. Replies are automatically polled & to be retrieved using 
        ``async_recv_response()``

        Parameters
        ----------
        id: str
            instance name of the server
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        server_execution_context: Dict[str, Any]
            see execution context definitions
        thing_execution_context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message_id: bytes
            created message ID
        """
        self.assert_client_ready(self.pool[client_id])
        message_id = await self.pool[client_id].async_send_request(
                                                thing_id=thing_id, 
                                                objekt=objekt,
                                                operation=operation, 
                                                payload=payload,
                                                preserialized_payload=preserialized_payload,
                                                server_execution_context=server_execution_context,
                                                thing_execution_context=thing_execution_context
                                            )
        event = self.event_pool.pop()
        self.events_map[message_id] = event 
        return message_id

    async def async_recv_response(self, 
                                client_id: str, 
                                message_id: bytes, 
                                timeout: float | int | None = None
                            ) -> typing.Dict[str, typing.Any]:
        """
        Receive response for specified message ID. 

        Parameters
        ----------
        message_id: bytes
            the message id for which response needs to eb fetched
        raise_client_side_exceptions: bool, default False
            raise exceptions from server on client side
        timeout: float, 
            client side timeout, not the same as timeout passed to server, recommended to be None in general cases. 
            Server side timeouts ensure start of execution of operations within specified timeouts and 
            drops execution altogether if timeout occured. Client side timeouts only wait for message to come within 
            the timeout, but do not gaurantee non-execution.  

        Returns
        -------
        response: dict, Any
            dictionary when plain response is False, any value returned from execution on the server side if plain response is
            True.

        Raises
        ------
        ValueError: 
            if supplied message id is not valid
        TimeoutError:
            if timeout is not None and response did not arrive
        """
        try:
            event = self.events_map[message_id]
        except KeyError:
            raise ValueError(f"message id {message_id} unknown.") from None
        while True:
            try:
                await asyncio.wait_for(event.wait(), timeout) 
                # default 5 seconds because we want to check if server is also dead
                if event.is_set(): # i.e. if timeout is not None, check if event is set
                    break
                self.assert_client_ready(self.pool[client_id])
            except TimeoutError:
                self.cancelled_messages.append(message_id)
                self.logger.debug(f'message_id {message_id} added to list of cancelled messages')
                raise TimeoutError(f"Execution not completed within {timeout} seconds") from None
        self.events_map.pop(message_id)
        self.event_pool.completed(event)
        response = self.message_map.pop(message_id)
        return response

    async def async_execute(self, 
                        client_id: str, 
                        thing_id: str, 
                        objekt: str, 
                        operation: str, 
                        payload: SerializableData = SerializableData(None, 'application/json'), 
                        preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                        server_execution_context: ServerExecutionContext = default_server_execution_context,
                        thing_execution_context: ThingExecutionContext  = default_thing_execution_context, raise_client_side_exception = False, 
                    ) -> typing.Dict[str, typing.Any]:
        """
        sends message and receives response.

        Parameters
        ----------
        id: str
            instance name of the server
        operation: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the operation invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions
        raise_client_side_exceptions: bool, default False
            raise exceptions from server on client side
        invokation_timeout: float, default 5
            server side timeout
        execution_timeout: float, default None
            client side timeout, not the same as timeout passed to server, recommended to be None in general cases. 
            Server side timeouts ensure start of execution of operations within specified timeouts and 
            drops execution altogether if timeout occured. Client side timeouts only wait for message to come within 
            the timeout, but do not gaurantee non-execution.  
        """
        message_id = await self.async_send_request(
                                                client_id=client_id, 
                                                thing_id=thing_id, 
                                                objekt=objekt, 
                                                operation=operation,
                                                payload=payload, 
                                                preserialized_payload=preserialized_payload,
                                                server_execution_context=server_execution_context,
                                                thing_execution_context=thing_execution_context
                                            )
        return await self.async_recv_response(
                                            client_id=client_id, 
                                            message_id=message_id, 
                                        )

    def start_polling(self) -> None:
        """
        register the server message polling loop in the asyncio event loop. 
        """
        event_loop = asyncio.get_event_loop()
        event_loop.call_soon(lambda: asyncio.create_task(self.poll()))

    def stop_polling(self):
        """
        stop polling for replies from server
        """
        self.stop_poll = True

    async def async_execute_in_all(self, 
                                objekt: str, 
                                operation: str, 
                                payload: SerializableData = SerializableData(None, 'application/json'), 
                                preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                                ids: typing.Optional[typing.List[str]] = None,
                                server_execution_context: ServerExecutionContext = default_server_execution_context,
                                thing_execution_context: ThingExecutionContext = default_thing_execution_context,
                            ) -> typing.Dict[str, typing.Any]:
        """
        execute a specified operation in all Thing including eventloops
        """
        if not ids:
            ids = self.pool.keys()
        gathered_replies = await asyncio.gather(*[
            self.async_execute(id=id, objekt=objekt, operation=operation, payload=payload, 
                            preserialized_payload=preserialized_payload, 
                            server_execution_context=server_execution_context,
                            thing_execution_context=thing_execution_context
                        ) 
                for id in ids])
        replies = dict()
        for id, response in zip(ids, gathered_replies):
            replies[id] = response
        return replies  
    
    async def async_execute_in_all_things(self, 
                                        objekt: str, 
                                        operation: str, 
                                        payload: SerializableData = SerializableData(None, 'application/json'), 
                                        preserialized_payload: PreserializedData = PreserializedData(EMPTY_BYTE, 'text/plain'),
                                        server_execution_context: ServerExecutionContext = default_server_execution_context,
                                        thing_execution_context: ThingExecutionContext = default_thing_execution_context,        
                                    ) -> typing.Dict[str, typing.Any]:
        """
        execute the same operation in all Things, eventloops are excluded. 
        """
        return await self.async_execute_in_all(
                        objekt=objekt, operation=operation, payload=payload, 
                        preserialized_payload=preserialized_payload,
                        ids=[id for id, client in self.pool.items()],
                        server_execution_context=server_execution_context,
                        thing_execution_context=thing_execution_context
                    )
    
    async def ping_all_servers(self):
        """
        ping all servers connected to the client pool, calls ping() on Thing
        """
        return await self.async_execute_in_all(operation='invokeAction', objekt=CommonRPC.PING)
        
    def __contains__(self, name: str) -> bool:
        return name in self.pool

    def __getitem__(self, key) ->AsyncZMQClient:
        return self.pool[key]
    
    def __iter__(self) -> typing.Iterator[AsyncZMQClient]:
        return iter(self.pool.values())
    
    def exit(self) -> None:
        BaseZMQ.exit(self)
        for client in self.pool.values():
            self.poller.unregister(client.socket)
            self.poller.unregister(client.socket.get_monitor_socket())
            client.exit()
        self.logger.info("all client socket unregistered from pool for '{}'".format(self.__class__))
        try:
            self.context.term()
            self.logger.info("context terminated for '{}'".format(self.__class__))        
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context" +
                            "'{}'. Exception message: {}".format(self.identity, str(ex)))

    """
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

    def __init__(self, 
                id: str, 
                transport: str, 
                context: zmq.Context | None = None, 
                **kwargs
            ) -> None:
        super().__init__(id=id, **kwargs)
        self.create_socket(id=id, node_type='server', context=context,
                           transport=transport, socket_type=zmq.PUB, **kwargs)
        self.logger.info(f"created event publishing socket at {self.socket_address}")
        self.events = set() # type: typing.Set[EventDispatcher] 
        self.event_ids = set() # type: typing.Set[bytes]

    def register(self, event: "EventDispatcher") -> None:
        """
        register event with a specific (unique) name

        Parameters
        ----------
        event: ``Event``
            ``Event`` object that needs to be registered. Events created at ``__init__()`` of Thing are 
            automatically registered. 
        """
        if event._unique_identifier in self.events and event not in self.events:
            raise AttributeError(f"event {event._unique_identifier} already found in list of events, please use another name.")
        self.event_ids.add(event._unique_identifier)       
        self.events.add(event) 
    
    def unregister(self, event : "EventDispatcher") -> None:
        """
        unregister event with a specific (unique) name

        Parameters
        ----------
        event: ``Event``
            ``Event`` object that needs to be unregistered. 
        """
        if event in self.events:
            self.events.remove(event)
            self.event_ids.remove(event._unique_identifier)
        else:
            warnings.warn(f"event {event._name} not found in list of events, please use another name.", UserWarning)
               
    def publish(self, event: "EventDispatcher", data: SerializableData, *, serialize: bool = True) -> None: 
        """
        publish an event with given unique name. 

        Parameters
        ----------
        unique_identifier: bytes
            unique identifier of the event
        data: Any
            payload of the event
        serialize: bool, default True
            serialize the payload before pushing, set to False when supplying raw bytes
        """
        if event._unique_identifier in self.event_ids:
            if serialize:
                self.socket.send_multipart(EventMessage([event._unique_identifier, data.serialize()]).byte_array)
            else:
                self.socket.send_multipart([event._unique_identifier, data])
        else:
            raise AttributeError("event name {} not yet registered with socket {}".format(event._unique_identifier, 
                                                                                        self.socket_address))
        
    def exit(self):
        if not hasattr(self, 'logger'):
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, uuid4()))
        try:
            self.socket.close(0)
            self.logger.info("terminated event publishing socket with address '{}'".format(self.socket_address))
        except Exception as E:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context at address '{}'. Exception message: {}".format(
                self.socket_address, str(E)))
        try:
            self.context.term()
            self.logger.info("terminated context of event publishing socket with address '{}'".format(self.socket_address)) 
        except Exception as E: 
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated socket of event publishing socket at address '{}'. Exception message: {}".format(
                self.socket_address, str(E)))
      


class BaseEventConsumer(BaseZMQClient):
    """
    Consumes events published at PUB sockets using SUB socket. 

    Parameters
    ----------
    unique_identifier: str
        identifier of the event registered at the PUB socket
    socket_address: str
        socket address of the event publisher (``EventPublisher``)
    identity: str
        unique identity for the consumer
    client_type: bytes 
        b'HTTP_SERVER' or b'PROXY'
    **kwargs:
        transport: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_id: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier: str, socket_address: str, 
                    identity: str, client_type = b'HTTP_SERVER', **kwargs) -> None:
        self._terminate_context: bool 
        transport = socket_address.split('://', 1)[0].upper()
        super().__init__(server_id=kwargs.get('server_id', None), 
                    client_type=client_type, **kwargs)
        self.create_socket(identity=identity, bind=False, context=self.context,
                        socket_address=socket_address, socket_type=zmq.SUB, transport=transport, **kwargs)
        self.unique_identifier = bytes(unique_identifier, encoding='utf-8')
        self.socket.setsockopt(zmq.SUBSCRIBE, self.unique_identifier) 
        # pair sockets cannot be polled unforunately, so we use router
        self.interruptor = self.context.socket(zmq.PAIR)
        self.interruptor.setsockopt_string(zmq.IDENTITY, f'interrupting-server')
        self.interruptor.bind(f'inproc://{self.identity}/interruption')    
        self.interrupting_peer = self.context.socket(zmq.PAIR)
        self.interrupting_peer.setsockopt_string(zmq.IDENTITY, f'interrupting-client')
        self.interrupting_peer.connect(f'inproc://{self.identity}/interruption')
        self.poller.register(self.socket, zmq.POLLIN)
        self.poller.register(self.interruptor, zmq.POLLIN)
        

    def exit(self):
        if not hasattr(self, 'logger'):
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, uuid4()))
        try:
            self.poller.unregister(self.socket)
            self.poller.unregister(self.interruptor)
        except Exception as E:
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated socket of event consuming socket at address '{}'. Exception message: {}".format(
                self.socket_address, str(E)))
            
        try:
            self.socket.close(0)
            self.interruptor.close(0)
            self.interrupting_peer.close(0)
            self.logger.info("terminated event consuming socket with address '{}'".format(self.socket_address))
        except:
            self.logger.warning("could not terminate sockets")

        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of event consuming socket with address '{}'".format(self.socket_address)) 
        except Exception as E: 
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context at address '{}'. Exception message: {}".format(
                self.socket_address, str(E)))



class AsyncEventConsumer(BaseEventConsumer):
    """
    Listens to events published at PUB sockets using SUB socket, use in async loops.

    Parameters
    ----------
    unique_identifier: str
        identifier of the event registered at the PUB socket
    socket_address: str
        socket address of the event publisher (``EventPublisher``)
    identity: str
        unique identity for the consumer
    client_type: bytes 
        b'HTTP_SERVER' or b'PROXY'
    **kwargs:
        transport: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_id: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier: str, socket_address: str, identity: str, client_type = b'HTTP_SERVER', 
                    context: typing.Optional[zmq.asyncio.Context] = None, **kwargs) -> None:
        self._terminate_context = context == None
        self.context = context or zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        super().__init__(unique_identifier=unique_identifier, socket_address=socket_address, 
                        identity=identity, client_type=client_type, **kwargs)
        
    async def receive(self, timeout: typing.Optional[float] = None, deserialize = True) -> typing.Union[bytes, typing.Any]:
        """
        receive event with given timeout

        Parameters
        ----------
        timeout: float, int, None
            timeout in milliseconds, None for blocking
        deserialize: bool, default True
            deseriliaze the data, use False for HTTP server sent event to simply bypass
        """
        contents = None
        sockets = await self.poller.poll(timeout) 
        if len(sockets) > 1:
            if socket[0] == self.interrupting_peer:
                sockets = [socket[0]]
            elif sockets[1] == self.interrupting_peer:
                sockets = [socket[1]]
        for socket, _ in sockets:
            try:
                raw_message = await socket.recv_multipart(zmq.NOBLOCK)
                event = EventMessage(raw_message)
            except zmq.Again:
                pass     
        if not deserialize or not contents: 
            return event 
        return event.body
        

    async def interrupt(self):
        """
        interrupts the event consumer and returns a 'INTERRUPT' string from the receive() method, 
        generally should be used for exiting this object
        """
     
        message = [JSONSerializer.dumps(f'{self.identity}/interrupting-server'), 
                JSONSerializer.dumps("INTERRUPT")]
        await self.interrupting_peer.send_multipart(message)

    
class EventConsumer(BaseEventConsumer):
    """
    Listens to events published at PUB sockets using SUB socket, listen in blocking fashion or use in threads. 

    Parameters
    ----------
    unique_identifier: str
        identifier of the event registered at the PUB socket
    socket_address: str
        socket address of the event publisher (``EventPublisher``)
    identity: str
        unique identity for the consumer
    client_type: bytes 
        b'HTTP_SERVER' or b'PROXY'
    **kwargs:
        transport: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_id: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier: str, socket_address: str, identity: str, client_type = b'HTTP_SERVER', 
                    context: typing.Optional[zmq.Context] = None, **kwargs) -> None:
        self._terminate_context = context == None
        self.context = context or zmq.Context()
        self.poller = zmq.Poller()
        super().__init__(unique_identifier=unique_identifier, socket_address=socket_address,
                        identity=identity, client_type=client_type, **kwargs)
        
    def receive(self, timeout: typing.Optional[float] = None, deserialize = True) -> typing.Union[bytes, typing.Any]:
        """
        receive event with given timeout

        Parameters
        ----------
        timeout: float, int, None
            timeout in milliseconds, None for blocking
        deserialize: bool, default True
            deseriliaze the data, use False for HTTP server sent event to simply bypass
        """
        contents = None
        sockets = self.poller.poll(timeout) # typing.List[typing.Tuple[zmq.Socket, int]]
        if len(sockets) > 1:
            if socket[0] == self.interrupting_peer:
                sockets = [socket[0]]
            elif sockets[1] == self.interrupting_peer:
                sockets = [socket[1]]
        for socket, _ in sockets:
            try:
                raw_message = socket.recv_multipart(zmq.NOBLOCK) 
            except zmq.Again:
                pass
        if not deserialize: 
            return contents
        return EventMessage(raw_message).body
        
    def interrupt(self):
        """
        interrupts the event consumer and returns a 'INTERRUPT' string from the receive() method, 
        generally should be used for exiting this object
        """
        message = [JSONSerializer.dumps(f'{self.identity}/interrupting-server'),
                JSONSerializer.dumps("INTERRUPT")]
        self.interrupting_peer.send_multipart(message)
    
        

from ...server.events import EventDispatcher


__all__ = [
    AsyncZMQServer.__name__, 
    ZMQServerPool.__name__, 
    SyncZMQClient.__name__, 
    AsyncZMQClient.__name__, 
    MessageMappedZMQClientPool.__name__, 
    AsyncEventConsumer.__name__, 
    EventConsumer.__name__
]