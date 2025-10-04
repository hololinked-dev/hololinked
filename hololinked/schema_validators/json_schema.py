import typing
from ..constants import JSON


class JSONSchema:
    """type restrictor converting python types to JSON schema types"""

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
    }

    _schemas = {}

    @classmethod
    def is_allowed_type(cls, typ: typing.Any) -> bool:
        """check if a certain base type has a JSON schema base type"""
        if typ in JSONSchema._replacements.keys():
            return True
        return False

    @classmethod
    def has_additional_schema_definitions(cls, typ: typing.Any) -> bool:
        """Check, if in additional to the JSON schema base type, additional schema definitions exists."""
        if typ in JSONSchema._schemas.keys():
            return True
        return False

    @classmethod
    def get_base_type(cls, typ: typing.Any) -> str:
        if not JSONSchema.is_allowed_type(typ):
            raise TypeError(
                f"Object for wot-td has invalid type for JSON conversion. Given type - {type(typ)}. "
                + "Use JSONSchema.register_replacements on hololinked.wot.td.JSONSchema object to recognise the type."
            )
        return JSONSchema._replacements[typ]

    @classmethod
    def register_type_replacement(
        self, type: typing.Any, json_schema_base_type: str, schema: typing.Optional[JSON] = None
    ) -> None:
        """
        Specify a python type to map to a specific JSON type.

        For example:
        - `JSONSchema.register_type_replacement(MyCustomObject, 'object', schema=MyCustomObject.schema())`
        - `JSONSchema.register_type_replacement(IPAddress, 'string')`
        - `JSONSchema.register_type_replacement(MyByteArray, 'array', schema=dict(items=dict(type="integer", minimum=0, maximum=255)))`
        - `JSONSchema.register_type_replacement(Image, 'string', schema=dict(contentEncoding='base64'))`

        Parameters
        ----------
        type: typing.Any
            The Python type to register. The python type must be hashable (can be stored as a key in a dictionary).
        json_schema_base_type: str
            The base JSON schema type to map the Python type to. One of
            ('string', 'number', 'integer', 'boolean', 'object', 'array', 'null').
        schema: typing.Optional[JSON]
            An optional JSON schema to use for the type.
        """
        if json_schema_base_type in JSONSchema._allowed_types:
            JSONSchema._replacements[type] = json_schema_base_type
            if schema is not None:
                if json_schema_base_type not in ("array", "object"):
                    raise ValueError(
                        f"schemas support only for array and object JSON schema types, your specified type - {type}."
                    )
                JSONSchema._schemas[type] = schema
        else:
            raise TypeError(
                "json schema replacement type must be one of allowed type - 'string', 'object', 'array', 'string', "
                + f"'number', 'integer', 'boolean', 'null'. Given value {json_schema_base_type}"
            )

    @classmethod
    def get_additional_schema_definitions(cls, typ: typing.Any):
        """schema for array and objects only supported"""
        if not JSONSchema.has_additional_schema_definitions(typ):
            raise ValueError(f"Schema for {typ} not provided. register one with JSONSchema.register_type_replacement()")
        return JSONSchema._schemas[typ]
