"""JSON serializers, wrapping msgspec and the python builtin json module."""

import array
import datetime
import decimal
import inspect
import json as pythonjson
import uuid

from collections import deque
from enum import Enum
from typing import Any

from msgspec import Struct
from msgspec import json as msgspecjson

from hololinked.constants import JSONSerializable
from hololinked.core.interfaces import BaseSerializer
from hololinked.param.parameters import (
    TypeConstrainedDict,
    TypeConstrainedList,
    TypedKeyMappingsConstrainedDict,
)
from hololinked.utils import format_exception_as_json


# default dytypes:
try:
    import numpy
except ImportError:
    pass


dict_keys = type(dict().keys())


class JSONSerializer(BaseSerializer):
    """Serializer that wraps the msgspec JSON serialization protocol, default serializer for this package."""

    _type_replacements = {}

    def __init__(self) -> None:
        super().__init__()
        self.type = msgspecjson

    def loads(self, data: bytearray | memoryview | bytes) -> JSONSerializable:
        return msgspecjson.decode(self.convert_to_bytes(data))

    def dumps(self, data: Any) -> bytes:
        return msgspecjson.encode(data, enc_hook=self.default)

    @classmethod
    def default(cls, obj: Any) -> JSONSerializable:
        """
        Method called if object is not serializable by default JSON encoder.

        To override, one can subclass and implement default method and call `super().default()` at the very end.
        Or one can directly register a type with `register_type_replacement()`.

        Parameters
        ----------
        obj: Any
            the object to be serialized

        Returns
        -------
        JSONSerializable
            a JSON serializable representation of the object, not bytes.

        Raises
        ------
        TypeError
            if the object cannot be serialized to JSON
        """
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "json"):
            # alternative to type replacement
            return obj.json()
        if isinstance(obj, Struct):
            return obj
        if isinstance(obj, Enum):
            return obj.name
        if isinstance(obj, (set, dict_keys, deque, tuple)):
            # json module can't deal with sets so we make a tuple out of it
            return list(obj)
        if isinstance(obj, (TypeConstrainedDict, TypeConstrainedList, TypedKeyMappingsConstrainedDict)):
            return obj._inner  # copy has been implemented with same signature for both types
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        if isinstance(obj, Exception):
            return format_exception_as_json(obj)
        if isinstance(obj, array.array):
            if obj.typecode == "c":
                return obj.tostring()
            if obj.typecode == "u":
                return obj.tounicode()
            return obj.tolist()
        if "numpy" in globals() and isinstance(obj, numpy.ndarray):
            return obj.tolist()
        replacer = cls._type_replacements.get(type(obj), None)
        if replacer:
            return replacer(obj)
        raise TypeError("Given type cannot be converted to JSON : {}".format(type(obj)))

    @classmethod
    def register_type_replacement(cls, object_type, replacement_function) -> None:
        """
        Register custom serialization function for a particular type.

        Parameters
        ----------
        object_type: type
            the type for which the replacement function is registered
        replacement_function: Function
            the function that takes an object of the given type and returns a JSON serializable representation of
            the object. `bytes` are not expected, only the JSON serializable representation.

        Raises
        ------
        ValueError
            if the object_type is not a type or is the type 'type' itself
        """
        if object_type is type or not inspect.isclass(object_type):
            raise ValueError("refusing to register replacement for a non-type or the type 'type' itself")
        cls._type_replacements[object_type] = replacement_function

    @property
    def content_type(self) -> str:
        return "application/json"


class PythonBuiltinJSONSerializer(JSONSerializer):
    """Serializer that wraps the python builtin JSON serializer."""

    def __init__(self) -> None:
        super().__init__()
        self.type = pythonjson

    def loads(self, data: bytearray | memoryview | bytes) -> Any:
        return pythonjson.loads(self.convert_to_bytes(data))

    def dumps(self, data: Any) -> bytes:
        data = pythonjson.dumps(data, ensure_ascii=False, allow_nan=True, default=self.default)
        return data.encode("utf-8")

    @classmethod
    def dump(cls, data: dict[str, Any], file_desc) -> None:
        """Write JSON to file."""
        pythonjson.dump(data, file_desc, ensure_ascii=False, allow_nan=True, default=cls.default)

    @classmethod
    def load(cls, file_desc) -> Any:
        """
        Load JSON from file.

        Returns
        -------
        Any
            the deserialized JSON object
        """
        return pythonjson.load(file_desc)
