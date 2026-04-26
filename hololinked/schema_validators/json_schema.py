"""JSON Schema type management."""

from typing import Any

from ..constants import JSON


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

    _allowed_types = ("string", "number", "integer", "boolean", "object", "array", None)

    _replacements = {
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
    }  # type: dict[type, str | dict]

    _schemas = {}

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
        if typ in JSONSchema._replacements.keys():
            return True
        return False

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
            return typ["type"]  # type: ignore[invalid-return-type]
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
        if typ in JSONSchema._schemas.keys():
            return True
        return False

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
