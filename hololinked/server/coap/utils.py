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
