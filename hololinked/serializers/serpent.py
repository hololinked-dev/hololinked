"""Serpent serializer, wrapping the serpent package."""

import inspect

from typing import Any

import serpent

from hololinked.core.interfaces import BaseSerializer


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
