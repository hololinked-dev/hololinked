import unittest, time, logging
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.meta import ThingMeta
from hololinked.server.http import HTTPServer
from hololinked.core.zmq.rpc_server import RPCServer # sets loop policy, TODO: move somewhere else
from hololinked.utils import get_current_async_loop, issubklass

try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from utils import TestCase, TestRunner



class TestHTTPServer(TestCase):


    def test_1_init_run_and_stop(self):
        """Test basic init, run and stop of the HTTP server."""

        # init, run and stop synchronously
        server = HTTPServer(log_level=logging.ERROR+10)
        self.assertTrue(server.all_ok)
        # server.listen(forked=True)
        # time.sleep(3)
        # server.stop()

        # init, run and stop asynchronously
        server.listen(forked=True)
        time.sleep(3)
        get_current_async_loop().run_until_complete(server.async_stop())


    def test_2_add_interaction_affordance(self):
        """Test adding an interaction affordance to the HTTP server."""

        # init, run and stop synchronously
        server = HTTPServer(log_level=logging.ERROR+10)
        self.assertTrue(server.all_ok)
        
        # add an interaction affordance
        server.add_property('/max-intensity', OceanOpticsSpectrometer.max_intensity)
        server.add_action('/connect', OceanOpticsSpectrometer.connect)
        server.add_event('/intensity/event', OceanOpticsSpectrometer.intensity_measurement_event)
        
        self.assertIn('/max-intensity', server.router)
        self.assertIn('/connect', server.router)
        self.assertIn('/intensity/event', server.router)

        # replacing interation affordances on an existing URL path causes a warning
        self.assertWarns(
            UserWarning,
            server.add_property,
            '/max-intensity', OceanOpticsSpectrometer.last_intensity
        )
        self.assertWarns(
            UserWarning,
            server.add_action,
            '/connect', OceanOpticsSpectrometer.disconnect
        )
        self.assertWarns(
            UserWarning,
            server.add_event,
            '/intensity/event', OceanOpticsSpectrometer.intensity_measurement_event
        )
        

    def test_3_add_thing(self):
        """Test adding a thing to the HTTP server."""

        # init, run and stop synchronously
        # self.assertTrue(server.all_ok)
        # server.listen(forked=True)
        
        # add a thing, both class and instance
        for thing in [
                    OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ]:
            server = HTTPServer(log_level=logging.ERROR+10)
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            server.add_thing(thing)
            self.assertTrue(
                len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
                len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            )
            # server.router.print_rules()

        for thing_meta in [OceanOpticsSpectrometer, TestThing]:
            self.assertWarns(
                UserWarning,
                server.add_thing,
                thing_meta
            )
       
        # dont overwrite already given routes
        for thing in [
                    OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ]:
            server = HTTPServer(log_level=logging.ERROR+10)
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            server.add_property('/max-intensity/custom', OceanOpticsSpectrometer.max_intensity)
            server.add_action('/connect/custom', OceanOpticsSpectrometer.connect)
            server.add_event('/intensity/event/custom', OceanOpticsSpectrometer.intensity_measurement_event)
            server.add_thing(thing)
            self.assertIn('/max-intensity/custom', server.router)
            self.assertIn('/connect/custom', server.router)
            self.assertIn('/intensity/event/custom', server.router)
            self.assertTrue(
                    len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
                    len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
                )
            

    def test_4_add_thing_over_zmq_server(self):
        """extension of previous two tests to complete adding a thing running over a zmq server"""
        server = HTTPServer(log_level=logging.ERROR+10)
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)

        thing = OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10)
        thing.run_with_zmq_server(ZMQ_TRANSPORTS.INPROC, forked=True)
        
        while thing.rpc_server is None: 
            time.sleep(0.1)
        server.zmq_client_pool.context = thing.rpc_server.context
        server.add_property('/max-intensity/custom', OceanOpticsSpectrometer.max_intensity)
        server.add_action('/connect/custom', OceanOpticsSpectrometer.connect)
        server.add_event('/intensity/event/custom', OceanOpticsSpectrometer.intensity_measurement_event)
        server.add_thing({"INPROC": thing.id})

        # self.assertTrue(
        #     len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
        #     len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
        # )
        thing.rpc_server.stop()
        server.stop()



def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))