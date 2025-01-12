import typing
from dataclasses import dataclass, field

from .base import Schema
from .data_schema import (DataSchema, StringSchema, NumberSchema, 
                        BooleanSchema, ArraySchema, EnumSchema, ObjectSchema, 
                        OneOfSchema)
from .forms import Form
from ..constants import JSON, ResourceTypes



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
    forms : typing.List[Form]
    # uri variables 

    def __init__(self):
        super().__init__()
        self._name = None 
        self._thing_id = None

    @property
    def what(self):
        raise NotImplementedError("Unknown interaction affordance - implement in subclass of InteractionAffordance")
    
    @property
    def name(self):
        if self._name is None:
            raise ValueError("name is not set for this interaction affordance")
        return self._name
    
    @property
    def thing_id(self):
        if self._thing_id is None:
            raise ValueError("thing_id is not set for this interaction affordance")
        return self._thing_id
    
    def _build(self, interaction: typing.Any, owner) -> None:
        raise NotImplementedError("_build must be implemented in subclass of InteractionAffordance")
    
    @classmethod 
    def generate(cls, interaction: typing.Any, owner, authority: str) -> JSON:
        raise NotImplementedError("generate_schema must be implemented in subclass of InteractionAffordance")

    @classmethod 
    def from_TD(cls, name: str, TD: JSON) -> "InteractionAffordance":
        raise NotImplementedError("from_TD must be implemented in subclass of InteractionAffordance")
    
   

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

    @property
    def what(self):
        return ResourceTypes.PROPERTY

    def _build(self, property, owner) -> None:
        """generates the schema"""
        from ..server import Property
        assert isinstance(property, Property)
        DataSchema._build_from_property(self, property, owner)
    
    def _build_forms(self, property, owner, authority: str) -> None:
        from ..server import Property
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
            form.contentType = "text/plain"
            self.forms.append(form.asdict())


    @classmethod
    def generate(self, property, owner, authority : str) -> JSON:
        from ..server.properties import (String, Number, Integer, Boolean, 
                                    List, TypedList, Tuple, TupleSelector,
                                    Selector, TypedDict, TypedKeyMappingsDict,
                                    ClassSelector, Filename, Foldername, Path)

        from ..server import Property
        assert isinstance(property, Property)

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
            from .pydantic_extensions import GenerateJsonSchemaWithoutDefaultTitles, type_to_dataschema
            schema = PropertyAffordance()
            schema.build(property=property, owner=owner, authority=authority)
            data_schema = type_to_dataschema(property.model).model_dump(mode='json', exclude_none=True)
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
    def register_descriptor(cls, descriptor, schema_generator) -> None:
        from ..server import Property
        if not isinstance(descriptor, Property):
            raise TypeError("custom schema generator can also be registered for Property." +
                            f" Given type {type(descriptor)}")
        if not isinstance(schema_generator, PropertyAffordance):
            raise TypeError("schema generator for Property must be subclass of PropertyAfforance. " +
                            f"Given type {type(schema_generator)}" )
        PropertyAffordance._custom_schema_generators[descriptor] = schema_generator




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
        super().__init__()

    @property 
    def what(self):
        return ResourceTypes.ACTION
        
    def _build(self, action: typing.Callable, owner, authority: str | None = None) -> None:
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
        if authority is not None:
            self._build_forms(action, owner, authority)

    def _build_forms(self, protocol: str, authority : str, **protocol_metadata) -> None:
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
    def generate(cls, action : typing.Callable, owner : "Thing", authority : str) -> JSON:
        schema = ActionAffordance()
        schema._build(action=action, owner=owner, authority=authority) 
        return schema.asdict()

    @classmethod
    def from_TD(self, name: str, TD: JSON) -> "ActionAffordance":
        action = TD["actions"][name] # type: typing.Dict[str, JSON]
        action_affordance = ActionAffordance()
        if action.get("title", None):
            action_affordance.title = action.get("title", None)
        if action.get("description", None):
            action_affordance.description = action.get("description", None)
        if action.get("input", None):
            action_affordance.input = action.get("input", None)
        if action.get("output", None):
            action_affordance.output = action.get("output", None)
        if action.get("safe", None) is not None:
            action_affordance.safe = action.get("safe", None)
        if action.get("idempotent", None) is not None:
            action_affordance.idempotent = action.get("idempotent", None)
        if action.get("synchronous", None) is not None:
            action_affordance.synchronous = action.get("synchronous", None)
        if action.get("forms", None):
            action_affordance.forms = action.get("forms", {})
        action_affordance._name = name
        action_affordance._thing_id = TD["id"]
        return action_affordance
    
    

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
    
    def build(self, event, owner, authority : str) -> None:
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
    def generate_schema(cls, event, owner, authority : str) -> JSON:
        schema = EventAffordance()
        schema.build(event=event, owner=owner, authority=authority)
        return schema.asdict()
    

# @dataclass(**__dataclass_kwargs)
# class ZMQEvent(ZMQResource):
#     """
#     event name and socket address of events to be consumed by clients. 
  
#     Attributes
#     ----------
#     name : str
#         name of the event, must be unique
#     obj_name: str
#         name of the event variable used to populate the ZMQ client
#     socket_address : str
#         address of the socket
#     unique_identifier: str
#         unique ZMQ identifier used in PUB-SUB model
#     what: str, default EVENT
#         is it a property, method/action or event?
#     """
#     friendly_name : str = field(default=UNSPECIFIED)
#     unique_identifier : str = field(default=UNSPECIFIED)
#     serialization_specific : bool = field(default=False)
#     socket_address : str = field(default=UNSPECIFIED)

#     def __init__(self, *, what : str, class_name : str, id : str, obj_name : str,
#                 friendly_name : str, qualname : str, unique_identifier : str, 
#                 serialization_specific : bool = False, socket_address : str, doc : str) -> None:
#         super(ZMQEvent, self).__init__(what=what, class_name=class_name, id=id, obj_name=obj_name,
#                         qualname=qualname, doc=doc, request_as_argument=False)  
#         self.friendly_name = friendly_name
#         self.unique_identifier = unique_identifier
#         self.serialization_specific = serialization_specific
#         self.socket_address = socket_address