import typing
from dataclasses import dataclass, field

from .constants import JSON
from .dataklasses import ActionInfoValidator
from .events import Event
from .properties import *
from .property import Property
from .thing import Thing
from .state_machine import StateMachine
from .zmq_server import EventLoop


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



@dataclass
class InteractionAffordance(Schema):
    """
    implements schema common to all interaction affordances. 
    concepts - https://www.w3.org/TR/wot-thing-description11/#interactionaffordance
    """
    title : str 
    titles : typing.Optional[typing.Dict[str, str]]
    description : str
    descriptions : typing.Optional[typing.Dict[str, str]] 
    forms : typing.List["Form"]
    # uri variables 

    def __init__(self):
        super().__init__()



@dataclass
class DataSchema(Schema):
    """
    implementes Dataschema attributes.
    https://www.w3.org/TR/wot-thing-description11/#sec-data-schema-vocabulary-definition
    """
    title : str 
    titles : typing.Optional[typing.Dict[str, str]]
    description : str
    descriptions : typing.Optional[typing.Dict[str, str]] 
    const : bool
    default : typing.Optional[typing.Any] 
    readOnly : bool
    writeOnly : bool # write only are to be considered actions with no return value
    format : typing.Optional[str]
    unit : typing.Optional[str]
    type : str
    oneOf : typing.Optional[typing.List[JSON]]
    enum : typing.Optional[typing.List[typing.Any]]

    def __init__(self):
        super().__init__()

    def build(self, property : Property, owner : Thing, authority : str) -> None:
        """generates the schema"""
        self.title = property.label or property.name 
        if property.constant:
            self.const = property.constant 
        if property.readonly:
            self.readOnly = property.readonly
        if property.fget is None:
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
class PropertyAffordance(InteractionAffordance, DataSchema):
    """
    creates property affordance schema from ``property`` descriptor object 
    schema - https://www.w3.org/TR/wot-thing-description11/#propertyaffordance
    """
    observable : bool

    _custom_schema_generators = dict()

    def __init__(self):
        super().__init__()

    def build(self, property : Property, owner : Thing, authority : str) -> None:
        """generates the schema"""
        DataSchema.build(self, property, owner, authority)

        self.forms = []
        for index, method in enumerate(property._remote_info.http_method):
            form = Form()
            # index is the order for http methods for (get, set, delete), generally (GET, PUT, DELETE)
            if (index == 1 and property.readonly) or index >= 2:
                continue # delete property is not a part of WoT, we also mostly never use it, so ignore.
            elif index == 0:
                form.op = 'readproperty'
            elif index == 1:
                form.op = 'writeproperty'
            form.href = f"{authority}{owner._full_URL_path_prefix}{property._remote_info.URL_path}"
            form.htv_methodName = method.upper()
            form.contentType = "application/json"
            self.forms.append(form.asdict())

        if property._observable:
            self.observable = property._observable
            form = Form()
            form.op = 'observeproperty'
            form.href = f"{authority}{owner._full_URL_path_prefix}{property._observable_event_descriptor.URL_path}"
            form.htv_methodName = "GET"
            form.subprotocol = "sse"
            form.contentType = "application/json"
            self.forms.append(form.asdict())


    @classmethod
    def generate_schema(self, property : Property, owner : Thing, authority : str) -> JSON:
        if not isinstance(property, Property):
            raise TypeError(f"Property affordance schema can only be generated for Property. "
                            f"Given type {type(property)}")
        if isinstance(property, (String, Filename, Foldername, Path)):
            schema = StringSchema()
        elif isinstance(property, (Number, Integer)):
            schema = NumberSchema()
        elif isinstance(property, Boolean):
            schema = BooleanSchema()
        elif isinstance(property, (List, TypedList, Tuple, TupleSelector)):
            schema = ArraySchema()
        elif isinstance(property, Selector):
            schema = EnumSchema()
        elif isinstance(property, (TypedDict, TypedKeyMappingsDict)):
            schema = ObjectSchema()       
        elif isinstance(property, ClassSelector):
            schema = OneOfSchema()
        elif self._custom_schema_generators.get(property, NotImplemented) is not NotImplemented:
            schema = self._custom_schema_generators[property]()
        elif isinstance(property, Property) and property.model is not None:
            if isinstance(property.model, dict):
                data_schema = property.model
            else: 
                from .td_pydantic_extensions import GenerateJsonSchemaWithoutDefaultTitles, type_to_dataschema
                data_schema = type_to_dataschema(property.model).model_dump(mode='json', exclude_none=True)
            schema = PropertyAffordance()
            schema.build(property=property, owner=owner, authority=authority)
            final_schema = schema.asdict()
            if schema.oneOf: # allow_None = True
                final_schema['oneOf'].append(data_schema)
            else:
                final_schema.update(data_schema)
            return final_schema
        else:
            raise TypeError(f"WoT schema generator for this descriptor/property is not implemented. name {property.name} & type {type(property)}")     
        schema.build(property=property, owner=owner, authority=authority)
        return schema.asdict()
    
    @classmethod
    def register_descriptor(cls, descriptor : Property, schema_generator : "PropertyAffordance") -> None:
        if not isinstance(descriptor, Property):
            raise TypeError("custom schema generator can also be registered for Property." +
                            f" Given type {type(descriptor)}")
        if not isinstance(schema_generator, PropertyAffordance):
            raise TypeError("schema generator for Property must be subclass of PropertyAfforance. " +
                            f"Given type {type(schema_generator)}" )
        PropertyAffordance._custom_schema_generators[descriptor] = schema_generator


@dataclass
class BooleanSchema(PropertyAffordance):
    """
    boolean schema - https://www.w3.org/TR/wot-thing-description11/#booleanschema
    used by Boolean descriptor    
    """
    def __init__(self):
        super().__init__()

    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        self.type = 'boolean'
        PropertyAffordance.build(self, property, owner, authority)


@dataclass
class StringSchema(PropertyAffordance):
    """
    string schema - https://www.w3.org/TR/wot-thing-description11/#stringschema
    used by String, Filename, Foldername, Path descriptors
    """
    pattern : typing.Optional[str] 
    
    def __init__(self):
        super().__init__()
        
    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        self.type = 'string' 
        PropertyAffordance.build(self, property, owner, authority)
        if isinstance(property, String): 
            if property.regex is not None:
                self.pattern = property.regex


@dataclass
class NumberSchema(PropertyAffordance):
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
        
    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        if isinstance(property, Integer):
            self.type = 'integer'
        elif isinstance(property, Number): # dont change order - one is subclass of other
            self.type = 'number' 
        PropertyAffordance.build(self, property, owner, authority)
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
class ArraySchema(PropertyAffordance):
    """
    array schema - https://www.w3.org/TR/wot-thing-description11/#arrayschema
    Used by List, Tuple, TypedList and TupleSelector
    """

    items : typing.Optional[JSON]
    minItems : typing.Optional[int]
    maxItems : typing.Optional[int]

    def __init__(self):
        super().__init__()
        
    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        self.type = 'array'
        PropertyAffordance.build(self, property, owner, authority)
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
class ObjectSchema(PropertyAffordance):
    """
    object schema - https://www.w3.org/TR/wot-thing-description11/#objectschema
    Used by TypedDict
    """
    properties : typing.Optional[JSON]
    required : typing.Optional[typing.List[str]]

    def __init__(self):
        super().__init__()
        
    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        PropertyAffordance.build(self, property, owner, authority)
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
class OneOfSchema(PropertyAffordance):
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

    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
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
        PropertyAffordance.build(self, property, owner, authority)
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
        
    def build(self, property: Property, owner: Thing, authority: str) -> None:
        """generates the schema"""
        assert isinstance(property, Selector), f"EnumSchema compatible property is only Selector, not {property.__class__}"
        self.enum = list(property.objects)
        OneOfSchema.build(self, property, owner, authority)


@dataclass
class Link(Schema):
    href : str
    anchor : typing.Optional[str]  
    type : typing.Optional[str] = field(default='application/json')
    # rel : typing.Optional[str] = field(default='next')

    def __init__(self):
        super().__init__()
    
    def build(self, resource : Thing, owner : Thing, authority : str) -> None:
        self.href = f"{authority}{resource._full_URL_path_prefix}/resources/wot-td"
        self.anchor = f"{authority}{owner._full_URL_path_prefix}"



@dataclass
class ExpectedResponse(Schema):
    """
    Form property. 
    schema - https://www.w3.org/TR/wot-thing-description11/#expectedresponse
    """
    contentType : str

    def __init__(self):
        super().__init__()


@dataclass
class AdditionalExpectedResponse(Schema):
    """
    Form field for additional responses which are different from the usual response.
    schema - https://www.w3.org/TR/wot-thing-description11/#additionalexpectedresponse
    """
    success : bool = field(default=False)
    contentType : str = field(default='application/json')
    schema : typing.Optional[JSON] = field(default='exception')

    def __init__(self):
        super().__init__()

   
@dataclass
class Form(Schema):
    """
    Form hypermedia.
    schema - https://www.w3.org/TR/wot-thing-description11/#form
    """
    href : str 
    op : str 
    htv_methodName : str 
    contentType : typing.Optional[str]
    additionalResponses : typing.Optional[typing.List[AdditionalExpectedResponse]]
    contentEncoding : typing.Optional[str]
    security : typing.Optional[str]
    scopes : typing.Optional[str]
    response : typing.Optional[ExpectedResponse]
    subprotocol : typing.Optional[str]
    
    def __init__(self):
        super().__init__()

    
@dataclass
class ActionAffordance(InteractionAffordance):
    """
    creates action affordance schema from actions (or methods).
    schema - https://www.w3.org/TR/wot-thing-description11/#actionaffordance
    """
    input : JSON
    output : JSON
    safe : bool
    idempotent : bool 
    synchronous : bool 

    def __init__(self):
        super(InteractionAffordance, self).__init__()
    
    def build(self, action : typing.Callable, owner : Thing, authority : str) -> None:
        assert isinstance(action._remote_info, ActionInfoValidator)
        if action._remote_info.argument_schema: 
            self.input = action._remote_info.argument_schema 
        if action._remote_info.return_value_schema: 
            self.output = action._remote_info.return_value_schema 
        self.title = action.__name__
        if action.__doc__:
            self.description = self.format_doc(action.__doc__)
        if not (hasattr(owner, 'state_machine') and owner.state_machine is not None and 
                owner.state_machine.has_object(action._remote_info.obj)) and action._remote_info.idempotent:
            self.idempotent = action._remote_info.idempotent
        if action._remote_info.synchronous:
            self.synchronous = action._remote_info.synchronous
        if action._remote_info.safe:
            self.safe = action._remote_info.safe 
        self.forms = []
        for method in action._remote_info.http_method:
            form = Form()
            form.op = 'invokeaction'
            form.href = f'{authority}{owner._full_URL_path_prefix}{action._remote_info.URL_path}'
            form.htv_methodName = method.upper()
            form.contentType = 'application/json'
            # form.additionalResponses = [AdditionalExpectedResponse().asdict()]
            self.forms.append(form.asdict())

    @classmethod
    def generate_schema(cls, action : typing.Callable, owner : Thing, authority : str) -> JSON:
        schema = ActionAffordance()
        schema.build(action=action, owner=owner, authority=authority) 
        return schema.asdict()
    

@dataclass
class EventAffordance(InteractionAffordance):
    """
    creates event affordance schema from events.
    schema - https://www.w3.org/TR/wot-thing-description11/#eventaffordance
    """
    subscription : str
    data : JSON
    
    def __init__(self):
        super().__init__()
    
    def build(self, event : Event, owner : Thing, authority : str) -> None:
        self.title = event.label or event._obj_name 
        if event.doc:
            self.description = self.format_doc(event.doc)
        if event.schema:
            self.data = event.schema

        form = Form()
        form.op = "subscribeevent"
        form.href = f"{authority}{owner._full_URL_path_prefix}{event.URL_path}"
        form.htv_methodName = "GET"
        form.contentType = "text/plain"
        form.subprotocol = "sse"
        self.forms = [form.asdict()]

    @classmethod
    def generate_schema(cls, event : Event, owner : Thing, authority : str) -> JSON:
        schema = EventAffordance()
        schema.build(event=event, owner=owner, authority=authority)
        return schema.asdict()


@dataclass
class VersionInfo:
    """
    create version info.
    schema - https://www.w3.org/TR/wot-thing-description11/#versioninfo
    """
    instance : str 
    model : str


@dataclass
class SecurityScheme(Schema):
    """
    create security scheme. 
    schema - https://www.w3.org/TR/wot-thing-description11/#sec-security-vocabulary-definition
    """
    scheme: str 
    description : str 
    descriptions : typing.Optional[typing.Dict[str, str]]
    proxy : typing.Optional[str]

    def __init__(self):
        super().__init__()

    def build(self, name : str, instance):
        self.scheme = 'nosec'
        self.description = 'currently no security scheme supported - use cookie auth directly on hololinked.server.HTTPServer object'
        return { name : self.asdict() }



@dataclass
class ThingDescription(Schema):
    """
    generate Thing Description schema of W3 Web of Things standard. 
    Refer standard - https://www.w3.org/TR/wot-thing-description11
    Refer schema - https://www.w3.org/TR/wot-thing-description11/#thing
    """
    context : typing.Union[typing.List[str], str, typing.Dict[str, str]] 
    type : typing.Optional[typing.Union[str, typing.List[str]]]
    id : str 
    title : str 
    description : str 
    version : typing.Optional[VersionInfo]
    created : typing.Optional[str] 
    modified : typing.Optional[str]
    support : typing.Optional[str] 
    base : typing.Optional[str] 
    properties : typing.List[PropertyAffordance]
    actions : typing.List[ActionAffordance]
    events : typing.List[EventAffordance]
    links : typing.Optional[typing.List[Link]] 
    forms : typing.Optional[typing.List[Form]]
    security : typing.Union[str, typing.List[str]]
    securityDefinitions : SecurityScheme
    schemaDefinitions : typing.Optional[typing.List[DataSchema]]
    
    skip_properties = ['expose', 'httpserver_resources', 'zmq_resources', 'gui_resources',
                    'events', 'thing_description', 'GUI', 'object_info' ]

    skip_actions = ['_set_properties', '_get_properties', '_add_property', '_get_properties_in_db', 
                    'get_postman_collection', 'get_thing_description', 'get_our_temp_thing_description']

    # not the best code and logic, but works for now

    def __init__(self, instance : Thing, authority : typing.Optional[str] = None, 
                    allow_loose_schema : typing.Optional[bool] = False, ignore_errors : bool = False) -> None:
        super().__init__()
        self.instance = instance
        self.authority = authority
        self.allow_loose_schema = allow_loose_schema
        self.ignore_errors = ignore_errors

    def produce(self) -> JSON: 
        self.context = "https://www.w3.org/2022/wot/td/v1.1"
        self.id = f"{self.authority}/{self.instance.instance_name}"
        self.title = self.instance.__class__.__name__ 
        self.description = Schema.format_doc(self.instance.__doc__) if self.instance.__doc__ else "no class doc provided" 
        self.properties = dict()
        self.actions = dict()
        self.events = dict()
        self.forms = NotImplemented
        self.links = NotImplemented
        
        # self.schemaDefinitions = dict(exception=JSONSchema.get_type(Exception))

        self.add_interaction_affordances()
        self.add_links()
        self.add_top_level_forms()
        self.add_security_definitions()
       
        return self
    

    def add_interaction_affordances(self):
        # properties 
        for prop in self.instance.properties.descriptors.values():
            if not isinstance(prop, Property) or not prop.remote or prop.name in self.skip_properties: 
                continue
            if prop.name == 'state' and (not hasattr(self.instance, 'state_machine') or 
                                not isinstance(self.instance.state_machine, StateMachine)):
                continue
            try:
                if (resource.isproperty and resource.obj_name not in self.properties and 
                    resource.obj_name not in self.skip_properties and hasattr(resource.obj, "_remote_info") and 
                    resource.obj._remote_info is not None): 
                    if (resource.obj_name == 'state' and (not hasattr(self.instance, 'state_machine') or 
                                not isinstance(self.instance.state_machine, StateMachine))):
                        continue
                    if resource.obj_name not in self.instance.properties:
                        continue 
                    self.properties[resource.obj_name] = PropertyAffordance.generate_schema(resource.obj, 
                                                                            self.instance, self.authority) 
                
                elif (resource.isaction and resource.obj_name not in self.actions and 
                    resource.obj_name not in self.skip_actions and hasattr(resource.obj, '_remote_info')):

                    if resource.bound_obj != self.instance or (resource.obj_name == 'exit' and 
                            self.instance._owner is not None) or (not hasattr(resource.bound_obj, 'db_engine') and
                            resource.obj_name == 'load_properties_from_DB'):
                        continue
                    self.actions[resource.obj_name] = ActionAffordance.generate_schema(resource.obj, 
                                                                                self.instance, self.authority)
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {prop.name} - {ex}")
        # actions       
        for name, resource in self.instance.actions.items():
            if name in self.skip_actions:
                continue    
            try:       
                self.actions[resource.obj_name] = ActionAffordance.generate_schema(resource.obj, self.instance, 
                                                                               self.authority)
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {name} - {ex}")
        # events
        for name, resource in self.instance.events.items():
            try:
                self.events[name] = EventAffordance.generate_schema(resource, self.instance, self.authority)
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {resource.obj_name} - {ex}")
    
    
    def add_links(self):
        for name, resource in self.instance.sub_things.items():
            if resource is self.instance or isinstance(resource, EventLoop):
                continue
            if self.links is None:
                self.links = []
            link = Link()
            link.build(resource, self.instance, self.authority)
            self.links.append(link.asdict())
    

    def add_top_level_forms(self):

        self.forms = []

        properties_end_point = f"{self.authority}{self.instance._full_URL_path_prefix}/properties"

        readallproperties = Form()
        readallproperties.href = properties_end_point
        readallproperties.op = "readallproperties"
        readallproperties.htv_methodName = "GET"
        readallproperties.contentType = "application/json"
        # readallproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
        self.forms.append(readallproperties.asdict())
        
        writeallproperties = Form() 
        writeallproperties.href = properties_end_point
        writeallproperties.op = "writeallproperties"   
        writeallproperties.htv_methodName = "PUT"
        writeallproperties.contentType = "application/json" 
        # writeallproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
        self.forms.append(writeallproperties.asdict())

        readmultipleproperties = Form()
        readmultipleproperties.href = properties_end_point
        readmultipleproperties.op = "readmultipleproperties"
        readmultipleproperties.htv_methodName = "GET"
        readmultipleproperties.contentType = "application/json"
        # readmultipleproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
        self.forms.append(readmultipleproperties.asdict())

        writemultipleproperties = Form() 
        writemultipleproperties.href = properties_end_point
        writemultipleproperties.op = "writemultipleproperties"   
        writemultipleproperties.htv_methodName = "PATCH"
        writemultipleproperties.contentType = "application/json"
        # writemultipleproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
        self.forms.append(writemultipleproperties.asdict())
  
        
    def add_security_definitions(self):
        self.security = 'unimplemented'
        self.securityDefinitions = SecurityScheme().build('unimplemented', self.instance)


    def json(self) -> JSON:
        return self.asdict()

__all__ = [
    ThingDescription.__name__,
    JSONSchema.__name__
]