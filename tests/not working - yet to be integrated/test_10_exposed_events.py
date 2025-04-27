import logging, threading, time
import unittest
from hololinked.client import ObjectProxy
from hololinked.server import Thing, action, Event
from hololinked.server.properties import Number
try:
    from .utils import TestCase, TestRunner
    from .things import TestThing
except ImportError:
    from utils import TestCase, TestRunner
    from things import start_thing_forked 



class TestThing(Thing):

    total_number_of_events = Number(default=1, bounds=(1, None),                            
                            doc="Total number of events pushed")
    
    test_event = Event(friendly_name="test-event", doc="A test event", 
                URL_path='/test-event') 
    
    @action()
    def push_events(self):
        threading.Thread(target=self._push_worker).start()

    def _push_worker(self):
        for i in range(100):
            self.test_event.push('test data')
            time.sleep(0.01) # 10ms



class TestEvent(TestCase):
    
    @classmethod
    def setUpClass(self):
        print("test event")
        self.thing_cls = TestThing
        start_thing_forked(self.thing_cls, instance_name='test-event',
                                    log_level=logging.WARN)   
        self.thing_client = ObjectProxy('test-event') # type: TestThing

    @classmethod
    def tearDownClass(self):
        print("tear down test event")
        self.thing_client.exit()
    
    
    def test_1_event(self):
        attempts = 100 
        self.thing_client.total_number_of_events = attempts

        results = []
        def cb(value):
            results.append(value)

        self.thing_client.test_event.subscribe(cb)
        time.sleep(3)
        # Calm down for event publisher to connect fully as there is no handshake for events
        self.thing_client.push_events()

        for i in range(attempts):
            if len(results) == attempts:
                break
            time.sleep(0.1)

        self.assertEqual(len(results), attempts)
        self.assertEqual(results, ['test data']*attempts)
        self.thing_client.test_event.unsubscribe(cb)



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())