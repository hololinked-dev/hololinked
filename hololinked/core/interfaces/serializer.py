"""Base class for serializer implementations."""

from typing import Any


class BaseSerializer(object):
    """
    Base class for serializer implementations.

    All serializers must inherit this class
    and overload dumps() and loads() to be usable. Any serializer
    that returns bytes when serialized and a python object on deserialization will be accepted.
    Serialization and deserialization errors will be passed as invalid message type
    from server side and a exception will be raised on the client.
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = None

    def loads(self, data) -> Any:
        """Deserialize data."""
        raise NotImplementedError("implement loads()/deserialization in subclass")

    def dumps(self, data) -> bytes:
        """Serialize data."""
        raise NotImplementedError("implement dumps()/serialization in subclass")

    def convert_to_bytes(self, data) -> bytes:
        """
        Convert data to bytes if it is bytearray or memoryview.

        Returns
        -------
        bytes

        Raises
        ------
        TypeError
            if data is not bytes, bytearray or memoryview
        """
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, memoryview):
            return data.tobytes()
        raise TypeError(
            "serializer convert_to_bytes accepts only bytes, bytearray or memoryview, not type {}".format(type(data))
        )

    @property
    def content_type(self) -> str:
        """Content type of the serializer."""
        raise NotImplementedError("serializer must implement a content type")
