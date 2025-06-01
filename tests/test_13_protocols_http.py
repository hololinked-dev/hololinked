from types import SimpleNamespace
import unittest, time, logging, requests
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.meta import ThingMeta
from hololinked.server.http import HTTPServer
from hololinked.core.zmq.rpc_server import RPCServer # sets loop policy, TODO: move somewhere else
from hololinked.utils import get_current_async_loop, issubklass, print_pending_tasks_in_current_loop

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
        server.listen(forked=True)
        time.sleep(3)
        server.stop()
        time.sleep(2)

        # init, run and stop asynchronously
        server.listen(forked=True)
        time.sleep(3)
        get_current_async_loop().run_until_complete(server.async_stop())
        time.sleep(2)

        server.listen(forked=True)
        time.sleep(3)
        response = requests.post('http://localhost:8080/stop')
        self.assertIn(response.status_code, [200, 201, 202, 204])
        time.sleep(2)

    def notest_2_add_interaction_affordance(self):
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
        

    def notest_3_add_thing(self):
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
            

    def notest_4_add_thing_over_zmq_server(self):
        """extension of previous two tests to complete adding a thing running over a zmq server"""
        server = HTTPServer(log_level=logging.ERROR+10)
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)

        thing = OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10)
        thing.run_with_zmq_server(ZMQ_TRANSPORTS.INPROC, forked=True)
        
        while thing.rpc_server is None: 
            time.sleep(0.01)
        server.zmq_client_pool.context = thing.rpc_server.context
        server.add_property('/max-intensity/custom', OceanOpticsSpectrometer.max_intensity)
        server.add_action('/connect/custom', OceanOpticsSpectrometer.connect)
        server.add_event('/intensity/event/custom', OceanOpticsSpectrometer.intensity_measurement_event)
        server.register_id_for_thing(OceanOpticsSpectrometer, 'test-spectrometer')
        server.add_thing({"INPROC": thing.id})

        self.assertTrue(
            len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
            len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
        )
        
        fake_request = SimpleNamespace(path='/test-spectrometer/max-intensity/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path='/non-existing-path-that-i-know-will-not-match')
        self.assertFalse(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path='/test-spectrometer/connect/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path='/test-spectrometer/intensity/event/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))

        # server.router.print_rules()
        thing.rpc_server.stop()


    def test_5_http_handler_functionalities(self):
        for thing, port in zip([
                    OceanOpticsSpectrometer(
                        id='test-spectrometer', 
                        serial_number='simulation',                        
                        log_level=logging.ERROR+10,
                    )
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ], [
                    8085
                ]):
            thing.run_with_http_server(forked=True, port=port)
            time.sleep(3) # TODO: add a way to check if the server is running

        session = requests.Session()
        for (method, path, body) in [
                    ('get',  '/test-spectrometer/max-intensity', 16384),
                    ('get',  '/test-spectrometer/serial-number', 'simulation'),
                    ('get',  '/test-spectrometer/integration-time', 1000),
                    ('post', '/test-spectrometer/disconnect', None),
                    ('post', '/test-spectrometer/connect', None)
                ]:
            if method == 'get':
                response = session.get(f'http://localhost:{port}{path}')
            elif method == 'post':
                response = session.post(f'http://localhost:{port}{path}')
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            if body:
                self.assertTrue(response.json() == body)


        for (method, path, body) in [
                ('post', '/test-spectrometer/exit', None),
                ('post', '/stop', None)
            ]:
            if method == 'get':
                response = session.get(f'http://localhost:{port}{path}')
            elif method == 'post':
                response = session.post(f'http://localhost:{port}{path}')
      

    def notest_5_run_thing_with_http_server(self):
        """Test running a thing with an HTTP server."""

        # add a thing, both class and instance
        for thing, port in zip([
                    OceanOpticsSpectrometer(id='test-spectrometer-stop', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ], [
                    8090
                ]):
            thing.run_with_http_server(forked=True, port=port)
            time.sleep(3)
            response = requests.post(f'http://localhost:{port}/stop')
            self.assertTrue(response.status_code in [200, 201, 202, 204])

        for thing, port in zip([
                    OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ], [
                    8091
                ]):
            thing.run_with_http_server(forked=True, port=port)
            time.sleep(3)
            response = requests.post(f'http://localhost:{port}/stop')
            self.assertTrue(response.status_code in [200, 201, 202, 204])

           


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))