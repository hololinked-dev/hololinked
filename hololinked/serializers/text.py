"""Plain text serializer."""

from typing import Any

from hololinked.core.interfaces import BaseSerializer


class TextSerializer(BaseSerializer):
    """Converts string or string compatible types to bytes and vice versa."""

    def __init__(self) -> None:
        super().__init__()
        self.type = None

    def dumps(self, data: Any) -> bytes:
        return str(data).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        return data.decode("utf-8")

    @property
    def content_type(self) -> str:
        return "text/plain"
