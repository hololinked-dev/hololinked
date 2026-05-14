"""Concrete implementations of serializers."""

from hololinked.core import Serializers

from .serializers import (
    JSONSerializer,
    MsgpackSerializer,
    PickleSerializer,
    TextSerializer,
)
from .serializers import (
    PythonBuiltinJSONSerializer as PythonBuiltinJSONSerializer,
)


default_serializer = JSONSerializer()
Serializers.default = default_serializer

Serializers.register(default_serializer, "json")
Serializers.register(MsgpackSerializer(), "msgpack")
Serializers.register(PickleSerializer(), "pickle")
Serializers.register(TextSerializer(), "text")
