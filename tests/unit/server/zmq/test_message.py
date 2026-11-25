from uuid import uuid4

import pytest

from testkit.helpers import (
    AppIDs,
    validate_event_message,
    validate_request_message,
    validate_response_message,
)

from hololinked import Serializers
from hololinked.server.zmq.message import (
    ERROR,
    EXIT,
    HANDSHAKE,
    INVALID_MESSAGE,
    OPERATION,
    REPLY,
    TIMEOUT,
    EventMessage,
    PreserializedData,
    RequestMessage,
    ResponseMessage,
    SerializableData,
)


def test_01_request_message(app_ids: AppIDs) -> None:
    """Test the request message"""
    # request messages types are OPERATION, HANDSHAKE & EXIT
    request_message = RequestMessage.craft_from_arguments(
        receiver_id=app_ids.server_id,
        sender_id=app_ids.client_id,
        thing_id=app_ids.thing_id,
        objekt="some_prop",
        operation="readproperty",
    )
    validate_request_message(request_message, app_ids)
    # check message type for the above craft_from_arguments method
    assert request_message.type == OPERATION

    request_message = RequestMessage.craft_with_message_type(
        receiver_id=app_ids.server_id, sender_id=app_ids.client_id, message_type=HANDSHAKE
    )
    validate_request_message(request_message, app_ids)
    # check message type for the above craft_with_message_type method
    assert request_message.type == HANDSHAKE

    request_message = RequestMessage.craft_with_message_type(
        receiver_id=app_ids.server_id, sender_id=app_ids.client_id, message_type=EXIT
    )
    validate_request_message(request_message, app_ids)
    # check message type for the above craft_with_message_type method
    assert request_message.type == EXIT


def test_02_response_message(app_ids: AppIDs) -> None:
    """Test the response message"""
    # response messages types are HANDSHAKE, TIMEOUT, INVALID_MESSAGE, ERROR and REPLY
    response_message = ResponseMessage.craft_from_arguments(
        receiver_id=app_ids.client_id,
        sender_id=app_ids.server_id,
        message_type=HANDSHAKE,
        message_id=uuid4(),
    )
    validate_response_message(response_message, app_ids)
    # check message type for the above craft_with_message_type method
    assert response_message.type == HANDSHAKE

    response_message = ResponseMessage.craft_from_arguments(
        receiver_id=app_ids.client_id,
        sender_id=app_ids.server_id,
        message_type=TIMEOUT,
        message_id=uuid4(),
    )
    validate_response_message(response_message, app_ids)
    # check message type for the above craft_with_message_type method
    assert response_message.type == TIMEOUT

    response_message = ResponseMessage.craft_from_arguments(
        receiver_id=app_ids.client_id,
        sender_id=app_ids.server_id,
        message_type=INVALID_MESSAGE,
        message_id=uuid4(),
    )
    validate_response_message(response_message, app_ids)
    # check message type for the above craft_with_message_type method
    assert response_message.type == INVALID_MESSAGE

    response_message = ResponseMessage.craft_from_arguments(
        receiver_id=app_ids.client_id,
        sender_id=app_ids.server_id,
        message_type=ERROR,
        message_id=uuid4(),
        payload=SerializableData(Exception("test")),
    )
    validate_response_message(response_message, app_ids)
    assert response_message.type == ERROR
    assert isinstance(Serializers.json.loads(response_message._bytes[2]), dict)

    request_message = RequestMessage.craft_from_arguments(
        sender_id=app_ids.client_id,
        receiver_id=app_ids.server_id,
        thing_id=app_ids.thing_id,
        objekt="some_prop",
        operation="readProperty",
    )
    request_message._sender_id = app_ids.client_id  # will be done by craft_from_self
    response_message = ResponseMessage.craft_reply_from_request(
        request_message=request_message,
    )
    validate_response_message(response_message, app_ids)
    assert response_message.type == REPLY
    assert Serializers.json.loads(response_message._bytes[3]) is None  # INDEX_BODY = 3
    assert request_message.id == response_message.id


def test_03_event_message(app_ids: AppIDs) -> None:
    """Test the event message"""
    event_message = EventMessage.craft_from_arguments(
        event_id="test-event",
        sender_id=app_ids.server_id,
        payload=SerializableData("test"),
        preserialized_payload=PreserializedData(b"test"),
    )
    validate_event_message(event_message, app_ids)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
