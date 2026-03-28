import socket

from aiocoap.numbers import ContentFormat

from hololinked.serializers import Serializers


class ContentTypeMap:
    _mapping = {
        Serializers.json.content_type: ContentFormat.JSON,
        Serializers.pickle.content_type: ContentFormat.OCTETSTREAM,
        "application/octet-stream": ContentFormat.OCTETSTREAM,
        Serializers.text.content_type: ContentFormat.TEXT,
    }

    @classmethod
    def get(cls, content_type: str) -> int | None:
        return cls._mapping.get(content_type)

    @classmethod
    def supports(cls, content_type: str) -> bool:
        return content_type in cls._mapping


def get_routable_ip() -> str:
    """Get the primary routable IP address of this machine."""
    try:
        # Connect to a public address to determine which interface is used
        # for outbound traffic. No data is actually sent.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"
