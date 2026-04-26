"""Generic reusable payload dataclasses for serialization and deserialization of data from/to different formats."""

from dataclasses import dataclass
from typing import Any

from ..constants import byte_types
from .serializers import BaseSerializer, Serializers


@dataclass
class SerializableData:
    """
    A container for data that can be serialized.

    Either provide a serializer or a content type to pick a suitable already supported serializer.
    """

    value: Any
    serializer: BaseSerializer | None = None
    content_type: str = "application/json"
    _serialized: bytes | None = None

    def serialize(self) -> bytes:
        """
        Serialize the value.

        Returns
        -------
        bytes
            serialized value

        Raises
        ------
        ValueError
            If no suitable serializer is found for the content type.
        """
        if self._serialized is not None:
            return self._serialized
        if isinstance(self.value, byte_types):
            return self.value
        if self.serializer is not None:
            return self.serializer.dumps(self.value)
        serializer = Serializers.content_types.get(self.content_type, None)
        if serializer is not None:
            return serializer.dumps(self.value)
        raise ValueError(f"content type {self.content_type} not supported for serialization")

    def deserialize(self) -> Any:
        """
        Deserialize the value.

        Returns
        -------
        Any
            deserialized value

        Raises
        ------
        ValueError
            If no suitable serializer is found for the content type.
        """
        if not isinstance(self.value, byte_types):
            return self.value
        if self.serializer is not None:
            return self.serializer.loads(self.value)
        serializer = Serializers.content_types.get(self.content_type, None)
        if serializer is not None:
            return serializer.loads(self.value)
        raise ValueError(f"content type {self.content_type} not supported for deserialization")

    def require_serialized(self) -> None:
        """Ensure the value is serialized. Can raise `ValueError` if no suitable serializer is found."""
        self._serialized = self.serialize()


@dataclass
class PreserializedData:
    """
    A container for data that is already serialized.

    The content type is only a metadata here. The value is expected to be bytes.
    """

    value: bytes
    content_type: str = "application/octet-stream"
