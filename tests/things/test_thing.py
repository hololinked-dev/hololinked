import asyncio
import time, logging, unittest, os
import typing
from pydantic import BaseModel

from hololinked.core import Thing, action, Property, Event
from hololinked.core.properties import Number, String, Selector, List, Integer, ClassSelector
from hololinked.core.actions import Action, BoundAction, BoundSyncAction, BoundAsyncAction
from hololinked.param import ParameterizedFunction
from hololinked.core.dataklasses import ActionInfoValidator
from hololinked.utils import isclassmethod


class TestThing(Thing):

    @action()
    def get_transports(self):
        transports = []
        if self.rpc_server.inproc_server is not None and self.rpc_server.inproc_server.socket_address.startswith('inproc://'):
            transports.append('INPROC')
        if self.rpc_server.ipc_server is not None and self.rpc_server.ipc_server.socket_address.startswith('ipc://'): 
            transports.append('IPC')
        if self.rpc_server.tcp_server is not None and self.rpc_server.tcp_server.socket_address.startswith('tcp://'): 
            transports.append('TCP')
        return transports

    @action()
    def action_echo(self, value):
        # print("action_echo called with value: ", value)
        return value
    
    @classmethod
    def action_echo_with_classmethod(self, value):
        return value
    
    async def action_echo_async(self, value):
        await asyncio.sleep(0.1)
        return value
    
    @classmethod
    async def action_echo_async_with_classmethod(self, value):
        await asyncio.sleep(0.1)
        return value
    
    class parameterized_action(ParameterizedFunction):

        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

        def __call__(self, instance, arg1, arg2, arg3):
            return instance.id, arg1, arg2, arg3

    class parameterized_action_without_call(ParameterizedFunction):

        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

    class parameterized_action_async(ParameterizedFunction):
            
        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

        async def __call__(self, instance, arg1, arg2, arg3):
            await asyncio.sleep(0.1)
            return instance.id, arg1, arg2, arg3

    def __internal__(self, value):
        return value

    def incorrectly_decorated_method(self, value):
        return value
    
    def not_an_action(self, value):
        return value
    
    async def not_an_async_action(self, value):
        await asyncio.sleep(0.1)
        return value
    
    def json_schema_validated_action(self, val1: int, val2: str, val3: dict, val4: list):
        return {
            'val1': val1,
            'val3': val3           
        }
    
    def pydantic_validated_action(self, val1: int, val2: str, val3: dict, val4: list) -> typing.Dict[str, typing.Union[int, dict]]:
        return {
            'val2': val2,
            'val4': val4           
        }
    
    @action()
    def get_serialized_data(self):
        return b'foobar'
    
    @action()
    def get_mixed_content_data(self):
        return 'foobar', b'foobar'
    
    @action()
    def sleep(self):
        time.sleep(10)

    #----------- Properties --------------

    base_property = Property(default=None, allow_None=True,
                            doc='a base Property class')
    number_prop = Number(doc="A fully editable number property", 
                        default=1)
    string_prop = String(default='hello', regex='^[a-z]+',
                        doc="A string property with a regex constraint to check value errors")
    int_prop = Integer(default=5, step=2, bounds=(0, 100),
                        doc="An integer property with step and bounds constraints to check RW")
    selector_prop = Selector(objects=['a', 'b', 'c', 1], default='a',
                        doc="A selector property to check RW")
    observable_list_prop = List(default=None, allow_None=True, observable=True,
                        doc="An observable list property to check observable events on write operations")
    observable_readonly_prop = Number(default=0, readonly=True, observable=True,
                        doc="An observable readonly property to check observable events on read operations")
    db_commit_number_prop = Number(default=0, db_commit=True,
                        doc="A fully editable number property to check commits to db on write operations")
    db_init_int_prop = Integer(default=1, db_init=True,
                        doc="An integer property to check initialization from db")
    db_persist_selector_prop = Selector(objects=['a', 'b', 'c', 1], default='a', db_persist=True,
                        doc="A selector property to check persistence to db on write operations")
    non_remote_number_prop = Number(default=5, remote=False,
                        doc="A non remote number property to check non-availability on client")
    sleeping_prop = Number(default=0, observable=True, readonly=True,
                        doc="A property that sleeps for 10 seconds on read operations")
    
    @sleeping_prop.getter
    def get_sleeping_prop(self):
        time.sleep(10)
        try:
            return self._sleeping_prop
        except AttributeError:
            return 42
    
    @sleeping_prop.setter
    def set_sleeping_prop(self, value):
        self._sleeping_prop = value
    
    
    #----------- Pydantic and JSON schema properties --------------
    
    class PydanticProp(BaseModel):
        foo : str
        bar : int
        foo_bar : float

    pydantic_prop = Property(default=None, allow_None=True, model=PydanticProp, 
                        doc="A property with a pydantic model to check RW")

    pydantic_simple_prop = Property(default=None, allow_None=True, model='int', 
                        doc="A property with a simple pydantic model to check RW")

    schema = {
        "type" : "string",
        "minLength" : 1,
        "maxLength" : 10,
        "pattern" : "^[a-z]+$"
    }

    json_schema_prop = Property(default=None, allow_None=True, model=schema, 
                        doc="A property with a json schema to check RW")

    @observable_readonly_prop.getter
    def get_observable_readonly_prop(self):
        if not hasattr(self, '_observable_readonly_prop'):
            self._observable_readonly_prop = 0
        self._observable_readonly_prop += 1
        return self._observable_readonly_prop

    #----------- Class properties --------------

    simple_class_prop = Number(class_member=True, default=42, 
                            doc='simple class property with default value')
    
    managed_class_prop = Number(class_member=True, 
                            doc='(managed) class property with custom getter/setter')
    
    @managed_class_prop.getter
    def get_managed_class_prop(cls):
        return getattr(cls, '_managed_value', 0)
    
    @managed_class_prop.setter
    def set_managed_class_prop(cls, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        cls._managed_value = value
        
    readonly_class_prop = String(class_member=True, readonly=True,
                                doc='read-only class property')
    
    @readonly_class_prop.getter
    def get_readonly_class_prop(cls):
        return "read-only-value"
    
    deletable_class_prop = Number(class_member=True, default=100,
                                doc='deletable class property with custom deleter')
    
    @deletable_class_prop.getter
    def get_deletable_class_prop(cls):
        return getattr(cls, '_deletable_value', 100)
    
    @deletable_class_prop.setter
    def set_deletable_class_prop(cls, value):
        cls._deletable_value = value
        
    @deletable_class_prop.deleter
    def del_deletable_class_prop(cls):
        if hasattr(cls, '_deletable_value'):
            del cls._deletable_value

    not_a_class_prop = Number(class_member=False, default=43,
                            doc="test property with class_member=False")

    @not_a_class_prop.getter
    def get_not_a_class_prop(self):
        return getattr(self, '_not_a_class_value', 43)
    
    @not_a_class_prop.setter
    def set_not_a_class_prop(self, value):
        self._not_a_class_value = value

    @not_a_class_prop.deleter
    def del_not_a_class_prop(self):
        if hasattr(self, '_not_a_class_value'):
            del self._not_a_class_value
    
    @action()
    def print_props(self):
        print(f'number_prop: {self.number_prop}')
        print(f'string_prop: {self.string_prop}')
        print(f'int_prop: {self.int_prop}')
        print(f'selector_prop: {self.selector_prop}')
        print(f'observable_list_prop: {self.observable_list_prop}')
        print(f'observable_readonly_prop: {self.observable_readonly_prop}')
        print(f'db_commit_number_prop: {self.db_commit_number_prop}')
        print(f'db_init_int_prop: {self.db_init_int_prop}')
        print(f'db_persist_selctor_prop: {self.db_persist_selector_prop}')
        print(f'non_remote_number_prop: {self.non_remote_number_prop}')
    
    test_event = Event(friendly_name='test-event', doc='test event')



def replace_methods_with_actions(thing_cls: typing.Type[TestThing]) -> None:
    exposed_actions = []
    if not isinstance(thing_cls.action_echo, (Action, BoundAction)):
        thing_cls.action_echo = action()(thing_cls.action_echo)
        thing_cls.action_echo.__set_name__(thing_cls, 'action_echo')
    exposed_actions.append('action_echo')

    if not isinstance(thing_cls.action_echo_with_classmethod, (Action, BoundAction)):
        # classmethod can be decorated with action   
        thing_cls.action_echo_with_classmethod = action()(thing_cls.action_echo_with_classmethod)   
        # BoundAction already, cannot call __set_name__ on it, at least at the time of writing
    exposed_actions.append('action_echo_with_classmethod')

    if not isinstance(thing_cls.action_echo_async, (Action, BoundAction)):
        # async methods can be decorated with action       
        thing_cls.action_echo_async = action()(thing_cls.action_echo_async)
        thing_cls.action_echo_async.__set_name__(thing_cls, 'action_echo_async')
    exposed_actions.append('action_echo_async')
    
    if not isinstance(thing_cls.action_echo_async_with_classmethod, (Action, BoundAction)):
        # async classmethods can be decorated with action    
        thing_cls.action_echo_async_with_classmethod = action()(thing_cls.action_echo_async_with_classmethod)
        # BoundAction already, cannot call __set_name__ on it, at least at the time of writing
    exposed_actions.append('action_echo_async_with_classmethod')

    if not isinstance(thing_cls.parameterized_action, (Action, BoundAction)):
        # parameterized function can be decorated with action
        thing_cls.parameterized_action = action(safe=True)(thing_cls.parameterized_action)
        thing_cls.parameterized_action.__set_name__(thing_cls, 'parameterized_action')  
    exposed_actions.append('parameterized_action')

    if not isinstance(thing_cls.parameterized_action_without_call, (Action, BoundAction)):
        thing_cls.parameterized_action_without_call = action(idempotent=True)(thing_cls.parameterized_action_without_call)
        thing_cls.parameterized_action_without_call.__set_name__(thing_cls, 'parameterized_action_without_call')
    exposed_actions.append('parameterized_action_without_call')

    if not isinstance(thing_cls.parameterized_action_async, (Action, BoundAction)):
        thing_cls.parameterized_action_async = action(synchronous=True)(thing_cls.parameterized_action_async)
        thing_cls.parameterized_action_async.__set_name__(thing_cls, 'parameterized_action_async')
    exposed_actions.append('parameterized_action_async')

    if not isinstance(thing_cls.json_schema_validated_action, (Action, BoundAction)):
        # schema validated actions
        thing_cls.json_schema_validated_action = action(
            input_schema={
                'type': 'object',
                'properties': {
                    'val1': {'type': 'integer'},
                    'val2': {'type': 'string'},
                    'val3': {'type': 'object'},
                    'val4': {'type': 'array'}
                }
            },
            output_schema={
                'type': 'object',
                'properties': {
                    'val1': {'type': 'integer'},
                    'val3': {'type': 'object'}
                }
            }
        )(thing_cls.json_schema_validated_action)
        thing_cls.json_schema_validated_action.__set_name__(thing_cls, 'json_schema_validated_action')
    exposed_actions.append('json_schema_validated_action')

    if not isinstance(thing_cls.pydantic_validated_action, (Action, BoundAction)):
        thing_cls.pydantic_validated_action = action()(thing_cls.pydantic_validated_action)
        thing_cls.pydantic_validated_action.__set_name__(thing_cls, 'pydantic_validated_action')
    exposed_actions.append('pydantic_validated_action')

    replace_methods_with_actions._exposed_actions = exposed_actions



test_thing_TD = {
    'title' : 'TestThing',
    'id': 'test-thing',
    'actions' : {
        'get_transports': {
            'title' : 'get_transports',
            'description' : 'returns available transports'
        },
        'action_echo': {
            'title' : 'action_echo',
            'description' : 'returns value as it is to the client'
        },
        'get_serialized_data': {
            'title' : 'get_serialized_data',
            'description' : 'returns serialized data',
        },
        'get_mixed_content_data': {
            'title' : 'get_mixed_content_data',
            'description' : 'returns mixed content data',
        },
        'sleep': {
            'title' : 'sleep',
            'description' : 'sleeps for 10 seconds',
        }
    },
    'properties' : {
        'base_property': {
            'title' : 'base_property',
            'description' : 'test property',
            'default' : None
        },
        'number_prop': {
            'title' : 'number_prop',
            'description' : 'A fully editable number property',
            'default' : 0
        },
        'string_prop': {
            'title' : 'string_prop',
            'description' : 'A string property with a regex constraint to check value errors',
            'default' : 'hello',
            'regex' : '^[a-z]+$'
        },
    }
}


if __name__ == '__main__':
    T = TestThing(id='test-thing')
    T.run()