from enum import Enum
import typing
from typing import ClassVar, Optional
from pydantic import ConfigDict

from .base import Schema
from .data_schema import DataSchema
from .forms import Form
from ..constants import JSON, Operations, ResourceTypes
from ..core.property import Property
from ..core.actions import Action
from ..core.events import Event
from ..core.thing import Thing, ThingMeta




class InteractionAffordance(Schema):
    """
    Implements schema information common to all interaction affordances. 
    
    [Specification Definitions](https://www.w3.org/TR/wot-thing-description11/#interactionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    [Supported Fields]() <br>
    """
    title: Optional[str] = None 
    titles: Optional[typing.Dict[str, str]] = None
    description: Optional[str] = None
    descriptions: Optional[typing.Dict[str, str]] = None 
    forms: Optional[typing.List[Form]] = None
    # uri variables 

    _custom_schema_generators: ClassVar = dict()
    model_config = ConfigDict(extra="allow")

    def __init__(self):
        super().__init__()
        self._name = None 
        self._objekt = None
        self._thing_id = None
        self._thing_cls = None
        self._owner = None
        
    @property
    def what(self) -> Enum:
        """Whether it is a property, action or event"""
        raise NotImplementedError("Unknown interaction affordance - implement in subclass of InteractionAffordance")
    
    @property
    def owner(self) -> Thing:
        """Owning `Thing` instance of the interaction affordance"""
        if self._owner is None:
            raise AttributeError("owner is not set for this interaction affordance")
        return self._owner
    
    @owner.setter
    def owner(self, value):
        if self._owner is not None:
            raise ValueError(f"owner is already set for this {self.what.name.lower()} affordance, " + 
                        "recreate the affordance to change owner")
        if not isinstance(value, Thing):
            raise TypeError(f"owner must be instance of Thing, given type {type(value)}")
        self._owner = value
        self._thing_cls = value.__class__
        self._thing_id = value.id

    @property
    def objekt(self) -> Property | Action | Event: 
        """Object instance of the interaction affordance - `Property`, `Action` or `Event`"""
        if self._objekt is None:
            raise AttributeError("objekt is not set for this interaction affordance")
        return self._objekt
    
    @objekt.setter
    def objekt(self, value: Property | Action | Event) -> None:
        """Set the object instance of the interaction affordance - `Property`, `Action` or `Event`"""
        if self._objekt is not None:
            raise ValueError(f"object is already set for this {self.what.name.lower()} affordance, " + 
                        "recreate the affordance to change objekt")
        if not (
            (self.__class__.__name__.startswith("Property") and isinstance(value, Property)) or
            (self.__class__.__name__.startswith("Action") and isinstance(value, Action)) or
            (self.__class__.__name__.startswith("Event") and isinstance(value, Event))
        ):
            if not isinstance(value, (Property, Action, Event)):
                raise TypeError(f"objekt must be instance of Property, Action or Event, given type {type(value)}")
            raise ValueError(f"provide only corresponding object for {self.__class__.__name__}, " +
                                f"given object {value.__class__.__name__}")
        self._objekt = value
        self._name = value.name
    
    @property
    def name(self) -> str:
        """Name of the interaction affordance used as key in the TD"""
        if self._name is None:
            raise AttributeError("name is not set for this interaction affordance")
        return self._name
    
    @property
    def thing_id(self) -> str:
        """ID of the `Thing` instance owning the interaction affordance"""
        if self._thing_id is None:
            raise AttributeError("thing_id is not set for this interaction affordance")
        return self._thing_id
    
    @property
    def thing_cls(self) -> ThingMeta:
        """`Thing` class owning the interaction affordance"""
        if self._thing_cls is None:
            raise AttributeError("thing_cls is not set for this interaction affordance")
        return self._thing_cls
    
    def build(self, interaction: Property | Action | Event, owner: Thing) -> None:
        """
        populate the fields of the schema for the specific interaction affordance

        Parameters
        ----------
        interaction: Property | Action | Event
            interaction object for which the schema is to be built
        owner: Thing
            owner of the interaction affordance        
        """
        raise NotImplementedError("_build must be implemented in subclass of InteractionAffordance")
    
    def build_forms(self, protocol: str, authority: str) -> None:
        """
        build the forms for the specific protocol for each szupported operation
        
        Parameters
        ----------
        protocol: str
            protocol used for the interaction
        authority: str
            authority of the interaction
        """
        raise NotImplementedError("_build_forms must be implemented in subclass of InteractionAffordance")
    
    def retrieve_form(self, op: str, default: typing.Any = None) -> JSON:
        """
        retrieve form for a certain operation, return default if not found

        Parameters
        ----------
        op: str
            operation for which the form is to be retrieved
        default: typing.Any, optional
            default value to return if form is not found, by default None. 
            One can make use of a sensible default value for one's logic.  

        Returns
        -------
        Dict[str, typing.Any]
            JSON representation of the form      
        """
        if not hasattr(self, 'forms'):
            return default
        for form in self.forms:
            if form.op == op:
                return form
        return default
    
    @classmethod 
    def generate(cls, 
                interaction: Property | Action | Event, 
                owner: Thing
            ) -> typing.Union["PropertyAffordance", "ActionAffordance", "EventAffordance"]:
        """
        build the schema for the specific interaction affordance within the container object. 
        Use the `json()` method to get the JSON representation of the schema.

        Parameters
        ----------
        interaction: Property | Action | Event
            interaction object for which the schema is to be built
        owner: Thing
            owner of the interaction affordance

        Returns
        -------
        typing.Union[PropertyAffordance, ActionAffordance, EventAffordance]
        """
        raise NotImplementedError("generate_schema must be implemented in subclass of InteractionAffordance")

    @classmethod 
    def from_TD(cls, name: str, TD: JSON) -> typing.Union["PropertyAffordance", "ActionAffordance", "EventAffordance"]:
        """
        populate the schema from the TD and return it as the container object
        
        Parameters
        ----------
        name: str
            name of the interaction affordance used as key in the TD
        TD: JSON
            Thing Description JSON dictionary

        Returns
        -------
        typing.Union[PropertyAffordance, ActionAffordance, EventAffordance]
        """
        raise NotImplementedError("from_TD must be implemented in subclass of InteractionAffordance")
    
    @classmethod
    def register_descriptor(cls, descriptor: Property | Action | Event, schema_generator: "InteractionAffordance") -> None:
        """register a custom schema generator for a descriptor"""
        if not isinstance(descriptor, (Property, Action, Event)):
            raise TypeError("custom schema generator can also be registered for Property." +
                            f" Given type {type(descriptor)}")
        if not isinstance(schema_generator, InteractionAffordance):
            raise TypeError("schema generator for Property must be subclass of PropertyAfforance. " +
                            f"Given type {type(schema_generator)}" )
        InteractionAffordance._custom_schema_generators[descriptor] = schema_generator

    def __hash__(self):
        return hash(self.thing_id + "" if not self.thing_cls else self.thing_cls.__name__ + self.name)

    def __str__(self):
        if self.thing_cls:
            return f"{self.__class__.__name__}({self.thing_cls.__name__}({self.thing_id}).{self.name})"
        return f"{self.__class__.__name__}({self.name} of {self.thing_id})"
    
    def __eq__(self, value):
        if not isinstance(value, self.__class__):
            return False
        return self.thing_id == value.thing_id and self.name == value.name
    

   
class PropertyAffordance(InteractionAffordance, DataSchema):
    """
    Implements property affordance schema from `Property` descriptor object.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#propertyaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    [Supported Fields]() <br>
    """
    observable: Optional[bool] = None

    def __init__(self):
        super().__init__()

    @property
    def what(self) -> Enum:
        return ResourceTypes.PROPERTY
    
    def build(self) -> None:
        property = self.objekt
        self.ds_build_from_property(property)
        if property._observable:
            self.observable = property._observable
    
    def build_forms(self, authority: str) -> None:
        property = self.objekt
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
            form.href = f"{authority}{self.owner._qualified_id}{property._remote_info.URL_path}"
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
    def generate(cls, property, owner):
        assert isinstance(property, Property), f"property must be instance of Property, given type {type(property)}"
        schema = PropertyAffordance()
        schema.owner = owner      
        schema.objekt = property
        schema.build()       
        return schema

 
class ActionAffordance(InteractionAffordance):
    """
    creates action affordance schema from actions (or methods).

    [Schema](https://www.w3.org/TR/wot-thing-description11/#actionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    [Supported Fields]() <br>
    """
    input: JSON = None
    output: JSON = None
    safe: bool = None
    idempotent: bool = None 
    synchronous: bool = None 

    def __init__(self, action: typing.Callable | None = None):
        super().__init__()
        self.action = action 

    @property 
    def what(self):
        return ResourceTypes.ACTION
           
    def build(self, action, owner) -> None:
        self.action = action
        self.owner = owner
        self.title = self.action.name
        if self.action.__doc__:
            self.description = self.format_doc(action.__doc__)
        if self.action.execution_info.argument_schema:
            self.input = self.action.execution_info.argument_schema 
        if self.action.execution_info.return_value_schema: 
            self.output = self.action.execution_info.return_value_schema 
        if (not (hasattr(owner, 'state_machine') and owner.state_machine is not None and 
                owner.state_machine.has_object(self.action)) and 
                self.action.execution_info.idempotent):
            self.idempotent = self.action.execution_info.idempotent
        if self.action.execution_info.synchronous:
            self.synchronous = self.action.execution_info.synchronous
        if self.action.execution_info.safe:
            self.safe = self.action.execution_info.safe 

    def build_forms(self, protocol: str, authority : str, **protocol_metadata) -> None:
        self.forms = []
        for method in self.action.execution_info_validator.http_method:
            form = Form()
            form.op = 'invokeaction'
            form.href = f'{authority}/{self.owner.id}/{protocol_metadata.get("path", "")}/{self.action.name}'
            form.htv_methodName = method.upper()
            form.contentType = 'application/json'
            # form.additionalResponses = [AdditionalExpectedResponse().asdict()]
            self.forms.append(form.asdict())
    
    @classmethod
    def generate(cls, action : typing.Callable, owner, **kwargs) -> JSON:
        affordance = ActionAffordance(action=action)
        affordance.owner = owner
        affordance._build(owner=owner) 
        if kwargs.get('protocol', None) and kwargs.get('authority', None):
            affordance._build_forms(protocol=kwargs['protocol'], authority=kwargs['authority'])
        return affordance.asdict()

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
            action_affordance.forms = action.get("forms", [])
        action_affordance._name = name
        action_affordance._thing_id = TD["id"]
        return action_affordance
          
    
class EventAffordance(InteractionAffordance):
    """
    creates event affordance schema from events.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#eventaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    [Supported Fields]() <br>
    """
    subscription: str = None
    data: JSON = None
    
    def __init__(self):
        super().__init__()

    @property 
    def what(self):
        return ResourceTypes.EVENT
    
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