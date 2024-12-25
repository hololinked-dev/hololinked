import time
from hololinked.server import Thing, action


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
    def get_mixed_content_type(self):
        return 'foobar', b'foorbar'
    
    @action()
    def sleep(self):
        time.sleep(10)

    
   