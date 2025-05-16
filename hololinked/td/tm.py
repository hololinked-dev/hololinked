import typing

from .base import *
from .data_schema import *
from .forms import *
from .security_definitions import *
from .metadata import *
from .interaction_affordance import *
from ..core.state_machine import StateMachine


class ThingModel(Schema):


    def __init__(self, 
                instance: "Thing", 
                allow_loose_schema: typing.Optional[bool] = False, 
                ignore_errors: bool = False
            ) -> None:
        super().__init__()
        self.instance = instance
        self.allow_loose_schema = allow_loose_schema
        self.ignore_errors = ignore_errors


    def produce(self) -> "ThingModel": 
        """create thing model"""
        self.id = self.instance.id
        self.title = self.instance.__class__.__name__ 
        self.description = Schema.format_doc(self.instance.__doc__) if self.instance.__doc__ else "no class doc provided" 
        self.properties = dict()
        self.actions = dict()
        self.events = dict()
        self.add_interaction_affordances()
        return self
    
    # not the best code and logic, but works for now
    skip_properties = ['expose', 'httpserver_resources', 'zmq_resources', 'gui_resources',
                    'events', 'thing_description', 'GUI', 'object_info' ]
    skip_actions = ['_set_properties', '_get_properties', '_add_property', '_get_properties_in_db', 
                    'get_postman_collection', 'get_thing_description', 'get_our_temp_thing_description']


    def add_interaction_affordances(self):
        """add interaction affordances to thing model"""
        for name, prop in self.instance.properties.remote_objects.items():
            if name in self.skip_properties: 
                continue
            if name == 'state' and (
                                not hasattr(self.instance, 'state_machine') or 
                                not isinstance(self.instance.state_machine, StateMachine)
                            ):
                continue
            try:
                self.properties[prop.name] = PropertyAffordance.generate(prop, self.instance) 
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {prop.name} - {ex}")
        
        for name, action in self.instance.actions.descriptors.items():
            if name in self.skip_actions:
                continue    
            try:       
                self.actions[name] = ActionAffordance.generate(action, self.instance)
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {name} - {ex}")
        for name, event in self.instance.events.descriptors.items():
            try:
                self.events[name] = EventAffordance.generate(event, self.instance)
            except Exception as ex:
                if not self.ignore_errors:
                    raise ex from None
                self.instance.logger.error(f"Error while generating schema for {name} - {ex}")