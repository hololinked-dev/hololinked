import builtins
import os
import threading
import time
import warnings
import zmq
import zmq.asyncio
import asyncio
import logging
import typing
from uuid import uuid4
from enum import Enum
from zmq.utils.monitor import parse_monitor_message

from .utils import *
from .config import global_config
from .constants import  ZMQ_PROTOCOLS, CommonRPC, ServerTypes, ZMQSocketType, ZMQ_EVENT_MAP
from .serializers import BaseSerializer, JSONSerializer, _get_serializer_from_user_given_options



# message types
# both directions
HANDSHAKE = b'HANDSHAKE' # 1 - find out if the server is alive
# client to server 
OPERATION = b'OPERATION' # 2 - operation request from client to server
EXIT = b'EXIT' # 3 - exit the server
# server to client
REPLY = b'REPLY' # 4 - response for operation
TIMEOUT = b'TIMEOUT' # 5 - timeout message, operation could not be completed
EXCEPTION = b'EXCEPTION' # 6 - exception occurred while executing operation
INVALID_MESSAGE = b'INVALID_MESSAGE' # 7 - invalid message
SERVER_DISCONNECTED = 'EVENT_DISCONNECTED' # 8 - socket died - zmq's builtin event EVENT_DISCONNECTED
# peer to peer
INTERRUPT = b'INTERRUPT' # 9 - interrupt a socket while polling 

# not used now
EVENT       = b'EVENT'
EVENT_SUBSCRIPTION = b'EVENT_SUBSCRIPTION'
SUCCESS     = b'SUCCESS'

# empty data
EMPTY_BYTE  = b''
EMPTY_DICT  = {}

# client types
HTTP_SERVER = b'HTTP_SERVER'
PROXY = b'PROXY'
TUNNELER = b'TUNNELER' # message passer from inproc client to inrproc server within RPC


"""
Message indices 

client's message to server: |br|
[address, bytes(), client type, message type, messsage id, server execution context, bytes(),
[   0   ,   1    ,     2      ,      3      ,      4     ,          5              ,    6   , 
    
thing instance name,  object, operation, arguments, thing execution context] 
      7            ,    8   ,      9   ,     10   ,       11               ] 

    
[address, bytes(), server_type, message_type, message id, data, pre encoded data]|br|
[   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6         ]|br|
"""
# CM = Client Message
CM_INDEX_ADDRESS = 0
CM_INDEX_CLIENT_TYPE = 2
CM_INDEX_MESSAGE_TYPE = 3
CM_INDEX_MESSAGE_ID = 4
CM_INDEX_SERVER_EXEC_CONTEXT = 5
CM_INDEX_THING_ID = 7
CM_INDEX_OBJECT = 8
CM_INDEX_OPERATION = 9
CM_INDEX_ARGUMENTS = 10
CM_INDEX_THING_EXEC_CONTEXT = 11
CM_MESSAGE_LENGTH = CM_INDEX_THING_EXEC_CONTEXT + 1

# SM = Server Message
SM_INDEX_ADDRESS = 0
SM_INDEX_SERVER_TYPE = 2
SM_INDEX_MESSAGE_TYPE = 3
SM_INDEX_MESSAGE_ID = 4
SM_INDEX_DATA = 5
SM_INDEX_PRE_ENCODED_DATA = 6
SM_MESSAGE_LENGTH = SM_INDEX_PRE_ENCODED_DATA + 1

byte_types = (bytes, bytearray, memoryview)

# Function to get the socket type name from the enum
def get_socket_type_name(socket_type):
    try:
        return ZMQSocketType(socket_type).name
    except ValueError:
        return "UNKNOWN"
    


class BaseZMQ: 
    """
    Base class for all ZMQ message brokers. Implements socket creation, logger, serializer instantiation 
    which is common to all server and client implementations. For HTTP clients, http_serializer is necessary and 
    for ZMQ clients, any of the allowed serializer is possible.
    """
    # init of this class must always take empty arguments due to inheritance structure
    def __init__(self) -> None:
        super().__init__()
        self.instance_name : str
        self.logger : logging.Logger
        
    def exit(self) -> None:
        """
        Cleanup method to terminate ZMQ sockets and contexts before quitting. Called by `__del__()`
        automatically. Each subclass server/client should implement their version of exiting if necessary.
        """
        if self.logger is None:
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, self.instance_name))

    def __del__(self) -> None:
        self.exit()

    def create_socket(self, *, identity : str, bind : bool, context : typing.Union[zmq.asyncio.Context, zmq.Context], 
                    protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, 
                    socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        """
        Create a socket with certain specifications. When successful, a logger is also created. Supported ZeroMQ protocols
        are TCP, IPC & INPROC. For IPC sockets, a file is created under TEMP_DIR of global configuration.

        Parameters
        ----------
        identity: str
            For servers, supplying the ``instance_name`` is sufficient. Clients need to have a different ID other 
            than the ``instance_name`` of the server. Each ROUTER socket require unique identity to correctly route the messages.
        bind: bool
            whether to bind (server) or connect (client), as per ZMQ definition
        context: zmq.Context or zmq.asyncio.Context
            ZeroMQ Context object that creates the socket
        protocol: Enum
            TCP, IPC or INPROC. Message crafting/passing/routing is protocol invariant as suggested by ZeroMQ docs
            Speed wise INPROC > IPC > TCP.
        socket_type: zmq.SocketType, default zmq.ROUTER
            Usually a ROUTER socket is implemented for both client-server and peer-to-peer communication
        **kwargs: dict
            socket_address: str
                applicable only for TCP socket to find the correct socket to connect 
            log_level: int
                logging.Logger log level if no logger previously created

        Returns
        -------
        None 

        Raises
        ------
        NotImplementedError
            if protocol other than TCP, IPC or INPROC is used
        RuntimeError
            if protocol is TCP, a socket connect from client side is requested but a socket address is not supplied
        """
        self.context = context
        self.identity = identity
        self.socket = self.context.socket(socket_type)
        self.socket.setsockopt_string(zmq.IDENTITY, identity)
        socket_address = kwargs.get('socket_address', None)
        if protocol == ZMQ_PROTOCOLS.IPC or protocol == "IPC":
            if socket_address is None:
                split_instance_name = self.instance_name.split('/')
                socket_dir = os.sep  + os.sep.join(split_instance_name[:-1]) if len(split_instance_name) > 1 else ''
                directory = global_config.TEMP_DIR + socket_dir
                if not os.path.exists(directory):
                    os.makedirs(directory)
                # re-compute for IPC because it looks for a file in a directory
                socket_address = "ipc://{}{}{}.ipc".format(directory, os.sep, split_instance_name[-1])
            if bind:
                self.socket.bind(socket_address)
            else:
                self.socket.connect(socket_address)
        elif protocol == ZMQ_PROTOCOLS.TCP or protocol == "TCP":
            if bind:
                if not socket_address:
                    for i in range(global_config.TCP_SOCKET_SEARCH_START_PORT, global_config.TCP_SOCKET_SEARCH_END_PORT):
                        socket_address = "tcp://0.0.0.0:{}".format(i)
                        try:
                            self.socket.bind(socket_address)
                            break 
                        except zmq.error.ZMQError as ex:
                            if not ex.strerror.startswith('Address in use'):
                                raise ex from None
                else:                   
                    self.socket.bind(socket_address)
            elif socket_address: 
                self.socket.connect(socket_address)
            else:
                raise RuntimeError(f"Socket address not supplied for TCP connection to identity - {identity}")
        elif protocol == ZMQ_PROTOCOLS.INPROC or protocol == "INPROC":
            # inproc_instance_name = instance_name.replace('/', '_').replace('-', '_')
            if socket_address is None:
                socket_address = f'inproc://{self.instance_name}'
            if bind:
                self.socket.bind(socket_address)
            else:
                self.socket.connect(socket_address)
        else:
            raise NotImplementedError("protocols other than IPC, TCP & INPROC are not implemented now for {}".format(
                                                                                                    self.__class__) + 
                                            f" Given protocol {protocol}.")
        self.socket_address = socket_address
        if not self.logger:
            self.logger = get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, socket_type, protocol, identity), 
                                                kwargs.get('log_level', logging.INFO))
        self.logger.info("created socket {} with address {} & identity {} and {}".format(get_socket_type_name(socket_type), socket_address,
                                                            identity, "bound" if bind else "connected"))

   
class BaseAsyncZMQ(BaseZMQ):
    """
    Base class for all async ZMQ servers and clients.
    """
    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(self, *, identity : str, bind : bool = False, context : typing.Optional[zmq.asyncio.Context] = None, 
                        protocol : str = "IPC", socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        """
        Overloads ``create_socket()`` to create, bind/connect an async socket. A async context is created if none is supplied. 
        """
        if context and not isinstance(context, zmq.asyncio.Context):
            raise TypeError("async ZMQ message broker accepts only async ZMQ context. supplied type {}".format(type(context)))
        context = context or zmq.asyncio.Context()
        super().create_socket(identity=identity, bind=bind, context=context, protocol=protocol, 
                            socket_type=socket_type, **kwargs)
        

class BaseSyncZMQ(BaseZMQ):
    """
    Base class for all sync ZMQ servers and clients.
    """
    # init of this class must always take empty arguments due to inheritance structure

    def create_socket(self, *, identity : str, bind : bool = False, context : typing.Optional[zmq.Context] = None, 
                    protocol : str = "IPC", socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        """
        Overloads ``create_socket()`` to create, bind/connect a synchronous socket. A synchronous context is created 
        if none is supplied. 
        """
        if context: 
            if not isinstance(context, zmq.Context):
                raise TypeError("sync ZMQ message broker accepts only sync ZMQ context. supplied type {}".format(type(context)))
            if isinstance(context, zmq.asyncio.Context):
                raise TypeError("sync ZMQ message broker accepts only sync ZMQ context. supplied type {}".format(type(context)))
        context = context or zmq.Context()
        super().create_socket(identity=identity, bind=bind, context=context, protocol=protocol, 
                            socket_type=socket_type, **kwargs)
        


class BaseZMQServer(BaseZMQ):
    """
    Implements messaging contract as suggested by ZMQ, this is defined as follows: 
    
    client's message to server: 
    ::
        [address, bytes(), client type, message type, messsage id, 
        [   0   ,   1    ,     2      ,      3      ,      4     , 
            
        server execution context, operation, object, arguments, thing execution context] 
            5                   ,      6   ,   7   ,     8    ,       9                ] 

    server's message to client: 
    ::
        [address, bytes(), server_type, message_type, message id, data, pre encoded data]
        [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6         ]

    The messaging contract does not depend on sync or async implementation.  
    """  
    def __init__(self, 
                instance_name : str,
                server_type : typing.Union[bytes, str], 
                http_serializer : typing.Union[None, JSONSerializer] = None, 
                zmq_serializer : typing.Union[str, BaseSerializer, None] = None,
                logger : typing.Optional[logging.Logger] = None,
                **kwargs
            ) -> None:
        super().__init__(**kwargs)
        self.zmq_serializer, self.http_serializer = _get_serializer_from_user_given_options(
                                                            zmq_serializer=zmq_serializer,
                                                            http_serializer=http_serializer
                                                        )
        self.instance_name = instance_name
        if isinstance(server_type, bytes):
            self.server_type = server_type
        elif isinstance(server_type, str):
            self.server_type = bytes(server_type, encoding='utf-8')
        elif isinstance(server_type, Enum):
            self.server_type = bytes(str(server_type), encoding='utf-8') 
        else:
            raise TypeError("Unknown type for assign server type.")
        self.logger = logger


    def parse_client_message(self, message : typing.List[bytes]) -> typing.List[typing.Union[bytes, typing.Any]]:
        """
        Deserializes important parts of the client's message, namely operation, arguments, thing execution context 
        based on the client type. For handshake messages, automatically handles handshake. In case of exceptions while 
        deserializing, automatically sends an invalid message to client informing the nature of exception with the 
        exception metadata. 
        
        client's message to server:
        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
                
            server execution context, operation, object, arguments, thing execution context] 
                5                   ,      6   ,   7   ,     8    ,       9                ] 

        Server Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "invokation_timeout" - time in seconds to wait for the operation to start
            - "execution_timeout" - time in seconds to wait for the operation to finish
            - "oneway" - does not response to client after executing the operation 

        Thing Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "fetch_execution_logs" - fetches logs that were accumulated while execution

        Parameters
        ----------
        message: List[bytes]
            message received from client
      
        Returns
        -------
        message: List[bytes | Any]
            message with operation, arguments and execution context deserialized

        """
        try:
            # TODO move it somewhere else or move all server operations to this place
            message_type = message[CM_INDEX_MESSAGE_TYPE]
            if message_type == OPERATION:
                client_type = message[CM_INDEX_CLIENT_TYPE]
                # message[CM_INDEX_OPERATION] = message[CM_INDEX_OPERATION].decode() # type: ignore
                message[CM_INDEX_OBJECT] = message[CM_INDEX_OBJECT].decode()
                if client_type == PROXY:
                    message[CM_INDEX_ARGUMENTS] = self.zmq_serializer.loads(message[CM_INDEX_ARGUMENTS]) # type: ignore
                    message[CM_INDEX_THING_EXEC_CONTEXT] = self.zmq_serializer.loads(message[CM_INDEX_THING_EXEC_CONTEXT]) # type: ignore
                elif client_type == HTTP_SERVER:
                    # message[CM_INDEX_OPERATION] = self.http_serializer.loads(message[CM_INDEX_OPERATION]) # type: ignore
                    message[CM_INDEX_ARGUMENTS] = self.http_serializer.loads(message[CM_INDEX_ARGUMENTS]) # type: ignore
                    message[CM_INDEX_THING_EXEC_CONTEXT] = self.http_serializer.loads(message[CM_INDEX_THING_EXEC_CONTEXT]) # type: ignore
                return message 
            elif message_type == HANDSHAKE:
                self.handshake(message)
                return
            elif message_type == EXIT:
                return message
            raise Exception("Invalid message type given '{}' with msg-ID '{}'".format(message_type, 
                                                                                        message[CM_INDEX_MESSAGE_ID])) 
        except Exception as ex:
            self.handle_invalid_message(message, ex)


    def craft_response_from_arguments(self, address : bytes, client_type: bytes, message_type : bytes, 
                            message_id : bytes = b'', data : typing.Any = None, 
                            pre_encoded_data : typing.Optional[bytes] = EMPTY_BYTE) -> typing.List[bytes]:
        """
        Crafts an arbitrary response to the client using the method's arguments. 

        server's message to client:
        ::
            [address, bytes(), server_type, message_type, message id, data, pre encoded data]
            [   0   ,   1    ,    2       ,      3      ,  4        ,  5  ,      6          ]

        Parameters
        ----------
        address: bytes 
            the ROUTER address of the client
        message_type: bytes 
            type of the message, possible values are b'REPLY', b'HANDSHAKE' and b'TIMEOUT' 
        message_id: bytes
            message id of the original client message for which the response is being crafted
        data: Any
            serializable data
        pre_encoded_data: bytes
            pre-encoded data, generally used for large or custom data that is already serialized
        
        Returns
        -------
        message: List[bytes]
            the crafted response with information in the correct positions within the list
        """
        if client_type == HTTP_SERVER:
            data = self.http_serializer.dumps(data)
        elif client_type == PROXY:
            data = self.zmq_serializer.dumps(data)
        elif client_type == TUNNELER:
            if data is not None:
                raise NotImplementedError(f"client type {client_type} not supported for serialization")
            data = self.zmq_serializer.dumps(data)

        return [
            address,
            EMPTY_BYTE,
            self.server_type,
            message_type,
            message_id,
            data,
            pre_encoded_data
        ] 
           

    def craft_response_from_client_message(self, original_client_message : typing.List[bytes], data : typing.Any = None,
                                            pre_encoded_data : bytes = EMPTY_BYTE) -> typing.List[bytes]:
        """
        Craft a response with certain data automatically from an originating client message, like the client's address, 
        type required for serialization requirements, message id etc. 

        server's message to client:
        ::
            [address, bytes(), server_type, message_type, message id, data, pre encoded data]
            [   0   ,   1    ,    2       ,      3      ,  4        ,  5  ,      6          ]

        Parameters
        ----------
        original_client_message: List[bytes]
            The message originated by the clieht for which the response is being crafted
        data: Any
            serializable data 
        pre_encoded_data: bytes
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        message: List[bytes]
            the crafted response with information in the correct positions within the list
        """
        client_type = original_client_message[CM_INDEX_CLIENT_TYPE]
        if client_type == HTTP_SERVER:
            data = self.http_serializer.dumps(data)
        elif client_type == PROXY:
            data = self.zmq_serializer.dumps(data)
        else:
            raise ValueError(f"invalid client type given '{client_type}' for preparing message to send from " +
                            f"'{self.identity}' of type {self.__class__}.")
        return [
            original_client_message[CM_INDEX_ADDRESS],
            EMPTY_BYTE,
            self.server_type,
            REPLY,
            original_client_message[CM_INDEX_MESSAGE_ID],
            data,
            pre_encoded_data
        ]
    

    def handshake(self, original_client_message : typing.List[bytes]) -> None:
        """
        Pass a handshake message to client. Absolutely mandatory to ensure initial messages do not get lost 
        because of ZMQ's very tiny but significant initial delay after creating socket.

        Parameters
        ----------
        original_client_message: List[bytes]
            the client message for which the handshake is being sent

        Returns
        -------
        None 
        """
        run_callable_somehow(self._handshake(original_client_message))

    def _handshake(self, original_client_message : typing.List[bytes]) -> None:
        raise NotImplementedError(f"handshake cannot be handled - implement _handshake in {self.__class__} to handshake.")


    def handle_invalid_message(self, original_client_message : typing.List[bytes], exception : Exception) -> None:
        """
        Pass an invalid message to the client when an exception occurred while parsing the message from the client 
        (``parse_client_message()``)

        Parameters
        ----------
        original_client_message: List[bytes]
            the client message parsing which the exception occurred
        exception: Exception
            exception object raised

        Returns
        -------
        None
        """
        run_callable_somehow(self._handle_invalid_message(original_client_message, exception))

    def _handle_invalid_message(self, message : typing.List[bytes], exception : Exception) -> None:
        raise NotImplementedError("invalid message cannot be handled" +
                f" - implement _handle_invalid_message in {self.__class__} to handle invalid messages.")
            

    def handle_timeout(self, original_client_message : typing.List[bytes]) -> None:
        """
        Pass timeout message to the client when the operation could not be executed within specified timeouts

        Parameters
        ----------
        original_client_message: List[bytes]
            the client message which could not executed within the specified timeout. timeout value is 
            generally specified within the execution context values.
        
        Returns
        -------
        None
        """
        run_callable_somehow(self._handle_timeout(original_client_message))

    def _handle_timeout(self, original_client_message : typing.List[bytes]) -> None:
        raise NotImplementedError("timeouts cannot be handled ",
                f"- implement _handle_timeout in {self.__class__} to handle timeout.")

        

class BaseAsyncZMQServer(BaseZMQServer):
    """
    Common to all async ZMQ servers
    """
    
    async def _handshake(self, original_client_message : typing.List[bytes]) -> None:
        """
        Inner method that handles handshake. Scheduled by ``handshake()`` method, signature same as ``handshake()``.
        """
        # Note that for ROUTER sockets, once the message goes through the sending socket, the address of the receiver 
        # is replaced by the address of the sender once received 
        await self.socket.send_multipart(self.craft_response_from_arguments(address=original_client_message[CM_INDEX_ADDRESS], 
                client_type=original_client_message[CM_INDEX_CLIENT_TYPE], message_type=HANDSHAKE, 
                message_id=original_client_message[CM_INDEX_MESSAGE_ID]))
        self.logger.info(f"sent handshake to client '{original_client_message[CM_INDEX_ADDRESS]}'")


    async def _handle_timeout(self, original_client_message : typing.List[bytes]) -> None:
        """
        Inner method that handles timeout. Scheduled by ``handle_timeout()``, signature same as ``handle_timeout``.
        """
        await self.socket.send_multipart(self.craft_response_from_arguments(address=original_client_message[CM_INDEX_ADDRESS], 
                client_type=original_client_message[CM_INDEX_CLIENT_TYPE], message_type=TIMEOUT, 
                message_id=original_client_message[CM_INDEX_MESSAGE_ID]))
        self.logger.info(f"sent timeout to client '{original_client_message[CM_INDEX_ADDRESS]}'")

    
    async def _handle_invalid_message(self, original_client_message : typing.List[bytes], exception : Exception) -> None:
        """
        Inner method that handles invalid messages. Scheduled by ``handle_invalid_message()``, 
        signature same as ``handle_invalid_message()``.
        """
        await self.socket.send_multipart(self.craft_response_from_arguments(address=original_client_message[CM_INDEX_ADDRESS], 
                client_type=original_client_message[CM_INDEX_CLIENT_TYPE], message_type=INVALID_MESSAGE, 
                message_id=original_client_message[CM_INDEX_MESSAGE_ID], data=exception))         
        self.logger.info(f"sent exception message to client '{original_client_message[CM_INDEX_ADDRESS]}'." +
                            f" exception - {str(exception)}") 	


       
class AsyncZMQServer(BaseAsyncZMQServer, BaseAsyncZMQ):
    """
    Implements both blocking (non-polled) and non-blocking/polling form of receive messages and send replies
    This server can be stopped from server side by calling ``stop_polling()`` unlike ``AsyncZMQServer`` which 
    cannot be stopped manually unless a message arrives.

    Parameters
    ----------
    instance_name: str
        ``instance_name`` of the Thing which the server serves
    server_type: str
        server type metadata - currently not useful/important
    context: Optional, zmq.asyncio.Context
        ZeroMQ Context object to use. All sockets share this context. Automatically created when None is supplied.
    socket_type : zmq.SocketType, default zmq.ROUTER
        socket type of ZMQ socket, default is ROUTER (enables address based routing of messages)
    protocol: Enum, default ZMQ_PROTOCOLS.IPC
        Use TCP for network access, IPC for multi-process applications, and INPROC for multi-threaded applications.  
    poll_timeout: int, default 25
        time in milliseconds to poll the sockets specified under ``procotols``. Useful for calling ``stop_polling()``
        where the max delay to stop polling will be ``poll_timeout``
  
    **kwargs:
        http_serializer: hololinked.server.serializers.JSONSerializer
            serializer used to send message to HTTP Server
        zmq_serializer: any of hololinked.server.serializers.serializer, default serpent
            serializer used to send message to ZMQ clients
    """

    def __init__(self, *, instance_name : str, server_type : Enum, context : typing.Union[zmq.asyncio.Context, None] = None, 
                socket_type : zmq.SocketType = zmq.ROUTER, protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, 
                poll_timeout = 25, **kwargs) -> None:
        BaseAsyncZMQServer.__init__(self, instance_name=instance_name, server_type=server_type, **kwargs)
        BaseAsyncZMQ.__init__(self)
        self.create_socket(identity=instance_name, bind=True, context=context, protocol=protocol, 
                        socket_type=socket_type, **kwargs) 
        self._terminate_context = context == None # terminate if it was created by instance
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self.poll_timeout = poll_timeout


    async def async_recv_request(self) -> typing.Any:
        """
        Receive one message in a blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``.   

        Returns
        -------
        message: List[bytes | Any]
            received message with important content (operation, arguments, thing execution context) deserialized. 
        """
        while True:
            message = self.parse_client_message(await self.socket.recv_multipart())
            if message:
                self.logger.debug(f"received message from client '{message[CM_INDEX_ADDRESS]}' with msg-ID '{message[CM_INDEX_MESSAGE_ID]}'")
                return message
        

    async def async_recv_requests(self) -> typing.List[typing.Any]:
        """
        Receive all currently available messages in blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``. 

        Returns
        -------
        messages: List[List[bytes | Any]]
            list of received messages with important content (operation, arguments, execution context) deserialized.
        """
        messages = [await self.async_recv_request()]
        while True:
            try:
                message = self.parse_client_message(await self.socket.recv_multipart(zmq.NOBLOCK))
                if message:
                    self.logger.debug(f"received message from client '{message[CM_INDEX_ADDRESS]}' with msg-ID '{message[CM_INDEX_MESSAGE_ID]}'")
                    messages.append(message)
            except zmq.Again: 
                break 
        return messages
    

    async def async_send_response(self, original_client_message : typing.List[bytes], data : typing.Any = None, 
                                        pre_encoded_data : bytes = EMPTY_BYTE) -> None:
        """
        Send response message for a request message. 

        Parameters
        ----------
        original_client_message: List[bytes]
            original message so that the response can be properly crafted and routed
        data: Any
            serializable data to be sent as response
        pre_encoded_data: bytes
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        None
        """
        await self.socket.send_multipart(self.craft_response_from_client_message(original_client_message=original_client_message, 
                                                        data=data, pre_encoded_data=pre_encoded_data))
        self.logger.debug(f"sent response to client '{original_client_message[CM_INDEX_ADDRESS]}' with msg-ID '{original_client_message[CM_INDEX_MESSAGE_ID]}'")
        
    
    async def async_send_response_with_message_type(self, original_client_message : typing.List[bytes], 
            message_type: bytes, data : typing.Any = None, pre_encoded_data : bytes = EMPTY_BYTE) -> None:
        """
        Send response message for a request message. 

        Parameters
        ----------
        original_client_message: List[bytes]
            original message so that the response can be properly crafted and routed
        data: Any
            serializable data to be sent as response

        Returns
        -------
        None
        """
        await self.socket.send_multipart(self.craft_response_from_arguments(address=original_client_message[CM_INDEX_ADDRESS], 
                    client_type=original_client_message[CM_INDEX_CLIENT_TYPE], message_type=message_type, 
                    message_id=original_client_message[CM_INDEX_MESSAGE_ID], data=data, pre_encoded_data=pre_encoded_data))
        self.logger.debug(f"sent response to client '{original_client_message[CM_INDEX_ADDRESS]}' with msg-ID '{original_client_message[CM_INDEX_MESSAGE_ID]}'")


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


    async def poll_requests(self) -> typing.List[typing.List[bytes]]:
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
                        message = self.parse_client_message(await socket.recv_multipart(zmq.NOBLOCK))
                    except zmq.Again:
                        break
                    else:
                        if message:
                            self.logger.debug(f"received message from client '{message[CM_INDEX_ADDRESS]}' with msg-ID '{message[CM_INDEX_MESSAGE_ID]}'")
                            messages.append(message)
            if len(messages) > 0:
                break
        return messages
    
    def stop_polling(self) -> None:
        """
        stop polling and unblock ``poll_messages()`` method
        """
        self.stop_poll = True 


    def exit(self) -> None:
        """
        unregister socket from poller and terminate socket and context.
        """
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
            self.socket.close(0)
            self.logger.info(f"terminated socket of server '{self.identity}' of type {self.__class__}")
        except Exception as ex:
            self.logger.warning(f"could not unregister socket {self.identity} from polling - {str(ex)}")
        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of socket '{}' of type '{}'".format(self.identity, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated " +
                            f" context '{self.identity}'. Exception message : {str(ex)}")
    
    """
    Available classes of servers are as follows: 

    BaseZMQ
    BaseAsyncZMQ
    BaseSyncZMQ
    BaseZMQServer
    AsyncZMQServer
    ZMQServerPool
    """


class ZMQServerPool(BaseZMQServer):
    """
    Implements pool of async ZMQ servers (& their sockets)
    """

    def __init__(self, *, instance_names : typing.Union[typing.List[str], None] = None, **kwargs) -> None:
        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.pool = dict() # type: typing.Dict[str, AsyncZMQServer]
        if instance_names:
            for instance_name in instance_names:
                self.pool[instance_name] = AsyncZMQServer(instance_name=instance_name, 
                                    server_type=ServerTypes.UNKNOWN_TYPE.value, context=self.context, **kwargs)
            for server in self.pool.values():
                self.poller.register(server.socket, zmq.POLLIN)
        super().__init__(instance_name="pool", server_type=ServerTypes.POOL.value, **kwargs)
        self.identity = "pool" # we fix the instance name because it is a pool of servers = does not create its own socket
        if self.logger is None:
            self.logger = get_default_logger("pool|polling", kwargs.get('log_level',logging.INFO))

    def create_socket(self, *, identity : str, bind: bool, context : typing.Union[zmq.asyncio.Context, zmq.Context], 
                protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        raise NotImplementedError("create socket not supported by ZMQServerPool")
        # we override this method to prevent socket creation. instance_name set to pool is simply a filler 
        return super().create_socket(identity=identity, bind=bind, context=context, protocol=protocol, 
                                    socket_type=socket_type, **kwargs)

    def register_server(self, server : AsyncZMQServer) -> None:
        if not isinstance(server, (AsyncZMQServer)):
            raise TypeError("registration possible for servers only subclass of AsyncZMQServer." +
                           f" Given type {type(server)}")
        self.pool[server.instance_name] = server 
        self.poller.register(server.socket, zmq.POLLIN)

    def deregister_server(self, server : AsyncZMQServer) -> None:
        self.poller.unregister(server.socket)
        self.pool.pop(server.instance_name)

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

    async def async_recv_request(self, instance_name : str) -> typing.List:
        """
        receive message for server instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ZMQ server. 
        """
        return await self.pool[instance_name].async_recv_request()
     
    async def async_recv_requests(self, instance_name : str) -> typing.List[typing.List]:
        """
        receive all available messages for server instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ZMQ server. 
        """
        return await self.pool[instance_name].async_recv_requests()
   
    async def async_send_response(self, *, instance_name : str, original_client_message : typing.List[bytes],  
                               data : typing.Any, pre_encoded_data : bytes = EMPTY_BYTE) -> None:
        """
        send response for instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ``Thing`` or in this case, the ZMQ server. 
        original_client_message: List[bytes]
            request message for which response is being given
        data: Any
            data to be given as response
        """
        await self.pool[instance_name].async_send_response(original_client_message=original_client_message, 
                                                        data=data, pre_encoded_data=pre_encoded_data)
    
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
                        message = self.parse_client_message(await socket.recv_multipart(zmq.NOBLOCK))
                    except zmq.Again:
                        break
                    else:
                        if message:
                            self.logger.debug(f"received message from client '{message[CM_INDEX_ADDRESS]}' with msg-ID '{message[CM_INDEX_MESSAGE_ID]}'")
                            messages.append(message)
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
    
    def __contains__(self, name : str) -> bool:
        return name in self.pool.keys()
    
    def exit(self) -> None:
        for server in self.pool.values():       
            try:
                self.poller.unregister(server.socket)
                server.exit()
            except Exception as ex:
                self.logger.warning(f"could not unregister poller and exit server {server.identity} - {str(ex)}")
        try:
            self.context.term()
            self.logger.info("context terminated for {}".format(self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context " +
                             f"'{self.identity}'. Exception message : {str(ex)}")

    
    
default_server_execution_context = dict(
    invokation_timeout=5,
    execution_timeout=5,
    oneway=False
)
    
class BaseZMQClient(BaseZMQ):
    """    
    Base class for all ZMQ clients irrespective of sync and async.

    server's response to client
    ::

        [address, bytes(), server_type, message_type, message id, data, pre encoded data]|br|
        [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6         ]|br|

    Parameters
    ----------
    server_instance_name: str
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
                server_instance_name : str, client_type : bytes, 
                server_type : typing.Union[bytes, str, Enum] = ServerTypes.UNKNOWN_TYPE, 
                http_serializer : typing.Union[None, JSONSerializer] = None, 
                zmq_serializer : typing.Union[str, BaseSerializer, None] = None,
                logger : typing.Optional[logging.Logger] = None,
                **kwargs
            ) -> None:
        if client_type in [PROXY, HTTP_SERVER, TUNNELER]: 
            self.client_type = client_type
        else:
            raise ValueError("Invalid client type for {}. Given option {}.".format(self.__class__, client_type)) 
        if server_instance_name:
            self.server_address = bytes(server_instance_name, encoding='utf-8')
        self.instance_name = server_instance_name
        self.zmq_serializer, self.http_serializer = _get_serializer_from_user_given_options(
                                                            zmq_serializer=zmq_serializer,
                                                            http_serializer=http_serializer
                                                        )
        if isinstance(server_type, bytes):
            self.server_type = server_type 
        elif isinstance(server_type, Enum):
            self.server_type = server_type.value
        else:
            self.server_type = bytes(server_type, encoding='utf-8') 
        self.logger = logger
        self._monitor_socket = None
        self._response_cache = dict()
        self._terminate_context = False
        self.poller : typing.Union[zmq.Poller, zmq.asyncio.Poller] 
        super().__init__()


    def raise_local_exception(self, exception : typing.Dict[str, typing.Any]) -> None:
        """
        raises an exception on client side using an exception from server by mapping it to the correct one based on type.

        Parameters
        ----------
        exception: Dict[str, Any]
            exception dictionary made by server with following keys - type, message, traceback, notes

        """
        if isinstance(exception, Exception):
            raise exception from None
        exc = getattr(builtins, exception["type"], None)
        message = exception["message"]
        if exc is None:
            ex = Exception(message)
        else: 
            ex = exc(message)
        exception["traceback"][0] = f"Server {exception['traceback'][0]}"
        ex.__notes__ = exception["traceback"][0:-1]
        raise ex from None 


    def parse_server_message(self, message : typing.List[bytes], raise_client_side_exception : bool = False, 
                                    deserialize_response : bool = True) -> typing.Any:
        """
        server's message to client: 

        ::
            [address, bytes(), server_type, message_type, message id, data, pre encoded data]|br|
            [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6         ]|br|

        Parameters
        ----------
        message: List[bytes]
            message sent be server
        raise_client_side_exception: bool
            raises exception from server on client
        deserialize_response: bool
            deserializes the data field of the message
        
        Raises
        ------
        NotImplementedError:
            if message type is not response, handshake or invalid
        """
        if len(message) == 2: # socket monitor message, not our message
            try: 
                if ZMQ_EVENT_MAP[parse_monitor_message(message)['event']] == SERVER_DISCONNECTED:
                    raise ConnectionAbortedError(f"server disconnected for {self.instance_name}")
                return None # None should simply continue the message receive logic
            except RuntimeError as ex:
                raise RuntimeError(f'message received from monitor socket cannot be deserialized for {self.instance_name}') from None
        message_type = message[SM_INDEX_MESSAGE_TYPE]
        if message_type == REPLY:
            if deserialize_response:
                if self.client_type == HTTP_SERVER:
                    message[SM_INDEX_DATA] = self.http_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
                elif self.client_type == PROXY:
                    message[SM_INDEX_DATA] = self.zmq_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            return message 
        elif message_type == HANDSHAKE:
            self.logger.debug("""handshake messages arriving out of order are silently dropped as receiving this message 
                means handshake was successful before. Received hanshake from {}""".format(message[0]))
            return message
        elif message_type == EXCEPTION or message_type == INVALID_MESSAGE:
            if self.client_type == HTTP_SERVER:
                message[SM_INDEX_DATA] = self.http_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            elif self.client_type == PROXY:
                message[SM_INDEX_DATA] = self.zmq_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            if not raise_client_side_exception:
                return message
            if message[SM_INDEX_DATA].get('exception', None) is not None:
                self.raise_local_exception(message[SM_INDEX_DATA]['exception'])
            else:
                raise NotImplementedError("message type {} received. No exception field found, exception field mandatory.".format(
                    message_type))
        elif message_type == TIMEOUT:
            if self.client_type == HTTP_SERVER:
                timeout_type = self.http_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            elif self.client_type == PROXY:
                timeout_type = self.zmq_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            exception =  TimeoutError(f"{timeout_type} timeout occurred")
            if raise_client_side_exception:
                raise exception from None 
            message[SM_INDEX_DATA] = format_exception_as_json(exception)
            return message
        else:
            raise NotImplementedError("Unknown message type {} received. This message cannot be dealt.".format(message_type))


    def craft_request_from_arguments(self, thing_id : bytes, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                            server_execution_context : typing.Optional[float] = default_server_execution_context, 
                            thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT) -> typing.List[bytes]: 
        """
        message from client to server:

        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
                
            server execution context, operation, object, arguments, thing execution context] 
                5                   ,      6   ,   7   ,     8    ,       9                ] 

        Parameters
        ----------
        operation: str
            operation to be performed
        arguments: Dict[str, Any]
            arguments for the operation
        server_execution_context: Dict[str, Any]
            server execution context 
        thing_execution_context: Dict[str, Any]
            thing execution context
        """
        message_id = bytes(str(uuid4()), encoding='utf-8')
        if self.client_type == HTTP_SERVER:
            server_execution_context = self.http_serializer.dumps(server_execution_context) # type: bytes
            # operation = self.http_serializer.dumps(operation) # type: bytes
            # TODO - following can be improved
            if arguments == b'':
                arguments = self.http_serializer.dumps({}) # type: bytes
            elif not isinstance(arguments, byte_types):
                arguments = self.http_serializer.dumps(arguments) # type: bytes
            thing_execution_context = self.http_serializer.dumps(thing_execution_context) # type: bytes
        elif self.client_type == PROXY:
            server_execution_context = self.zmq_serializer.dumps(server_execution_context) # type: bytes
            # operation = self.zmq_serializer.dumps(operation) # type: bytes
            if not isinstance(arguments, byte_types):
                arguments = self.zmq_serializer.dumps(arguments) # type: bytes
            thing_execution_context = self.zmq_serializer.dumps(thing_execution_context)
              
        return [
            self.server_address, 
            EMPTY_BYTE,
            self.client_type,
            OPERATION,
            message_id,
            server_execution_context, 
            EMPTY_BYTE,
            thing_id,
            objekt,
            operation,
            arguments,
            thing_execution_context
        ]


    def craft_empty_request_with_message_type(self, message_type : bytes = HANDSHAKE):
        """
        create handshake message for example

        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
                
            server execution context, operation, object, arguments, thing execution context] 
                5                   ,      6   ,   7   ,     8    ,       9                ] 

        Parameters
        ----------
        message_type: bytes
            message type to be sent
        """
        message_id = bytes(str(uuid4()), encoding='utf-8')
        return [
            self.server_address,
            EMPTY_BYTE,
            self.client_type,
            message_type,
            message_id,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE
        ]
    
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
            self.logger.info("terminated socket of server '{}' of type '{}'".format(self.identity, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated " +
                             f"socket '{self.identity}' of type '{self.__class__}'. Exception message : {str(ex)}")
        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of socket '{}' of type '{}'".format(self.identity, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context" +
                            "'{}'. Exception message : {}".format(self.identity, str(ex)))



class SyncZMQClient(BaseZMQClient, BaseSyncZMQ):
    """
    Synchronous ZMQ client that connect with sync or async server based on ZMQ protocol. Works like REQ-REP socket. 
    Each request is blocking until response is received. Suitable for most purposes. 

    Parameters
    ----------
    server_instance_name: str
        The instance name of the server (or ``Thing``)
    identity: str 
        Unique identity of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID. 
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    protocol: str | Enum, TCP, IPC or INPROC, default IPC 
        protocol implemented by the server 
    **kwargs:
        socket_address: str
            socket address for connecting to TCP server
        zmq_serializer: 
            custom implementation of ZMQ serializer if necessary
        http_serializer:
            custom implementation of JSON serializer if necessary
    """

    def __init__(self, server_instance_name : str, identity : str, client_type = HTTP_SERVER, 
                handshake : bool = True, protocol : str = ZMQ_PROTOCOLS.IPC, 
                context : typing.Union[zmq.Context, None] = None,
                **kwargs) -> None:
        BaseZMQClient.__init__(self, server_instance_name=server_instance_name, 
                            client_type=client_type, **kwargs)
        BaseSyncZMQ.__init__(self)
        self.create_socket(identity=identity, context=context, protocol=protocol, **kwargs)
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self._terminate_context = context == None
        self._client_queue = threading.RLock()
        # print("context on client", self.context)
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))
    
    def send_request(self, thing_id : bytes, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                        thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT) -> bytes:
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
        message id : bytes
            a byte representation of message id
        """
        message = self.craft_request_from_arguments(thing_id=thing_id, objekt=objekt, operation=operation, arguments=arguments, 
                        server_execution_context=server_execution_context, thing_execution_context=thing_execution_context)
        self.socket.send_multipart(message)
        self.logger.debug(f"sent operation '{operation}' to server '{self.instance_name}' with msg-id '{message[SM_INDEX_MESSAGE_ID]}'")
        return message[SM_INDEX_MESSAGE_ID]
    
    def recv_response(self, message_id : bytes, timeout : typing.Optional[int] = None, raise_client_side_exception : bool = False, 
                    deserialize_response : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]:
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
            sockets = self.poller.poll(timeout)
            response = None
            for socket, _ in sockets:
                try:    
                    message = socket.recv_multipart(zmq.NOBLOCK)
                    response = self.parse_server_message(message=message, raise_client_side_exception=raise_client_side_exception, 
                                                    deserialize_response=deserialize_response) # type: ignore
                except zmq.Again:
                    pass 
            if response: 
                if message_id != response[SM_INDEX_MESSAGE_ID]:
                    self._response_cache[message_id] = response
                    continue
                elif response[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
                    continue
                self.logger.debug("received response with msg-id {}".format(response[SM_INDEX_MESSAGE_ID]))
                return response
            if timeout is not None:
                break # this should not break, technically an error, should be fixed when inventing better RPC contract
                
    def execute(self, thing_id : bytes, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT, raise_client_side_exception : bool = False, 
                deserialize_response : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]:
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
        message id : bytes
            a byte representation of message id
        """
        acquire_timeout = server_execution_context.get("invokation_timeout", None) 
        if not acquire_timeout:
            acquire_timeout = -1 
        acquired = self._client_queue.acquire(timeout=acquire_timeout)
        if not acquired:
            raise TimeoutError("Previous request still in progress, did not send request to server")
        try:
            msg_id = self.send_request(thing_id=thing_id, objekt=objekt, operation=operation, arguments=arguments, 
                        server_execution_context=server_execution_context, thing_execution_context=thing_execution_context)
            return self.recv_response(message_id=msg_id, raise_client_side_exception=raise_client_side_exception, 
                                    deserialize_response=deserialize_response)
        finally:
            self._client_queue.release() 


    def handshake(self, timeout : typing.Union[float, int] = 60000) -> None: 
        """
        hanshake with server before sending first message
        """
        start_time = time.time_ns()
        while True:
            if timeout is not None and (time.time_ns() - start_time)/1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.instance_name}' from client '{self.identity}'")
            self.socket.send_multipart(self.craft_empty_request_with_message_type(HANDSHAKE))
            self.logger.info(f"sent Handshake to server '{self.instance_name}'")
            if self.poller.poll(500):
                try:
                    message = self.socket.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    pass 
                else:
                    if message[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:  
                        self.logger.info(f"client '{self.identity}' handshook with server '{self.instance_name}'")
                        self.server_type = message[SM_INDEX_SERVER_TYPE]
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with '{self.instance_name}'. Another message arrived before handshake complete.")
            else:
                self.logger.info('got no response')
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
    server_instance_name: str
        The instance name of the server (or ``Thing``)  
    identity: str
        Unique identity of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID.
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    protocol: str | Enum, TCP, IPC or INPROC, default IPC
        protocol implemented by the server
    **kwargs:
        socket_address: str
            socket address for connecting to TCP server
        zmq_serializer:
            custom implementation of ZMQ serializer if necessary
        http_serializer:
            custom implementation of JSON serializer if necessary
    """

    def __init__(self, server_instance_name : str, identity : str, client_type = HTTP_SERVER, 
                handshake : bool = True, protocol : str = "IPC", context : typing.Union[zmq.asyncio.Context, None] = None, 
                **kwargs) -> None:
        BaseZMQClient.__init__(self, server_instance_name=server_instance_name, client_type=client_type, **kwargs)
        BaseAsyncZMQ.__init__(self)
        self.create_socket(context=context, identity=identity, protocol=protocol, **kwargs)
        self.poller = zmq.asyncio.Poller()
        self.poller.register(self.socket, zmq.POLLIN)
        self._terminate_context = context == None
        self._handshake_event = asyncio.Event()
        self._handshake_event.clear()
        self._client_queue = asyncio.Lock()
        if handshake:
            self.handshake(kwargs.pop("handshake_timeout", 60000))
    
    def handshake(self, timeout : typing.Optional[int] = 60000) -> None:
        """
        automatically called when handshake argument at init is True. When not automatically called, it is necessary
        to call this method before awaiting ``handshake_complete()``.
        """
        run_callable_somehow(self._handshake(timeout))

    async def _handshake(self, timeout : typing.Union[float, int] = 60000) -> None:
        """
        hanshake with server before sending first message
        """
        if self._monitor_socket is not None and self._monitor_socket in self.poller:
            self.poller.unregister(self._monitor_socket)
        self._handshake_event.clear()
        start_time = time.time_ns()    
        while True:
            if timeout is not None and (time.time_ns() - start_time)/1e6 > timeout:
                raise ConnectionError(f"Unable to contact server '{self.instance_name}' from client '{self.identity}'")
            await self.socket.send_multipart(self.craft_empty_request_with_message_type(HANDSHAKE))
            self.logger.info(f"sent Handshake to server '{self.instance_name}'")
            if await self.poller.poll(500):
                try:
                    message = await self.socket.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    pass 
                else:
                    if message[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:  # type: ignore
                        self.logger.info(f"client '{self.identity}' handshook with server '{self.instance_name}'")
                        self.server_type = message[SM_INDEX_SERVER_TYPE]
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with '{self.instance_name}'. Another message arrived before handshake complete.")
            else:
                self.logger.info('got no response')
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN) 
        self._handshake_event.set()

    async def handshake_complete(self):
        """
        wait for handshake to complete
        """
        await self._handshake_event.wait()
       
    async def async_send_request(self, thing_id : bytes, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                    thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT) -> bytes:
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
        message id : bytes
            a byte representation of message id
        """
        message = self.craft_request_from_arguments(thing_id=thing_id, objekt=objekt, operation=operation, arguments=arguments,
                                    server_execution_context=server_execution_context, 
                                    thing_execution_context=thing_execution_context) 
        await self.socket.send_multipart(message)
        self.logger.debug(f"sent operation '{operation}' to server '{self.instance_name}' with msg-id '{message[SM_INDEX_MESSAGE_ID]}'")
        return message[SM_INDEX_MESSAGE_ID]
    
    async def async_recv_response(self, message_id : bytes, timeout : typing.Optional[int] = None, 
                        raise_client_side_exception : bool = False, 
                        deserialize_response : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]:
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
            sockets = await self.poller.poll(timeout)
            response = None
            for socket, _ in sockets:
                try:    
                    message = await socket.recv_multipart(zmq.NOBLOCK)
                    response = self.parse_server_message(message=message, raise_client_side_exception=raise_client_side_exception, 
                                                    deserialize_response=deserialize_response) # type: ignore
                except zmq.Again:
                    pass 
            if response:
                if message_id != response[SM_INDEX_MESSAGE_ID]:
                    self._response_cache[message_id] = response
                    continue 
                elif response[SM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
                    continue
                self.logger.debug(f"received response with message-id '{response[SM_INDEX_MESSAGE_ID]}'")
                return response
            if timeout is not None:
                break
            
    async def async_execute(self, thing_id : bytes, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context, 
                    thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT,
                    raise_client_side_exception = False, deserialize_response : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]: 
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
        message id : bytes
            a byte representation of message id
        """
        try:
            await asyncio.wait_for(self._client_queue.acquire(), 
                            timeout=server_execution_context.get("invokation_timeout", None))
        except TimeoutError:
            raise TimeoutError("previous request still in progress") from None
        try:
            msg_id = await self.async_send_request(thing_id=thing_id, objekt=objekt, operation=operation, arguments=arguments, 
                                            server_execution_context=server_execution_context, 
                                            thing_execution_context=thing_execution_context)
            return await self.async_recv_response(msg_id, raise_client_side_exception=raise_client_side_exception, 
                                            deserialize_response=deserialize_response)
        finally:
            self._client_queue.release()
   

        
class MessageMappedZMQClientPool(BaseZMQClient):
    """
    Pool of clients where message ID can track the replies irrespective of order of arrival. 

    Parameters
    ----------
    server_instance_names: List[str]
        list of instance names of servers to connect to
    identity: str
        Unique identity of the client to receive messages from the server. Each client connecting to same server must 
        still have unique ID.
    client_type: str
        ZMQ or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    poll_timeout: int
        socket polling timeout in milliseconds greater than 0.
    protocol: str
        protocol implemented by ZMQ server
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

    def __init__(self, server_instance_names: typing.List[str], identity: str, client_type = HTTP_SERVER,
                handshake : bool = True, poll_timeout = 25, protocol : str = 'IPC',  
                context : zmq.asyncio.Context = None, deserialize_server_messages : bool= True, 
                **kwargs) -> None:
        super().__init__(server_instance_name='pool', client_type=client_type, **kwargs)
        self.identity = identity 
        self.logger = kwargs.get('logger', get_default_logger('{}|{}'.format(identity, 'pooled'), logging.INFO))
        # this class does not call create_socket method
        self.context = context or zmq.asyncio.Context()
        self.pool = dict() # type: typing.Dict[str, AsyncZMQClient]
        self.poller = zmq.asyncio.Poller()
        for instance_name in server_instance_names:
            client = AsyncZMQClient(server_instance_name=instance_name,
                identity=identity, client_type=client_type, handshake=handshake, protocol=protocol, 
                context=self.context, zmq_serializer=self.zmq_serializer, http_serializer=self.http_serializer,
                logger=self.logger)
            client._monitor_socket = client.socket.get_monitor_socket()
            self.poller.register(client._monitor_socket, zmq.POLLIN)
            self.pool[instance_name] = client
        # Both the client pool as well as the individual client get their serializers and client_types
        # This is required to implement pool level sending and receiving messages like polling of pool of sockets
        self.event_pool = AsyncioEventPool(len(server_instance_names))
        self.events_map = dict() # type: typing.Dict[bytes, asyncio.Event]
        self.message_map = dict()
        self.cancelled_messages = []
        self.poll_timeout = poll_timeout
        self.stop_poll = False 
        self._deserialize_server_messages = deserialize_server_messages

    def create_new(self, server_instance_name : str, protocol : str = 'IPC') -> None:
        """
        Create new server with specified protocol. other arguments are taken from pool specifications. 
        
        Parameters
        ----------
        instance_name: str
            instance name of server 
        protocol: str
            protocol implemented by ZMQ server
        """
        if server_instance_name not in self.pool.keys():
            client = AsyncZMQClient(server_instance_name=server_instance_name,
                identity=self.identity, client_type=self.client_type, handshake=True, protocol=protocol, 
                context=self.context, zmq_serializer=self.zmq_serializer, http_serializer=self.http_serializer,
                logger=self.logger)
            client._monitor_socket = client.socket.get_monitor_socket()
            self.poller.register(client._monitor_socket, zmq.POLLIN)
            self.pool[server_instance_name] = client
        else: 
            raise ValueError(f"client for instance name '{server_instance_name}' already present in pool")


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
                        response = self.parse_server_message(await socket.recv_multipart(zmq.NOBLOCK),
                                                    raise_client_side_exception=False,
                                                    deserialize_response=self._deserialize_server_messages)
                        if not response:
                            continue
                    except zmq.Again:
                        # errors in handle_message should reach the client. 
                        break
                    except ConnectionAbortedError:
                        for client in self.pool.values():
                            if client.socket.get_monitor_socket() == socket:
                                self.poller.unregister(client.socket) # leave the monitor in the pool
                                client.handshake(timeout=None)
                                self.logger.error(f"{client.instance_name} disconnected." +
                                    " Unregistering from poller temporarily until server comes back.")
                                break
                    else:
                        address, _, server_type, message_type, message_id, data, encoded_data = response
                        if message_type == HANDSHAKE:
                            continue
                        self.logger.debug(f"received response from server '{address}' with msg-ID '{message_id}'")
                        if message_id in self.cancelled_messages:
                            self.cancelled_messages.remove(message_id)
                            self.logger.debug(f"msg-ID '{message_id}' cancelled")
                            continue
                        event = self.events_map.get(message_id, None) 
                        if len(encoded_data) > 0 and data:
                            final_data = (data, encoded_data)
                        elif len(encoded_data) > 0:
                            final_data = encoded_data
                        else:
                            final_data = data
                        if event:
                            event.set()
                        else:    
                            invalid_event_task = asyncio.create_task(self._resolve_response(message_id, final_data))
                            event_loop.call_soon(lambda: invalid_event_task)


    async def _resolve_response(self, message_id : bytes, data : typing.Any) -> None:
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

    def assert_client_ready(self, client : AsyncZMQClient):
        if not client._handshake_event.is_set():
            raise ConnectionAbortedError(f"{client.instance_name} is currently not alive")
        if not client.socket in self.poller._map:
            raise ConnectionError("handshake complete, server is alive but client socket not yet ready to be polled." +
                                "Application using MessageMappedClientPool should register the socket manually for polling." +
                                "If using hololinked.server.HTTPServer, socket is waiting until HTTP Server updates its "
                                "routing logic as the server has just now come alive, please try again soon.")

    async def async_send_request(self, instance_name : str, thing_id : bytes, objekt : str, operation : str,
                arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT) -> bytes:
        """
        Send operation to server with instance name. Replies are automatically polled & to be retrieved using 
        ``async_recv_response()``

        Parameters
        ----------
        instance_name: str
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
        self.assert_client_ready(self.pool[instance_name])
        message_id = await self.pool[instance_name].async_send_request(thing_id=thing_id, operation=operation, 
                        objekt=objekt, arguments=arguments, 
                        server_execution_context=server_execution_context, thing_execution_context=thing_execution_context)
        event = self.event_pool.pop()
        self.events_map[message_id] = event 
        return message_id

    async def async_recv_response(self, instance_name : str, message_id : bytes, raise_client_side_exception = False,
                        timeout : typing.Optional[float] = None) -> typing.Dict[str, typing.Any]:
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
                await asyncio.wait_for(event.wait(), timeout if (timeout and timeout > 0) else 5) 
                # default 5 seconds because we want to check if server is also dead
                if event.is_set():
                    break
                self.assert_client_ready(self.pool[instance_name])
            except TimeoutError:
                if timeout is None:
                    continue
                self.cancelled_messages.append(message_id)
                self.logger.debug(f'message_id {message_id} added to list of cancelled messages')
                raise TimeoutError(f"Execution not completed within {timeout} seconds") from None
        self.events_map.pop(message_id)
        self.event_pool.completed(event)
        response = self.message_map.pop(message_id)
        if raise_client_side_exception and response.get('exception', None) is not None:
            self.raise_local_exception(response['exception'])
        return response

    async def async_execute(self, instance_name : str, thing_id : bytes, objekt : str, operation : str, 
                arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT, raise_client_side_exception = False, 
            ) -> typing.Dict[str, typing.Any]:
        """
        sends message and receives response.

        Parameters
        ----------
        instance_name: str
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
        message_id = await self.async_send_request(instance_name=instance_name, thing_id=thing_id, objekt=objekt, operation=operation,
                                                    arguments=arguments, server_execution_context=server_execution_context,
                                                    thing_execution_context=thing_execution_context)
        return await self.async_recv_response(instance_name=instance_name, message_id=message_id, 
                                                raise_client_side_exception=raise_client_side_exception, timeout=None)

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

    async def async_execute_in_all(self, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        instance_names : typing.Optional[typing.List[str]] = None,
                        server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                        thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT,
                    ) -> typing.Dict[str, typing.Any]:
        """
        execute a specified operation in all Thing including eventloops
        """
        if not instance_names:
            instance_names = self.pool.keys()
        gathered_replies = await asyncio.gather(*[
            self.async_execute(instance_name=instance_name, objekt=objekt, operation=operation, arguments=arguments, 
                            raise_client_side_exception=False, server_execution_context=server_execution_context,
                            thing_execution_context=thing_execution_context
                        ) 
                for instance_name in instance_names])
        replies = dict()
        for instance_name, response in zip(instance_names, gathered_replies):
            replies[instance_name] = response
        return replies  
    
    async def async_execute_in_all_things(self, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                        thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT,                   
                    ) -> typing.Dict[str, typing.Any]:
        """
        execute the same operation in all Things, eventloops are excluded. 
        """
        return await self.async_execute_in_all(objekt=objekt, operation=operation, arguments=arguments,
                        instance_names=[instance_name for instance_name, client in self.pool.items() if client.server_type == ServerTypes.THING],
                        server_execution_context=server_execution_context,
                        thing_execution_context=thing_execution_context)
    
    async def async_execute_in_all_eventloops(self, objekt : str, operation : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        server_execution_context : typing.Dict[str, typing.Any] = default_server_execution_context,
                        thing_execution_context : typing.Dict[str, typing.Any] = EMPTY_DICT,                          
                    ) -> typing.Dict[str, typing.Any]: # raise_client_side_exception = False
        """
        execute the same operation in all eventloops.
        """
        return await self.async_execute_in_all(objekt=objekt, operation=operation, arguments=arguments, 
                        instance_names=[instance_name for instance_name, client in self.pool.items() if client.server_type == ServerTypes.EVENTLOOP],
                        server_execution_context=server_execution_context, 
                        thing_execution_context=thing_execution_context   
                    )

    async def ping_all_servers(self):
        """
        ping all servers connected to the client pool, calls ping() on Thing
        """
        return await self.async_execute_in_all(operation='invokeAction', objekt=CommonRPC.PING)
        
    def __contains__(self, name : str) -> bool:
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
                            "'{}'. Exception message : {}".format(self.identity, str(ex)))

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

    def __init__(self, initial_number_of_events : int) -> None:
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

    def completed(self, event : asyncio.Event) -> None:
        """
        put an event back into the pool
        """
        self.pool.append(event)



class EventPublisher(BaseZMQServer, BaseSyncZMQ):

    def __init__(self, instance_name : str, protocol : str, 
                    context : typing.Union[zmq.Context, None] = None, **kwargs) -> None:
        super().__init__(instance_name=instance_name, server_type=ServerTypes.THING.value, 
                            **kwargs)
        self.create_socket(identity=f'{instance_name}/event-publisher', bind=True, context=context,
                           protocol=protocol, socket_type=zmq.PUB, **kwargs)
        self.logger.info(f"created event publishing socket at {self.socket_address}")
        self.events = set() # type: typing.Set[EventDispatcher] 
        self.event_ids = set() # type: typing.Set[bytes]

    def register(self, event : "EventDispatcher") -> None:
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
        if isinstance(self.zmq_serializer, JSONSerializer):
            event._unique_zmq_identifier = event._unique_identifier
            event._unique_http_identifier = event._unique_identifier  
        else:
            event._unique_zmq_identifier = event._unique_identifier + b'-zmq'
            event._unique_http_identifier = event._unique_identifier + b'-http' 
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
               
    def publish(self, event : "EventDispatcher", data : typing.Any, *, zmq_clients : bool = True, 
                        http_clients : bool = True, serialize : bool = True) -> None: 
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
        zmq_clients: bool, default True
            pushes event to ZMQ clients
        http_clients: bool, default True
            pushed event to HTTP clients
        """
        if event._unique_identifier in self.event_ids:
            if serialize:
                if isinstance(self.zmq_serializer , JSONSerializer):
                    self.socket.send_multipart([event._unique_identifier, self.http_serializer.dumps(data)])
                    return
                if zmq_clients:
                    # TODO - event id should not any longer be unique
                    self.socket.send_multipart([b'zmq-' + unique_identifier, self.zmq_serializer.dumps(data)])
                if http_clients:
                    self.socket.send_multipart([unique_identifier, self.http_serializer.dumps(data)])
            elif not isinstance(self.zmq_serializer , JSONSerializer):
                if zmq_clients:
                    self.socket.send_multipart([b'zmq-' + unique_identifier, data])
                if http_clients:
                    self.socket.send_multipart([unique_identifier, data])
            else: 
                self.socket.send_multipart([unique_identifier, data])
        else:
            raise AttributeError("event name {} not yet registered with socket {}".format(event._unique_identifier, self.socket_address))
        
    def exit(self):
        if not hasattr(self, 'logger'):
            self.logger = get_default_logger('{}|{}'.format(self.__class__.__name__, uuid4()))
        try:
            self.socket.close(0)
            self.logger.info("terminated event publishing socket with address '{}'".format(self.socket_address))
        except Exception as E:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context at address '{}'. Exception message : {}".format(
                self.socket_address, str(E)))
        try:
            self.context.term()
            self.logger.info("terminated context of event publishing socket with address '{}'".format(self.socket_address)) 
        except Exception as E: 
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated socket of event publishing socket at address '{}'. Exception message : {}".format(
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
        protocol: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_instance_name: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier : str, socket_address : str, 
                    identity : str, client_type = b'HTTP_SERVER', **kwargs) -> None:
        self._terminate_context : bool 
        protocol = socket_address.split('://', 1)[0].upper()
        super().__init__(server_instance_name=kwargs.get('server_instance_name', None), 
                    client_type=client_type, **kwargs)
        self.create_socket(identity=identity, bind=False, context=self.context,
                        socket_address=socket_address, socket_type=zmq.SUB, protocol=protocol, **kwargs)
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
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated socket of event consuming socket at address '{}'. Exception message : {}".format(
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
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated context at address '{}'. Exception message : {}".format(
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
        protocol: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_instance_name: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier : str, socket_address : str, identity : str, client_type = b'HTTP_SERVER', 
                    context : typing.Optional[zmq.asyncio.Context] = None, **kwargs) -> None:
        self._terminate_context = context == None
        self.context = context or zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        super().__init__(unique_identifier=unique_identifier, socket_address=socket_address, 
                        identity=identity, client_type=client_type, **kwargs)
        
    async def receive(self, timeout : typing.Optional[float] = None, deserialize = True) -> typing.Union[bytes, typing.Any]:
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
                _, contents = await socket.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                pass     
        if not deserialize or not contents: 
            return contents
        if self.client_type == HTTP_SERVER:
            return self.http_serializer.loads(contents)
        elif self.client_type == PROXY:
            return self.zmq_serializer.loads(contents)
        else:
            raise ValueError("invalid client type")

    async def interrupt(self):
        """
        interrupts the event consumer and returns a 'INTERRUPT' string from the receive() method, 
        generally should be used for exiting this object
        """
        if self.client_type == HTTP_SERVER:
            message = [self.http_serializer.dumps(f'{self.identity}/interrupting-server'), 
                       self.http_serializer.dumps("INTERRUPT")]
        elif self.client_type == PROXY:
            message = [self.zmq_serializer.dumps(f'{self.identity}/interrupting-server'), 
                       self.zmq_serializer.dumps("INTERRUPT")]
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
        protocol: str 
            TCP, IPC or INPROC
        http_serializer: JSONSerializer
            json serializer instance for HTTP_SERVER client type
        zmq_serializer: BaseSerializer
            serializer for ZMQ clients
        server_instance_name: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier : str, socket_address : str, identity : str, client_type = b'HTTP_SERVER', 
                    context : typing.Optional[zmq.Context] = None, **kwargs) -> None:
        self._terminate_context = context == None
        self.context = context or zmq.Context()
        self.poller = zmq.Poller()
        super().__init__(unique_identifier=unique_identifier, socket_address=socket_address,
                        identity=identity, client_type=client_type, **kwargs)
        
    def receive(self, timeout : typing.Optional[float] = None, deserialize = True) -> typing.Union[bytes, typing.Any]:
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
                _, contents = socket.recv_multipart(zmq.NOBLOCK) 
            except zmq.Again:
                pass
        if not deserialize: 
            return contents
        if self.client_type == HTTP_SERVER:
            return self.http_serializer.loads(contents)
        elif self.client_type == PROXY:
            return self.zmq_serializer.loads(contents)
        else:
            raise ValueError("invalid client type for event")
        
    def interrupt(self):
        """
        interrupts the event consumer and returns a 'INTERRUPT' string from the receive() method, 
        generally should be used for exiting this object
        """
        if self.client_type == HTTP_SERVER:
            message = [self.http_serializer.dumps(f'{self.identity}/interrupting-server'), 
                       self.http_serializer.dumps("INTERRUPT")]
        elif self.client_type == PROXY:
            message = [self.zmq_serializer.dumps(f'{self.identity}/interrupting-server'), 
                       self.zmq_serializer.dumps("INTERRUPT")]
        self.interrupting_peer.send_multipart(message)
    
        

from .events import EventDispatcher


__all__ = [
    AsyncZMQServer.__name__, 
    ZMQServerPool.__name__, 
    SyncZMQClient.__name__, 
    AsyncZMQClient.__name__, 
    MessageMappedZMQClientPool.__name__, 
    AsyncEventConsumer.__name__, 
    EventConsumer.__name__
]