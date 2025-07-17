import typing
from pydantic import Field, ConfigDict

from .base import *
from .data_schema import *
from .forms import *
from .security_definitions import *
from .metadata import *
from .interaction_affordance import *
from ..core.state_machine import BoundFSM


class ThingModel(Schema):

    context: typing.List[str] | str | typing.Dict[str, str] = "https://www.w3.org/2022/wot/td/v1.1"
    type: typing.Optional[typing.Union[str, typing.List[str]]] = None
    id: str = None
    title: str = None
    description: typing.Optional[str] = None
    version: typing.Optional[VersionInfo] = None
    created: typing.Optional[str] = None
    modified: typing.Optional[str] = None
    support: typing.Optional[str] = None
    base: typing.Optional[str] = None 
    properties: typing.Dict[str, DataSchema] = Field(default_factory=dict)
    actions: typing.Dict[str, ActionAffordance] = Field(default_factory=dict)
    events: typing.Dict[str, EventAffordance] = Field(default_factory=dict) 
   
    model_config = ConfigDict(extra="allow")

    def __init__(self, 
                instance: "Thing", 
                allow_loose_schema: typing.Optional[bool] = False, 
                ignore_errors: bool = False
            ) -> None:
        super().__init__()
        self.instance = instance
        self.allow_loose_schema = allow_loose_schema
        self.ignore_errors = ignore_errors


    def generate(self) -> "ThingModel": 
        """create thing model"""
        self.id = self.instance.id
        self.title = self.instance.__class__.__name__
        if self.instance.__doc__:
            self.description = Schema.format_doc(self.instance.__doc__)
        self.properties = dict()
        self.actions = dict()
        self.events = dict()
        self.add_interaction_affordances()
        return self
    
    def produce(self) -> Thing:
        raise NotImplementedError("This will be implemented in a future release for an API first approach")
    
    # not the best code and logic, but works for now
    skip_properties: typing.List[str] = ['expose', 'httpserver_resources', 'zmq_resources', 'gui_resources',
                    'events', 'thing_description', 'GUI', 'object_info' ]
    skip_actions: typing.List[str] = ['_set_properties', '_get_properties', '_add_property', '_get_properties_in_db', 
                    'get_postman_collection', 'get_thing_description', 'get_our_temp_thing_description']
    skip_events: typing.List[str] = []


    def add_interaction_affordances(self):
        """add interaction affordances to thing model"""
        for affordance, items, affordance_cls, skip_list in [
                ['properties', self.instance.properties.remote_objects.items(), PropertyAffordance, self.skip_properties],
                ['actions', self.instance.actions.descriptors.items(), ActionAffordance, self.skip_actions],
                ['events', self.instance.events.descriptors.items(), EventAffordance, self.skip_events],    
            ]:
            for name, obj in items:
                if name in skip_list: 
                    continue
                if (    
                    name == 'state' and affordance == 'properties' and
                    (not hasattr(self.instance, 'state_machine') or 
                    not isinstance(self.instance.state_machine, BoundFSM))
                ):
                    continue
                try:
                    affordance_dict = getattr(self, affordance)
                    affordance_dict[name] = affordance_cls.generate(obj, self.instance) 
                except Exception as ex:
                    if not self.ignore_errors:
                        raise ex from None
                    self.instance.logger.error(f"Error while generating schema for {name} - {ex}")
       