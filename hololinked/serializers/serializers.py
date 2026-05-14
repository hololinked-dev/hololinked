"""
Concrete implementations of serializers.

adopted from pyro - https://github.com/irmen/Pyro5 - see following license

MIT License

Copyright (c) Irmen de Jong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import array
import datetime
import decimal
import inspect
import io
import json as pythonjson
import pickle  # SAST(id='hololinked.serializers.serializers.pickle_import', description='B403:blacklist', tool='bandit')
import uuid

from collections import deque
from enum import Enum
from typing import Any

from msgspec import Struct, msgpack
from msgspec import json as msgspecjson

from hololinked.config import global_config
from hololinked.core.interfaces import BaseSerializer


# default dytypes:
try:
    import numpy
except ImportError:
    pass

from hololinked.constants import JSONSerializable
from hololinked.param.parameters import (
    TypeConstrainedDict,
    TypeConstrainedList,
    TypedKeyMappingsConstrainedDict,
)
from hololinked.utils import format_exception_as_json


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


class PickleSerializer(BaseSerializer):
    """(de)serializer that wraps the pickle serialization protocol, use with encryption for safety."""

    def __init__(self) -> None:
        super().__init__()
        self.type = pickle

    def loads(self, data: bytearray | memoryview | bytes) -> Any:
        if global_config.ALLOW_PICKLE:
            return pickle.loads(self.convert_to_bytes(data))
            # SAST(id='hololinked.serializers.serializers.PickleSerializer.loads', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle deserialization is not allowed by the global configuration")

    def dumps(self, data: Any) -> bytes:
        if global_config.ALLOW_PICKLE:
            return pickle.dumps(data)
            # SAST(id='hololinked.serializers.serializers.PickleSerializer.dumps', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle serialization is not allowed by the global configuration")

    @property
    def content_type(self) -> str:
        return "application/x-pickle"


class MsgpackSerializer(BaseSerializer):
    """
    Serializer that wraps the msgspec MessagePack serialization protocol.

    Recommended serializer for highspeed applications.
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = msgpack

    codes = dict(NDARRAY_EXT=1)

    def loads(self, data: bytearray | memoryview | bytes) -> Any:
        return msgpack.decode(self.convert_to_bytes(data), ext_hook=self.ext_decode)

    def dumps(self, data: Any) -> bytes:
        return msgpack.encode(data, enc_hook=self.default_encode)

    @classmethod
    def default_encode(cls, obj) -> Any:
        if "numpy" in globals() and isinstance(obj, numpy.ndarray):
            buf = io.BytesIO()
            numpy.save(buf, obj, allow_pickle=False)  # use .npy. which stores dtype, shape, order, endianness
            return msgpack.Ext(MsgpackSerializer.codes["NDARRAY_EXT"], buf.getvalue())
        raise TypeError("Given type cannot be converted to MessagePack : {}".format(type(obj)))

    @classmethod
    def ext_decode(cls, code: int, obj: memoryview) -> Any:
        if code == MsgpackSerializer.codes["NDARRAY_EXT"]:
            if "numpy" in globals():
                return numpy.load(io.BytesIO(obj), allow_pickle=False)
            else:
                raise ValueError("numpy is required to decode numpy array from MessagePack")
        return obj

    @property
    def content_type(self) -> str:
        return "application/msgpack"


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


try:
    import serpent

    class SerpentSerializer(BaseSerializer):
        """Serializer that wraps the serpent serialization protocol."""

        def __init__(self) -> None:
            super().__init__()
            self.type = serpent

        def dumps(self, data) -> bytes:
            return serpent.dumps(data, module_in_classname=True)

        def loads(self, data) -> Any:
            return serpent.loads(self.convert_to_bytes(data))

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
                the object, not bytes.

            Raises
            ------
            ValueError
                if the object_type is not a type or is the type 'type' itself
            """

            def custom_serializer(obj, serpent_serializer, outputstream, indentlevel):
                replaced = replacement_function(obj)
                if replaced is obj:
                    serpent_serializer.ser_default_class(replaced, outputstream, indentlevel)
                else:
                    serpent_serializer._serialize(replaced, outputstream, indentlevel)

            if object_type is type or not inspect.isclass(object_type):
                raise ValueError("refusing to register replacement for a non-type or the type 'type' itself")
            serpent.register_class(object_type, custom_serializer)

    # __all__.append(SerpentSerializer.__name__)
except ImportError:
    pass
