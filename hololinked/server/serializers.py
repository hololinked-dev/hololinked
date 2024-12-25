# adopted from pyro - https://github.com/irmen/Pyro5 - see following license
"""
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
import pickle
from msgspec import json as msgspecjson, msgpack 
import json as pythonjson
import inspect
import array
import datetime
import uuid
import decimal
import typing
import warnings
from enum import Enum
from collections import deque

try:
    import numpy 
except ImportError:
    pass 

from ..param.parameters import TypeConstrainedList, TypeConstrainedDict, TypedKeyMappingsConstrainedDict
from .constants import JSONSerializable, Serializers
from .utils import format_exception_as_json



class BaseSerializer(object):
    """
    Base class for (de)serializer implementations. All serializers must inherit this class 
    and overload dumps() and loads() to be usable by the ZMQ message brokers. Any serializer 
    that returns bytes when serialized and a python object on deserialization will be accepted. 
    Serialization and deserialization errors will be passed as invalid message type 
    (see ZMQ messaging contract) from server side and a exception will be raised on the client.  
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = None
    
    def loads(self, data) -> typing.Any:
        "method called by ZMQ message brokers to deserialize data"
        raise NotImplementedError("implement in subclass")

    def dumps(self, data) -> bytes:
        "method called by ZMQ message brokers to serialize data"
        raise NotImplementedError("implement in subclass")
    
    def convert_to_bytes(self, data) -> bytes:
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray):
            return bytes(data)
        if isinstance(data, memoryview):
            return data.tobytes()
        raise TypeError("serializer convert_to_bytes accepts only bytes, bytearray or memoryview")
    

dict_keys = type(dict().keys())

class JSONSerializer(BaseSerializer):
    "(de)serializer that wraps the msgspec JSON serialization protocol, default serializer for all clients."

    _type_replacements = {}

    def __init__(self) -> None:
        super().__init__()
        self.type = msgspecjson

    def loads(self, data : typing.Union[bytearray, memoryview, bytes]) -> JSONSerializable:
        "method called by ZMQ message brokers to deserialize data"
        return msgspecjson.decode(self.convert_to_bytes(data))
    
    def dumps(self, data) -> bytes:
        "method called by ZMQ message brokers to serialize data"
        return msgspecjson.encode(data, enc_hook=self.default)
      
    @classmethod
    def default(cls, obj) -> JSONSerializable:
        "method called if no serialization option was found."
        if hasattr(obj, 'json'):
            # alternative to type replacement
            return obj.json()
        if isinstance(obj, msgspec.Struct):
            return obj
        if isinstance(obj, Enum):
            return obj.name
        if isinstance(obj, (set, dict_keys, deque, tuple)):
            # json module can't deal with sets so we make a tuple out of it
            return list(obj)  
        if isinstance(obj, (TypeConstrainedDict, TypeConstrainedList, TypedKeyMappingsConstrainedDict)):
            return obj._inner # copy has been implemented with same signature for both types 
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        if isinstance(obj, Exception):
            return format_exception_as_json(obj)
        if isinstance(obj, array.array):
            if obj.typecode == 'c':
                return obj.tostring()
            if obj.typecode == 'u':
                return obj.tounicode()
            return obj.tolist()
        if 'numpy' in globals() and isinstance(obj, numpy.ndarray):
            return obj.tolist()
        replacer = cls._type_replacements.get(type(obj), None)
        if replacer:
            return replacer(obj)
        raise TypeError("Given type cannot be converted to JSON : {}".format(type(obj)))
      
    @classmethod
    def register_type_replacement(cls, object_type, replacement_function) -> None:
        "register custom serialization function for a particular type"
        if object_type is type or not inspect.isclass(object_type):
            raise ValueError("refusing to register replacement for a non-type or the type 'type' itself")
        cls._type_replacements[object_type] = replacement_function


class PythonBuiltinJSONSerializer(JSONSerializer):
    "(de)serializer that wraps the python builtin JSON serialization protocol."

    def __init__(self) -> None:
        super().__init__() 
        self.type = pythonjson 
       
    def loads(self, data : typing.Union[bytearray, memoryview, bytes]) -> typing.Any:
        "method called by ZMQ message brokers to deserialize data"
        return pythonjson.loads(self.convert_to_bytes(data))

    def dumps(self, data) -> bytes:
        "method called by ZMQ message brokers to serialize data"
        data = pythonjson.dumps(data, ensure_ascii=False, allow_nan=True, default=self.default)
        return data.encode("utf-8")
       
    def dump(self, data : typing.Dict[str, typing.Any], file_desc) -> None:
        "write JSON to file"
        pythonjson.dump(data, file_desc, ensure_ascii=False, allow_nan=True, default=self.default)

    def load(cls, file_desc) -> JSONSerializable:
        "load JSON from file"
        return pythonjson.load(file_desc)


class PickleSerializer(BaseSerializer):
    "(de)serializer that wraps the pickle serialization protocol, use with encryption for safety."

    def __init__(self) -> None:
        super().__init__() 
        self.type = pickle 

    def dumps(self, data) -> bytes:
        "method called by ZMQ message brokers to serialize data"
        return pickle.dumps(data)
    
    def loads(self, data) -> typing.Any:
        "method called by ZMQ message brokers to deserialize data"
        return pickle.loads(self.convert_to_bytes(data))
    


class MsgpackSerializer(BaseSerializer):
    """
    (de)serializer that wraps the msgspec MessagePack serialization protocol, recommended serializer for ZMQ based 
    high speed applications. Set an instance of this serializer to both ``Thing.zmq_serializer`` and 
    ``hololinked.client.ObjectProxy``. Unfortunately, MessagePack is currently not supported for HTTP clients. 
    """

    def __init__(self) -> None:
        super().__init__()
        self.type = msgpack

    def dumps(self, value) -> bytes:
        return msgpack.encode(value)

    def loads(self, value) -> typing.Any:
        return msgpack.decode(self.convert_to_bytes(value))
    
serializers = {
    None      : JSONSerializer,
    'json'    : JSONSerializer, 
    'pickle'  : PickleSerializer,
    'msgpack' : MsgpackSerializer
}
    


class Serializers:
    json = JSONSerializer()
    pickle = PickleSerializer()
    msgpack = MsgpackSerializer()

    


try:
    import serpent

    class SerpentSerializer(BaseSerializer):
        """(de)serializer that wraps the serpent serialization protocol."""

        def __init__(self) -> None:
            super().__init__()
            self.type = serpent

        def dumps(self, data) -> bytes:
            "method called by ZMQ message brokers to serialize data"
            return serpent.dumps(data, module_in_classname=True)

        def loads(self, data) -> typing.Any:
            "method called by ZMQ message brokers to deserialize data"
            return serpent.loads(self.convert_to_bytes(data))

        @classmethod
        def register_type_replacement(cls, object_type, replacement_function) -> None:
            "register custom serialization function for a particular type"
            def custom_serializer(obj, serpent_serializer, outputstream, indentlevel):
                replaced = replacement_function(obj)
                if replaced is obj:
                    serpent_serializer.ser_default_class(replaced, outputstream, indentlevel)
                else:
                    serpent_serializer._serialize(replaced, outputstream, indentlevel)

            if object_type is type or not inspect.isclass(object_type):
                raise ValueError("refusing to register replacement for a non-type or the type 'type' itself")
            serpent.register_class(object_type, custom_serializer)

    serializers['serpent'] = SerpentSerializer
except ImportError:
    pass





def set_serializer_from_user_given_options(
        zmq_serializer : typing.Union[str, BaseSerializer], 
        http_serializer : typing.Union[str, JSONSerializer]
    ) -> typing.Tuple[BaseSerializer, JSONSerializer]:
    """
    We give options to specify serializer as a string or an object,  
    """ 
    if http_serializer in [None, 'json'] or isinstance(http_serializer, JSONSerializer):
        http_serializer = http_serializer if isinstance(http_serializer, JSONSerializer) else JSONSerializer()
    else:
        raise ValueError("invalid JSON serializer option : {}".format(http_serializer))
        # could also technically be TypeError 
    if isinstance(zmq_serializer, BaseSerializer):
        zmq_serializer = zmq_serializer 
        if isinstance(zmq_serializer, PickleSerializer) or zmq_serializer.type == pickle:
            warnings.warn("using pickle serializer which is unsafe, consider another like msgpack.", UserWarning)
    elif zmq_serializer == 'json' or zmq_serializer is None:
        zmq_serializer = http_serializer
    elif isinstance(zmq_serializer, str): 
        zmq_serializer = serializers.get(zmq_serializer, JSONSerializer)()
    else:
        raise ValueError("invalid rpc serializer option : {}".format(zmq_serializer))    
    return zmq_serializer, http_serializer



__all__ = ['JSONSerializer', 'PickleSerializer', 'MsgpackSerializer', 
        'serializers', 'BaseSerializer']