import typing
from dataclasses import dataclass, field
from .base import Schema, JSONSchema, JSON


@dataclass
class DataSchema(Schema):
    """
    implementes Dataschema attributes.
    https://www.w3.org/TR/wot-thing-description11/#sec-data-schema-vocabulary-definition
    """
    title: str 
    titles: typing.Optional[typing.Dict[str, str]]
    description: str
    descriptions: typing.Optional[typing.Dict[str, str]] 
    const: bool
    default: typing.Optional[typing.Any] 
    readOnly: bool
    writeOnly: bool # write only are to be considered actions with no return value
    format: typing.Optional[str]
    unit: typing.Optional[str]
    type: str
    oneOf: typing.Optional[typing.List[JSON]]
    enum: typing.Optional[typing.List[typing.Any]]

    def __init__(self):
        super().__init__()

    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import Property
        assert isinstance(property, Property), f"only Property is a subclass of dataschema, not {type(property)}"
        self.title = property.label or property.name 
        if property.constant:
            self.const = property.constant 
        if property.readonly:
            self.readOnly = property.readonly
        if property.default is not None:
            self.default = property.default
        if property.doc:
            self.description = Schema.format_doc(property.doc)
        if property.metadata and property.metadata.get("unit", None) is not None:
            self.unit = property.metadata["unit"]
        if property.allow_None:
            if not hasattr(self, 'oneOf'):
                self.oneOf = []
            if hasattr(self, 'type'):
                self.oneOf.append(dict(type=self.type))
                del self.type 
            if not any(types["type"] == None for types in self.oneOf):
                self.oneOf.append(dict(type="null"))



@dataclass
class BooleanSchema(DataSchema):
    """
    boolean schema - https://www.w3.org/TR/wot-thing-description11/#booleanschema
    used by Boolean descriptor    
    """
    def __init__(self):
        super().__init__()

    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        self.type = 'boolean'
        super()._build_from_property(property, owner)


@dataclass
class StringSchema(DataSchema):
    """
    string schema - https://www.w3.org/TR/wot-thing-description11/#stringschema
    used by String, Filename, Foldername, Path descriptors
    """
    pattern : typing.Optional[str] 
    
    def __init__(self):
        super().__init__()
        
    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import String
        self.type = 'string' 
        super()._build_from_property(property, owner)
        if isinstance(property, String): 
            if property.regex is not None:
                self.pattern = property.regex


@dataclass
class NumberSchema(DataSchema):
    """
    number schema - https://www.w3.org/TR/wot-thing-description11/#numberschema
    used by String, Filename, Foldername, Path descriptors
    """
    minimum : typing.Optional[typing.Union[int, float]]
    maximum : typing.Optional[typing.Union[int, float]]
    exclusiveMinimum : typing.Optional[bool] 
    exclusiveMaximum : typing.Optional[bool] 
    step : typing.Optional[typing.Union[int, float]]

    def __init__(self):
        super().__init__()
        
    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import Integer, Number
        if isinstance(property, Integer):
            self.type = 'integer'
        elif isinstance(property, Number): # dont change order - one is subclass of other
            self.type = 'number' 
        super()._build_from_property(property, owner)
        if property.bounds is not None:      
            if isinstance(property.bounds[0], (int, float)): # i.e. value is not None which is allowed by param
                if not property.inclusive_bounds[0]:
                    self.exclusiveMinimum = property.bounds[0]
                else:
                    self.minimum = property.bounds[0]
            if isinstance(property.bounds[1], (int, float)):
                if not property.inclusive_bounds[1]:
                    self.exclusiveMaximum = property.bounds[1]
                else:
                    self.maximum = property.bounds[1]
        if property.step:
            self.multipleOf = property.step


@dataclass
class ArraySchema(DataSchema):
    """
    array schema - https://www.w3.org/TR/wot-thing-description11/#arrayschema
    Used by List, Tuple, TypedList and TupleSelector
    """

    items : typing.Optional[JSON]
    minItems : typing.Optional[int]
    maxItems : typing.Optional[int]

    def __init__(self):
        super().__init__()
        
    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import List, Tuple, TypedList, TupleSelector
        self.type = 'array'
        super()._build_from_property(property, owner)
        self.items = []
        if isinstance(property, (List, Tuple, TypedList)) and property.item_type is not None:
            if property.bounds:
                if property.bounds[0]:
                    self.minItems = property.bounds[0]
                if property.bounds[1]:
                    self.maxItems = property.bounds[1]
            if isinstance(property.item_type, (list, tuple)):
                for typ in property.item_type:
                    self.items.append(dict(type=JSONSchema.get_type(typ)))
            elif property.item_type is not None: 
                self.items.append(dict(type=JSONSchema.get_type(property.item_type)))
        elif isinstance(property, TupleSelector):
            objects = list(property.objects)
            for obj in objects:
                if any(types["type"] == JSONSchema._replacements.get(type(obj), None) for types in self.items):
                    continue 
                self.items.append(dict(type=JSONSchema.get_type(type(obj))))
        if len(self.items) == 0:
            del self.items
        elif len(self.items) > 1:
            self.items = dict(oneOf=self.items)
            

@dataclass
class ObjectSchema(DataSchema):
    """
    object schema - https://www.w3.org/TR/wot-thing-description11/#objectschema
    Used by TypedDict
    """
    properties : typing.Optional[JSON]
    required : typing.Optional[typing.List[str]]

    def __init__(self):
        super().__init__()
        
    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        super()._build_from_property(property, owner)
        properties = None 
        required = None 
        if hasattr(property, 'json_schema'):
            # Code will not reach here for now as have not implemented schema for typed dictionaries. 
            properties = property.json_schema["properties"]
            if property.json_schema.get("required", NotImplemented) is not NotImplemented:
                required = property.json_schema["required"] 
        if not property.allow_None:
            self.type = 'object'
            if properties:
                self.properties = properties
            if required:
                self.required = required
        else:
            schema = dict(type='object')
            if properties:
                schema['properties'] = properties
            if required:
                schema['required'] = required
            self.oneOf.append(schema)


@dataclass
class OneOfSchema(DataSchema):
    """
    custom schema to deal with ClassSelector to fill oneOf field correctly
    https://www.w3.org/TR/wot-thing-description11/#dataschema
    """
    properties : typing.Optional[JSON]
    required : typing.Optional[typing.List[str]]
    items : typing.Optional[JSON]
    minItems : typing.Optional[int]
    maxItems : typing.Optional[int]
    # ClassSelector can technically have a JSON serializable as a class_

    def __init__(self):
        super().__init__()

    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import Selector, ClassSelector
        self.oneOf = []
        if isinstance(property, ClassSelector):
            if not property.isinstance:
                raise NotImplementedError("WoT TD for ClassSelector with isinstance set to True is not supported yet. "  +
                                          "Consider user this property in a different way.")
            if isinstance(property.class_, (list, tuple)):
                objects = list(property.class_)
            else:
                objects = [property.class_]
        elif isinstance(property, Selector):
            objects = list(property.objects)
        else:
            raise TypeError(f"EnumSchema and OneOfSchema supported only for Selector and ClassSelector. Given Type - {property}")
        for obj in objects:
            if any(types["type"] == JSONSchema._replacements.get(type(obj), None) for types in self.oneOf):
                continue 
            if isinstance(property, ClassSelector):
                if not JSONSchema.is_allowed_type(obj):
                    raise TypeError(f"Object for wot-td has invalid type for JSON conversion. Given type - {obj}. " +
                                "Use JSONSchema.register_replacements on hololinked.wot.td.JSONSchema object to recognise the type.")
                subschema = dict(type=JSONSchema.get_type(obj))
                if JSONSchema.is_supported(obj):
                    subschema.update(JSONSchema.get(obj))
                self.oneOf.append(subschema)
            elif isinstance(property, Selector):
                if JSONSchema.get_type(type(obj)) == "null":
                    continue
                self.oneOf.append(dict(type=JSONSchema.get_type(type(obj))))
        super()._build_from_property(property, owner)
        self.cleanup()

    def cleanup(self):
        if len(self.oneOf) == 1:
            oneOf = self.oneOf[0]
            self.type = oneOf["type"]
            if oneOf["type"] == 'object':
                if oneOf.get("properties", NotImplemented) is not NotImplemented:
                    self.properties = oneOf["properties"]
                if oneOf.get("required", NotImplemented) is not NotImplemented:
                    self.required = oneOf["required"]
            elif oneOf["type"] == 'array':
                if oneOf.get("items", NotImplemented) is not NotImplemented:
                    self.items = oneOf["items"]
                if oneOf.get("maxItems", NotImplemented) is not NotImplemented:
                    self.minItems = oneOf["minItems"]
                if oneOf.get("maxItems", NotImplemented) is not NotImplemented:
                    self.maxItems = oneOf["maxItems"]
            del self.oneOf


@dataclass
class EnumSchema(OneOfSchema):
    """
    custom schema to fill enum field of property affordance correctly
    https://www.w3.org/TR/wot-thing-description11/#dataschema
    """ 
    def __init__(self):
        super().__init__()
        
    def _build_from_property(self, property, owner) -> None:
        """generates the schema"""
        from ..server.properties import Selector
        assert isinstance(property, Selector), f"EnumSchema compatible property is only Selector, not {property.__class__}"
        self.enum = list(property.objects)
        super()._build_from_property(property, owner)



