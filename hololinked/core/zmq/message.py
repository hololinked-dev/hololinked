from typing import Any, Optional
from uuid import uuid4

import msgspec

from ...constants import JSON, byte_types
from ...param.parameters import Integer
from ...serializers.payloads import PreserializedData, SerializableData
from ...serializers.serializers import Serializers


# message types
# both directions
HANDSHAKE = "HANDSHAKE"  # 1 - find out if the server is alive/connect to it
# client to server
OPERATION = "OPERATION"  # 2 - i.e. message type is a request to perform an operation on the interaction affordance
EXIT = "EXIT"  # 3 - exit the server
# server to client
REPLY = "REPLY"  # 4 - response for operation
TIMEOUT = "TIMEOUT"  # 5 - timeout message, operation could not be completed
ERROR = "EXCEPTION"  # 6 - exception occurred while executing operation
INVALID_MESSAGE = "INVALID_MESSAGE"  # 7 - invalid message
SERVER_DISCONNECTED = "EVENT_DISCONNECTED"  # 8 - socket died - zmq's builtin event EVENT_DISCONNECTED
# peer to peer
INTERRUPT = "INTERRUPT"  # 9 - interrupt a socket while polling

# not used now
EVENT = "EVENT"
EVENT_SUBSCRIPTION = "EVENT_SUBSCRIPTION"
SUCCESS = "SUCCESS"


EMPTY_BYTE = b""

"""
Message indices 

| Index | 0       | 1          | 2      | 3      | 4                     |
|-------|---------|------------|--------|--------|-----------------------|
| Desc  | address | empty byte | header | payload| preserialized payload |

"""
# CM = Client Message
INDEX_ADDRESS = 0
INDEX_DELIMITER = 1
INDEX_HEADER = 2
INDEX_BODY = 3
INDEX_PRESERIALIZED_BODY = 4


class ServerExecutionContext(msgspec.Struct):
    """Additional context for the server while executing an operation"""

    invokationTimeout: float
    executionTimeout: float
    oneway: bool


class ThingExecutionContext(msgspec.Struct):
    """Additional context for the thing while executing an operation"""

    fetchExecutionLogs: bool


default_server_execution_context = ServerExecutionContext(invokationTimeout=5, executionTimeout=5, oneway=False)

default_thing_execution_context = ThingExecutionContext(fetchExecutionLogs=False)

SerializableNone = SerializableData(None, content_type="application/json")
PreserializedEmptyByte = PreserializedData(EMPTY_BYTE, content_type="text/plain")


class RequestHeader(msgspec.Struct):
    """Header of a request message"""

    messageType: str
    messageID: str
    senderID: str
    receiverID: str
    serverExecutionContext: ServerExecutionContext = msgspec.field(
        default_factory=lambda: default_server_execution_context
    )
    thingExecutionContext: ThingExecutionContext = msgspec.field(
        default_factory=lambda: default_thing_execution_context
    )
    thingID: Optional[str] = ""
    objekt: Optional[str] = ""
    operation: Optional[str] = ""
    payloadContentType: Optional[str] = "application/json"
    preencodedPayloadContentType: Optional[str] = "text/plain"

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"key {key} not found in {self.__class__.__name__}") from None

    def json(self):
        return {f: getattr(self, f) for f in self.__struct_fields__}


class ResponseHeader(msgspec.Struct):
    """Header of a response message"""

    messageType: str
    messageID: str
    receiverID: str
    senderID: str
    payloadContentType: Optional[str] = "application/json"
    preencodedPayloadContentType: Optional[str] = ""

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"key {key} not found in {self.__class__.__name__}") from None

    def json(self):
        return {f: getattr(self, f) for f in self.__struct_fields__}


class EventHeader(msgspec.Struct):
    """Header of an event message"""

    messageType: str
    messageID: str
    senderID: str
    eventID: str
    payloadContentType: Optional[str] = "application/json"
    preencodedPayloadContentType: Optional[str] = ""

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"key {key} not found in {self.__class__.__name__}") from None

    def json(self):
        return {f: getattr(self, f) for f in self.__struct_fields__}


class RequestMessage:
    """
    A single unit of message from a ZMQ client to server. The message may be parsed and deserialized into header and body.

    Message indices:

    | Index | 0       | 1          | 2      |   3     |          4            |
    |-------|---------|------------|--------|---------|-----------------------|
    | Desc  | address | empty byte | header | payload | preserialized payload |

    For header's JSON schema, visit [here](https://github.com/hololinked-dev/hololinked/blob/main/hololinked/core/zmq/request_message_header_schema.json).
    """

    length = Integer(default=5, readonly=True, class_member=True, doc="length of the message")  # type: int

    def __init__(self, msg: list[bytes]) -> None:
        self._bytes = msg
        self._header = None  # deserialized header
        self._body = None  # type: Optional[tuple[SerializableData, PreserializedData]]
        self._sender_id = None

    @property
    def byte_array(self) -> list[bytes]:
        """
        message byte array, either after being composed or as received from the socket.

        Message indices:

        | Index | 0       | 1          | 2      |   3     |          4            |
        |-------|---------|------------|--------|---------|-----------------------|
        | Desc  | address | empty byte | header | payload | preserialized payload |
        """
        return self._bytes

    @property
    def header(self) -> RequestHeader:
        """header of the message, namely index 1 of the byte array, deserizalized to a dictionary"""
        if self._header is None:
            self.parse_header()
        return self._header

    @property
    def body(self) -> tuple[SerializableData, PreserializedData]:
        """body of the message"""
        if self._body is None:
            self.parse_body()
        return self._body

    @property
    def id(self) -> str:
        """ID of the message"""
        return self.header["messageID"]

    @property
    def receiver_id(self) -> str:
        """ID of the sender"""
        return self.header["receiverID"]

    @property
    def sender_id(self) -> str:
        """ID of the receiver"""
        return self.header["senderID"]

    @property
    def thing_id(self) -> str:
        """ID of the thing on which the operation is to be performed"""
        return self.header["thingID"]

    @property
    def type(self) -> str:
        """type of the message"""
        return self.header["messageType"]

    @property
    def server_execution_context(self) -> dict[str, Any]:
        """server execution context"""
        return self.header["serverExecutionContext"]

    @property
    def thing_execution_context(self) -> dict[str, Any]:
        """thing execution context"""
        return self.header["thingExecutionContext"]

    @property
    def qualified_operation(self) -> str:
        """qualified objekt - a possibly unique string for the operation"""
        return f"{self.header['thingID']}.{self.header['objekt']}.{self.header['operation']}"

    def parse_header(self) -> None:
        """extract the header and deserialize it"""
        if isinstance(self._bytes[INDEX_HEADER], RequestHeader):
            self._header = self._bytes[INDEX_HEADER]
        elif isinstance(self._bytes[INDEX_HEADER], byte_types):
            self._header = RequestHeader(**Serializers.json.loads(self._bytes[INDEX_HEADER]))
        else:
            raise ValueError(f"header must be of type RequestHeader or bytes, not {type(self._bytes[INDEX_HEADER])}")

    def parse_body(self) -> None:
        """extract the body and deserialize payload"""
        self._body = [
            SerializableData(self._bytes[INDEX_BODY], content_type=self.header["payloadContentType"]),
            PreserializedData(
                self._bytes[INDEX_PRESERIALIZED_BODY], content_type=self.header["preencodedPayloadContentType"]
            ),
        ]

    @classmethod
    def craft_from_arguments(
        cls,
        receiver_id: str,
        sender_id: str,
        thing_id: str,
        objekt: str,
        operation: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
        server_execution_context: dict[str, Any] = default_server_execution_context,
        thing_execution_context: dict[str, Any] = default_thing_execution_context,
    ) -> "RequestMessage":
        """
        create a request message from the given arguments

        Parameters
        ----------
        receiver_id: str
            id of the server (ZMQ socket identity)
        sender_id: str
            id of the client (ZMQ socket identity)
        thing_id: str
            id of the thing to which the operation is to be performed
        objekt: str
            objekt of the thing on which the operation is to be performed, i.e. a property, action or event name
        operation: str
            operation to be performed (`invokeaction`, `readproperty`, `writeproperty` etc.)
        payload: SerializableData
            payload for the operation
        preserialized_payload: PreserializedData
            pre-encoded payload for the operation
        server_execution_context: Dict[str, Any]
            server-level execution context while performing the operation
        thing_execution_context: Dict[str, Any]
            thing-level execution context while performing the operation

        Returns
        -------
        message: RequestMessage
            the crafted message
        """
        message = RequestMessage([])
        message._header = RequestHeader(
            messageID=str(uuid4()),
            messageType=OPERATION,
            senderID=sender_id,
            receiverID=receiver_id,
            # i.e. the message type is 'OPERATION', not 'HANDSHAKE', 'REPLY', 'TIMEOUT' etc.
            serverExecutionContext=server_execution_context,
            thingID=thing_id,
            objekt=objekt,
            operation=operation,
            payloadContentType=payload.content_type,
            preencodedPayloadContentType=preserialized_payload.content_type,
            thingExecutionContext=thing_execution_context,
        )
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(receiver_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    @classmethod
    def craft_with_message_type(
        cls, sender_id: str, receiver_id: str, message_type: bytes = HANDSHAKE
    ) -> "RequestMessage":
        """
        create a plain message with a certain type, for example a handshake message.

        Parameters
        ----------
        sender_id: str
            id of the client (ZMQ socket identity)
        receiver_id: str
            id of the server (ZMQ socket identity)
        message_type: bytes
            message type to be sent (i.e. 'HANDSHAKE', 'EXIT' etc.)

        Returns
        -------
        message: RequestMessage
            the crafted message
        """

        message = RequestMessage([])
        message._header = RequestHeader(
            messageID=str(uuid4()),
            messageType=message_type,
            senderID=sender_id,
            receiverID=receiver_id,
            serverExecutionContext=default_server_execution_context,
        )
        payload = SerializableNone
        preserialized_payload = PreserializedEmptyByte
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(receiver_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    def __str__(self) -> str:
        return f"RequestMessage(id={self.id}, type={self.type}, header={self.header})"


class ResponseMessage:
    """
    A single unit of message from a ZMQ server to client.
    The message may be parsed and deserialized into header and body.

    Message indices:

    | Index | 0       |   2    | 3    |     4            |
    |-------|---------|--------|------|------------------|
    | Desc  | address | header | data | pre encoded data |

    For header's JSON schema, visit [here](https://github.com/hololinked-dev/hololinked/blob/main/hololinked/core/zmq/response_message_header_schema.json).
    """

    length = Integer(default=5, readonly=True, class_member=True, doc="length of the message")  # type: int

    def __init__(self, msg: list[bytes]):
        self._bytes = msg
        self._header = None
        self._body = None
        self._sender_id = None

    @property
    def byte_array(self) -> list[bytes]:
        """the message in bytes, either after being composed or as received from the socket.

        Message indices:

        | Index | 0       |   2    | 3    |     4            |
        |-------|---------|--------|------|------------------|
        | Desc  | address | header | data | pre encoded data |
        """
        return self._bytes

    @property
    def id(self) -> str:
        """ID of the message"""
        return self.header["messageID"]

    @property
    def type(self) -> str:
        """type of the message"""
        return self.header["messageType"]

    @property
    def receiver_id(self) -> str:
        """ID of the sender"""
        return self.header["receiverID"]

    @property
    def sender_id(self) -> str:
        """ID of the receiver"""
        return self.header["senderID"]

    @property
    def header(self) -> JSON:
        """header of the message"""
        if self._header is None:
            self.parse_header()
        return self._header

    @property
    def body(self) -> tuple[SerializableData, PreserializedData]:
        """body of the message"""
        if self._body is None:
            self.parse_body()
        return self._body

    @property
    def payload(self) -> SerializableData:
        """payload of the message"""
        return self.body[0]

    @property
    def preserialized_payload(self) -> PreserializedData:
        """pre-encoded payload of the message"""
        return self.body[1]

    @property
    def oneof_valid_payload(self) -> SerializableData | PreserializedData:
        """
        checks if only one of payload or preserialized payload is valid (non-empty),
        and returns that. To be used with non-multipart messages (multipart as in
        containing multiple content types). This property can lead to loss of information
        if any response contains both payload and preserialized payload.
        """
        if self._body[1].value != b"":
            return self._body[1]
        return self._body[0]

    def parse_header(self) -> None:
        """parse the header"""
        if isinstance(self._bytes[INDEX_HEADER], ResponseHeader):
            self._header = self._bytes[INDEX_HEADER]
        elif isinstance(self._bytes[INDEX_HEADER], byte_types):
            self._header = ResponseHeader(**Serializers.json.loads(self._bytes[INDEX_HEADER]))
        else:
            raise ValueError(f"header must be of type ResponseHeader or bytes, not {type(self._bytes[INDEX_HEADER])}")

    def parse_body(self) -> None:
        """parse the body"""
        self._body = [
            SerializableData(self._bytes[INDEX_BODY], content_type=self.header["payloadContentType"]),
            PreserializedData(
                self._bytes[INDEX_PRESERIALIZED_BODY], content_type=self.header["preencodedPayloadContentType"]
            ),
        ]

    @classmethod
    def craft_from_arguments(
        cls,
        receiver_id: str,
        sender_id: str,
        message_type: str,
        message_id: bytes = b"",
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> "ResponseMessage":
        """
        Crafts an arbitrary response to the client using the method's arguments.

        Parameters
        ----------
        receiver_id: str
            id of the client (ZMQ socket identity)
        sender_id: str
            id of the server (ZMQ socket identity)
        message_type: str
            type of the message, possible values are 'REPLY', 'HANDSHAKE' and 'TIMEOUT'
        message_id: bytes
            message id of the original client message for which the response is being crafted
        payload: SerializableData
            response payload to send to the client
        preserialized_payload: bytes
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        ResponseMessage
            the crafted response
        """
        message = ResponseMessage([])
        message._header = ResponseHeader(
            messageType=message_type,
            messageID=message_id,
            receiverID=receiver_id,
            senderID=sender_id,
            payloadContentType=payload.content_type,
            preencodedPayloadContentType=preserialized_payload.content_type,
        )
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(receiver_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    @classmethod
    def craft_reply_from_request(
        cls,
        request_message: RequestMessage,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> "ResponseMessage":
        """
        Craft a response with certain data extracted from an originating client message,
        like the client's address, message id etc.

        Parameters
        ----------
        request_message: RequestMessage
            The message originated by the client for which the response is being crafted
        payload: SerializableData
            response payload to send to the client
        preserialized_payload: PreserializedData
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        ResponseMessage
            the crafted response
        """
        message = ResponseMessage([])
        message._header = ResponseHeader(
            messageType=REPLY,
            messageID=request_message.id,
            receiverID=request_message.sender_id,
            senderID=request_message.receiver_id,
            payloadContentType=payload.content_type,
            preencodedPayloadContentType=preserialized_payload.content_type,
        )
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(request_message.sender_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    @classmethod
    def craft_with_message_type(
        cls,
        request_message: RequestMessage,
        message_type: str,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> "ResponseMessage":
        """
        create a plain message with a certain type, for example a handshake message.

        Parameters
        ----------
        request_message: RequestMessage
            The message originated by the client for which the response is being crafted
        message_type: str
            message type to be sent
        payload: SerializableData
            response payload to send to the client
        preserialized_payload: PreserializedData
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        ResponseMessage
            the crafted response
        """
        message = ResponseMessage([])
        message._header = ResponseHeader(
            messageType=message_type,
            messageID=request_message.id,
            receiverID=request_message.sender_id,
            senderID=request_message.receiver_id,
            payloadContentType=payload.content_type,
            preencodedPayloadContentType=preserialized_payload.content_type,
        )
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(request_message.sender_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    def __str__(self) -> str:
        return f"ResponseMessage(id={self.id}, type={self.type}, header={self.header})"


class EventMessage(ResponseMessage):
    """
    Event message class for handling events in the system.

    Message indices:

    | Index | 0       | 1      |   2     |          3            |
    |-------|---------|--------|---------|-----------------------|
    | Desc  | address | header | payload | preserialized payload |

    """

    # For header's JSON schema, visit [here](https://hololinked.readthedocs.io/en/latest/protocols/zmq/event-message-header.json).

    @classmethod
    def craft_from_arguments(
        cls,
        event_id: str,
        sender_id: str,
        message_type: str = EVENT,
        payload: SerializableData = SerializableNone,
        preserialized_payload: PreserializedData = PreserializedEmptyByte,
    ) -> "EventMessage":
        """
        create a plain message with a certain type, for example a handshake message.

        Parameters
        ----------
        event_id: str
            id of the event (used by ZMQ pub-sub)
        sender_id: str
            id of the sender (ZMQ socket identity)
        message_type: str
            message type to be sent (`EVENT` usually)
        payload: SerializableData
            event payload to send to the client
        preserialized_payload: PreserializedData
            pre-encoded data, generally used for large or custom data that is already serialized

        Returns
        -------
        EventMessage
            the crafted message
        """
        message = EventMessage([])
        message._header = EventHeader(
            messageType=message_type,
            messageID=str(uuid4()),
            eventID=event_id,
            senderID=sender_id,
            payloadContentType=payload.content_type,
            preencodedPayloadContentType=preserialized_payload.content_type,
        )
        message._body = [payload, preserialized_payload]
        message._bytes = [
            bytes(event_id, encoding="utf-8"),
            bytes(),
            Serializers.json.dumps(message._header.json()),
            payload.serialize(),
            preserialized_payload.value,
        ]
        return message

    @property
    def event_id(self) -> str:
        """unique ID of the event by which ZMQ pub-sub works"""
        return self.header["eventID"]

    def parse_header(self) -> None:
        """parse the header"""
        if isinstance(self._bytes[INDEX_HEADER], EventHeader):
            self._header = self._bytes[INDEX_HEADER]
        elif isinstance(self._bytes[INDEX_HEADER], byte_types):
            self._header = EventHeader(**Serializers.json.loads(self._bytes[INDEX_HEADER]))
        else:
            raise ValueError(f"header must be of type ResponseHeader or bytes, not {type(self._bytes[INDEX_HEADER])}")

    def __str__(self) -> str:
        return f"EventMessage(id={self.id}, type={self.type}, header={self.header})"
