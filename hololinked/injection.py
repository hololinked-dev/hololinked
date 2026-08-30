"""The dependency injection layer, where adapters are registered against the ports declared in `hololinked.core`."""

from __future__ import annotations

import warnings

from collections.abc import Callable, Iterator, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from hololinked.config import global_config
from hololinked.core.interfaces import BaseSchemaValidator, BaseSerializer
from hololinked.param.parameters import Parameter, String
from hololinked.utils import MappableSingleton, issubklass


class AdapterRegistry(MappableSingleton):
    """
    Metaclass that imports an adapter the first time it is asked for (i.e. a lazy import).

    Adapter is a concrete implementation of a specific dependency, for example, `JSONSchemaValidator` is an adapter for
    schema validation based on JSON schema, whereas pydantic is a different implementation. However, their interfaces
    or external behaviour is similar, so they can be used interchangeably or for different technological reasons.

    Each adapter lives in its own module, so resolving one never imports the dependencies of the others. This lets
    one install only the dependencies you need. For individual adapters types, for example schema validators or
    serializers, a registry class is defined that uses this metaclass to resolve adapters by name, as a lazy import
    at runtime.

    This metaclass providers lazy import functionality.
    """

    modules: ClassVar[dict[str, tuple[str, str]]] = {}
    """Name of an implementation mapped to the module path and attribute it is imported from."""

    tables: ClassVar[tuple[str, ...]] = ()
    """
    Names of the registry's lookup dictionaries, snapshotted at class creation. 
    One can clear the cache using `forget_adapters()`.
    """

    adapter_kind: ClassVar[str] = "adapter"
    """What this registry holds ("serializers", "schema-validators", "ddl" etc.), used in error messages."""

    instantiate: ClassVar[bool] = False
    """Whether a resolved adapter class needs to be instantiated, or whether the class itself is what is used."""

    def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any) -> None:
        """Initialize the registry."""
        super().__init__(name, bases, namespace, **kwargs)
        cls._installed = set()  # type: set[str]
        cls._adapters = {}  # type: dict[tuple[str, str], Any]
        cls._pristine = {table: dict(getattr(cls, table)) for table in cls.tables}

    def __getattr__(cls, name: str) -> Any:
        if name not in cls.modules:
            raise AttributeError(f"no {cls.adapter_kind} is registered under the name {name!r}")
        import importlib

        module_path, attribute = cls.modules[name]
        try:
            adapter = getattr(importlib.import_module(module_path), attribute)
        except ModuleNotFoundError as ex:
            if ex.name and not ex.name.startswith("hololinked"):
                raise ModuleNotFoundError(
                    f"the {name!r} {cls.adapter_kind} needs {ex.name!r}, which is not installed. "
                    + "Please install first."
                ) from ex
            raise
        if cls.instantiate:
            # one instance per adapter class, so that aliases resolving to the same class - Serializers.default
            # and Serializers.json, say - also resolve to the same object
            if (module_path, attribute) not in cls._adapters:
                cls._adapters[(module_path, attribute)] = adapter()
            adapter = cls._adapters[(module_path, attribute)]
        cls.install(name, adapter)
        return adapter

    def install(cls, name: str, adapter: Any) -> None:
        """
        Caching the adapter so that subsequent access skips `__getattr__`.

        Parameters
        ----------
        name: str
            the name to serve the adapter under
        adapter: Any
            the adapter, a class or an instance depending on the registry
        """
        setattr(cls, name, adapter)
        cls._installed.add(name)

    def forget_adapters(cls) -> None:
        """Drop every resolved adapter and restore the lookup tables, leaving the registry as it was on import."""
        for name in cls._installed | set(cls.modules):
            if name in cls.__dict__:
                delattr(cls, name)
        cls._installed.clear()
        cls._adapters.clear()
        for table, pristine in cls._pristine.items():
            current = getattr(cls, table)
            current.clear()
            current.update(pristine)


class Registry(metaclass=AdapterRegistry):
    """
    Base for the registries below, so that a registry instance resolves adapters the way its class does.

    All members are class attributes, and only the metaclass knows how to resolve an unresolved adapter
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(type(self), name)


class SchemaValidators(Registry):
    """
    A singleton registry that decides which schema validator class validates against a given schema.

    All members are class attributes and settings are applied process-wide (python process).
    Which validator handles a schema is decided by the class of the payload type.
    Usually pydantic models invoke a pydantic validator and dictionaries invoke a JSON schema validator,
    but the mapping can be changed by registering a new validator. Use `register()` with a `predicate` function to
    activate a custom validator.

    ```python
    from hololinked import SchemaValidators

    SchemaValidators.register_lazy(
        "my_package.validators",
        "MsgspecValidator",
        "msgspec",
        predicate=lambda schema: issubklass(schema, msgspec.Struct),
    )

    class MyThing(Thing):
        @action(input_schema=MyStruct)  # validated by MsgspecValidator
        def act(self, value): ...
    ```

    A validator registered later is selected for a schema in preference to one registered earlier, so the built-in
    JSON schema and pydantic validators can be superseded for schemas they would otherwise handle.
    """

    adapter_kind: ClassVar[str] = "schema validator"
    tables: ClassVar[tuple[str, ...]] = ("modules", "predicates")

    modules: ClassVar[dict[str, tuple[str, str]]] = {
        "json_schema": ("hololinked.schema_validators.json_schema", "JSONSchemaValidator"),
        "pydantic": ("hololinked.schema_validators.pydantic_model", "PydanticSchemaValidator"),
    }

    json_schema: type[BaseSchemaValidator]
    """JSON Schema validator class that can be instantiated with a JSON schema to validate data against that schema."""
    pydantic: type[BaseSchemaValidator]
    """
    Pydantic validator class that can be instantiated with a Pydantic model to validate data against
    the schema defined by that model.
    """

    predicates: ClassVar[dict[str, Callable[[Any], bool]]] = {
        "json_schema": lambda schema: isinstance(schema, dict),
        "pydantic": lambda schema: issubklass(schema, BaseModel),  # RootModel is a subclass of BaseModel
    }
    """
    Name of a validator mapped to a predicate deciding whether it can validate against a given schema.

    Insertion ordered and consulted in reverse, so a validator registered later is selected for a schema in
    preference to one registered earlier. Predicates must be answerable without importing the adapter they
    belong to, since they are what decides which adapter to import in the first place.
    """

    @classmethod
    def register(
        cls,
        validator: type[BaseSchemaValidator],
        name: str,
        predicate: Callable[[Any], bool],
    ) -> None:
        """
        Register a schema validator class under a given name, overriding any validator already using that name.

        Parameters
        ----------
        validator: type[BaseSchemaValidator]
            the validator class to register, must be a subclass of `BaseSchemaValidator`
        name: str
            the name to register the validator under, for example 'json_schema' or 'pydantic'
        predicate: Callable[[Any], bool]
            predicate returning whether this validator can validate against a given schema, which is how a
            property or action picks a validator for the schema it was declared with.

        Raises
        ------
        TypeError
            if the validator is not a subclass of `BaseSchemaValidator`
        """
        if not issubklass(validator, BaseSchemaValidator):
            raise TypeError(f"validator must be a subclass of BaseSchemaValidator, given : {validator}")
        cls.install(name, validator)
        cls.predicates.pop(name, None)
        cls.predicates[name] = predicate

    @classmethod
    def name_for_schema(cls, schema: Any) -> str | None:
        """
        Get the name of the validator selected for the given schema.

        ```python
        print(SchemaValidators.name_for_schema({"type": "string"}))
        # prints 'json_schema'
        print(SchemaValidators.name_for_schema(MyPydanticModel))
        # prints 'pydantic'
        ```

        Parameters
        ----------
        schema: Any
            the schema to find a validator for

        Returns
        -------
        str | None
            the name the selected validator is registered under, None if no registered validator matches the schema
        """
        for name in reversed(cls.predicates):
            if cls.predicates[name](schema):
                return name
        return None

    @classmethod
    def is_supported(cls, schema: Any) -> bool:
        """
        Check whether any registered validator can validate against the given schema.

        Parameters
        ----------
        schema: Any
            the schema to check

        Returns
        -------
        bool
            True if a registered validator matches the schema
        """
        return cls.name_for_schema(schema) is not None

    @classmethod
    def for_schema(cls, schema: Any) -> type[BaseSchemaValidator]:
        """
        Get the validator class that validates against the given schema, importing it if necessary.

        Parameters
        ----------
        schema: Any
            the schema to find a validator for

        Returns
        -------
        type[BaseSchemaValidator]
            the validator class, to be instantiated with the schema

        Raises
        ------
        TypeError
            if no registered validator matches the schema
        """
        name = cls.name_for_schema(schema)
        if name is None:
            raise TypeError(
                f"no registered schema validator can validate against a schema of type {type(schema)}. "
                + "Register one with SchemaValidators.register() or SchemaValidators.register_lazy(), "
                + "supplying a 'predicate' that recognises it."
            )
        return getattr(cls, name)

    @classmethod
    def check_schema(cls, schema: Any) -> None:
        """
        Check that the given object is a well formed schema, using whichever validator is selected for it.

        Does nothing if the selected validator has no notion of checking a schema, as is the case for pydantic
        models.

        Parameters
        ----------
        schema: Any
            the schema to check

        Raises
        ------
        TypeError
            if no registered validator matches the schema
        Exception
            whatever the selected validator raises for a malformed schema
        """
        check = getattr(cls.for_schema(schema), "check_schema", None)
        if check is not None:
            check(schema)

    @classmethod
    def reset(cls) -> None:
        """Reset the schema validator registry."""
        cls.forget_adapters()


class ContentTypeMap(Mapping):
    """
    A read-only view of the content types the serializer registry knows, resolving a serializer only when asked.

    Which content type belongs to which serializer is answerable from `Serializers.content_type_names` without
    importing anything, so listing or iterating the content types never pulls in a serializer's dependencies.
    """

    def __init__(self, registry: type[Serializers]) -> None:
        """
        Bind the view to a serializer registry.

        Parameters
        ----------
        registry: type[Serializers]
            the registry whose content types are viewed
        """
        self._registry = registry

    def __getitem__(self, content_type: str) -> BaseSerializer:
        return getattr(self._registry, self._registry.content_type_names[content_type])

    def __iter__(self) -> Iterator[str]:
        return iter(dict(self._registry.content_type_names))

    def __len__(self) -> int:
        return len(self._registry.content_type_names)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ContentTypeMap):
            return self._registry is other._registry
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._registry)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({sorted(self._registry.content_type_names)})"


class Serializers(Registry):
    """
    A singleton class that holds all serializers and provides a registry for content types.

    All members are class attributes and settings are applied process-wide (python process).
    Registration of serializer is not mandatory for any property, action or event.
    The default serializer is `JSONSerializer`, which will be provided to any unregistered object.
    """

    adapter_kind: ClassVar[str] = "serializer"
    instantiate: ClassVar[bool] = True
    tables: ClassVar[tuple[str, ...]] = ("modules", "content_type_names")

    modules: ClassVar[dict[str, tuple[str, str]]] = {
        "default": ("hololinked.serializers.json", "JSONSerializer"),
        "json": ("hololinked.serializers.json", "JSONSerializer"),
        "msgpack": ("hololinked.serializers.msgpack", "MsgpackSerializer"),
        "pickle": ("hololinked.serializers.pickle", "PickleSerializer"),
        "text": ("hololinked.serializers.text", "TextSerializer"),
        "serpent": ("hololinked.serializers.serpent", "SerpentSerializer"),
    }

    content_type_names: ClassVar[dict[str, str]] = {
        "application/json": "json",
        "application/msgpack": "msgpack",
        "application/x-pickle": "pickle",
        "text/plain": "text",
    }
    # Content type mapped to the name of the serializer that handles it.
    # Must be answerable without importing the serializer it names, since it is what decides which serializer to
    # import in the first place.

    default: BaseSerializer
    """The default serializer."""
    # some known types:
    json: BaseSerializer
    msgpack: BaseSerializer
    pickle: BaseSerializer
    text: BaseSerializer

    _content_types: ClassVar[ContentTypeMap | None] = None

    default_content_type = String(
        fget=lambda self: self.default.content_type,
        class_member=True,
        doc="The default content type for the default serializer",
    )  # type: str

    content_types = Parameter(
        default=None,
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
        name = name or serializer.__class__.__name__
        try:
            if serializer.content_type in cls.content_type_names and not override:
                raise ValueError(f"content type already registered : {serializer.content_type}")
            cls.content_type_names[serializer.content_type] = name
        except NotImplementedError:
            warnings.warn("serializer does not implement a content type", category=UserWarning)
        cls.install(name, serializer)

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
            if thing in cls.object_serializer_map and objekt in cls.object_serializer_map[thing]:
                return cls.object_serializer_map[thing][objekt]
            if thing in cls.object_content_type_map and objekt in cls.object_content_type_map[thing]:
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
            if thing in self.object_content_type_map and objekt in self.object_content_type_map[thing]:
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
        from hololinked.core import Action, Event, Property, Thing

        if not isinstance(serializer, BaseSerializer):
            raise ValueError(f"serializer must be an instance of BaseSerializer, given : {type(serializer)}")
        if not isinstance(objekt, (Property, Action, Event)) and not issubklass(objekt, Thing):
            raise ValueError(f"object must be a Property, Action or Event, or Thing, got : {type(objekt)}")
        if issubklass(objekt, Thing):
            owner = objekt.__name__
        elif not objekt.owner:
            raise ValueError(f"object owner cannot be determined : {objekt}")
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
        from hololinked.core import Action, Event, Property, Thing

        if not isinstance(objekt, (Property, Action, Event)) and not issubklass(objekt, Thing):
            raise ValueError(f"object must be a Property, Action or Event, got : {type(objekt)}")
        if issubklass(objekt, Thing):
            owner = objekt.__name__
        elif not objekt.owner:
            raise ValueError(f"object owner cannot be determined, cannot register content type: {objekt}")
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
        from hololinked.core import Action, Event, Property, Thing  # noqa

        if not isinstance(objekt, (Property, Action, Event, str)):
            raise ValueError(f"object must be a Property, Action or Event, got : {type(objekt)}")
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
        cls.forget_adapters()

    @content_types.getter
    def get_content_types(cls: type[Serializers]) -> ContentTypeMap:
        """
        Get the mapping of content type to serializer.

        Returns
        -------
        ContentTypeMap
            a read-only mapping that imports a serializer only when one is looked up
        """
        if cls._content_types is None:
            cls._content_types = ContentTypeMap(cls)
        return cls._content_types

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
        _allowed_content_types = list(cls.content_type_names.keys())
        for content_type, name in list(cls.content_type_names.items()):
            # the name is compared instead of the serializer, so that asking which content types are allowed
            # never imports the pickle serializer
            if name != "pickle":
                continue
            _allowed_content_types.remove(content_type)
            if global_config.ALLOW_PICKLE:
                _allowed_content_types.append(content_type)
        return _allowed_content_types
