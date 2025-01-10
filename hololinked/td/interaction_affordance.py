




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
        self._name = None 
        self._thing_id = None

    @property
    def what(self):
        raise NotImplementedError("what property must be implemented in subclass of InteractionAffordance")

    @property
    def name(self):
        return self._name
    
    @property
    def thing_id(self):
        return self._thing_id
    
    @classmethod 
    def generate_schema(cls, resource : typing.Any, owner : Thing, authority : str) -> JSON:
        raise NotImplementedError("generate_schema must be implemented in subclass of InteractionAffordance")

    @classmethod 
    def from_TD(cls, name: str, TD: JSON) -> "InteractionAffordance":
        raise NotImplementedError("from_TD must be implemented in subclass of InteractionAffordance")
    


@dataclass(**__dataclass_kwargs)
class ZMQResource(SerializableDataclass): 
    """
    Representation of resource used by ZMQ clients for mapping client method/action calls, property read/writes & events
    to a server resource. Used to dynamically populate the ``ObjectProxy``

    Attributes
    ----------

    what : str
        is it a property, method/action or event?
    id : str
        The ``id`` of the thing which owns the resource. Used by ZMQ client to inform 
        message brokers to send the message to the correct recipient.
    name : str
        the name of the resource (__name__)
    qualname : str
        the qualified name of the resource (__qualname__) 
    doc : str
        the docstring of the resource
    argument_schema : JSON
        argument schema of the method/action for validation before passing over the instruction to the ZMQ server. 
    """
    what : str 
    class_name : str # just metadata
    id : str 
    obj_name : str # what looks on the client & the ID of the resource on the server
    qualname : str # qualified name to use by the client 
    doc : typing.Optional[str] 
    request_as_argument : bool = field(default=False)

    def __init__(self, *, what: str, thing_id: str, class_name: str, objekt: str,
                doc : str, request_as_argument : bool = False, ) -> None:
        self.what = what 
        self.class_name = class_name
        self.thing_id = thing_id
        self.objekt = objekt 
        self.doc = doc
        self.request_as_argument = request_as_argument

    def get_dunder_attr(self, __dunder_name : str):
        name = __dunder_name.strip('_')
        name = 'obj_name' if name == 'name' else name
        return getattr(self, name)

    def from_TD(self, name: str, TD: JSON) -> "ZMQResource":
        """
        Populate the resource from a Thing Description. 
        """
        raise NotImplementedError("This method is not implemented yet.")
    
    def supported_operations(self) -> typing.List[str]:
        """
        Return the supported operations on the resource. 
        """
        raise NotImplementedError("This method is not implemented yet.")

    
@dataclass(**__dataclass_kwargs)
class ZMQProperty(ZMQResource):

    @classmethod
    def from_TD(cls, name: str, TD: JSON) -> "ZMQResource":
        """
        Populate the resource from a Thing Description. 
        """
        self.what = TD['what']
        self.class_name = TD['class_name']
        self.id = TD['id']
        self.obj_name = TD['obj_name']
        self.qualname = TD['qualname']
        self.doc = TD['doc']
        self.request_as_argument = TD['request_as_argument']
        return self


@dataclass(**__dataclass_kwargs)
class ZMQAction(ZMQResource):
    argument_schema : typing.Optional[JSON] = field(default=None)
    return_value_schema : typing.Optional[JSON] = field(default=None)

    def __init__(self, *, what : str, class_name : str, id : str, obj_name : str,
                qualname : str, doc : str, argument_schema : typing.Optional[JSON] = None,
                return_value_schema : typing.Optional[JSON] = None, request_as_argument : bool = False) -> None:
        super(ZMQAction, self).__init__(what=what, class_name=class_name, id=id, obj_name=obj_name,
                        qualname=qualname, doc=doc, request_as_argument=request_as_argument)
        self.argument_schema = argument_schema
        self.return_value_schema = return_value_schema


@dataclass(**__dataclass_kwargs)
class ZMQEvent(ZMQResource):
    """
    event name and socket address of events to be consumed by clients. 
  
    Attributes
    ----------
    name : str
        name of the event, must be unique
    obj_name: str
        name of the event variable used to populate the ZMQ client
    socket_address : str
        address of the socket
    unique_identifier: str
        unique ZMQ identifier used in PUB-SUB model
    what: str, default EVENT
        is it a property, method/action or event?
    """
    friendly_name : str = field(default=UNSPECIFIED)
    unique_identifier : str = field(default=UNSPECIFIED)
    serialization_specific : bool = field(default=False)
    socket_address : str = field(default=UNSPECIFIED)

    def __init__(self, *, what : str, class_name : str, id : str, obj_name : str,
                friendly_name : str, qualname : str, unique_identifier : str, 
                serialization_specific : bool = False, socket_address : str, doc : str) -> None:
        super(ZMQEvent, self).__init__(what=what, class_name=class_name, id=id, obj_name=obj_name,
                        qualname=qualname, doc=doc, request_as_argument=False)  
        self.friendly_name = friendly_name
        self.unique_identifier = unique_identifier
        self.serialization_specific = serialization_specific
        self.socket_address = socket_address

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
            form.contentType = "text/plain"
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
    def register_descriptor(cls, descriptor : Property, schema_generator : "PropertyAffordance") -> None:
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
        
    def _build(self, action: typing.Callable, owner: Thing, authority: str | None = None) -> None:
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
    def build(cls, action : typing.Callable, owner : Thing, authority : str) -> JSON:
        schema = ActionAffordance()
        schema._build(action=action, owner=owner, authority=authority) 
        return schema.asdict()

    @classmethod
    def from_TD(self, name: str, TD: JSON) -> "ActionAffordance":
        action = TD["actions"][name]
        action_affordance = ActionAffordance()
        action_affordance.title = action.get("title", None)
        action_affordance.description = action.get("description", None)
        action_affordance.input = action.get("input", None)
        action_affordance.output = action.get("output", None)
        action_affordance.safe = action.get("safe", None)
        action_affordance.idempotent = action.get("idempotent", None)
        action_affordance.synchronous = action.get("synchronous", None)
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

