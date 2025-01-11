import typing
from dataclasses import dataclass

from ..constants import JSON, ResourceTypes
from ..server.dataklasses import ActionInfoValidator


@dataclass
class Schema:
    """
    Base dataclass for all WoT schema; Implements a custom asdict method which replaces dataclasses' asdict 
    utility function
    """

    skip_keys = [] # override this to skip some dataclass attributes in the schema

    replacement_keys = {
        'context' : '@context',
        'htv_methodName' : 'htv:methodName'
    }

    def asdict(self):
        """dataclass fields as dictionary skip_keys and replacement_keys accounted"""
        schema = dict()
        for field, value in self.__dataclass_fields__.items():    
            if getattr(self, field, NotImplemented) is NotImplemented or field in self.skip_keys:
                continue
            if field in self.replacement_keys: 
                schema[self.replacement_keys[field]] = getattr(self, field)
            else: 
                schema[field] = getattr(self, field)
        return schema
    
    @classmethod
    def format_doc(cls, doc : str):
        """strip tabs, newlines, whitespaces etc."""
        doc_as_list = doc.split('\n')
        final_doc = []
        for index, line in enumerate(doc_as_list):
            line = line.lstrip('\n').rstrip('\n')
            line = line.lstrip('\t').rstrip('\t')
            line = line.lstrip('\n').rstrip('\n')
            line = line.lstrip().rstrip()   
            if index > 0:
                line = ' ' + line # add space to left in case of new line            
            final_doc.append(line)
        final_doc = ''.join(final_doc)
        final_doc = final_doc.lstrip().rstrip()
        return final_doc
    


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
    def register_type_replacement(self, type : typing.Any, json_schema_type : str, 
                                schema : typing.Optional[JSON] = None) -> None:
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
