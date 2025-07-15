from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
import typing
import unittest, time, logging, requests
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.meta import ThingMeta
from hololinked.core.zmq.message import ServerExecutionContext, ThingExecutionContext
from hololinked.server.http import HTTPServer
from hololinked.core.zmq.rpc_server import RPCServer # sets loop policy, TODO: move somewhere else
from hololinked.server.http.handlers import PropertyHandler, RPCHandler
from hololinked.utils import pep8_to_dashed_name

try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from utils import TestCase, TestRunner



class TestHTTPServer(TestCase):

    def notest_1_init_run_and_stop(self):
        """Test basic init, run and stop of the HTTP server."""
        # init, run and stop synchronously
        server = HTTPServer(log_level=logging.ERROR+10)
        self.assertTrue(server.all_ok)
        server.listen(forked=True)
        time.sleep(5)
        server.stop()
        time.sleep(2)

        server.listen(forked=True)
        time.sleep(5)
        response = requests.post('http://localhost:8080/stop')
        self.assertIn(response.status_code, [200, 201, 202, 204])
        time.sleep(2)

    def notest_2_add_interaction_affordance(self):
        """Test adding an interaction affordance to the HTTP server."""
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
        """Test adding a Thing object to the HTTP server."""

        # self.assertTrue(server.all_ok)
        # server.listen(forked=True)
        
        # add a thing, both class and instance
        server = HTTPServer(log_level=logging.ERROR+10)
        for thing in [
                    OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ]:
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            server.add_thing(thing)
            self.assertTrue(
                len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
                len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            )
            # server.router.print_rules()

        # adding a metaclass does not raise error, but warns and does nothing
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
        for thing_meta in [OceanOpticsSpectrometer, TestThing]:
            self.assertWarns(
                UserWarning,
                server.add_thing,
                thing_meta
            )
        self.assertTrue(len(server.app.wildcard_router.rules)+len(server.router._pending_rules) == old_number_of_rules)

        # dont overwrite already given routes
        for thing in [
                    OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ]:
            # create new server to compute number of rules
            server = HTTPServer(log_level=logging.ERROR+10)
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            # append route with /custom to denote its a custom route
            server.add_property('/max-intensity/custom', OceanOpticsSpectrometer.max_intensity)
            server.add_action('/connect/custom', OceanOpticsSpectrometer.connect)
            server.add_event('/intensity/event/custom', OceanOpticsSpectrometer.intensity_measurement_event)
            server.add_thing(thing)
            self.assertIn('/max-intensity/custom', server.router)
            self.assertIn('/connect/custom', server.router)
            self.assertIn('/intensity/event/custom', server.router)
            # check if the affordance was not added twice using the default paths while add_thing was called
            self.assertNotIn(pep8_to_dashed_name(OceanOpticsSpectrometer.max_intensity.name), server.router)
            self.assertNotIn(pep8_to_dashed_name(OceanOpticsSpectrometer.connect.name), server.router)
            self.assertNotIn(pep8_to_dashed_name(OceanOpticsSpectrometer.intensity_measurement_event.name), server.router)
            self.assertTrue(
                    len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
                    len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
                )
            # also check that it does not create duplicate rules

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


    def notest_5_http_object_proxy(self):
        pass


    def test_5_handlers(self):

        latest_request_info = None # type: typing.Optional["LatestRequestInfo"]

        @dataclass 
        class LatestRequestInfo:
            server_execution_context: Any 
            thing_execution_context: Any
            payload: Any 
            preserialized_payload: Any

        class TestableRPCHandler(RPCHandler):

            def handle_through_thing(self, operation):
                print("Handling operation through thing:", operation)
                nonlocal latest_request_info
                server_execution_context, thing_execution_context = self.get_execution_parameters()
                payload, preserialized_payload = self.get_payload()
                latest_request_info = LatestRequestInfo(
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                    payload=payload,
                    preserialized_payload=preserialized_payload
                )
                self.set_status(200)
                self.finish()

        thing = OceanOpticsSpectrometer(id='test-spectrometer', log_level=logging.ERROR+10)
        thing.run_with_http_server(port=8086, forked=True, property_handler=TestableRPCHandler,
                                action_handler=TestableRPCHandler)
        
        time.sleep(3)  # wait for the server to start
        session = requests.session()
        for (method, path, body) in [
                    ('get', '/test-spectrometer/serial-number', 'simulation'),
                    # ('put', '/test-spectrometer/integration-time', 1200),
                    # ('get', '/test-spectrometer/integration-time', 1200),
                    # ('post', '/test-spectrometer/disconnect', None),
                    # ('post', '/test-spectrometer/connect', None)
                ]:

            response = session.request(method=method, url=f'http://localhost:8086{path}')
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            assert isinstance(latest_request_info, LatestRequestInfo)
            self.assertTrue(
                isinstance(latest_request_info.thing_execution_context,dict) and \
                key in ThingExecutionContext.__dataclass_fields__ for key in latest_request_info.thing_execution_context.keys()
            )
            # self.assertTrue(
            #     isinstance(latest_request_info.server_execution_context,dict) and \
            #     key in ServerExecutionContext.__dataclass_fields__ for key in latest_request_info.server_execution_context.keys()
            # )
            # self.assertTrue(payload == body)
            # self.assertTrue()


    def notest_5_http_handler_functionalities(self):
        for (thing, port) in [
            (OceanOpticsSpectrometer(id='test-spectrometer', serial_number='simulation', log_level=logging.ERROR+10), 8085), 
        ]:
            thing.run_with_http_server(forked=True, port=port)
            time.sleep(3) # TODO: add a way to check if the server is running

        session = requests.Session()
        for (method, path, body) in [
                    ('get', '/test-spectrometer/max-intensity', 16384),
                    ('get', '/test-spectrometer/serial-number', 'simulation'),
                    ('put', '/test-spectrometer/integration-time', 1200),
                    ('get', '/test-spectrometer/integration-time', 1200),
                    ('post', '/test-spectrometer/disconnect', None),
                    ('post', '/test-spectrometer/connect', None)
                ]:
            response = session.request(method=method, url=f'http://localhost:{port}{path}')
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            if body:
                self.assertTrue(response.json() == body)

        for (method, path, body) in [  
                ('get',  '/test-spectrometer/max-intensity', 16384),
                ('get',  '/test-spectrometer/serial-number', 'simulation'),
                ('get',  '/test-spectrometer/integration-time', 1000),
                ('post', '/test-spectrometer/disconnect', None),
                ('post', '/test-spectrometer/connect', None)
            ]:
            response = session.request(method=method, url=f'http://localhost:{port}{path}')
            self.assertTrue(response.status_code == 404)

        for (method, path, body) in [
                ('post', '/test-spectrometer/exit', None),
                ('post', '/stop', None)
            ]:
            response = session.request(method=method, url=f'http://localhost:{port}{path}')
        

           
def load_tests(loader, tests, pattern): 
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))