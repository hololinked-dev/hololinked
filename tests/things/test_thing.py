import time
from hololinked.core import Thing, action, Property, Event
from hololinked.core.properties import Number, String, Selector, List, Integer
from pydantic import BaseModel



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
    def test_echo(self, value):
        return value
    
    @action()
    def get_serialized_data(self):
        return b'foobar'
    
    @action()
    def get_mixed_content_data(self):
        return 'foobar', b'foobar'
    
    @action()
    def sleep(self):
        time.sleep(10)


    test_property = Property(default=None, doc='test property', allow_None=True)

    test_event = Event(friendly_name='test-event', doc='test event')


    number_prop = Number(doc="A fully editable number property")

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

    
    # Simple class property with default value
    simple_class_prop = Number(class_member=True, default=42)
    
    # Class property with custom getter/setter
    managed_class_prop = Number(class_member=True)
    
    @managed_class_prop.getter
    def get_managed_class_prop(cls):
        return getattr(cls, '_managed_value', 0)
    
    @managed_class_prop.setter
    def set_managed_class_prop(cls, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        cls._managed_value = value
        
    # Read-only class property
    readonly_class_prop = String(class_member=True, readonly=True)
    
    @readonly_class_prop.getter
    def get_readonly_class_prop(cls):
        return "read-only-value"
    
    # Deletable class property
    deletable_class_prop = Number(class_member=True, default=100)
    
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

    not_a_class_prop = Number(class_member=False, default=43)

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
   


test_thing_TD = {
    'title' : 'TestThing',
    'id': 'test-thing',
    'actions' : {
        'get_transports': {
            'title' : 'get_transports',
            'description' : 'returns available transports'
        },
        'test_echo': {
            'title' : 'test_echo',
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
        'test_property': {
            'title' : 'test_property',
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