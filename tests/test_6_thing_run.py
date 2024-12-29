import threading
import typing
import unittest
import multiprocessing 
import logging
import zmq.asyncio

from hololinked.server import Thing
from hololinked.client import ObjectProxy
from hololinked.server.eventloop import EventLoop
try:
    from .things import TestThing, OceanOpticsSpectrometer
    from .utils import TestCase
except ImportError:
    from things import TestThing, OceanOpticsSpectrometer
    from utils import TestCase


class TestThingRun(TestCase):

    @classmethod    
    def setUpClass(self):
        print("test Thing run")
        self.thing_cls = Thing 

    @classmethod
    def tearDownClass(self):
        # Code to clean up any resources or configurations after each test case
        print("tear down test Thing run")

    def test_thing_run_and_exit(self):
        # should be able to start and end with exactly the specified transports
        done_queue = multiprocessing.Queue()
        multiprocessing.Process(target=start_thing, args=('test-run', ), kwargs=dict(done_queue=done_queue), 
                            daemon=True).start()
        thing_client = ObjectProxy('test-run', log_level=logging.WARN) # type: Thing
        self.assertEqual(thing_client.get_transports(), ['IPC']) 
        thing_client.exit()
        self.assertEqual(done_queue.get(), 'test-run') 
        
        done_queue = multiprocessing.Queue()
        multiprocessing.Process(target=start_thing, args=('test-run-2', ['IPC', 'INPROC'],),
                                kwargs=dict(done_queue=done_queue), daemon=True).start()
        thing_client = ObjectProxy('test-run-2', log_level=logging.WARN) # type: Thing
        self.assertEqual(thing_client.get_transports(), ['INPROC', 'IPC']) # order should reflect get_transports() action
        thing_client.exit()
        self.assertEqual(done_queue.get(), 'test-run-2') 
        
        done_queue = multiprocessing.Queue()
        multiprocessing.Process(target=start_thing, args=('test-run-3', ['IPC', 'INPROC', 'TCP'], 'tcp://*:59000'), 
                                kwargs=dict(done_queue=done_queue), daemon=True).start()
        thing_client = ObjectProxy('test-run-3', log_level=logging.WARN) # type: Thing
        self.assertEqual(thing_client.get_transports(), ['INPROC', 'IPC', 'TCP'])
        thing_client.exit()
        self.assertEqual(done_queue.get(), 'test-run-3')

    
    # def test_thing_run_and_exit_with_httpserver(self):
        # EventLoop.get_async_loop() # creates the event loop if absent
        # context = zmq.asyncio.Context()
        # T = threading.Thread(target=start_thing_with_http_server, args=('test-run-4', context), daemon=True)
        # T.start()       
        # # difficult case, currently not supported - https://github.com/zeromq/pyzmq/issues/1354
        # thing_client = ObjectProxy('test-run-4', log_level=logging.WARN, context=context) # type: Thing
        # self.assertEqual(thing_client.get_transports(), ['INPROC']) 
        # thing_client.exit()
        # T.join()


class TestOceanOpticsSpectrometer(TestThing):

    @classmethod
    def setUpClass(self):
        self.thing_cls = OceanOpticsSpectrometer

        
        

def start_thing(id : str, transports : typing.List[str] = ['IPC'], tcp_socket_address : str = None,
                done_queue : typing.Optional[multiprocessing.Queue] = None) -> None:
    thing = TestThing(id=id) #, log_level=logging.WARN)
    thing.run_with_zmq_server(zmq_transports=transports, tcp_socket_address=tcp_socket_address)
    if done_queue is not None:
        done_queue.put(id)


def start_thing_with_http_server(id : str, context : zmq.asyncio.Context) -> None:
    EventLoop.get_async_loop() # creates the event loop if absent
    thing = TestThing(id=id)# , log_level=logging.WARN)
    thing.run_with_http_server(context=context)


if __name__ == '__main__':
    try:
        from utils import TestRunner
    except ImportError:
        from .utils import TestRunner
    unittest.main(testRunner=TestRunner())
