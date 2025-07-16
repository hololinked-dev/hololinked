from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
import typing
import unittest, time, logging, requests
from hololinked.config import global_config
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.meta import ThingMeta
from hololinked.core.zmq.message import ServerExecutionContext, ThingExecutionContext, default_server_execution_context
from hololinked.serializers import JSONSerializer
from hololinked.serializers.payloads import PreserializedData, SerializableData
from hololinked.serializers.serializers import MsgpackSerializer, PickleSerializer, BaseSerializer
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
        
        # stop remotely
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
        

    def notest_3_add_thing(self):
        """Test adding a Thing object to the HTTP server."""
   
        # add a thing, both class and instance
        server = HTTPServer(log_level=logging.ERROR+10)
        for thing in [
                    OceanOpticsSpectrometer(id='test', log_level=logging.ERROR+10),
                    # TestThing(id='test-thing', log_level=logging.ERROR+10)
                ]:
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            server.add_thing(thing)
            # self.assertTrue(
            #     len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
            #     len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            # )
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
                    OceanOpticsSpectrometer(id='test', log_level=logging.ERROR+10),
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
            # self.assertNotIn(f'/{pep8_to_dashed_name(OceanOpticsSpectrometer.max_intensity.name)}', server.router)
            # self.assertNotIn(f'/{pep8_to_dashed_name(OceanOpticsSpectrometer.connect.name)}', server.router)
            # self.assertNotIn(f'/{pep8_to_dashed_name(OceanOpticsSpectrometer.intensity_measurement_event.name)}', server.router)
            # self.assertTrue(
            #         len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
            #         len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            #     )
            # also check that it does not create duplicate rules


    def notest_4_add_thing_over_zmq_server(self):
        """extension of previous two tests to complete adding a thing running over a zmq server"""
        server = HTTPServer(log_level=logging.ERROR+10)
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)

        thing_id = 'test-spectrometer-add-over-zmq'
        thing = OceanOpticsSpectrometer(id=thing_id, log_level=logging.ERROR+10)
        thing.run_with_zmq_server(ZMQ_TRANSPORTS.INPROC, forked=True)
        
        server.add_property('/max-intensity/custom', OceanOpticsSpectrometer.max_intensity)
        server.add_action('/connect/custom', OceanOpticsSpectrometer.connect)
        server.add_event('/intensity/event/custom', OceanOpticsSpectrometer.intensity_measurement_event)
        server.register_id_for_thing(OceanOpticsSpectrometer, thing_id)   
        server.add_thing({"INPROC": thing.id})
  
        # server.router.print_rules()
        # print(thing.properties.remote_objects.keys(), thing.actions.descriptors.keys(), thing.events.descriptors.keys())
        # self.assertTrue(
        #     len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >= 
        #     len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
        # )
        
        fake_request = SimpleNamespace(path=f'/{thing_id}/max-intensity/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path='/non-existing-path-that-i-know-will-not-match')
        self.assertFalse(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path=f'/{thing_id}/connect/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))
        fake_request = SimpleNamespace(path=f'/{thing_id}/intensity/event/custom')
        self.assertTrue(any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules]))

        thing.rpc_server.stop()


    def notest_5_handlers(self):
        """Test request info and payload decoding in RPC handlers along with content type handling"""
        latest_request_info = None # type: "LatestRequestInfo"

        @dataclass 
        class LatestRequestInfo:
            server_execution_context: ServerExecutionContext | dict[str, Any]
            thing_execution_context: ThingExecutionContext | dict[str, Any]
            payload: SerializableData
            preserialized_payload: PreserializedData

        class TestableRPCHandler(RPCHandler):

            def update_latest_request_info(self) -> None:
                nonlocal latest_request_info
                server_execution_context, thing_execution_context = self.get_execution_parameters()
                payload, preserialized_payload = self.get_request_payload()
                latest_request_info = LatestRequestInfo(
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                    payload=payload,
                    preserialized_payload=preserialized_payload
                )
                
            async def get(self):
                self.update_latest_request_info()
                self.set_status(200)
                self.finish()
            
            async def put(self):
                self.update_latest_request_info()
                self.set_status(200)
                self.finish()
            
            async def post(self):
                # for exit to go through 
                await self.handle_through_thing('invokeAction')

        global_config.ALLOW_PICKLE = True # allow pickle serializer for testing
        thing_id = 'test-spectrometer-request-info'
        thing = OceanOpticsSpectrometer(id=thing_id, log_level=logging.ERROR+10)
        thing.run_with_http_server(port=8086, forked=True, property_handler=TestableRPCHandler,
                                action_handler=TestableRPCHandler)
        
        session = requests.session()
        for serializer in [JSONSerializer(), MsgpackSerializer(), PickleSerializer()]:
            serializer: BaseSerializer
            for (method, path, body) in [
                # server and thing execution context tests
                ('get', f'/{thing_id}/integration-time', None),
                ('get', f'/{thing_id}/integration-time?fetchExecutionLogs=true', None),
                ('get', f'/{thing_id}/integration-time?fetchExecutionLogs=true&oneway=true', None),
                ('get', f'/{thing_id}/integration-time?oneway=true&invokationTimeout=100', None),
                ('get', f'/{thing_id}/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true', None),
                # test payloads for JSON content type
                ('put', f'/{thing_id}/integration-time', 1200),
                ('put', f'/{thing_id}/integration-time?fetchExecutionLogs=true', {'a' : 1, 'b': 2}),
                ('put', f'/{thing_id}/integration-time?fetchExecutionLogs=true&oneway=true', [1, 2, 3]),
                ('put', f'/{thing_id}/integration-time?oneway=true&invokationTimeout=100', 'abcd'),
                ('put', f'/{thing_id}/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true', True),
                # test payloads for other content types
            ]:
                response = session.request(
                            method=method, 
                            url=f'http://localhost:8086{path}',
                            data=serializer.dumps(body) if body is not None else None,
                            headers={"Content-Type": serializer.content_type}
                        )
                self.assertTrue(response.status_code in [200, 201, 202, 204])
                assert isinstance(latest_request_info, LatestRequestInfo)
                # test ThingExecutionContext 
                self.assertTrue(isinstance(latest_request_info.thing_execution_context, ThingExecutionContext))
                self.assertTrue(
                    ('fetchExecutionLogs' in path and latest_request_info.thing_execution_context.fetchExecutionLogs) or \
                    not latest_request_info.thing_execution_context.fetchExecutionLogs
                ) 
                # test ServerExecutionContext
                self.assertTrue(isinstance(latest_request_info.server_execution_context, ServerExecutionContext))
                self.assertTrue(
                    ('oneway' in path and latest_request_info.server_execution_context.oneway) or \
                    not latest_request_info.server_execution_context.oneway
                )
                self.assertTrue(
                    ('invokationTimeout' in path and latest_request_info.server_execution_context.invokationTimeout == 100) or \
                    # assume that in all tests where invokation timeout is specified, it will be 100
                    latest_request_info.server_execution_context.invokationTimeout == default_server_execution_context.invokationTimeout
                )
                self.assertTrue(
                    ('executionTimeout' in path and latest_request_info.server_execution_context.executionTimeout == 120) or \
                    # assume that in all tests where execution timeout is specified, it will be 120
                    latest_request_info.server_execution_context.executionTimeout == default_server_execution_context.executionTimeout
                )
                # test body
                self.assertTrue(latest_request_info.payload.deserialize() == body)
      
        self.stop_server(8086, thing_ids=[thing_id])


    def test_6_handlers_end_to_end(self):
        """
        basic end-to-end test with the HTTP server using handlers. Auth & other features not included, only invokation 
        of interaction affordances.
        """
        thing_id = 'test-spectrometer-end-to-end'
        for (thing, port) in [
            (OceanOpticsSpectrometer(id=thing_id, serial_number='simulation', log_level=logging.ERROR+10), 8085), 
        ]:
            thing.run_with_http_server(forked=True, port=port, config={"set_cors_headers": True})
            time.sleep(1) # TODO: add a way to check if the server is running

        session = requests.Session()
        for (method, path, body) in self.generate_endpoints_for_thing(OceanOpticsSpectrometer, thing_id):
            response = session.request(
                            method=method, 
                            url=f'http://localhost:{port}{path}',
                            data=JSONSerializer().dumps(body) if body is not None and method != 'get' else None,
                            headers={"Content-Type": "application/json"}
                        )
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            # check if the response body is as expected
            if body and method != 'put':
                self.assertTrue(response.json() == body)
            # check headers
            self.assertIn('Access-Control-Allow-Origin', response.headers)   
            self.assertIn('Access-Control-Allow-Credentials', response.headers)
            self.assertIn('Content-Type', response.headers)
        self.stop_server(port, thing_ids=[thing_id])

    
    def notest_7_object_proxy(self):
        pass 

    def notest_8_CORS_and_access_control(self):
        # NOTE: CORS and access control is not the same thing
        # We set CORS headers, that too only upon request, if the client has appropriate credentials to access the server
        pass 

    def notest_9_forms_generation(self):
        pass

    @classmethod
    def stop_server(self, port, thing_ids: list[str] = []):
        session = requests.Session()
        endpoints = [( 'post', f'/{thing_id}/exit', None ) for thing_id in thing_ids]
        endpoints += [('post', '/stop', None)]
        for (method, path, body) in endpoints:
            response = session.request(method=method, url=f'http://localhost:{port}{path}')

    @classmethod
    def generate_endpoints_for_thing(cls, class_: ThingMeta, thing_id: str) -> list[tuple[str, str, Any]]:
        if class_ == OceanOpticsSpectrometer:
            return [
                # read Property
                ('get', f'/{thing_id}/max-intensity', 16384),
                ('get', f'/{thing_id}/serial-number', 'simulation'),
                # write Property
                ('put', f'/{thing_id}/integration-time', 1200),
                ('get', f'/{thing_id}/integration-time', 1200),
                # invoke action
                ('post', f'/{thing_id}/disconnect', None),
                ('post', f'/{thing_id}/connect', None)
            ]
        raise NotImplementedError(f"Endpoints for {class_.__name__} not implemented yet")
           
def load_tests(loader, tests, pattern): 
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))