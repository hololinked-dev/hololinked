"""
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
import warnings

from collections import deque
from enum import Enum
from typing import Any

from msgspec import Struct, msgpack
from msgspec import json as msgspecjson

from ..config import global_config


# default dytypes:
try:
    import numpy
except ImportError:
    pass

from ..constants import JSONSerializable
from ..param.parameters import (
    ClassSelector,
    Parameter,
    String,
    TypeConstrainedDict,
    TypeConstrainedList,
    TypedKeyMappingsConstrainedDict,
)
from ..utils import MappableSingleton, format_exception_as_json, issubklass


class BaseSerializer(object):
    """
    Base class for (de)serializer implementations. All serializers must inherit this class
    and overload dumps() and loads() to be usable. Any serializer
    that returns bytes when serialized and a python object on deserialization will be accepted.
    Serialization and deserialization errors will be passed as invalid message type
    from server side and a exception will be raised on the client.
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = None

    def loads(self, data) -> Any:
        """deserialize data"""
        raise NotImplementedError("implement loads()/deserialization in subclass")

    def dumps(self, data) -> bytes:
        """serialize data"""
        raise NotImplementedError("implement dumps()/serialization in subclass")

    def convert_to_bytes(self, data) -> bytes:
        """convert data to bytes if it is bytearray or memoryview"""
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
        """content type of the serializer"""
        raise NotImplementedError("serializer must implement a content type")


dict_keys = type(dict().keys())


class JSONSerializer(BaseSerializer):
    """(de)serializer that wraps the msgspec JSON serialization protocol, default serializer for hololinked"""

    _type_replacements = {}

    def __init__(self) -> None:
        super().__init__()
        self.type = msgspecjson

    def loads(self, data: bytearray | memoryview | bytes) -> JSONSerializable:
        return msgspecjson.decode(self.convert_to_bytes(data))

    def dumps(self, data) -> bytes:
        return msgspecjson.encode(data, enc_hook=self.default)

    @classmethod
    def default(cls, obj) -> JSONSerializable:
        """method called if no serialization option was found"""
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
        """register custom serialization function for a particular type"""
        if object_type is type or not inspect.isclass(object_type):
            raise ValueError("refusing to register replacement for a non-type or the type 'type' itself")
        cls._type_replacements[object_type] = replacement_function

    @property
    def content_type(self) -> str:
        return "application/json"


class PythonBuiltinJSONSerializer(JSONSerializer):
    """(de)serializer that wraps the python builtin JSON serialization protocol"""

    def __init__(self) -> None:
        super().__init__()
        self.type = pythonjson

    def loads(self, data: bytearray | memoryview | bytes) -> Any:
        return pythonjson.loads(self.convert_to_bytes(data))

    def dumps(self, data) -> bytes:
        data = pythonjson.dumps(data, ensure_ascii=False, allow_nan=True, default=self.default)
        return data.encode("utf-8")

    @classmethod
    def dump(cls, data: dict[str, Any], file_desc) -> None:
        """write JSON to file"""
        pythonjson.dump(data, file_desc, ensure_ascii=False, allow_nan=True, default=cls.default)

    @classmethod
    def load(cls, file_desc) -> JSONSerializable:
        """load JSON from file"""
        return pythonjson.load(file_desc)


class PickleSerializer(BaseSerializer):
    """(de)serializer that wraps the pickle serialization protocol, use with encryption for safety."""

    def __init__(self) -> None:
        super().__init__()
        self.type = pickle

    def dumps(self, data) -> bytes:
        if global_config.ALLOW_PICKLE:
            return pickle.dumps(data)
            # SAST(id='hololinked.serializers.serializers.PickleSerializer.dumps', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle serialization is not allowed by the global configuration")

    def loads(self, data) -> Any:
        if global_config.ALLOW_PICKLE:
            return pickle.loads(self.convert_to_bytes(data))
            # SAST(id='hololinked.serializers.serializers.PickleSerializer.loads', description='B301:blacklist', tool='bandit')
        raise RuntimeError("Pickle deserialization is not allowed by the global configuration")

    @property
    def content_type(self) -> str:
        return "application/x-pickle"


class MsgpackSerializer(BaseSerializer):
    """
    (de)serializer that wraps the msgspec MessagePack serialization protocol, recommended serializer for
    highspeed applications.
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = msgpack

    codes = dict(NDARRAY_EXT=1)

    def dumps(self, value) -> bytes:
        return msgpack.encode(value, enc_hook=self.default_encode)

    def loads(self, value) -> Any:
        return msgpack.decode(self.convert_to_bytes(value), ext_hook=self.ext_decode)

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
    """Converts string or string compatible types to bytes and vice versa"""

    def __init__(self) -> None:
        super().__init__()
        self.type = None

    def dumps(self, data) -> bytes:
        return str(data).encode("utf-8")

    def loads(self, data) -> Any:
        return data.decode("utf-8")

    @property
    def content_type(self) -> str:
        return "text/plain"


try:
    import serpent

    class SerpentSerializer(BaseSerializer):
        """(de)serializer that wraps the serpent serialization protocol."""

        def __init__(self) -> None:
            super().__init__()
            self.type = serpent

        def dumps(self, data) -> bytes:
            return serpent.dumps(data, module_in_classname=True)

        def loads(self, data) -> Any:
            return serpent.loads(self.convert_to_bytes(data))

        @classmethod
        def register_type_replacement(cls, object_type, replacement_function) -> None:
            """register custom serialization function for a particular type"""

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
    SerpentSerializer = None


class Serializers(metaclass=MappableSingleton):
    """
    A singleton class that holds all serializers and provides a registry for content types.
    All members are class attributes and settings are applied process-wide (python process).

    Registration of serializer is not mandatory for any property, action or event.
    The default serializer is `JSONSerializer`, which will be provided to any unregistered object.
    """

    json = ClassSelector(
        default=JSONSerializer(),
        class_=BaseSerializer,
        class_member=True,
        doc="The default serializer for all properties, actions and events",
    )  # type: BaseSerializer
    """JSON serializer"""

    pickle = ClassSelector(
        default=PickleSerializer(),
        class_=BaseSerializer,
        class_member=True,
        doc="pickle serializer, unsafe without encryption but useful for faster & flexible serialization of python specific types",
    )  # type: BaseSerializer
    """Pickle serializer, use global_config.ALLOW_PICKE to enable it"""

    msgpack = ClassSelector(
        default=MsgpackSerializer(),
        class_=BaseSerializer,
        class_member=True,
        doc="MessagePack serializer, efficient binary format that is both fast & interoperable between languages ",
    )  # type: BaseSerializer
    """MessagePack serializer"""

    text = ClassSelector(
        default=TextSerializer(),
        class_=BaseSerializer,
        class_member=True,
        doc="Text serializer, converts string or string compatible types to bytes and vice versa",
    )  # type: BaseSerializer
    """Text serializer"""

    default = ClassSelector(
        default=json.default,
        class_=BaseSerializer,
        class_member=True,
        doc="The default serialization to be used",
    )  # type: BaseSerializer
    """The default serializer, change value to set a different default serializer"""

    default_content_type = String(
        fget=lambda self: self.default.content_type,
        class_member=True,
        doc="The default content type for the default serializer",
    )  # type: str

    content_types = Parameter(
        default={
            json.default.content_type: json.default,  # as in the default value of the descriptor
            pickle.default.content_type: pickle.default,
            msgpack.default.content_type: msgpack.default,
            text.default.content_type: text.default,
        },
        doc="A dictionary of content types and their serializers",
        readonly=True,
        class_member=True,
    )  # type: dict[str, BaseSerializer]
    """A dictionary of content types and their serializers"""

    allowed_content_types = Parameter(
        default=None,
        class_member=True,
        doc="A list of content types that are usually considered safe and will be supported by default without any configuration",
        readonly=True,
    )  # type: list[str]
    """
    A list of content types that are usually considered safe 
    and will be supported by default without any configuration
    """

    object_content_type_map = Parameter(
        default=dict(),
        class_member=True,
        doc="A dictionary of content types for specific properties, actions and events",
        readonly=True,
    )  # type: dict[str, dict[str, str]]
    """A dictionary of content types for specific properties, actions and events"""

    object_serializer_map = Parameter(
        default=dict(),
        class_member=True,
        doc="A dictionary of serializer for specific properties, actions and events",
        readonly=True,
    )  # type: dict[str, dict[str, BaseSerializer]]
    """A dictionary of serializer for specific properties, actions and events"""

    protocol_serializer_map = Parameter(
        default=dict(),
        class_member=True,
        doc="A dictionary of serializer for a specific protocol",
        readonly=True,
    )  # type: dict[str, BaseSerializer]
    """A dictionary of default serializer for a specific protocol, currently unimplemented"""

    @classmethod
    def register(cls, serializer: BaseSerializer, name: str | None = None, override: bool = False) -> None:
        """
        Register a new serializer. It is recommended to implement a content type property/attribute for the serializer
        to facilitate automatic deserialization on client side, otherwise deserialization is not gauranteed.
        Moreover, the said serializer must be defined on both client and server side if running in a distributed
        environment.

        Parameters
        ----------
        serializer: BaseSerializer
            the serializer to register
        name: str, optional
            the name of the serializer to be accessible under the object namespace. If not provided, the name of the
            serializer class is used.
        override: bool, optional
            whether to override the serializer if the content type is already registered,
            by default False & raises ValueError for duplicate content type. For example, registering
            a custom JSON serializer will conflict with the default JSONSerializer, so set `override=True`.

        Raises
        ------
        ValueError
            if the serializer content type is already registered
        """
        try:
            if serializer.content_type in cls.content_types and not override:
                raise ValueError("content type already registered : {}".format(serializer.content_type))
            cls.content_types[serializer.content_type] = serializer
        except NotImplementedError:
            warnings.warn("serializer does not implement a content type", category=UserWarning)
        cls[name or serializer.__name__] = serializer

    @classmethod
    def for_object(cls, thing_id: str, thing_cls: str, objekt: str) -> BaseSerializer | None:
        """
        Retrieve a serializer for a given property, action or event

        Parameters
        ----------
        thing_id: str | Any
            the id of the Thing or the Thing that owns the property, action or event
        thing_cls: str | Any
            the class name of the Thing or the Thing that owns the property, action or event
        objekt: str
            the name of the property, action or event

        Returns
        -------
        BaseSerializer | JSONSerializer
            the serializer for the property, action or event. If no serializer is found, the default JSONSerializer is
            returned.
        """
        if len(cls.object_serializer_map) == 0 and len(cls.object_content_type_map) == 0:
            return cls.default
        for thing in [thing_id, thing_cls]:  # first thing id, then thing cls
            if thing in cls.object_serializer_map:
                if objekt in cls.object_serializer_map[thing]:
                    return cls.object_serializer_map[thing][objekt]
            if thing in cls.object_content_type_map:
                if objekt in cls.object_content_type_map[thing]:
                    return cls.content_types.get(cls.object_content_type_map[thing][objekt], None)
                    # if said content type has no serializer, return None instead of default serializer
        return cls.default  # JSON is default serializer

    @classmethod
    def get_content_type_for_object(self, thing_id: str, thing_cls: str, objekt: str) -> str:
        """
        Retrieve a content type for a given property, action or event

        Parameters
        ----------
        thing_id: str | Any
            the id of the Thing or the Thing that owns the property, action or event
        thing_cls: str | Any
            the class name of the Thing or the Thing that owns the property, action or event
        objekt: str
            the name of the property, action or event

        Returns
        -------
        str
            the content type for the property, action or event. If no content type is found, the default content type is
            returned.
        """

        if len(self.object_serializer_map) == 0 and len(self.object_content_type_map) == 0:
            return self.default_content_type
        for thing in [thing_id, thing_cls]:  # first thing id, then thing cls
            if thing in self.object_content_type_map:
                if objekt in self.object_content_type_map[thing]:
                    return self.object_content_type_map[thing][objekt]
        return self.default_content_type  # JSON is default serializer

    @classmethod
    def register_for_object(cls, objekt: Any, serializer: BaseSerializer) -> None:
        """
        Register (an existing) serializer for a property, action or event. Other option is to register a content type,
        the effects are similar.

        Parameters
        ----------
        objekt: str | Property | Action | Event
            the property, action or event
        serializer: BaseSerializer
            the serializer to be used
        """
        if not isinstance(serializer, BaseSerializer):
            raise ValueError("serializer must be an instance of BaseSerializer, given : {}".format(type(serializer)))
        from ..core import Action, Event, Property, Thing

        if not isinstance(objekt, (Property, Action, Event)) and not issubklass(objekt, Thing):
            raise ValueError("object must be a Property, Action or Event, or Thing, got : {}".format(type(objekt)))
        if issubklass(objekt, Thing):
            owner = objekt.__name__
        elif not objekt.owner:
            raise ValueError("object owner cannot be determined : {}".format(objekt))
        else:
            owner = objekt.owner.__name__
        if owner not in cls.object_serializer_map:
            cls.object_serializer_map[owner] = dict()
        if issubklass(objekt, Thing):
            cls.object_serializer_map[owner][objekt.__name__] = serializer
        else:
            cls.object_serializer_map[owner][objekt.name] = serializer

    # @validate_call
    @classmethod
    def register_content_type_for_object(cls, objekt: Any, content_type: str) -> None:
        """
        Register content type for a property, action, event, or a `Thing` class to use a specific serializer.
        If no serializer is found, content type could still be used as metadata.

        Parameters
        ----------
        objekt: Property | Action | Event | Thing
            the property, action or event. string is not accepted - use `register_content_type_for_object_by_name()` instead.
        content_type: str
            the content type for the value of the objekt or the serializer to be used

        Raises
        ------
        ValueError
            if the object is not a Property, Action or Event
        """
        from ..core import Action, Event, Property, Thing

        if not isinstance(objekt, (Property, Action, Event)) and not issubklass(objekt, Thing):
            raise ValueError("object must be a Property, Action or Event, got : {}".format(type(objekt)))
        if issubklass(objekt, Thing):
            owner = objekt.__name__
        elif not objekt.owner:
            raise ValueError("object owner cannot be determined, cannot register content type: {}".format(objekt))
        else:
            owner = objekt.owner.__name__
        if owner not in cls.object_content_type_map:
            cls.object_content_type_map[owner] = dict()
        if issubklass(objekt, Thing):
            cls.object_content_type_map[owner][objekt.__name__] = content_type
            # its a redundant key, TODO - may be there is a better way to structure this map
        else:
            cls.object_content_type_map[owner][objekt.name] = content_type

    # @validate_call
    @classmethod
    def register_content_type_for_object_per_thing_instance(
        cls,
        thing_id: str,
        objekt: str | Any,
        content_type: str,
    ) -> None:
        """
        Register a content type for a property, action or event to use a specific serializer. Other option is
        to register a serializer directly, the effects are similar. If no serializer is found,
        content type could still be used as metadata.

        Parameters
        ----------
        thing_id: str
            the id of the Thing that owns the property, action or event
        objekt: str
            the name of the property, action or event
        content_type: str
            the content type to be used
        """
        from ..core import Action, Event, Property

        if not isinstance(objekt, (Property, Action, Event, str)):
            raise ValueError("object must be a Property, Action or Event, got : {}".format(type(objekt)))
        if not isinstance(objekt, str):
            objekt = objekt.name
        if thing_id not in cls.object_content_type_map:
            cls.object_content_type_map[thing_id] = dict()
        cls.object_content_type_map[thing_id][objekt] = content_type

    @classmethod
    def register_content_type_for_thing_instance(cls, thing_id: str, content_type: str) -> None:
        """
        Register a content type for a specific Thing instance.

        Parameters
        ----------
        thing_id: str
            the id of the Thing
        content_type: str
            the content type to be used
        """
        cls.object_content_type_map[thing_id][thing_id] = content_type
        # remember, its a redundant key, TODO

    @classmethod
    def register_for_object_per_thing_instance(cls, thing_id: str, objekt: str, serializer: BaseSerializer) -> None:
        """
        Register a serializer for a property, action or event for a specific Thing instance.
        If no serializer is found, content type could still be used as metadata.

        Parameters
        ----------
        thing_id: str
            the id of the Thing that owns the property, action or event
        objekt: str
            the name of the property, action or event
        serializer: BaseSerializer
            the serializer to be used
        """
        if thing_id not in cls.object_serializer_map:
            cls.object_serializer_map[thing_id] = dict()
        cls.object_serializer_map[thing_id][objekt] = serializer

    @classmethod
    def register_for_thing_instance(cls, thing_id: str, serializer: BaseSerializer) -> None:
        """
        Register a serializer for a specific Thing instance.

        Parameters
        ----------
        thing_id: str
            the id of the Thing
        serializer: BaseSerializer
            the serializer to be used
        """
        if thing_id not in cls.object_serializer_map:
            cls.object_serializer_map[thing_id] = dict()
        cls.object_serializer_map[thing_id][thing_id] = serializer

    @classmethod
    def reset(cls) -> None:
        """Reset the serializer registry"""
        cls.object_content_type_map.clear()
        cls.object_serializer_map.clear()
        cls.protocol_serializer_map.clear()
        cls.default = cls.json

    @allowed_content_types.getter
    def get_allowed_content_types(cls) -> list[str]:
        """Get a list of all allowed content types for serialization"""
        _allowed_content_types = list(cls.content_types.keys())
        _allowed_content_types.remove(cls.pickle.content_type)
        if global_config.ALLOW_PICKLE:
            _allowed_content_types.append(cls.pickle.content_type)
        return _allowed_content_types


__all__ = [
    JSONSerializer.__name__,
    PickleSerializer.__name__,
    MsgpackSerializer.__name__,
    TextSerializer.__name__,
    PythonBuiltinJSONSerializer.__name__,
    BaseSerializer.__name__,
    Serializers.__name__,
]
