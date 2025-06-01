import queue, requests, unittest, logging, time, multiprocessing

try:
    from utils import TestCase, TestRunner, print_lingering_threads
    from things import start_thing_forked, TestThing
except ImportError:
    from .utils import TestCase, TestRunner, print_lingering_threads
    from .things import start_thing_forked, TestThing



class TestHTTPServer(TestCase):

    @classmethod
    def setUpClass(self):
        # Code to set up any necessary resources or configurations before each test case
        print("test HTTP server")

    @classmethod
    def tearDownClass(self):
        # Code to clean up any resources or configurations after each test case
        print("tear down test HTTP server")


    def test_1_threaded_http_server(self):
        # Connect HTTP server and Thing in different threads
        done_queue = queue.Queue()
        T = start_thing_forked(
           TestThing,   
           instance_name='test-http-server-in-thread',
           as_process=False, 
           http_server=True,
           done_queue=done_queue
        )
        time.sleep(1) # let the server start
        session = requests.Session()
        session.post('http://localhost:8080/test-http-server-in-thread/exit')
        session.post('http://localhost:8080/stop')
        T.join()
        self.assertEqual(done_queue.get(), 'test-http-server-in-thread')
        done_queue.task_done()
        done_queue.join()
       

    def test_2_process_http_server(self):
        # Connect HTTP server and Thing in separate processes
        done_queue = multiprocessing.Queue()
        P = start_thing_forked(
           TestThing,   
           instance_name='test-http-server-in-process',
           as_process=True, 
           http_server=True,
           done_queue=done_queue
        )
        time.sleep(5) # let the server start
        session = requests.Session()
        session.post('http://localhost:8080/test-http-server-in-process/exit')       
        session.post('http://localhost:8080/stop')       
        self.assertEqual(done_queue.get(), 'test-http-server-in-process')
        
       
if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
   