"""A serializer registry for content types and serializers."""

import warnings

from typing import Any

from hololinked.config import global_config
from hololinked.core import Action, Event, Property, Thing  # noqa
from hololinked.core.interfaces import BaseSerializer
from hololinked.param.parameters import Parameter, String
from hololinked.utils import MappableSingleton, issubklass


class Serializers(metaclass=MappableSingleton):
    """
    A singleton class that holds all serializers and provides a registry for content types.

    All members are class attributes and settings are applied process-wide (python process).
    Registration of serializer is not mandatory for any property, action or event.
    The default serializer is `JSONSerializer`, which will be provided to any unregistered object.
    """

    default = BaseSerializer()
    """The default serializer."""

    # some known types:
    json: BaseSerializer
    msgpack: BaseSerializer
    pickle: BaseSerializer
    text: BaseSerializer

    default_content_type = String(
        fget=lambda self: self.default.content_type,
        class_member=True,
        doc="The default content type for the default serializer",
    )  # type: str

    content_types = Parameter(
        default={},
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
        Register a new serializer to be generally available for the running application.

        It is recommended to implement a content type property/attribute for the serializer
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
        cls[name or serializer.__class__.__name__] = serializer

    @classmethod
    def for_object(cls, thing_id: str, thing_cls: str, objekt: str) -> BaseSerializer:
        """
        Retrieve a serializer for a given property, action or event.

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
        Retrieve a content type for a given property, action or event.

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
        Register (an existing) serializer for a property, action or event.

        Other option is to register a content type, the effects are similar.

        Parameters
        ----------
        objekt: str | Property | Action | Event
            the property, action or event
        serializer: BaseSerializer
            the serializer to be used

        Raises
        ------
        ValueError
            if the object is not a Property, Action or Event, or Thing class
        """
        if not isinstance(serializer, BaseSerializer):
            raise ValueError("serializer must be an instance of BaseSerializer, given : {}".format(type(serializer)))
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
        Register a content type for a property, action or event to use a specific serializer.

        Other option is to register a serializer directly, the effects are similar. If no serializer is found,
        content type could still be used as metadata.

        Parameters
        ----------
        thing_id: str
            the id of the Thing that owns the property, action or event
        objekt: str
            the name of the property, action or event
        content_type: str
            the content type to be used

        Raises
        ------
        ValueError
            if the object is not a Property, Action or Event
        """
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
        """Reset the serializer registry."""
        cls.object_content_type_map.clear()
        cls.object_serializer_map.clear()
        cls.protocol_serializer_map.clear()
        cls.default = BaseSerializer()
        cls.content_types.clear()

    @allowed_content_types.getter
    def get_allowed_content_types(cls) -> list[str]:
        """
        Get a list of all allowed content types for serialization.

        Set `global_config.ALLOW_PICKLE` to `True` to allow pickle content type,
        which is not allowed by default for security reasons.

        Returns
        -------
        list[str]
            a list of allowed content types
        """
        _allowed_content_types = list(cls.content_types.keys())
        if hasattr(cls, "pickle"):
            _allowed_content_types.remove(cls.pickle.content_type)
            if global_config.ALLOW_PICKLE:
                _allowed_content_types.append(cls.pickle.content_type)
        return _allowed_content_types
