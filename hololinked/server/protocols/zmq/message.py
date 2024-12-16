from dataclasses import dataclass
import typing 
from uuid import uuid4


from ...constants import byte_types
from ...serializers import Serializers


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



default_server_execution_context = dict(
    invokation_timeout=5,
    execution_timeout=5,
    oneway=False
)
    
@dataclass
class SerializableData:
    value: typing.Any
    content_type: str

    def serialize(self):
        if self.content_type == 'json' or self.content_type == 'application/json':
            return Serializers.json.dumps(self.value)
        elif self.content_type == 'pickle':
            return Serializers.pickle.dumps(self.value)
        elif self.content_type == 'x-msgpack':
            return Serializers.msgpack.dumps(self.value)
        elif self.content_type == 'text' or self.content_type == 'text/plain':
            if not isinstance(self.value, str):
                value = str(self.value)
            else:
                value = self.value
            return value.encode('utf-8')
        raise ValueError(f"content type {self.content_type} not supported for serialization")
    
    def deserialize(self):
        if self.content_type == 'json' or self.content_type == 'application/json':
            return Serializers.json.loads(self.value)
        elif self.content_type == 'pickle':
            return Serializers.pickle.loads(self.value)
        elif self.content_type == 'x-msgpack':
            return Serializers.msgpack.loads(self.value)
        elif self.content_type == 'text' or self.content_type == 'text/plain':
            return self.value.decode('utf-8')
        raise ValueError(f"content type {self.content_type} not supported for deserialization")



class RequestMessage:
    """
    A single unit of message from a ZMQ client to server. The message may be parsed and deserialized into header and body,
    or used in bytes.

    Message indices:

    Header:

    | Index | 0       | 1       | 2           | 3            | 4          | 5                        |
    |-------|---------|---------|-------------|--------------|------------|--------------------------|
    | Desc  | address | bytes() | client type | message type | message id | server execution context |

    Body:   

    | Index | 6       | 7         | 8       | 9         | 10        | 11                      |    
    |-------|---------|-----------|---------|-----------|-----------|-------------------------|    
    | Desc  | bytes() | thing id  | object  | operation | arguments | thing execution context |
    
    """

    def __init__(self, msg : typing.List[bytes]):
        self._msg_bytes = msg  
        self._header = None # deserialized header
        self._body = None  # deserialized body

    @property
    def bytes(self) -> typing.List[bytes]:
        """returns the message in bytes"""
        return self._msg_bytes
    
    @property
    def header(self) -> typing.Tuple[bytes, bytes, bytes, bytes, bytes, typing.Dict[str, typing.Any]]:
        """
        returns the header of the message, namely:

        | Index | 0       | 1       | 2           | 3            | 4          | 5                        |
        |-------|---------|---------|-------------|--------------|------------|--------------------------|
        | Desc  | address | bytes() | client type | message type | message id | server execution context |

        where the server execution context is deserialized and is a dictionary with the following keys:

        - oneway - does not respond to client after executing the operation
        - invokation_timeout - time in seconds to wait for the operation to start
        - execution_timeout - time in seconds to wait for the operation to finish
        """
        if self._header is None:
            self.parse_header()
        return self._header 
    
    @property
    def body(self) -> typing.Tuple[bytes, bytes, bytes, typing.Any, typing.Dict[str, typing.Any]]:
        """
        returns the body of the message, namely:

        | Index | 7         | 8       | 9         | 10        | 11                      |
        |-------|-----------|---------|-----------|-----------|-------------------------|
        | Desc  | thing id  | object  | operation | arguments | thing execution context |

        where the thing execution context is deserialized and is a dictionary with the following keys:

        - fetch_execution_logs - fetches logs that were accumulated while execution
        """
        if self._body is None:
            self.parse_body()
        return self._body
    
    @property
    def id(self) -> bytes:
        """ID of the message"""
        return self._msg_bytes[4]
    
    @property
    def sender_id(self) -> bytes:
        """ID of the sender"""
        return self._msg_bytes[0]
    
    @property
    def thing_id(self) -> bytes:
        """ID of the thing on which the operation is to be performed"""
        return self._msg_bytes[7]
    
    
    def parse_header(self) -> None:
        """
        extract the header and deserialize the server execution context
        """
        self._header = self._msg_bytes[:6]
        self._header[5] = Serializers.json.loads(self._header[5])


    def parse_body(self) -> None:
        """
        extract the body and deserialize arguments and thing execution context
        """
        self._body = self._msg_bytes[7:]
        self._body[4] = Serializers.json.loads(self._body[4])


    def craft_from_arguments(self, server_id: bytes, thing_id: bytes, objekt: str, operation: str, 
                            arguments: SerializableData = SerializableData({}, 'json'),
                            server_execution_context: typing.Dict[str, typing.Any] = default_server_execution_context, 
                            thing_execution_context: typing.Dict[str, typing.Any] = EMPTY_DICT
                        ) -> "RequestMessage": 
        """
        create a request message from the given arguments

        Parameters
        ----------
        thing_id: bytes
            id of the thing to which the operation is to be performed
        objekt: str
            object of the thing on which the operation is to be performed, i.e. a property, action or event
        operation: str
            operation to be performed
        arguments: SerializableData
            arguments for the operation
        server_execution_context: Dict[str, Any]
            server-level execution context while performing the operation
        thing_execution_context: Dict[str, Any]
            thing-level execution context while performing the operation
        """
        return RequestMessage([
            server_id,
            EMPTY_BYTE,
            self.client_type,
            OPERATION, # i.e. the message type is b'OPERATION', not b'HANDSHAKE', b'REPLY', b'TIMEOUT' etc.
            bytes(str(uuid4()), encoding='utf-8'), # message id
            Serializers.json.dumps(server_execution_context), 
            EMPTY_BYTE,
            thing_id,
            objekt,
            operation,
            arguments.serialize(),
            Serializers.json.dumps(thing_execution_context) 
        ])


    def craft_with_message_type(self, server_id: bytes, message_type: bytes = HANDSHAKE):
        """
        create a plain message with a certain type, for example a handshake message.

        Parameters
        ----------
        server_id: bytes
            id of the server
        message_type: bytes
            message type to be sent
        """

        return RequestMessage([
            server_id,
            EMPTY_BYTE,
            self.client_type,
            message_type,
            bytes(str(uuid4()), encoding='utf-8'), # message id
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE,
            EMPTY_BYTE
        ])



class ResponseMessage:

    @classmethod
    def craft_response_from_request_message(self, message) -> "ResponseMessage":
        return Message() 
    
    # def craft_response_from_arguments(self, self.craft_response_from_arguments(address=original_client_message[CM_INDEX_ADDRESS], 
    #                 client_type=original_client_message[CM_INDEX_CLIENT_TYPE], message_type=message_type, 
    #                 message_id=original_client_message[CM_INDEX_MESSAGE_ID], data=data, pre_encoded_data=pre_encoded_data))
    

    def craft_from_arguments(self, client_id: bytes, address: bytes, client_type: bytes, message_type: bytes, 
                            message_id: bytes = b'', 
                            data: SerializableData = SerializableData(None, 'application/json'), 
                            pre_encoded_data : typing.Optional[bytes] = EMPTY_BYTE
                        ) -> typing.List[bytes]:
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