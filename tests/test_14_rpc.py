import threading, random, asyncio, requests
import logging, multiprocessing, unittest
from hololinked.client import ObjectProxy

try:
    from .utils import TestCase, TestRunner
    from .things import TestThing, start_thing_forked
except ImportError:
    from utils import TestCase, TestRunner
    from things import TestThing, start_thing_forked 



class TestRPC(TestCase):

    @classmethod
    def setUpClass(self):
        print("test RPC")
        self.thing_cls = TestThing
        start_thing_forked(
                        thing_cls=self.thing_cls, 
                        instance_name='test-rpc',
                        log_level=logging.WARN,
                        protocols=['IPC', 'TCP'],
                        tcp_socket_address='tcp://*:58000',
                        http_server=True
                    )   
        self.thing_client = ObjectProxy('test-rpc') # type: TestThing
       
    @classmethod
    def tearDownClass(self):
        print("tear down test RPC")
        self.thing_client.exit()


    def test_1_normal_client(self):
        # First test a simple single-threaded client and make sure it succeeds 
        # all requests  
        done_queue = multiprocessing.Queue()
        start_client(done_queue)
        self.assertEqual(done_queue.get(), True)

    def test_2_threaded_client(self):
        # Then test a multi-threaded client and make sure it succeeds all requests
        done_queue = multiprocessing.Queue()
        start_client(done_queue, 'threading')
        self.assertEqual(done_queue.get(), True)

    def test_3_async_client(self):
        # Then an async client
        done_queue = multiprocessing.Queue()
        start_client(done_queue, 'async')
        self.assertEqual(done_queue.get(), True)

    def test_4_async_multiple_client(self):
        # Then an async client with multiple coroutines/futures
        done_queue = multiprocessing.Queue()
        start_client(done_queue, 'async_multiple')
        self.assertEqual(done_queue.get(), True)

    def test_5_http_client(self):
        # Then a HTTP client which uses a message mapped ZMQ client pool on the HTTP server
        done_queue = multiprocessing.Queue()
        start_client(done_queue, 'http')
        self.assertEqual(done_queue.get(), True)

    def test_6_tcp_client(self):
        # Also, for sake, a TCP client
        done_queue = multiprocessing.Queue()
        start_client(done_queue, tcp_socket_address='tcp://localhost:58000')
        self.assertEqual(done_queue.get(), True)


    def test_7_multiple_clients(self):
        # Then parallely run all of them at once and make sure they all succeed
        # which means the server can request accept from anywhere at any time and not fail
        done_queue_1 = multiprocessing.Queue()
        start_client(done_queue_1)

        done_queue_2 = multiprocessing.Queue()
        start_client(done_queue_2)
        
        done_queue_3 = multiprocessing.Queue()
        start_client(done_queue_3, 'threading')

        done_queue_4 = multiprocessing.Queue()
        start_client(done_queue_4, 'async')

        done_queue_5 = multiprocessing.Queue()
        start_client(done_queue_5, 'async_multiple')

        done_queue_6 = multiprocessing.Queue()
        start_client(done_queue_6, 'http')

        done_queue_7 = multiprocessing.Queue()
        start_client(done_queue_7, typ='threading', tcp_socket_address='tcp://localhost:58000')

        done_queue_8 = multiprocessing.Queue()
        start_client(done_queue_8, tcp_socket_address='tcp://localhost:58000')

        self.assertEqual(done_queue_1.get(), True)
        self.assertEqual(done_queue_2.get(), True)
        self.assertEqual(done_queue_3.get(), True)
        self.assertEqual(done_queue_4.get(), True)
        self.assertEqual(done_queue_5.get(), True)
        self.assertEqual(done_queue_6.get(), True)
        self.assertEqual(done_queue_7.get(), True)
        self.assertEqual(done_queue_8.get(), True)



def start_client(done_queue : multiprocessing.Queue, typ : str = 'normal', tcp_socket_address : str = None):
    if typ == 'normal':
        return multiprocessing.Process(target=normal_client, args=(done_queue, tcp_socket_address)).start()
    elif typ == 'threading':
        return multiprocessing.Process(target=threading_client, args=(done_queue, tcp_socket_address)).start()
    elif typ == 'async':
        return multiprocessing.Process(target=async_client, args=(done_queue,)).start()
    elif typ == 'async_multiple':
        return multiprocessing.Process(target=async_client_multiple, args=(done_queue,)).start()
    elif typ == 'http':
        return multiprocessing.Process(target=http_client, args=(done_queue,)).start()
    raise NotImplementedError(f"client type {typ} not implemented or unknown.")


def gen_random_data():
    choice = random.randint(0, 1)
    if choice == 0: # float
        return random.random()*1000
    elif choice == 1:
        return random.choice(['a', True, False, 10, 55e-3, [i for i in range(100)], {'a': 1, 'b': 2}, 
                        None])


def normal_client(done_queue : multiprocessing.Queue = None, tcp_socket_address : str = None):
    success = True
    if tcp_socket_address:
        client = ObjectProxy('test-rpc', socket_address=tcp_socket_address, protocol='TCP') # type: TestThing
    else:
        client = ObjectProxy('test-rpc') # type: TestThing
    for i in range(2000):
        value = gen_random_data()
        ret = client.test_echo(value)
        # print("single-thread", 1, i, value, ret)
        if value != ret:    
            print("error", "single-thread", 1, i, value, ret)
            success = False
            break

    if done_queue is not None:
        done_queue.put(success)

   
def threading_client(done_queue : multiprocessing.Queue = None, tcp_socket_address : str = None):
    success = True
    if tcp_socket_address:
        client = ObjectProxy('test-rpc', socket_address=tcp_socket_address, protocol='TCP') # type: TestThing
    else:
        client = ObjectProxy('test-rpc') # type: TestThing

    def message_thread(id : int):
        nonlocal success, client
        for i in range(1000):
            value = gen_random_data()
            ret = client.test_echo(value)
            # print("multi-threaded", id, i, value, ret)
            if value != ret:
                print("error", "multi-threaded", 1, i, value, ret)
                success = False
                break

    T1 = threading.Thread(target=message_thread, args=(1,))
    T2 = threading.Thread(target=message_thread, args=(2,))
    T3 = threading.Thread(target=message_thread, args=(3,))
    T1.start()
    T2.start()
    T3.start()
    T1.join()
    T2.join()
    T3.join()

    if done_queue is not None:
        done_queue.put(success)


def async_client(done_queue : multiprocessing.Queue = None):
    success = True
    client = ObjectProxy('test-rpc', async_mixin=True) # type: TestThing

    async def message_coro():
        nonlocal success, client
        for i in range(2000):
            value = gen_random_data()
            ret = await client.async_invoke_action('test_echo', value)
            # print("async", 1, i, value, ret)
            if value != ret:
                print("error", "async", 1, i, value, ret)
                success = False
                break

    asyncio.run(message_coro())
    if done_queue is not None:
        done_queue.put(success)


def async_client_multiple(done_queue : multiprocessing.Queue = None):
    success = True
    client = ObjectProxy('test-rpc', async_mixin=True) # type: TestThing

    async def message_coro(id):
        nonlocal success, client
        for i in range(1000):
            value = gen_random_data()
            ret = await client.async_invoke_action('test_echo', value)
            # print("multi-coro", id, i, value, ret)
            if value != ret:
                print("error", "multi-coro", id, i, value, ret)
                success = False
                break

    asyncio.get_event_loop().run_until_complete(
        asyncio.gather(*[message_coro(1), message_coro(2), message_coro(3)]))
    if done_queue is not None:
        done_queue.put(success)


def http_client(done_queue : multiprocessing.Queue = None):
    success = True
    session = requests.Session()

    def worker(id : int):
        nonlocal success
        for i in range(1000):
            value = gen_random_data()
            ret =  session.post(
                            'http://localhost:8080/test-rpc/test-echo', 
                            json={'value': value},
                            headers={'Content-Type': 'application/json'}
                        )       
            # print("http", id, i, value, ret)
            if value != ret.json():
                print("http", id, i, value, ret)
                success = False
                break
            
    T1 = threading.Thread(target=worker, args=(1,))
    T2 = threading.Thread(target=worker, args=(2,))
    T1.start()
    T2.start()
    T1.join()
    T2.join()

    if done_queue is not None:
        done_queue.put(success)





if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
