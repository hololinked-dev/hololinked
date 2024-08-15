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
from collections import deque
from enum import Enum
from zmq.utils.monitor import parse_monitor_message

from .utils import *
from .config import global_config
from .constants import JSON, ZMQ_PROTOCOLS, CommonRPC, ServerTypes, ZMQSocketType, ZMQ_EVENT_MAP
from .serializers import BaseSerializer, JSONSerializer, _get_serializer_from_user_given_options



# message types
HANDSHAKE   = b'HANDSHAKE'
INVALID_MESSAGE = b'INVALID_MESSAGE'
TIMEOUT = b'TIMEOUT'
INSTRUCTION = b'INSTRUCTION'
REPLY       = b'REPLY'
EXCEPTION   = b'EXCEPTION'
INTERRUPT   = b'INTERRUPT'
ONEWAY      = b'ONEWAY'
SERVER_DISCONNECTED = 'EVENT_DISCONNECTED'
EXIT = b'EXIT'

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
[address, bytes(), client type, message type, message id, timeout, instruction, arguments, execution_context] |br|
[ 0     ,   1    ,     2      ,      3      ,   4   ,   5        ,    6       ,     7    ,        8         ] |br|

[address, bytes(), server_type, message_type, message id, data]|br|
[   0   ,   1    ,    2       ,      3      ,      4    ,  5  ]|br|
"""
# CM = Client Message
CM_INDEX_ADDRESS = 0
CM_INDEX_CLIENT_TYPE = 2
CM_INDEX_MESSAGE_TYPE = 3
CM_INDEX_MESSAGE_ID = 4
CM_INDEX_TIMEOUT = 5
CM_INDEX_INSTRUCTION = 6
CM_INDEX_ARGUMENTS = 7
CM_INDEX_EXECUTION_CONTEXT = 8

# SM = Server Message
SM_INDEX_ADDRESS = 0
SM_INDEX_SERVER_TYPE = 2
SM_INDEX_MESSAGE_TYPE = 3
SM_INDEX_MESSAGE_ID = 4
SM_INDEX_DATA = 5

# Server types - currently useless metadata

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
    for RPC clients, any of the allowed serializer is possible.

    Parameters
    ----------
    instance_name: str
        instance name of the serving ``Thing``
    server_type: Enum
        metadata about the nature of the server
    http_serializer: hololinked.server.serializers.JSONSerializer
        serializer used to send message to HTTP Server
    zmq_serializer: any of hololinked.server.serializers.serializer, default serpent
        serializer used to send message to RPC clients
    logger: logging.Logger, Optional
        logger, on will be created while creating a socket automatically if None supplied 
    """
    # init of this class must always take empty arguments due to inheritance structure
    def __init__(self) -> None:
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
            especially useful for clients to have a different ID other than the ``instance_name`` of the ``Thing``.
            For servers, supplying the ``instance_name`` is sufficient.
        bind: bool
            whether to bind (server) or connect (client)
        context: zmq.Context or zmq.asyncio.Context
            ZeroMQ Context object that creates the socket
        protocol: Enum
            TCP, IPC or INPROC. Message crafting/passing/routing is protocol invariant as suggested by ZeroMQ docs.
        socket_type: zmq.SocketType, default zmq.ROUTER
            Usually a ROUTER socket is implemented for both client-server and peer-to-peer communication
        **kwargs: dict
            socket_address: str
                applicable only for TCP socket to find the correct socket to connect. 
            log_level: int
                logging.Logger log level

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
            self.logger = get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, 
                                                socket_type, protocol, identity), kwargs.get('log_level', logging.INFO))
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
        Overloads ``create_socket()`` to create, bind/connect a synchronous socket. A (synchronous) context is created 
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
    Implements messaging contract as suggested by ZMQ, this is defined as 
    as follows: 
    
    client's message to server: 
    ::
        [address, bytes(), client type, message type, messsage id, 
        [   0   ,   1    ,     2      ,      3      ,      4     , 
        
        timeout, instruction, arguments, execution context] 
          5    ,      6     ,     7    ,       8          ]
        
    server's message to client: 
    ::
        [address, bytes(), server_type, message_type, message id, data, encoded_data]
        [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ,       6     ]

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
        super().__init__()
        self.zmq_serializer, self.http_serializer = _get_serializer_from_user_given_options(
                                                            zmq_serializer=zmq_serializer,
                                                            http_serializer=http_serializer
                                                        )
        self.instance_name = instance_name 
        self.server_type = server_type if isinstance(server_type, bytes) else bytes(server_type, encoding='utf-8') 
        self.logger = logger


    def parse_client_message(self, message : typing.List[bytes]) -> typing.List[typing.Union[bytes, typing.Any]]:
        """
        deserializes important parts of the client's message, namely instruction, arguments, execution context 
        based on the client type. For handshake messages, automatically handles handshake. In case of exceptions while 
        deserializing, automatically sends an invalid message to client informing the nature of exception with the 
        exception metadata. 
        
        client's message to server:
        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
            
            timeout, instruction, arguments, execution context] 
               5   ,      6     ,     7    ,       8          ]

        Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "oneway" - does not reply to client after executing the instruction 
            - "fetch_execution_logs" - fetches logs that were accumulated while execution

        Parameters
        ----------
        message: List[bytes]
            message received from client
      
        Returns
        -------
        message: List[bytes | Any]
            message with instruction, arguments and execution context deserialized

        """
        try:
            message_type = message[CM_INDEX_MESSAGE_TYPE]
            if message_type == INSTRUCTION:
                client_type = message[CM_INDEX_CLIENT_TYPE]
                if client_type == PROXY:
                    message[CM_INDEX_INSTRUCTION] = self.zmq_serializer.loads(message[CM_INDEX_INSTRUCTION]) # type: ignore
                    message[CM_INDEX_ARGUMENTS] = self.zmq_serializer.loads(message[CM_INDEX_ARGUMENTS]) # type: ignore
                    message[CM_INDEX_EXECUTION_CONTEXT] = self.zmq_serializer.loads(message[CM_INDEX_EXECUTION_CONTEXT]) # type: ignore
                elif client_type == HTTP_SERVER:
                    message[CM_INDEX_INSTRUCTION] = self.http_serializer.loads(message[CM_INDEX_INSTRUCTION]) # type: ignore
                    message[CM_INDEX_ARGUMENTS] = self.http_serializer.loads(message[CM_INDEX_ARGUMENTS]) # type: ignore
                    message[CM_INDEX_EXECUTION_CONTEXT] = self.http_serializer.loads(message[CM_INDEX_EXECUTION_CONTEXT]) # type: ignore
                return message 
            elif message_type == HANDSHAKE:
                self.handshake(message)
        except Exception as ex:
            self.handle_invalid_message(message, ex)


    def craft_reply_from_arguments(self, address : bytes, client_type: bytes, message_type : bytes, 
                            message_id : bytes = b'', data : typing.Any = None, 
                            pre_encoded_data : typing.Optional[bytes] = EMPTY_BYTE) -> typing.List[bytes]:
        """
        call this method to craft an arbitrary reply or message to the client using the method arguments. 

        server's message to client:
        ::
            [address, bytes(), server_type, message_type, message id, data]
            [   0   ,   1    ,    2       ,      3      ,  4        ,  5  ]

        Parameters
        ----------
        address: bytes 
            the ROUTER address of the client
        message_type: bytes 
            type of the message, possible values are b'REPLY', b'HANDSHAKE' and b'TIMEOUT' 
        message_id: bytes
            message id of the original client message for which the reply is being crafted
        data: Any
            serializable data
        
        Returns
        -------
        message: List[bytes]
            the crafted reply with information in the correct positions within the list
        """
        if client_type == HTTP_SERVER:
            data = self.http_serializer.dumps(data)
        elif client_type == PROXY:
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
           

    def craft_reply_from_client_message(self, original_client_message : typing.List[bytes], data : typing.Any = None,
                                            pre_encoded_data : bytes = EMPTY_BYTE) -> typing.List[bytes]:
        """
        craft a reply with certain data automatically from an originating client message. The client's address, type required
        for serialization requirements, message id etc. are automatically created from the original message.         

        server's message to client:
        ::
            [address, bytes(), server_type, message_type, message id, data]
            [   0   ,   1    ,    2       ,      3      ,      4    ,  5  ]

        Parameters
        ----------
        original_client_message: List[bytes]
            The message originated by the clieht for which the reply is being crafted
        data: Any
            serializable data 

        Returns
        -------
        message: List[bytes]
            the crafted reply with information in the correct positions within the list
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
        pass a handshake message to client. Absolutely mandatory to ensure initial messages do not get lost 
        because of ZMQ's very tiny but significant initial delay after creating socket.

        Parameters
        ----------
        address: bytes
            the address of the client to send the handshake

        Returns
        -------
        None 
        """
        run_callable_somehow(self._handshake(original_client_message))

    def _handshake(self, original_client_message : typing.List[bytes]) -> None:
        raise NotImplementedError(f"handshake cannot be handled - implement _handshake in {self.__class__} to handshake.")


    def handle_invalid_message(self, original_client_message : typing.List[bytes], exception : Exception) -> None:
        """
        pass an invalid message to the client when an exception occurred while parsing the message from the client 
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
        pass timeout message to the client when the instruction could not be executed within specified timeout

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
        Inner method that handles handshake. scheduled by ``handshake()`` method, signature same as ``handshake()``.
        """
        await self.socket.send_multipart(self.craft_reply_from_arguments(original_client_message[CM_INDEX_ADDRESS], 
                original_client_message[CM_INDEX_CLIENT_TYPE], HANDSHAKE, original_client_message[CM_INDEX_MESSAGE_ID],
                EMPTY_BYTE))
        self.logger.info(f"sent handshake to client '{original_client_message[CM_INDEX_ADDRESS]}'")


    async def _handle_timeout(self, original_client_message : typing.List[bytes]) -> None:
        """
        Inner method that handles timeout. scheduled by ``handle_timeout()``, signature same as ``handle_timeout``.
        """
        await self.socket.send_multipart(self.craft_reply_from_arguments(original_client_message[CM_INDEX_ADDRESS], 
                original_client_message[CM_INDEX_CLIENT_TYPE], TIMEOUT, original_client_message[CM_INDEX_MESSAGE_ID]))
        self.logger.info(f"sent timeout to client '{original_client_message[CM_INDEX_ADDRESS]}'")

    
    async def _handle_invalid_message(self, original_client_message : typing.List[bytes], exception : Exception) -> None:
        """
        Inner method that handles invalid messages. scheduled by ``handle_invalid_message()``, 
        signature same as ``handle_invalid_message()``.
        """
        await self.socket.send_multipart(self.craft_reply_from_arguments(original_client_message[CM_INDEX_ADDRESS], 
                                            original_client_message[CM_INDEX_CLIENT_TYPE], INVALID_MESSAGE, 
                                            original_client_message[CM_INDEX_MESSAGE_ID]), exception)         
        self.logger.info(f"sent exception message to client '{original_client_message[CM_INDEX_ADDRESS]}'." +
                            f" exception - {str(exception)}") 	


       
class AsyncZMQServer(BaseAsyncZMQServer, BaseAsyncZMQ):
    """
    Implements blocking (non-polled) but async receive instructions and send replies.  
    """

    def __init__(self, *, instance_name : str, server_type : Enum, context : typing.Union[zmq.asyncio.Context, None] = None, 
                protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        BaseAsyncZMQServer.__init__(self, instance_name=instance_name, server_type=server_type, **kwargs)
        BaseAsyncZMQ.__init__(self)
        self.create_socket(identity=instance_name, bind=True, context=context, protocol=protocol, 
                        socket_type=socket_type, **kwargs) 
        self._terminate_context = context == None # terminate if it was created by instance


    async def async_recv_instruction(self) -> typing.Any:
        """
        Receive one instruction in a blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``.   

        Returns
        -------
        instruction: List[bytes | Any]
            received instruction with important content (instruction, arguments, execution context) deserialized. 
        """
        while True:
            instruction = self.parse_client_message(await self.socket.recv_multipart())
            if instruction:
                self.logger.debug(f"received instruction from client '{instruction[CM_INDEX_ADDRESS]}' with msg-ID {instruction[CM_INDEX_MESSAGE_ID]}")
                return instruction
        

    async def async_recv_instructions(self) -> typing.List[typing.Any]:
        """
        Receive all currently available instructions in blocking form. Async for multi-server paradigm, each server should schedule
        this method in the event loop explicitly. This is taken care by the ``Eventloop`` & ``RPCServer``. 

        Returns
        -------
        instructions: List[List[bytes | Any]]
            list of received instructions with important content (instruction, arguments, execution context) deserialized.
        """
        instructions = [await self.async_recv_instruction()]
        while True:
            try:
                instruction = self.parse_client_message(await self.socket.recv_multipart(zmq.NOBLOCK))
                if instruction:
                    self.logger.debug(f"received instruction from client '{instruction[CM_INDEX_ADDRESS]}' with msg-ID {instruction[CM_INDEX_MESSAGE_ID]}")
                    instructions.append(instruction)
            except zmq.Again: 
                break 
        return instructions
    

    async def async_send_reply(self, original_client_message : typing.List[bytes], data : typing.Any) -> None:
        """
        Send reply for an instruction. 

        Parameters
        ----------
        original_client_message: List[bytes]
            original message so that the reply can be properly crafted and routed
        data: Any
            serializable data to be sent as reply

        Returns
        -------
        None
        """
        await self.socket.send_multipart(self.craft_reply_from_client_message(original_client_message, data))
        self.logger.debug(f"sent reply to client '{original_client_message[CM_INDEX_ADDRESS]}' with msg-ID {original_client_message[CM_INDEX_MESSAGE_ID]}")
        
    
    async def async_send_reply_with_message_type(self, original_client_message : typing.List[bytes], 
                                                message_type: bytes, data : typing.Any) -> None:
        """
        Send reply for an instruction. 

        Parameters
        ----------
        original_client_message: List[bytes]
            original message so that the reply can be properly crafted and routed
        data: Any
            serializable data to be sent as reply

        Returns
        -------
        None
        """
        await self.socket.send_multipart(self.craft_reply_from_arguments(original_client_message[CM_INDEX_ADDRESS], 
                                                        original_client_message[CM_INDEX_CLIENT_TYPE], message_type, 
                                                        original_client_message[CM_INDEX_MESSAGE_ID], data))
        self.logger.debug(f"sent reply to client '{original_client_message[CM_INDEX_ADDRESS]}' with msg-ID {original_client_message[CM_INDEX_MESSAGE_ID]}")
        

    def exit(self) -> None:
        """
        closes socket and context, warns if any error occurs. 
        """
        super().exit()
        try:
            self.socket.close(0)
            self.logger.info(f"terminated socket of server '{self.identity}' of type {self.__class__}")
        except Exception as ex:
            self.logger.warning("could not properly terminate socket or attempted to terminate an already terminated " +
                            f" socket '{self.identity}' of type {self.__class__}. Exception message : {str(ex)}")
        try:
            if self._terminate_context:
                self.context.term()
                self.logger.info("terminated context of socket '{}' of type '{}'".format(self.identity, self.__class__))
        except Exception as ex:
            self.logger.warning("could not properly terminate context or attempted to terminate an already terminated " +
                            f" context '{self.identity}'. Exception message : {str(ex)}")

    

class AsyncPollingZMQServer(AsyncZMQServer):
    """
    Identical to AsyncZMQServer, except that instructions are received in non-blocking/polling form. 
    This server can be stopped from server side by calling ``stop_polling()`` unlike ``AsyncZMQServer`` which 
    cannot be stopped manually unless an instruction arrives.

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
            serializer used to send message to RPC clients
    """

    def __init__(self, *, instance_name : str, server_type : Enum, context : typing.Union[zmq.asyncio.Context, None] = None, 
                socket_type : zmq.SocketType = zmq.ROUTER, protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, 
                poll_timeout = 25, **kwargs) -> None:
        super().__init__(instance_name=instance_name, server_type=server_type, context=context, 
                        socket_type=socket_type, protocol=protocol, **kwargs)
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

    async def poll_instructions(self) -> typing.List[typing.List[bytes]]:
        """
        poll for instructions with specified timeout (``poll_timeout``) and return if any instructions are available.
        This method blocks, so make sure other methods are scheduled which can stop polling. 

        Returns
        -------
        instructions: List[List[bytes]]
            list of received instructions with important content (instruction, arguments, execution context) deserialized.
        """
        self.stop_poll = False
        instructions = []
        while not self.stop_poll:
            sockets = await self.poller.poll(self._poll_timeout) # type hints dont work in this line
            for socket, _ in sockets:
                while True:
                    try:
                        instruction = self.parse_client_message(await socket.recv_multipart(zmq.NOBLOCK))
                    except zmq.Again:
                        break
                    else:
                        if instruction:
                            self.logger.debug(f"received instruction from client '{instruction[CM_INDEX_ADDRESS]}' with msg-ID {instruction[CM_INDEX_MESSAGE_ID]}")
                            instructions.append(instruction)
            if len(instructions) > 0:
                break
        return instructions

    def stop_polling(self) -> None:
        """
        stop polling and unblock ``poll_instructions()`` method
        """
        self.stop_poll = True 

    def exit(self) -> None:
        """
        unregister socket from poller and terminate socket and context.
        """
        try:
            BaseZMQ.exit(self)
            self.poller.unregister(self.socket)
        except Exception as ex:
            self.logger.warning(f"could not unregister socket {self.identity} from polling - {str(ex)}")
        return super().exit()
        


class ZMQServerPool(BaseZMQServer):
    """
    Implements pool of async ZMQ servers (& their sockets)
    """

    def __init__(self, *, instance_names : typing.Union[typing.List[str], None] = None, **kwargs) -> None:
        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.pool = dict() # type: typing.Dict[str, typing.Union[AsyncZMQServer, AsyncPollingZMQServer]]
        if instance_names:
            for instance_name in instance_names:
                self.pool[instance_name] = AsyncZMQServer(instance_name=instance_name, 
                                    server_type=ServerTypes.UNKNOWN_TYPE.value, context=self.context, **kwargs)
            for server in self.pool.values():
                self.poller.register(server.socket, zmq.POLLIN)
        super().__init__(instance_name="pool", server_type=ServerTypes.POOL.value, **kwargs)
        self.identity = "pool"
        if self.logger is None:
            self.logger = get_default_logger("pool|polling", kwargs.get('log_level',logging.INFO))

    def create_socket(self, *, identity : str, bind: bool, context : typing.Union[zmq.asyncio.Context, zmq.Context], 
                protocol : ZMQ_PROTOCOLS = ZMQ_PROTOCOLS.IPC, socket_type : zmq.SocketType = zmq.ROUTER, **kwargs) -> None:
        raise NotImplementedError("create socket not supported by ZMQServerPool")
        # we override this method to prevent socket creation. instance_name set to pool is simply a filler 
        return super().create_socket(identity=identity, bind=bind, context=context, protocol=protocol, 
                                    socket_type=socket_type, **kwargs)

    def register_server(self, server : typing.Union[AsyncZMQServer, AsyncPollingZMQServer]) -> None:
        if not isinstance(server, (AsyncZMQServer, AsyncPollingZMQServer)):
            raise TypeError("registration possible for servers only subclass of AsyncZMQServer or AsyncPollingZMQServer." +
                           f" Given type {type(server)}")
        self.pool[server.instance_name] = server 
        self.poller.register(server.socket, zmq.POLLIN)

    def deregister_server(self, server : typing.Union[AsyncZMQServer, AsyncPollingZMQServer]) -> None:
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

    async def async_recv_instruction(self, instance_name : str) -> typing.List:
        """
        receive instruction for instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ``Thing`` or in this case, the ZMQ server. 
        """
        return await self.pool[instance_name].async_recv_instruction()
     
    async def async_recv_instructions(self, instance_name : str) -> typing.List[typing.List]:
        """
        receive all available instructions for instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ``Thing`` or in this case, the ZMQ server. 
        """
        return await self.pool[instance_name].async_recv_instructions()
   
    async def async_send_reply(self, *, instance_name : str, original_client_message : typing.List[bytes],  
                               data : typing.Any) -> None:
        """
        send reply for instance name

        Parameters
        ----------
        instance_name : str
            instance name of the ``Thing`` or in this case, the ZMQ server. 
        original_client_message: List[bytes]
            instruction for which reply is being given
        data: Any
            data to be given as reply
        """
        await self.pool[instance_name].async_send_reply(original_client_message, data)
    
    async def poll(self) -> typing.List[typing.List[typing.Any]]:
        """
        Pool for instruction in the entire server pool. Map the instruction to the correct instance 
        using the 0th index of the instruction.  
        """
        self.stop_poll = False
        instructions = []
        while not self.stop_poll:
            sockets = await self.poller.poll(self._poll_timeout) 
            for socket, _ in sockets:
                while True:
                    try:
                        instruction = self.parse_client_message(await socket.recv_multipart(zmq.NOBLOCK))
                    except zmq.Again:
                        break
                    else:
                        if instruction:
                            self.logger.debug(f"received instruction from client '{instruction[CM_INDEX_ADDRESS]}' with msg-ID {instruction[CM_INDEX_MESSAGE_ID]}")
                            instructions.append(instruction)
        return instructions
        
    def stop_polling(self) -> None:
        """
        stop polling method ``poll()``
        """
        self.stop_poll = True 

    def __getitem__(self, key) -> typing.Union[AsyncZMQServer, AsyncPollingZMQServer]:
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

    
    
class RPCServer(BaseZMQServer):
    """
    Top level ZMQ RPC server used by ``Thing`` and ``Eventloop``. 

    Parameters
    ----------
    instance_name: str
        ``instance_name`` of the Thing which the server serves
    server_type: str
        server type metadata - currently not useful/important
    context: Optional, zmq.asyncio.Context
        ZeroMQ Context object to use. All sockets share this context. Automatically created when None is supplied.
    protocols: List[str, Enum], default [ZMQ_PROTOCOLS.TCP, ZMQ_PROTOCOLS.IPC, ZMQ_PROTOCOLS.INPROC]
        all ZeroMQ sockets where instructions can be passed to the RPC server. Use TCP for network access,
        IPC for multi-process applications, and INPROC for multi-threaded applications. Use all for complete access. 
    poll_timeout: int, default 25
        time in milliseconds to poll the sockets specified under ``procotols``. Useful for calling ``stop_polling()``
        where the max delay to stop polling will be ``poll_timeout``
    **kwargs:
        tcp_socket_address: str
            address of the TCP socket, if not given, a random port is chosen
    """

    def __init__(self, instance_name : str, *, server_type : Enum, context : typing.Union[zmq.asyncio.Context, None] = None, 
                protocols : typing.Union[ZMQ_PROTOCOLS, str, typing.List[ZMQ_PROTOCOLS]] = ZMQ_PROTOCOLS.IPC, 
                poll_timeout = 25, **kwargs) -> None:
        super().__init__(instance_name=instance_name, server_type=server_type, **kwargs)
        
        self.identity = f"{instance_name}/rpc-server"
        if isinstance(protocols, list): 
            protocols = protocols 
        elif isinstance(protocols, str): 
            protocols = [protocols]
        else:
            raise TypeError(f"unsupported protocols type : {type(protocols)}")
        tcp_socket_address = kwargs.pop('tcp_socket_address', None)
        kwargs["http_serializer"] = self.http_serializer
        kwargs["zmq_serializer"] = self.zmq_serializer
        self.inproc_server = self.ipc_server = self.tcp_server = self.event_publisher = None
        event_publisher_protocol = None 
        if self.logger is None:
            self.logger =  get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, 
                                                'RPC', 'MIXED', instance_name), kwargs.get('log_level', logging.INFO))
        # contexts and poller
        self.context = context or zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.poll_timeout = poll_timeout
        # initialise every externally visible protocol
        if ZMQ_PROTOCOLS.TCP in protocols or "TCP" in protocols:
            self.tcp_server = AsyncPollingZMQServer(instance_name=instance_name, server_type=server_type, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.TCP, poll_timeout=poll_timeout, 
                                    socket_address=tcp_socket_address, **kwargs)
            self.poller.register(self.tcp_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.TCP
        if ZMQ_PROTOCOLS.IPC in protocols or "IPC" in protocols: 
            self.ipc_server = AsyncPollingZMQServer(instance_name=instance_name, server_type=server_type, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.IPC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.ipc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.IPC if not event_publisher_protocol else event_publisher_protocol              
        if ZMQ_PROTOCOLS.INPROC in protocols or "INPROC" in protocols: 
            self.inproc_server = AsyncPollingZMQServer(instance_name=instance_name, server_type=server_type, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.INPROC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.inproc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.INPROC if not event_publisher_protocol else event_publisher_protocol    
        self.event_publisher = EventPublisher(
                            instance_name=instance_name + '-event-pub',
                            protocol=event_publisher_protocol,
                            zmq_serializer=self.zmq_serializer,
                            http_serializer=self.http_serializer,
                            logger=self.logger
                        )        
        # instruction serializing broker
        self.inner_inproc_client = AsyncZMQClient(
                                        server_instance_name=f'{instance_name}/inner', 
                                        identity=f'{instance_name}/tunneler',
                                        client_type=TUNNELER, 
                                        context=self.context, 
                                        protocol=ZMQ_PROTOCOLS.INPROC, 
                                        handshake=False, # handshake manually done later when event loop is run
                                        logger=self.logger
                                    )
        self.inner_inproc_server = AsyncZMQServer(
                                        instance_name=f'{self.instance_name}/inner', # hardcoded be very careful
                                        server_type=server_type,
                                        context=self.context,
                                        protocol=ZMQ_PROTOCOLS.INPROC, 
                                        **kwargs
                                    )       
        self._instructions = deque() # type: deque[typing.Tuple[typing.List[bytes], asyncio.Event, asyncio.Future, zmq.Socket]]
        self._instructions_event = asyncio.Event()
        

    async def handshake_complete(self):
        """
        handles inproc client's handshake with ``Thing``'s inproc server
        """
        await self.inner_inproc_client.handshake_complete()


    def prepare(self):
        """
        registers socket polling method and message tunnelling methods to the running 
        asyncio event loop
        """
        eventloop = asyncio.get_event_loop()
        eventloop.call_soon(lambda : asyncio.create_task(self.poll()))
        eventloop.call_soon(lambda : asyncio.create_task(self.tunnel_message_to_things()))


    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(("polling period must be an integer greater than 0, not {}.",
                              "Value is considered in milliseconds.".format(value)))
        self._poll_timeout = value 

    
    def _get_timeout_from_instruction(self, message : typing.Tuple[bytes]) -> float:
        """
        Unlike ``parse_client_message()``, this method only retrieves the timeout parameter
        """
        client_type = message[CM_INDEX_CLIENT_TYPE]
        if client_type == PROXY:
            return self.zmq_serializer.loads(message[CM_INDEX_TIMEOUT]) 
        elif client_type == HTTP_SERVER:
            return self.http_serializer.loads(message[CM_INDEX_TIMEOUT])
       

    async def poll(self):
        """
        poll for instructions and append them to instructions list to pass them to ``Eventloop``/``Thing``'s inproc 
        server using an inner inproc client. Registers the messages for timeout calculation.
        """
        self.stop_poll = False
        eventloop = asyncio.get_event_loop()
        self.inner_inproc_client.handshake()
        await self.inner_inproc_client.handshake_complete()
        if self.inproc_server:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_instruction(self.inproc_server)))
        if self.ipc_server:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_instruction(self.ipc_server)))
        if self.tcp_server:
            eventloop.call_soon(lambda : asyncio.create_task(self.recv_instruction(self.tcp_server)))
       

    def stop_polling(self):
        """
        stop polling method ``poll()``
        """
        self.stop_poll = True
        self._instructions_event.set()
        if self.inproc_server is not None:
            def kill_inproc_server(instance_name, context, logger):
                # this function does not work when written fully async - reason is unknown
                try: 
                    event_loop = asyncio.get_event_loop()
                except RuntimeError:
                    event_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(event_loop)
                temp_inproc_client = AsyncZMQClient(server_instance_name=instance_name,
                                            identity=f'{self.instance_name}-inproc-killer',
                                            context=context, client_type=PROXY, protocol=ZMQ_PROTOCOLS.INPROC, 
                                            logger=logger) 
                event_loop.run_until_complete(temp_inproc_client.handshake_complete())
                event_loop.run_until_complete(temp_inproc_client.socket.send_multipart(temp_inproc_client.craft_empty_message_with_type(EXIT)))
                temp_inproc_client.exit()
            threading.Thread(target=kill_inproc_server, args=(self.instance_name, self.context, self.logger), daemon=True).start()
        if self.ipc_server is not None:
            temp_client = SyncZMQClient(server_instance_name=self.instance_name, identity=f'{self.instance_name}-ipc-killer',
                                    client_type=PROXY, protocol=ZMQ_PROTOCOLS.IPC, logger=self.logger) 
            temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
            temp_client.exit()
        if self.tcp_server is not None:
            socket_address = self.tcp_server.socket_address
            if '/*:' in self.tcp_server.socket_address:
                socket_address = self.tcp_server.socket_address.replace('*', 'localhost')
            # print("TCP socket address", self.tcp_server.socket_address)
            temp_client = SyncZMQClient(server_instance_name=self.instance_name, identity=f'{self.instance_name}-tcp-killer',
                                    client_type=PROXY, protocol=ZMQ_PROTOCOLS.TCP, logger=self.logger,
                                    socket_address=socket_address)
            temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
            temp_client.exit()   


    async def recv_instruction(self, server : AsyncZMQServer):
        eventloop = asyncio.get_event_loop()
        socket = server.socket
        while True:
            try:
                original_instruction = await socket.recv_multipart()
                if original_instruction[CM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
                    handshake_task = asyncio.create_task(self._handshake(original_instruction, socket))
                    eventloop.call_soon(lambda : handshake_task)
                    continue
                if original_instruction[CM_INDEX_MESSAGE_TYPE] == EXIT:
                    break
                timeout = self._get_timeout_from_instruction(original_instruction)
                ready_to_process_event = None
                timeout_task = None
                if timeout is not None:
                    ready_to_process_event = asyncio.Event()
                    timeout_task = asyncio.create_task(self.process_timeouts(original_instruction, 
                                                ready_to_process_event, timeout, socket))
                    eventloop.call_soon(lambda : timeout_task)
            except Exception as ex:
                # handle invalid message
                self.logger.error(f"exception occurred for message id {original_instruction[CM_INDEX_MESSAGE_ID]} - {str(ex)}")
                invalid_message_task = asyncio.create_task(self._handle_invalid_message(original_instruction,
                                                                                ex, socket))
                eventloop.call_soon(lambda: invalid_message_task)
            else:
                self._instructions.append((original_instruction, ready_to_process_event, 
                                                            timeout_task, socket))
            self._instructions_event.set()
        self.logger.info(f"stopped polling for server '{server.identity}' {server.socket_address[0:3].upper() if server.socket_address[0:3] in ['ipc', 'tcp'] else 'INPROC'}")
           

    async def tunnel_message_to_things(self):
        """
        message tunneler between external sockets and interal inproc client
        """
        while not self.stop_poll:
            if len(self._instructions) > 0:
                message, ready_to_process_event, timeout_task, origin_socket = self._instructions.popleft()
                timeout = True 
                if ready_to_process_event is not None: 
                    ready_to_process_event.set()
                    timeout = await timeout_task
                if ready_to_process_event is None or not timeout:
                    original_address = message[CM_INDEX_ADDRESS]
                    message[CM_INDEX_ADDRESS] = self.inner_inproc_client.server_address # replace address
                    await self.inner_inproc_client.socket.send_multipart(message)
                    reply = await self.inner_inproc_client.socket.recv_multipart()
                    reply[SM_INDEX_ADDRESS] = original_address
                    if reply[SM_INDEX_MESSAGE_TYPE] != ONEWAY:
                        await origin_socket.send_multipart(reply)
            else:
                await self._instructions_event.wait()
                self._instructions_event.clear()
        self.logger.info("stopped tunneling messages to things")

    async def process_timeouts(self, original_client_message : typing.List, ready_to_process_event : asyncio.Event,
                               timeout : typing.Optional[float], origin_socket : zmq.Socket) -> bool:
        """
        replies timeout to client if timeout occured and prevents the instruction from being executed. 
        """
        try:
            await asyncio.wait_for(ready_to_process_event.wait(), timeout)
            return False 
        except TimeoutError:    
            await origin_socket.send_multipart(self.craft_reply_from_arguments(original_client_message[CM_INDEX_ADDRESS], 
                original_client_message[CM_INDEX_CLIENT_TYPE], TIMEOUT, original_client_message[CM_INDEX_MESSAGE_ID]))
            return True

    async def _handle_invalid_message(self, original_client_message: builtins.list[builtins.bytes], 
                                exception: builtins.Exception, originating_socket : zmq.Socket) -> None:
        await originating_socket.send_multipart(self.craft_reply_from_arguments(
                            original_client_message[CM_INDEX_ADDRESS], original_client_message[CM_INDEX_CLIENT_TYPE], 
                            INVALID_MESSAGE, original_client_message[CM_INDEX_MESSAGE_ID], exception))
        self.logger.info(f"sent exception message to client '{original_client_message[CM_INDEX_ADDRESS]}'." +
                            f" exception - {str(exception)}") 	
    
    async def _handshake(self, original_client_message: builtins.list[builtins.bytes],
                                    originating_socket : zmq.Socket) -> None:
        await originating_socket.send_multipart(self.craft_reply_from_arguments(
                original_client_message[CM_INDEX_ADDRESS], 
                original_client_message[CM_INDEX_CLIENT_TYPE], HANDSHAKE, original_client_message[CM_INDEX_MESSAGE_ID],
                EMPTY_DICT))
        self.logger.info("sent handshake to client '{}'".format(original_client_message[CM_INDEX_ADDRESS]))


    def exit(self):
        self.stop_poll = True
        for socket in list(self.poller._map.keys()): # iterating over keys will cause dictionary size change during iteration
            try:
                self.poller.unregister(socket)
            except Exception as ex:
                self.logger.warning(f"could not unregister socket from polling - {str(ex)}") # does not give info about socket
        try:
            self.inproc_server.exit()
            self.ipc_server.exit()
            self.tcp_server.exit()
            self.inner_inproc_client.exit()
        except:
            pass 
        self.context.term()
        self.logger.info("terminated context of socket '{}' of type '{}'".format(self.identity, self.__class__))

    
       
class BaseZMQClient(BaseZMQ):
    """    
    Base class for all ZMQ clients irrespective of sync and async.

    server's reply to client
    ::

        [address, bytes(), server type , message_type, message id, content or response or reply]
        [   0   ,   1    ,    2        ,     3       ,     4     ,            5                ]

    Parameters
    ----------
    server_instance_name: str
        The instance name of the server (or ``Thing``)
    client_type: str
        RPC or HTTP Server
    **kwargs:
        zmq_serializer: BaseSerializer
            custom implementation of RPC serializer if necessary
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
        self._reply_cache = dict()
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
                                    deserialize : bool = True) -> typing.Any:
        """
        server's message to client: 

        ::
            [address, bytes(), server type , message_type, message id, content or response or reply]
            [   0   ,   1    ,    2        ,     3     ,       4     ,            5                ]

        Parameters
        ----------
        message: List[bytes]
            message sent be server
        raise_client_side_exception: bool
            raises exception from server on client
        
        Raises
        ------
        NotImplementedError:
            if message type is not reply, handshake or invalid
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
            if deserialize:
                if self.client_type == HTTP_SERVER:
                    message[SM_INDEX_DATA] = self.http_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
                elif self.client_type == PROXY:
                    message[SM_INDEX_DATA] = self.zmq_serializer.loads(message[SM_INDEX_DATA]) # type: ignore
            return message 
        elif message_type == HANDSHAKE:
            self.logger.debug("""handshake messages arriving out of order are silently dropped as receiving this message 
                means handshake was successful before. Received hanshake from {}""".format(message[0]))
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
            exception =  TimeoutError("message timed out.")
            if raise_client_side_exception:
                raise exception from None 
            message[SM_INDEX_DATA] = format_exception_as_json(exception)
            return message
        else:
            raise NotImplementedError("Unknown message type {} received. This message cannot be dealt.".format(message_type))


    def craft_instruction_from_arguments(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                timeout : typing.Optional[float] = None, context : typing.Dict[str, typing.Any] = EMPTY_DICT) -> typing.List[bytes]: 
        """
        message from client to server:

        ::
            [address, bytes(), client type, message type, message id, instruction, arguments]
            [ 0     ,   1    ,     2      ,      3      ,       4   ,    5       ,     6    ]

        """
        message_id = bytes(str(uuid4()), encoding='utf-8')
        if self.client_type == HTTP_SERVER:
            timeout = self.http_serializer.dumps(timeout) # type: bytes
            instruction = self.http_serializer.dumps(instruction) # type: bytes
            # TODO - following can be improved
            if arguments == b'':
                arguments = self.http_serializer.dumps({}) # type: bytes
            elif not isinstance(arguments, byte_types):
                arguments = self.http_serializer.dumps(arguments) # type: bytes
            context = self.http_serializer.dumps(context) # type: bytes
        elif self.client_type == PROXY:
            timeout = self.zmq_serializer.dumps(timeout) # type: bytes
            instruction = self.zmq_serializer.dumps(instruction) # type: bytes
            if not isinstance(arguments, byte_types):
                arguments = self.zmq_serializer.dumps(arguments) # type: bytes
            context = self.zmq_serializer.dumps(context)
              
        return [
            self.server_address, 
            EMPTY_BYTE,
            self.client_type,
            INSTRUCTION,
            message_id,
            timeout, 
            instruction,
            arguments,
            context
        ]


    def craft_empty_message_with_type(self, message_type : bytes = HANDSHAKE):
        """
        create handshake message for example
        """
        return [
            self.server_address,
            EMPTY_BYTE,
            self.client_type,
            message_type,
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
        RPC or HTTP Server
    handshake: bool
        when true, handshake with the server first before allowing first message and block until that handshake was
        accomplished.
    protocol: str | Enum, TCP, IPC or INPROC, default IPC 
        protocol implemented by the server 
    **kwargs:
        socket_address: str
            socket address for connecting to TCP server
        zmq_serializer: 
            custom implementation of RPC serializer if necessary
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
    
    def send_instruction(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        invokation_timeout : typing.Optional[float] = None, execution_timeout : typing.Optional[float] = None,
                        context : typing.Dict[str, typing.Any] = EMPTY_DICT,
                        argument_schema : typing.Optional[JSON] = None) -> bytes:
        """
        send message to server. 

        client's message to server:
        ::
        
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
            
            timeout, instruction, arguments, execution context] 
               5   ,      6     ,     7    ,       8          ]

        Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "plain_reply" - does not return state 
            - "fetch_execution_logs" - fetches logs that were accumulated while execution

        Parameters
        ----------
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message id : bytes
            a byte representation of message id
        """
        message = self.craft_instruction_from_arguments(instruction, arguments, invokation_timeout, context)
        self.socket.send_multipart(message)
        self.logger.debug(f"sent instruction '{instruction}' to server '{self.instance_name}' with msg-id '{message[SM_INDEX_MESSAGE_ID]}'")
        return message[SM_INDEX_MESSAGE_ID]
    
    def recv_reply(self, message_id : bytes, timeout : typing.Optional[int] = None, raise_client_side_exception : bool = False, 
                    deserialize : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]:
        """
        Receives reply from server. Messages are identified by message id, so call this method immediately after 
        calling ``send_instruction()`` to avoid receiving messages out of order. Or, use other methods like
        ``execute()``, ``read_attribute()`` or ``write_attribute()``.

        Parameters
        ----------
        raise_client_side_exception: bool, default False
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
            See docs of ``raise_local_exception()`` for info on exception 
        """
        while True:
            sockets = self.poller.poll(timeout)
            reply = None
            for socket, _ in sockets:
                try:    
                    message = socket.recv_multipart(zmq.NOBLOCK)
                    reply = self.parse_server_message(message, raise_client_side_exception, deserialize) # type: ignore
                except zmq.Again:
                    pass 
            if reply: 
                if message_id != reply[SM_INDEX_MESSAGE_ID]:
                    self._reply_cache[message_id] = reply
                    continue 
                self.logger.debug("received reply with msg-id {}".format(reply[SM_INDEX_MESSAGE_ID]))
                return reply
            if timeout is not None:
                break # this should not break, technically an error, should be fixed when inventing better RPC contract
                
    def execute(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                invokation_timeout : typing.Optional[float] = None, execution_timeout : typing.Optional[float] = None,
                context : typing.Dict[str, typing.Any] = EMPTY_DICT, raise_client_side_exception : bool = False, 
                argument_schema : typing.Optional[JSON] = None, 
                deserialize_reply : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]:
        """
        send an instruction and receive the reply for it. 

        Parameters
        ----------
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message id : bytes
            a byte representation of message id
        """
        acquire_timeout = -1 if invokation_timeout is None else invokation_timeout   
        acquired = self._client_queue.acquire(timeout=acquire_timeout)
        if not acquired:
            raise TimeoutError("previous request still in progress")
        try:
            msg_id = self.send_instruction(instruction, arguments, invokation_timeout, 
                                        execution_timeout, context, argument_schema)
            return self.recv_reply(msg_id, raise_client_side_exception=raise_client_side_exception, deserialize=deserialize_reply)
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
            self.socket.send_multipart(self.craft_empty_message_with_type(HANDSHAKE))
            self.logger.info(f"sent Handshake to server '{self.instance_name}'")
            if self.poller.poll(500):
                try:
                    message = self.socket.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    pass 
                else:
                    if message[3] == HANDSHAKE:  # type: ignore
                        self.logger.info(f"client '{self.identity}' handshook with server '{self.instance_name}'")
                        self.server_type = message[SM_INDEX_SERVER_TYPE]
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with '{self.instance_name}'. Another message arrived before handshake complete.")
            else:
                self.logger.info('got no reply')
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN) 
        # sufficient to know when server dies only while receiving messages, not continuous polling
 
    

class AsyncZMQClient(BaseZMQClient, BaseAsyncZMQ):
    """ 
    Asynchronous client to talk to a ZMQ server where the server is identified by the instance name. The identity 
    of the client needs to be different from the server, unlike the ZMQ Server. The client will also perform handshakes 
    if necessary.
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

    async def _handshake(self,  timeout : typing.Union[float, int] = 60000) -> None:
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
            await self.socket.send_multipart(self.craft_empty_message_with_type(HANDSHAKE))
            self.logger.info(f"sent Handshake to server '{self.instance_name}'")
            if await self.poller.poll(500):
                try:
                    message = await self.socket.recv_multipart(zmq.NOBLOCK)
                except zmq.Again:
                    pass 
                else:
                    if message[3] == HANDSHAKE:  # type: ignore
                        self.logger.info(f"client '{self.identity}' handshook with server '{self.instance_name}'")
                        self.server_type = message[SM_INDEX_SERVER_TYPE]
                        break
                    else:
                        raise ConnectionAbortedError(f"Handshake cannot be done with '{self.instance_name}'. Another message arrived before handshake complete.")
            else:
                self.logger.info('got no reply')
        self._monitor_socket = self.socket.get_monitor_socket()
        self.poller.register(self._monitor_socket, zmq.POLLIN) 
        self._handshake_event.set()

 
    async def handshake_complete(self):
        """
        wait for handshake to complete
        """
        await self._handshake_event.wait()
       
    async def async_send_instruction(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    invokation_timeout : typing.Optional[float] = None, execution_timeout : typing.Optional[float] = None,
                    context : typing.Dict[str, typing.Any] = EMPTY_DICT,
                    argument_schema : typing.Optional[JSON] = None) -> bytes:
        """
        send message to server. 

        client's message to server:
        ::
            [address, bytes(), client type, message type, messsage id, 
            [   0   ,   1    ,     2      ,      3      ,      4     , 
            
            timeout, instruction, arguments, execution context] 
               5   ,      6     ,     7    ,       8          ]

        Execution Context Definitions (typing.Dict[str, typing.Any] or JSON):
            - "plain_reply" - does not return state 
            - "fetch_execution_logs" - fetches logs that were accumulated while execution

        Parameters
        ----------
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message id : bytes
            a byte representation of message id
        """
        message = self.craft_instruction_from_arguments(instruction, arguments, invokation_timeout, context) 
        await self.socket.send_multipart(message)
        self.logger.debug(f"sent instruction '{instruction}' to server '{self.instance_name}' with msg-id {message[SM_INDEX_MESSAGE_ID]}")
        return message[SM_INDEX_MESSAGE_ID]
    
    async def async_recv_reply(self, message_id : bytes, timeout : typing.Optional[int] = None, 
                        raise_client_side_exception : bool = False, deserialize : bool = True) -> typing.List[
                                                                    typing.Union[bytes, typing.Dict[str, typing.Any]]]:
        """
        Receives reply from server. Messages are identified by message id, so call this method immediately after 
        calling ``send_instruction()`` to avoid receiving messages out of order. Or, use other methods like
        ``execute()``, ``read_attribute()`` or ``write_attribute()``.

        Parameters
        ----------
        raise_client_side_exception: bool, default False
            if True, any exceptions raised during execution inside ``Thing`` instance will be raised on the client.
            See docs of ``raise_local_exception()`` for info on exception 
        """
        while True:
            sockets = await self.poller.poll(timeout)
            reply = None
            for socket, _ in sockets:
                try:    
                    message = await socket.recv_multipart(zmq.NOBLOCK)
                    reply = self.parse_server_message(message, raise_client_side_exception, deserialize) # type: ignore
                except zmq.Again:
                    pass 
            if reply:
                if message_id != reply[SM_INDEX_MESSAGE_ID]:
                    self._reply_cache[message_id] = reply
                    continue 
                self.logger.debug(f"received reply with message-id '{reply[SM_INDEX_MESSAGE_ID]}'")
                return reply
            if timeout is not None:
                break
            
    async def async_execute(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    invokation_timeout : typing.Optional[float] = None, execution_timeout : typing.Optional[float] = None, 
                    context : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    raise_client_side_exception = False, argument_schema : typing.Optional[JSON] = None,
                    deserialize_reply : bool = True) -> typing.List[typing.Union[bytes, typing.Dict[str, typing.Any]]]: 
        """
        send an instruction and receive the reply for it. 

        Parameters
        ----------
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message id : bytes
            a byte representation of message id
        """
        try:
            await asyncio.wait_for(self._client_queue.acquire(), timeout=invokation_timeout)
        except TimeoutError:
            raise TimeoutError("previous request still in progress") from None
        try:
            msg_id = await self.async_send_instruction(instruction, arguments, invokation_timeout, execution_timeout, 
                                                    context, argument_schema)
            return await self.async_recv_reply(msg_id, raise_client_side_exception=raise_client_side_exception, 
                                            deserialize=deserialize_reply)
        finally:
            self._client_queue.release()
   

        
class MessageMappedZMQClientPool(BaseZMQClient):
    """
    Pool of clients where message ID can track the replies irrespective of order of arrival. 
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


    async def poll(self) -> None:
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
                        reply = self.parse_server_message(await socket.recv_multipart(zmq.NOBLOCK),
                                                    deserialize=self._deserialize_server_messages)
                        if not reply:
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
                        address, _, server_type, message_type, message_id, data, encoded_data = reply
                        self.logger.debug(f"received reply from server '{address}' with message ID '{message_id}'")
                        if message_id in self.cancelled_messages:
                            self.cancelled_messages.remove(message_id)
                            self.logger.debug(f"message_id '{message_id}' cancelled")
                            continue
                        event = self.events_map.get(message_id, None) 
                        if event:
                            if len(encoded_data) > 0:
                                self.message_map[message_id] = encoded_data
                            else:
                                self.message_map[message_id] = data
                            event.set()
                        else:    
                            if len(encoded_data) > 0:
                                invalid_event_task = asyncio.create_task(self._resolve_reply(message_id, encoded_data))
                            else:
                                invalid_event_task = asyncio.create_task(self._resolve_reply(message_id, data))
                            event_loop.call_soon(lambda: invalid_event_task)


    async def _resolve_reply(self, message_id : bytes, data : typing.Any) -> None:
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

    async def async_send_instruction(self, instance_name : str, instruction : str, 
                arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, invokation_timeout : typing.Optional[float] = 3,
                execution_timeout : typing.Optional[float] = None, 
                context : typing.Dict[str, typing.Any] = EMPTY_DICT, argument_schema : typing.Optional[JSON] = None) -> bytes:
        """
        Send instruction to server with instance name. Replies are automatically polled & to be retrieved using 
        ``async_recv_reply()``

        Parameters
        ----------
        instance_name: str
            instance name of the server
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions

        Returns
        -------
        message_id: bytes
            created message ID
        """
        self.assert_client_ready(self.pool[instance_name])
        message_id = await self.pool[instance_name].async_send_instruction(instruction=instruction, arguments=arguments, 
                                            invokation_timeout=invokation_timeout, execution_timeout=execution_timeout, 
                                            context=context, argument_schema=argument_schema)
        event = self.event_pool.pop()
        self.events_map[message_id] = event 
        return message_id

    async def async_recv_reply(self, instance_name : str, message_id : bytes, raise_client_side_exception = False,
                        timeout : typing.Optional[float] = None) -> typing.Dict[str, typing.Any]:
        """
        Receive reply for specified message ID. 

        Parameters
        ----------
        message_id: bytes
            the message id for which reply needs to eb fetched
        raise_client_side_exceptions: bool, default False
            raise exceptions from server on client side
        timeout: float, 
            client side timeout, not the same as timeout passed to server, recommended to be None in general cases. 
            Server side timeouts ensure start of execution of instructions within specified timeouts and 
            drops execution altogether if timeout occured. Client side timeouts only wait for message to come within 
            the timeout, but do not gaurantee non-execution.  

        Returns
        -------
        reply: dict, Any
            dictionary when plain reply is False, any value returned from execution on the server side if plain reply is
            True.

        Raises
        ------
        ValueError: 
            if supplied message id is not valid
        TimeoutError:
            if timeout is not None and reply did not arrive
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
        reply = self.message_map.pop(message_id)
        if raise_client_side_exception and reply.get('exception', None) is not None:
            self.raise_local_exception(reply['exception'])
        return reply

    async def async_execute(self, instance_name : str, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                    *, context : typing.Dict[str, typing.Any] = EMPTY_DICT, raise_client_side_exception = False, 
                    invokation_timeout : typing.Optional[float] = 5, execution_timeout : typing.Optional[float] = None,
                    argument_schema : typing.Optional[JSON] = None) -> typing.Dict[str, typing.Any]:
        """
        sends message and receives reply.

        Parameters
        ----------
        instance_name: str
            instance name of the server
        instruction: str
            unique str identifying a server side or ``Thing`` resource. These values corresponding 
            to automatically extracted name from the object name or the URL_path prepended with the instance name. 
        arguments: Dict[str, Any]
            if the instruction invokes a method, arguments of that method. 
        context: Dict[str, Any]
            see execution context definitions
        raise_client_side_exceptions: bool, default False
            raise exceptions from server on client side
        invokation_timeout: float, default 5
            server side timeout
        execution_timeout: float, default None
            client side timeout, not the same as timeout passed to server, recommended to be None in general cases. 
            Server side timeouts ensure start of execution of instructions within specified timeouts and 
            drops execution altogether if timeout occured. Client side timeouts only wait for message to come within 
            the timeout, but do not gaurantee non-execution.  
        """
        message_id = await self.async_send_instruction(instance_name=instance_name, instruction=instruction, 
                                                    arguments=arguments, invokation_timeout=invokation_timeout, 
                                                    execution_timeout=execution_timeout, context=context, 
                                                    argument_schema=argument_schema)
        return await self.async_recv_reply(instance_name=instance_name, message_id=message_id, 
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

    async def async_execute_in_all(self, instruction : str, instance_names : typing.Optional[typing.List[str]] = None,  
                        arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, context : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        invokation_timeout : typing.Optional[float] = 5, execution_timeout : typing.Optional[float] = None, 
                    ) -> typing.Dict[str, typing.Any]:
        """
        execute a specified instruction in all Thing including eventloops
        """
        if not instance_names:
            instance_names = self.pool.keys()
        gathered_replies = await asyncio.gather(*[
            self.async_execute(instance_name, instruction, arguments, 
                        context=context, raise_client_side_exception=False,
                        invokation_timeout=invokation_timeout, execution_timeout=execution_timeout) 
                for instance_name in instance_names])
        replies = dict()
        for instance_name, reply in zip(instance_names, gathered_replies):
            replies[instance_name] = reply
        return replies  
    
    async def async_execute_in_all_things(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        context : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        invokation_timeout : typing.Optional[float] = 5, execution_timeout : typing.Optional[float] = None, 
                       ) -> typing.Dict[str, typing.Any]: #  raise_client_side_exception = False
        """
        execute the same instruction in all Things, eventloops are excluded. 
        """
        return await self.async_execute_in_all(instruction=instruction, 
                        instance_names=[instance_name for instance_name, client in self.pool.items() if client.server_type == ServerTypes.THING],
                        arguments=arguments, context=context, invokation_timeout=invokation_timeout, 
                        execution_timeout=execution_timeout)
    
    async def async_execute_in_all_eventloops(self, instruction : str, arguments : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        context : typing.Dict[str, typing.Any] = EMPTY_DICT, 
                        invokation_timeout : typing.Optional[float] = 5, execution_timeout : typing.Optional[float] = None, 
                    ) -> typing.Dict[str, typing.Any]: # raise_client_side_exception = False
        """
        execute the same instruction in all eventloops.
        """
        return await self.async_execute_in_all(instruction=instruction, 
                        instance_names=[instance_name for instance_name, client in self.pool.items() if client.server_type == ServerTypes.EVENTLOOP],
                        arguments=arguments, context=context, invokation_timeout=invokation_timeout, 
                        execution_timeout=execution_timeout)

    async def ping_all_servers(self):
        """
        ping all servers connected to the client pool, calls ping() on Thing
        """
        return await self.async_execute_in_all(instruction=CommonRPC.PING)
        
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
            raise AttributeError(f"event {event._name} already found in list of events, please use another name.")
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
            pushes event to RPC clients
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
            serializer for RPC clients
        server_instance_name: str
            instance name of the Thing publishing the event
    """

    def __init__(self, unique_identifier : str, socket_address : str, 
                    identity : str, client_type = b'HTTP_SERVER', 
                        **kwargs) -> None:
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
            serializer for RPC clients
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
            serializer for RPC clients
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
    AsyncPollingZMQServer.__name__, 
    ZMQServerPool.__name__, 
    RPCServer.__name__, 
    SyncZMQClient.__name__, 
    AsyncZMQClient.__name__, 
    MessageMappedZMQClientPool.__name__, 
    AsyncEventConsumer.__name__, 
    EventConsumer.__name__
]