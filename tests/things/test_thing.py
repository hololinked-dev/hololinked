import time
from hololinked.core import Thing, action, Property, Event


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
    
   
test_thing_TD = {
    'title' : 'TestThing',
    'id': 'test-thing',
    'actions' : {
        'get_transports': {
            'title' : 'get_transports',
            'description' : 'returns available transports'
        },
        'echo_action': {
            'title' : 'echo_action',
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
        }
    }
}


if __name__ == '__main__':
    T = TestThing(id='test-thing')
    T.run()