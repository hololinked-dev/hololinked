"""JSON Schema type management."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import BaseModel

from hololinked.constants import JSON
from hololinked.core.interfaces import BaseSchemaValidator
from hololinked.utils import MappableSingleton, issubklass


class JSONSchema:
    """
    JSON Schema type management.

    Handles converting highly specific python types to JSON schema types.
    One needs to explicitly register such python types with the `register_type_replacement` method to be able to
    insert JSON schema in JSON documents (like the Thing Description).

    ```python
    JSONSchema.register_type_replacement(Image, 'string', schema=dict(contentEncoding='base64'))
    JSONSchema.register_type_replacement(MyCustomObject, 'object', schema=MyCustomObject.schema())
    ```

    Validation of JSON schema, say for properties or action payloads, is carried out by the `JSONSchemaValidator`
    class which is separate.
    """

    _allowed_types: ClassVar = ("string", "number", "integer", "boolean", "object", "array", None)

    _replacements: ClassVar[dict[type, str | dict]] = {
        int: "integer",
        float: "number",
        str: "string",
        bool: "boolean",
        dict: "object",
        list: "array",
        tuple: "array",
        set: "array",
        type(None): "null",
        Exception: {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "type": {"type": "string"},
                "traceback": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["message", "type", "traceback"],
        },
    }

    _schemas: ClassVar = {}

    @classmethod
    def is_allowed_type(cls, typ: Any) -> bool:
        """
        Check if a certain base type has a JSON schema base type.

        For example:

        ```python
        JSONSchema.is_allowed_type(int)  # returns True
        JSONSchema.is_allowed_type(MyCustomClass)  # returns False

        JSONSchema.register_type_replacement(MyCustomClass, 'object', schema=MyCustomClass.schema())
        JSONSchema.is_allowed_type(MyCustomClass)  # returns True
        ```

        Parameters
        ----------
        typ: Any
            the python type to check

        Returns
        -------
        bool
            True or False
        """
        return typ in JSONSchema._replacements

    @classmethod
    def get_base_type(cls, typ: Any) -> str:
        """
        Get the JSON schema base type for a certain python type.

        ```python
        JSONSchema.register_type_replacement(MyCustomObject, 'object', schema=MyCustomObject.schema())
        JSONSchema.get_base_type(MyCustomObject)  # returns 'object'
        ```

        Parameters
        ----------
        typ: Any
            the python type to get the JSON schema base type

        Returns
        -------
        str
            the JSON schema base type

        Raises
        ------
        TypeError
            If the type is not natively supported in JSON schema or is not registered for conversion.
        """
        if not JSONSchema.is_allowed_type(typ):
            raise TypeError(
                f"Object for wot-td has invalid type for JSON conversion. Given type - {type(typ)}. "
                + "Use JSONSchema.register_replacements on hololinked.schema_validators.JSONSchema object to recognise the type."
            )
        typ = JSONSchema._replacements[typ]
        if isinstance(typ, str):
            return typ
        if isinstance(typ, dict) and "type" in typ:
            return typ["type"]  # type: ignore
        return "object"

    @classmethod
    def register_type_replacement(self, type: Any, json_schema_base_type: str, schema: JSON | None = None) -> None:
        """
        Specify a python type to map to a specific JSON type.

        For example:
        - `JSONSchema.register_type_replacement(MyCustomObject, 'object', schema=MyCustomObject.schema())`
        - `JSONSchema.register_type_replacement(IPAddress, 'string')`
        - `JSONSchema.register_type_replacement(MyByteArray, 'array', schema=dict(items=dict(type="integer", minimum=0, maximum=255)))`
        - `JSONSchema.register_type_replacement(Image, 'string', schema=dict(contentEncoding='base64'))`

        Parameters
        ----------
        type: Any
            The Python type to register. The python type must be hashable (can be stored as a key in a dictionary).
        json_schema_base_type: str
            The base JSON schema type to map the Python type to. One of
            ('string', 'number', 'integer', 'boolean', 'object', 'array', 'null').
        schema: Optional[JSON]
            An optional JSON schema to use for the type.

        Raises
        ------
        TypeError
            If the provided JSON schema base type is not one of the allowed types.
        """
        if json_schema_base_type in JSONSchema._allowed_types:
            JSONSchema._replacements[type] = json_schema_base_type
            if schema is not None:
                JSONSchema._schemas[type] = schema
        else:
            raise TypeError(
                "json schema replacement type must be one of allowed type - 'string', 'object', 'array', 'string', "
                + f"'number', 'integer', 'boolean', 'null'. Given value {json_schema_base_type}"
            )

    @classmethod
    def has_additional_schema_definitions(cls, typ: Any) -> bool:
        """
        Check, if in additional to the JSON schema base type, additional schema definitions exists.

        Utility function to decide where to insert additional schema definitions in a JSON document.

        ```python
        JSONSchema.register_type_replacement(Image, 'string', schema=dict(contentEncoding='base64'))
        JSONSchema.has_additional_schema_definitions(Image)  # returns True
        ```

        Parameters
        ----------
        typ: Any
            the python type to check

        Returns
        -------
        bool
            True, if additional schema definitions exist for the type
        """
        return typ in JSONSchema._schemas

    @classmethod
    def get_additional_schema_definitions(cls, typ: Any):
        """
        Retrieve additional schema definitions for a certain python type.

        Returns
        -------
        JSON
            the additional schema definitions for the type

        Raises
        ------
        ValueError
            If no additional schema definitions exist for the type.
        """
        if not JSONSchema.has_additional_schema_definitions(typ):
            raise ValueError(f"Schema for {typ} not provided. register one with JSONSchema.register_type_replacement()")
        return JSONSchema._schemas[typ]


class SchemaValidatorRegistry(MappableSingleton):
    """
    Metaclass that imports a schema validator adapter the first time it is asked for.

    Each adapter lives in its own module, so resolving one never imports the dependencies of the others.
    """

    modules: ClassVar[dict[str, tuple[str, str]]] = {
        "json_schema": ("hololinked.schema_validators.json_schema", "JSONSchemaValidator"),
        "pydantic": ("hololinked.schema_validators.pydantic_model", "PydanticSchemaValidator"),
    }

    def __getattr__(cls, name: str) -> type[BaseSchemaValidator]:
        if name not in cls.modules:
            raise AttributeError(f"no schema validator is registered under the name {name!r}")
        import importlib

        module_path, attribute = cls.modules[name]
        try:
            validator = getattr(importlib.import_module(module_path), attribute)
        except ModuleNotFoundError as ex:
            if ex.name and not ex.name.startswith("hololinked"):
                raise ModuleNotFoundError(
                    f"the {name!r} schema validator needs {ex.name!r}, which is not installed. "
                    + "Please install first."
                ) from ex
            raise
        setattr(cls, name, validator)  # cache so subsequent access skips __getattr__
        return validator


class SchemaValidators(metaclass=SchemaValidatorRegistry):
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
        setattr(cls, name, validator)
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
