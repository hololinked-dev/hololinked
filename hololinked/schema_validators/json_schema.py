



import typing
from ..constants import JSON



class JSONSchema:
    """type restrictor converting python types to JSON schema types"""

    _allowed_types = ('string', 'object', 'array',  'number', 'integer', 'boolean', None)

    _replacements = {
        int : 'integer',
        float : 'number',
        str : 'string',
        bool : 'boolean',
        dict : 'object',
        list : 'array',
        tuple : 'array',
        type(None) : 'null',
        Exception : {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "type": {"type": "string"},
                "traceback": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": ["string", "null"]}
            },
            "required": ["message", "type", "traceback"]
        }
    }

    _schemas = {

    }

    @classmethod
    def is_allowed_type(cls, type : typing.Any) -> bool: 
        if type in JSONSchema._replacements.keys():
            return True 
        return False 
    
    @classmethod
    def is_supported(cls, typ: typing.Any) -> bool:
        """"""
        if typ in JSONSchema._schemas.keys():
            return True 
        return False 
    
    @classmethod
    def get_type(cls, typ : typing.Any) -> str:
        if not JSONSchema.is_allowed_type(typ):
            raise TypeError(f"Object for wot-td has invalid type for JSON conversion. Given type - {type(typ)}. " +
                                "Use JSONSchema.register_replacements on hololinked.wot.td.JSONSchema object to recognise the type.")
        return JSONSchema._replacements[typ]
    
    @classmethod
    def register_type_replacement(self, type: typing.Any, json_schema_type: str, 
                                schema: typing.Optional[JSON] = None) -> None:
        """
        specify a python type as a JSON type.
        schema only supported for array and objects. 
        """
        if json_schema_type in JSONSchema._allowed_types:
            JSONSchema._replacements[type] = json_schema_type
            if schema is not None:
                if json_schema_type not in ('array', 'object'):
                    raise ValueError(f"schemas support only for array and object JSON schema types, your specified type - {type}.")
                JSONSchema._schemas[type] = schema
        else:
            raise TypeError(f"json schema replacement type must be one of allowed type - 'string', 'object', 'array', 'string', " +
                                f"'number', 'integer', 'boolean', 'null'. Given value {json_schema_type}")

    @classmethod
    def get(cls, typ : typing.Any):
        """schema for array and objects only supported"""
        if not JSONSchema.is_supported(typ):
            raise ValueError(f"Schema for {typ} not provided. register one with JSONSchema.register_type_replacement()")
        return JSONSchema._schemas[typ]
