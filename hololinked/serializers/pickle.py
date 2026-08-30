"""Pickle serializer, wrapping the python builtin pickle module."""

import pickle  # SAST(id='hololinked.serializers.pickle.pickle_import', description='B403:blacklist', tool='bandit')

from typing import Any

from hololinked.config import global_config
from hololinked.core.interfaces import BaseSerializer


class PickleSerializer(BaseSerializer):
    """(de)serializer that wraps the pickle serialization protocol, use with encryption for safety."""

    def __init__(self) -> None:
        super().__init__()
        self.type = pickle

    def loads(self, data: bytearray | memoryview | bytes) -> Any:
        if global_config.ALLOW_PICKLE:
            return pickle.loads(self.convert_to_bytes(data))
            # SAST(id='hololinked.serializers.pickle.PickleSerializer.loads', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle deserialization is not allowed by the global configuration")

    def dumps(self, data: Any) -> bytes:
        if global_config.ALLOW_PICKLE:
            return pickle.dumps(data)
            # SAST(id='hololinked.serializers.pickle.PickleSerializer.dumps', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle serialization is not allowed by the global configuration")

    @property
    def content_type(self) -> str:
        return "application/x-pickle"
