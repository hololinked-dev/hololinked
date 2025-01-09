import unittest
from uuid import UUID, uuid4

from hololinked.protocols.zmq.message import (EXIT, OPERATION, HANDSHAKE, 
                                            PreserializedData, RequestHeader, RequestMessage, SerializableData) # client to server
from hololinked.protocols.zmq.message import (TIMEOUT, INVALID_MESSAGE, ERROR, REPLY, ERROR,
                                            ResponseMessage, ResponseHeader) # server to client
from hololinked.serializers.serializers import Serializers


try:
    from .utils import TestCase, TestRunner
except ImportError:
    from utils import TestCase, TestRunner
  



class MessageValidatorMixin(TestCase):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        self.server_id = 'test-server'
        self.client_id = 'test-client'
        self.thing_id = 'test-thing'

    def validate_request_message(self, request_message: RequestMessage) -> None:
        # check message ID is a UUID
        self.assertTrue(isinstance(request_message.id, UUID) or isinstance(UUID(request_message.id, version=4), UUID))
        # check message length
        self.assertEqual(len(request_message.byte_array), request_message.length)
        # check receiver which must be the server
        self.assertEqual(request_message.receiver_id, self.server_id)
        # sender_id is not set before sending message on the socket       
        self.assertEqual(request_message.sender_id, self.client_id)
        # check that all indices are bytes 
        for obj in request_message.byte_array:
            self.assertIsInstance(obj, bytes)
        # check that header is correct type
        self.assertIsInstance(request_message.header, RequestHeader)
        # check that body is correct type
        self.assertIsInstance(request_message.body, list)
        self.assertEqual(len(request_message.body), 2)
        # check that body is having both serialized and deserialized data
        self.assertIsInstance(request_message.body[0], SerializableData)
        self.assertIsInstance(request_message.body[1], PreserializedData)


    def validate_response_message(self, response_message: ResponseMessage) -> None:
        # check message ID is a UUID
        self.assertTrue(isinstance(response_message.id, UUID) or isinstance(UUID(response_message.id, version=4), UUID))
        # check message length
        self.assertEqual(len(response_message.byte_array), response_message.length)
        # check receiver which must be the client
        self.assertEqual(response_message.receiver_id, self.client_id)
        # sender_id is not set before sending message on the socket       
        self.assertEqual(response_message.sender_id, self.server_id)
        # check that all indices are bytes 
        for obj in response_message.byte_array:
            self.assertIsInstance(obj, bytes)
        # check that header is correct type
        self.assertIsInstance(response_message.header, ResponseHeader)
        # check that body is correct type
        self.assertIsInstance(response_message.body, list)
        self.assertEqual(len(response_message.body), 2)
        # check that body is having both serialized and deserialized data
        self.assertIsInstance(response_message.body[0], SerializableData)
        self.assertIsInstance(response_message.body[1], PreserializedData)



class TestMessagingContract(MessageValidatorMixin):
    """Tests request and response messages"""

    @classmethod    
    def setUpClass(self):
        super().setUpClass()
        print(f"test message contract with {self.__name__}")
    
    
    def test_1_request_message(self):
        """test the request message"""
    
        # request messages types are OPERATION, HANDSHAKE & EXIT
        request_message = RequestMessage.craft_from_arguments(
                                                        receiver_id=self.server_id,
                                                        sender_id=self.client_id, 
                                                        thing_id=self.thing_id, 
                                                        objekt='some_prop', 
                                                        operation='readProperty',
                                                    )
        self.validate_request_message(request_message)
        # check message type for the above craft_from_arguments method
        self.assertEqual(request_message.type, OPERATION)

        request_message = RequestMessage.craft_with_message_type(
            receiver_id=self.server_id,
            sender_id=self.client_id,
            message_type=HANDSHAKE
        )
        self.validate_request_message(request_message)
        # check message type for the above craft_with_message_type method
        self.assertEqual(request_message.type, HANDSHAKE)

        request_message = RequestMessage.craft_with_message_type(
            receiver_id=self.server_id,
            sender_id=self.client_id,
            message_type=EXIT
        )
        self.validate_request_message(request_message)
        # check message type for the above craft_with_message_type method
        self.assertEqual(request_message.type, EXIT)


    def test_2_response_message(self):
        """test the response message"""

        # response messages types are HANDSHAKE, TIMEOUT, INVALID_MESSAGE, ERROR and REPLY
        response_message = ResponseMessage.craft_from_arguments(
            receiver_id=self.client_id,
            sender_id=self.server_id,
            message_type=HANDSHAKE,
            message_id=uuid4(),
        )
        self.validate_response_message(response_message)
        # check message type for the above craft_with_message_type method
        self.assertEqual(response_message.type, HANDSHAKE)

        response_message = ResponseMessage.craft_from_arguments(
            receiver_id=self.client_id,
            sender_id=self.server_id,
            message_type=TIMEOUT,
            message_id=uuid4()
        )
        self.validate_response_message(response_message)
        # check message type for the above craft_with_message_type method
        self.assertEqual(response_message.type, TIMEOUT)

        response_message = ResponseMessage.craft_from_arguments(
            receiver_id=self.client_id,
            sender_id=self.server_id,
            message_type=INVALID_MESSAGE,
            message_id=uuid4()
        )
        self.validate_response_message(response_message)
        # check message type for the above craft_with_message_type method
        self.assertEqual(response_message.type, INVALID_MESSAGE)

        response_message = ResponseMessage.craft_from_arguments(
            receiver_id=self.client_id,
            sender_id=self.server_id,
            message_type=ERROR,
            message_id=uuid4(),
            payload=SerializableData(Exception('test'))
        )
        self.validate_response_message(response_message)
        self.assertEqual(response_message.type, ERROR)
        self.assertIsInstance(Serializers.json.loads(response_message._bytes[2]), dict)

        request_message = RequestMessage.craft_from_arguments(
                sender_id=self.client_id,
                receiver_id=self.server_id,
                thing_id=self.thing_id, 
                objekt='some_prop', 
                operation='readProperty',
            )
        request_message._sender_id = self.client_id # will be done by craft_from_self
        response_message = ResponseMessage.craft_reply_from_request(
            request_message=request_message,
        )
        self.validate_response_message(response_message)
        self.assertEqual(response_message.type, REPLY)
        self.assertEqual(Serializers.json.loads(response_message._bytes[2]), None)
        self.assertEqual(request_message.id, response_message.id)



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
