"""MessagePack serializer, wrapping msgspec."""

import io

from typing import Any

from msgspec import msgpack

from hololinked.core.interfaces import BaseSerializer


# default dytypes:
try:
    import numpy
except ImportError:
    pass


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
        """
        Encode types that MessagePack does not support natively, currently numpy arrays.

        Parameters
        ----------
        obj: Any
            the object to be serialized

        Returns
        -------
        Any
            a MessagePack serializable representation of the object

        Raises
        ------
        TypeError
            if the object cannot be serialized to MessagePack
        """
        if "numpy" in globals() and isinstance(obj, numpy.ndarray):
            buf = io.BytesIO()
            numpy.save(buf, obj, allow_pickle=False)  # use .npy. which stores dtype, shape, order, endianness
            return msgpack.Ext(MsgpackSerializer.codes["NDARRAY_EXT"], buf.getvalue())
        raise TypeError("Given type cannot be converted to MessagePack : {}".format(type(obj)))

    @classmethod
    def ext_decode(cls, code: int, obj: memoryview) -> Any:
        """
        Decode a MessagePack extension type, currently numpy arrays.

        Parameters
        ----------
        code: int
            the extension type code
        obj: memoryview
            the payload of the extension type

        Returns
        -------
        Any
            the decoded object, or the payload itself for an unknown extension code

        Raises
        ------
        ValueError
            if a numpy array is encountered but numpy is not installed
        """
        if code == MsgpackSerializer.codes["NDARRAY_EXT"]:
            if "numpy" in globals():
                return numpy.load(io.BytesIO(obj), allow_pickle=False)
            else:
                raise ValueError("numpy is required to decode numpy array from MessagePack")
        return obj

    @property
    def content_type(self) -> str:
        return "application/msgpack"
