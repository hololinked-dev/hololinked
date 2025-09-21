import typing
from dataclasses import dataclass

from ..constants import byte_types
from .serializers import Serializers, BaseSerializer


@dataclass
class SerializableData:
    """
    A container for data that can be serialized.
    The content type decides the serializer to be used.
    """

    value: typing.Any
    serializer: BaseSerializer | None = None
    content_type: str = "application/json"

    def serialize(self):
        """serialize the value"""
        if isinstance(self.value, byte_types):
            return self.value
        if self.serializer is not None:
            return self.serializer.dumps(self.value)
        serializer = Serializers.content_types.get(self.content_type, None)
        if serializer is not None:
            return serializer.dumps(self.value)
        raise ValueError(f"content type {self.content_type} not supported for serialization")

    def deserialize(self):
        """deserialize the value"""
        if not isinstance(self.value, byte_types):
            return self.value
        if self.serializer is not None:
            return self.serializer.loads(self.value)
        serializer = Serializers.content_types.get(self.content_type, None)
        if serializer is not None:
            return serializer.loads(self.value)
        raise ValueError(f"content type {self.content_type} not supported for deserialization")


@dataclass
class PreserializedData:
    """
    A container for data that is already serialized.
    The content type may indicate the serializer used.
    """

    value: bytes
    content_type: str = "unknown"
