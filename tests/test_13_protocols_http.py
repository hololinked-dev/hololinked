import asyncio
import base64
import random
import uuid
import unittest
import time
import logging
import requests
from typing import Any
from dataclasses import dataclass
from types import SimpleNamespace

from hololinked.client.abstractions import SSE
from hololinked.utils import pep8_to_dashed_name
from hololinked.config import global_config
from hololinked.constants import ZMQ_TRANSPORTS
from hololinked.core.zmq.message import (
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
)
from hololinked.serializers import JSONSerializer
from hololinked.serializers.payloads import PreserializedData, SerializableData
from hololinked.serializers.serializers import (
    MsgpackSerializer,
    PickleSerializer,
    BaseSerializer,
)
from hololinked.core.meta import ThingMeta
from hololinked.core.zmq.rpc_server import (
    RPCServer,
)  # sets loop policy, TODO: move somewhere else
from hololinked.client.proxy import ObjectProxy
from hololinked.client.factory import ClientFactory
from hololinked.server.http import HTTPServer
from hololinked.server.http.handlers import (
    PropertyHandler,
    RPCHandler,
    ThingDescriptionHandler,
)
from hololinked.server.security import Argon2BasicSecurity, BcryptBasicSecurity
from hololinked.td.security_definitions import SecurityScheme

try:
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import TestCase, TestRunner, fake
    from .test_11_rpc_e2e import TestRPCEndToEnd
except ImportError:
    from things import OceanOpticsSpectrometer, TestThing
    from utils import TestCase, TestRunner, fake
    from test_11_rpc_e2e import TestRPCEndToEnd


class TestHTTPServer(TestCase):
    def test_01_init_run_and_stop(self):
        """Test basic init, run and stop of the HTTP server."""
        # init, run and stop synchronously
        server = HTTPServer(log_level=logging.ERROR + 10, port=60001)
        self.assertTrue(server.all_ok)
        server.listen(forked=True)
        time.sleep(5)
        server.stop()
        time.sleep(2)

        # stop remotely
        server.listen(forked=True)
        time.sleep(5)
        response = requests.post(f"http://127.0.0.1:{server.port}/stop")
        self.assertIn(response.status_code, [200, 201, 202, 204])
        time.sleep(2)

    def test_02_add_interaction_affordance(self):
        """Test adding an interaction affordance to the HTTP server."""
        server = HTTPServer(log_level=logging.ERROR + 10)
        self.assertTrue(server.all_ok)

        # add an interaction affordance
        server.add_property("/max-intensity", OceanOpticsSpectrometer.max_intensity)
        server.add_action("/connect", OceanOpticsSpectrometer.connect)
        server.add_event("/intensity/event", OceanOpticsSpectrometer.intensity_measurement_event)

        self.assertIn("/max-intensity", server.router)
        self.assertIn("/connect", server.router)
        self.assertIn("/intensity/event", server.router)

        # replacing interation affordances on an existing URL path causes a warning
        self.assertWarns(
            UserWarning,
            server.add_property,
            "/max-intensity",
            OceanOpticsSpectrometer.last_intensity,
        )
        self.assertWarns(
            UserWarning,
            server.add_action,
            "/connect",
            OceanOpticsSpectrometer.disconnect,
        )
        self.assertWarns(
            UserWarning,
            server.add_event,
            "/intensity/event",
            OceanOpticsSpectrometer.intensity_measurement_event,
        )

    def test_03_add_thing(self):
        """Test adding a Thing object to the HTTP server."""

        # add a thing, both class and instance
        server = HTTPServer(log_level=logging.ERROR + 10)
        for thing in [
            OceanOpticsSpectrometer(id="test", log_level=logging.ERROR + 10),
            TestThing(id="test-thing", log_level=logging.ERROR + 10),
        ]:
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            server.add_things(thing)
            # self.assertTrue(
            #     len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >=
            #     len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            # )
            # server.router.print_rules()

        # adding a metaclass does not raise error, but warns and does nothing
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
        for thing_meta in [OceanOpticsSpectrometer, TestThing]:
            self.assertRaises(ValueError, server.add_things, thing_meta)
        self.assertTrue(
            len(server.app.wildcard_router.rules) + len(server.router._pending_rules) == old_number_of_rules
        )

        # dont overwrite already given routes
        for thing in [
            OceanOpticsSpectrometer(id="test", log_level=logging.ERROR + 10),
            TestThing(id="test-thing", log_level=logging.ERROR + 10),
        ]:
            # create new server to compute number of rules
            server = HTTPServer(log_level=logging.ERROR + 10)
            old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)
            # append route with /custom to denote its a custom route
            server.add_property("/max-intensity/custom", OceanOpticsSpectrometer.max_intensity)
            server.add_action("/connect/custom", OceanOpticsSpectrometer.connect)
            server.add_event(
                "/intensity/event/custom",
                OceanOpticsSpectrometer.intensity_measurement_event,
            )
            server.add_things(thing)
            self.assertIn("/max-intensity/custom", server.router)
            self.assertIn("/connect/custom", server.router)
            self.assertIn("/intensity/event/custom", server.router)
            # check if the affordance was not added twice using the default paths while add_thing was called
            self.assertNotIn(
                f"/{pep8_to_dashed_name(OceanOpticsSpectrometer.max_intensity.name)}",
                server.router,
            )
            self.assertNotIn(
                f"/{pep8_to_dashed_name(OceanOpticsSpectrometer.connect.name)}",
                server.router,
            )
            self.assertNotIn(
                f"/{pep8_to_dashed_name(OceanOpticsSpectrometer.intensity_measurement_event.name)}",
                server.router,
            )
            # self.assertTrue(
            #         len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >=
            #         len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
            #     )
            # also check that it does not create duplicate rules

    def test_04_add_thing_over_zmq_server(self):
        """extension of previous two tests to complete adding a thing running over a zmq server"""
        server = HTTPServer(log_level=logging.ERROR + 10)
        old_number_of_rules = len(server.app.wildcard_router.rules) + len(server.router._pending_rules)

        thing_id = f"test-add-zmq-{uuid.uuid4().hex[0:8]}"
        thing = OceanOpticsSpectrometer(id=thing_id, log_level=logging.ERROR + 10)
        thing.run_with_zmq_server(ZMQ_TRANSPORTS.INPROC, forked=True)

        server.add_property("/max-intensity/custom", OceanOpticsSpectrometer.max_intensity)
        server.add_action("/connect/custom", OceanOpticsSpectrometer.connect)
        server.add_event(
            "/intensity/event/custom",
            OceanOpticsSpectrometer.intensity_measurement_event,
        )
        server.register_id_for_thing(OceanOpticsSpectrometer, thing_id)
        server.add_things({"INPROC": thing.id})

        # server.router.print_rules()
        # print(thing.properties.remote_objects.keys(), thing.actions.descriptors.keys(), thing.events.descriptors.keys())
        # self.assertTrue(
        #     len(server.app.wildcard_router.rules) + len(server.router._pending_rules) - old_number_of_rules >=
        #     len(thing.properties.remote_objects) + len(thing.actions) + len(thing.events)
        # )

        fake_request = SimpleNamespace(path=f"/{thing_id}/max-intensity/custom")
        self.assertTrue(
            any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules])
        )
        fake_request = SimpleNamespace(path="/non-existing-path-that-i-know-will-not-match")
        self.assertFalse(
            any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules])
        )
        fake_request = SimpleNamespace(path=f"/{thing_id}/connect/custom")
        self.assertTrue(
            any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules])
        )
        fake_request = SimpleNamespace(path=f"/{thing_id}/intensity/event/custom")
        self.assertTrue(
            any([rule.matcher.match(fake_request) is not None for rule in server.app.wildcard_router.rules])
        )

        thing.rpc_server.stop()

    def test_05_handlers(self):
        """Test request info and payload decoding in RPC handlers along with content type handling"""
        latest_request_info = None  # type: "LatestRequestInfo"

        @dataclass
        class LatestRequestInfo:
            server_execution_context: ServerExecutionContext | dict[str, Any]
            thing_execution_context: ThingExecutionContext | dict[str, Any]
            payload: SerializableData
            preserialized_payload: PreserializedData

        class TestableRPCHandler(RPCHandler):
            def update_latest_request_info(self) -> None:
                nonlocal latest_request_info
                server_execution_context, thing_execution_context, _ = self.get_execution_parameters()
                payload, preserialized_payload = self.get_request_payload()
                latest_request_info = LatestRequestInfo(
                    server_execution_context=server_execution_context,
                    thing_execution_context=thing_execution_context,
                    payload=payload,
                    preserialized_payload=preserialized_payload,
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
                await self.handle_through_thing("invokeaction")

        global_config.ALLOW_PICKLE = True  # allow pickle serializer for testing
        thing_id = f"test-request-info-{uuid.uuid4().hex[0:8]}"
        port = 60002

        thing = OceanOpticsSpectrometer(id=thing_id, log_level=logging.ERROR + 10)
        thing.run_with_http_server(
            port=port,
            forked=True,
            property_handler=TestableRPCHandler,
            action_handler=TestableRPCHandler,
        )
        time.sleep(2)  # linux machines need a few moments otherwise the clients error
        session = requests.session()
        for serializer in [JSONSerializer(), MsgpackSerializer(), PickleSerializer()]:
            serializer: BaseSerializer
            for method, path, body in [
                # server and thing execution context tests
                ("get", f"/{thing_id}/integration-time", None),
                ("get", f"/{thing_id}/integration-time?fetchExecutionLogs=true", None),
                (
                    "get",
                    f"/{thing_id}/integration-time?fetchExecutionLogs=true&oneway=true",
                    None,
                ),
                (
                    "get",
                    f"/{thing_id}/integration-time?oneway=true&invokationTimeout=100",
                    None,
                ),
                (
                    "get",
                    f"/{thing_id}/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true",
                    None,
                ),
                # test payloads for JSON content type
                ("put", f"/{thing_id}/integration-time", 1200),
                (
                    "put",
                    f"/{thing_id}/integration-time?fetchExecutionLogs=true",
                    {"a": 1, "b": 2},
                ),
                (
                    "put",
                    f"/{thing_id}/integration-time?fetchExecutionLogs=true&oneway=true",
                    [1, 2, 3],
                ),
                (
                    "put",
                    f"/{thing_id}/integration-time?oneway=true&invokationTimeout=100",
                    "abcd",
                ),
                (
                    "put",
                    f"/{thing_id}/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true",
                    True,
                ),
                # test payloads for other content types
            ]:
                response = session.request(
                    method=method,
                    url=f"http://127.0.0.1:{port}{path}",
                    data=serializer.dumps(body) if body is not None else None,
                    headers={"Content-Type": serializer.content_type},
                )
                self.assertTrue(response.status_code in [200, 201, 202, 204])
                assert isinstance(latest_request_info, LatestRequestInfo)
                # test ThingExecutionContext
                self.assertTrue(
                    isinstance(
                        latest_request_info.thing_execution_context,
                        ThingExecutionContext,
                    )
                )
                self.assertTrue(
                    ("fetchExecutionLogs" in path and latest_request_info.thing_execution_context.fetchExecutionLogs)
                    or not latest_request_info.thing_execution_context.fetchExecutionLogs
                )
                # test ServerExecutionContext
                self.assertTrue(
                    isinstance(
                        latest_request_info.server_execution_context,
                        ServerExecutionContext,
                    )
                )
                self.assertTrue(
                    ("oneway" in path and latest_request_info.server_execution_context.oneway)
                    or not latest_request_info.server_execution_context.oneway
                )
                self.assertTrue(
                    (
                        "invokationTimeout" in path
                        and latest_request_info.server_execution_context.invokationTimeout == 100
                    )
                    or
                    # assume that in all tests where invokation timeout is specified, it will be 100
                    latest_request_info.server_execution_context.invokationTimeout
                    == default_server_execution_context.invokationTimeout
                )
                self.assertTrue(
                    (
                        "executionTimeout" in path
                        and latest_request_info.server_execution_context.executionTimeout == 120
                    )
                    or
                    # assume that in all tests where execution timeout is specified, it will be 120
                    latest_request_info.server_execution_context.executionTimeout
                    == default_server_execution_context.executionTimeout
                )
                # test body
                self.assertTrue(latest_request_info.payload.deserialize() == body)

        self.stop_server(port=port, thing_ids=[thing_id])

    def _test_handlers_end_to_end(self, port: int, thing_id: str, **request_kwargs):
        """
        basic end-to-end test with the HTTP server using handlers.
        Auth & other features not included, only invokation of interaction affordances.
        """
        session = requests.Session()
        logging.getLogger("requests").setLevel(logging.CRITICAL)
        logging.getLogger("urllib3").setLevel(logging.CRITICAL)
        # test end to end
        for method, path, body in self.generate_endpoints_for_thing(OceanOpticsSpectrometer, thing_id):
            # request will go through the Thing object
            response = session.request(
                method=method,
                url=f"http://127.0.0.1:{port}{path}",
                data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
                **request_kwargs,
            )
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            # check if the response body is as expected
            if body and method != "put":
                self.assertTrue(response.json() == body)
            # check headers
            self.assertIn("Access-Control-Allow-Origin", response.headers)
            self.assertIn("Access-Control-Allow-Credentials", response.headers)
            self.assertIn("Content-Type", response.headers)

        # test unsupported HTTP methods
        for method, path, body in self.generate_endpoints_for_thing(OceanOpticsSpectrometer, thing_id):
            response = session.request(
                method="post"
                if method in ["get", "put"]
                else random.choice(["put", "delete"])
                if method == "post"
                else method,
                # get and put become post and post becomes put
                # i.e swap the default HTTP method with an unsupported one to generate 405
                url=f"http://127.0.0.1:{port}{path}",
                data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
                **request_kwargs,
            )
            self.assertTrue(response.status_code == 405)

        # check options for supported HTTP methods
        for method, path, body in self.generate_endpoints_for_thing(OceanOpticsSpectrometer, thing_id):
            response = session.options(f"http://127.0.0.1:{port}{path}", **request_kwargs)
            self.assertTrue(response.status_code in [200, 201, 202, 204])
            self.assertIn("Access-Control-Allow-Origin", response.headers)
            self.assertIn("Access-Control-Allow-Credentials", response.headers)
            self.assertIn("Access-Control-Allow-Headers", response.headers)
            self.assertIn("Access-Control-Allow-Methods", response.headers)
            allow_methods = response.headers.get("Access-Control-Allow-Methods", [])
            self.assertTrue(
                method.upper() in allow_methods,
                f"Method {method} not allowed in {allow_methods}",
            )

    def _test_invalid_auth_end_to_end(self, port: int, thing_id: str, wrong_auth_headers: list[str] = None):
        # check wrong credentials
        session = requests.Session()
        for wrong_auth in wrong_auth_headers:
            for method, path, body in self.generate_endpoints_for_thing(OceanOpticsSpectrometer, thing_id):
                response = session.request(
                    method=method,
                    url=f"http://127.0.0.1:{port}{path}",
                    data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
                    headers=wrong_auth,
                )
                self.assertTrue(response.status_code == 401)

    def _test_authenticated_end_to_end(
        self,
        port: int,
        security_scheme: SecurityScheme,
        auth_headers: dict[str, str] = None,
        wrong_auth_headers: dict[str, str] = None,
    ):
        """Test end-to-end with authentication"""
        thing_id = f"test-sec-{uuid.uuid4().hex[0:8]}"
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(
            forked=True,
            port=port,
            config={"allow_cors": True},
            security_schemes=[security_scheme],
        )
        time.sleep(2)  # linux machines need a few moments otherwise the clients error
        self._test_handlers_end_to_end(port=port, thing_id=thing_id, headers=auth_headers)
        self._test_invalid_auth_end_to_end(port=port, thing_id=thing_id, wrong_auth_headers=wrong_auth_headers)
        # reinstate correct credentials to stop
        self.stop_server(port=port, thing_ids=[thing_id], headers=auth_headers)

    def test_06_basic_end_to_end(self):
        thing_id = f"test-sec-{uuid.uuid4().hex[0:8]}"
        port = 60004
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(forked=True, port=port, config={"allow_cors": True})
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        self._test_handlers_end_to_end(port=port, thing_id=thing_id, headers={"Content-Type": "application/json"})
        self.stop_server(port, thing_ids=[thing_id])

    def test_07_bcrypt_basic_security_end_to_end(self):
        security_scheme = BcryptBasicSecurity(username="someuser", password="somepassword")
        port = 60005
        self._test_authenticated_end_to_end(
            port=port,
            security_scheme=security_scheme,
            auth_headers={
                "Content-type": "application/json",
                "Authorization": f"Basic {base64.b64encode(b'someuser:somepassword').decode('utf-8')}",
            },
            wrong_auth_headers=[
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'wronguser:wrongpassword').decode('utf-8')}",
                },
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'someuser:wrongpassword').decode('utf-8')}",
                },
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'wronguser:somepassword').decode('utf-8')}",
                },
            ],
        )

    def test_08_argon2_basic_security_end_to_end(self):
        security_scheme = Argon2BasicSecurity(username="someuserargon2", password="somepasswordargon2")
        port = 60006
        self._test_authenticated_end_to_end(
            port=port,
            security_scheme=security_scheme,
            auth_headers={
                "Content-type": "application/json",
                "Authorization": f"Basic {base64.b64encode(b'someuserargon2:somepasswordargon2').decode('utf-8')}",
            },
            wrong_auth_headers=[
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'wronguserargon2:wrongpasswordargon2').decode('utf-8')}",
                },
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'someuserargon2:wrongpasswordargon2').decode('utf-8')}",
                },
                {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'wronguserargon2:somepasswordargon2').decode('utf-8')}",
                },
            ],
        )

    def _test_sse_end_to_end(
        self,
        port: int,
        security_scheme: SecurityScheme = None,
        headers: dict[str, str] = None,
    ):
        """
        Test end-to-end with Server-Sent Events (SSE).
        """
        thing_id = f"test-sse-{uuid.uuid4().hex[0:8]}"
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(
            forked=True,
            port=port,
            config={"allow_cors": True},
            security_schemes=[security_scheme] if security_scheme else None,
        )
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        session = requests.Session()
        response = session.post(f"http://127.0.0.1:{port}/{thing_id}/start-acquisition", headers=headers)
        self.assertEqual(response.status_code, 200)
        sse_gen = self.sse_stream(
            f"http://127.0.0.1:{port}/{thing_id}/intensity-measurement-event",
            headers=headers,
        )
        for i in range(5):
            evt = next(sse_gen)
            self.assertTrue("exception" not in evt)
        response = session.post(f"http://127.0.0.1:{port}/{thing_id}/stop-acquisition", headers=headers)
        self.stop_server(port=port, thing_ids=[thing_id], headers=headers)

    def test_09_sse(self):
        """Test Server-Sent Events (SSE)"""
        for security_scheme, port in [
            (None, 60007),
            (BcryptBasicSecurity(username="someuser", password="somepassword"), 60008),
        ]:
            # test SSE with and without security
            if security_scheme:
                headers = {
                    "Content-type": "application/json",
                    "Authorization": f"Basic {base64.b64encode(b'someuser:somepassword').decode('utf-8')}",
                }
            else:
                headers = dict()
            self._test_sse_end_to_end(port=port, security_scheme=security_scheme, headers=headers)

    def test_10_forms_generation(self):
        thing_id = f"test-forms-{uuid.uuid4().hex[0:8]}"
        port = 60009
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(forked=True, port=port, config={"allow_cors": True})
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        session = requests.Session()
        response = session.get(f"http://127.0.0.1:{port}/{thing_id}/resources/wot-td")
        self.assertEqual(response.status_code, 200)
        td = response.json()
        self.assertIn("properties", td)
        self.assertIn("actions", td)
        self.assertIn("events", td)
        self.assertTrue(len(td["properties"]) >= 0)
        self.assertTrue(len(td["actions"]) >= 0)
        self.assertTrue(len(td["events"]) >= 0)
        for prop in list(td["properties"].values()) + list(td["actions"].values()) + list(td["events"].values()):
            self.assertIn("forms", prop)
            self.assertTrue(len(prop["forms"]) > 0)
            for form in prop["forms"]:
                self.assertIn("href", form)
                self.assertIn("htv:methodName", form)
                self.assertIn("contentType", form)
                self.assertIn("op", form)
        self.stop_server(port=port, thing_ids=[thing_id])

    def test_11_object_proxy_basic(self):
        thing_id = f"test-obj-proxy-{uuid.uuid4().hex[0:8]}"
        port = 60010
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(forked=True, port=port, config={"allow_cors": True})
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        object_proxy = ClientFactory.http(url=f"http://127.0.0.1:{port}/{thing_id}/resources/wot-td")
        self.assertIsInstance(object_proxy, ObjectProxy)
        self.assertEqual(object_proxy.test_echo("Hello World!"), "Hello World!")
        self.assertEqual(
            asyncio.run(object_proxy.async_invoke_action("test_echo", "Hello World!")),
            "Hello World!",
        )
        self.assertEqual(object_proxy.read_property("max_intensity"), 16384)
        self.assertEqual(object_proxy.write_property("integration_time", 1200), None)
        self.assertEqual(object_proxy.read_property("integration_time"), 1200)
        self.stop_server(port=port, thing_ids=[thing_id])

    def test_12_object_proxy_with_basic_auth(self):
        security_scheme = BcryptBasicSecurity(username="cliuser", password="clipass")
        port = 60013
        thing_id = f"test-basic-proxy-{uuid.uuid4().hex[0:8]}"
        thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        thing.run_with_http_server(
            forked=True,
            port=port,
            config={"allow_cors": True},
            security_schemes=[security_scheme],
        )
        time.sleep(2)

        object_proxy = ClientFactory.http(
            url=f"http://127.0.0.1:{port}/{thing_id}/resources/wot-td",
            username="cliuser",
            password="clipass",
        )
        self.assertEqual(object_proxy.read_property("max_intensity"), 16384)
        headers = {}
        token = base64.b64encode("cliuser:clipass".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
        self.stop_server(port=port, thing_ids=[thing_id], headers=headers)

    @classmethod
    def stop_server(cls, port, thing_ids: list[str] = [], **request_kwargs):
        session = requests.Session()
        endpoints = [("post", f"/{thing_id}/exit", None) for thing_id in thing_ids]
        endpoints += [("post", "/stop", None)]
        for method, path, body in endpoints:
            response = session.request(method=method, url=f"http://127.0.0.1:{port}{path}", **request_kwargs)

    @classmethod
    def sse_stream(cls, url, chunk_size=2048, **kwargs):
        """Generator yielding dicts with the fields of each SSE event"""
        with requests.get(url, stream=True, **kwargs) as resp:
            resp.raise_for_status()
            buffer = ""
            for chunk in resp.iter_content(chunk_size=chunk_size, decode_unicode=True):
                buffer += chunk
                # split events on the SSE separator: two newlines
                while "\n\n" in buffer:
                    raw_event, buffer = buffer.split("\n\n", 1)
                    event = {}
                    for line in raw_event.splitlines():
                        # skip comments
                        if not line or line.startswith(":"):
                            continue
                        if ":" in line:
                            field, value = line.split(":", 1)
                            event.setdefault(field, "")
                            # strip leading space after colon
                            event[field] += value.lstrip()
                yield event

    @classmethod
    def generate_endpoints_for_thing(cls, class_: ThingMeta, thing_id: str) -> list[tuple[str, str, Any]]:
        if class_ == OceanOpticsSpectrometer:
            return [
                # read Property
                ("get", f"/{thing_id}/max-intensity", 16384),
                ("get", f"/{thing_id}/serial-number", "simulation"),
                # write Property
                ("put", f"/{thing_id}/integration-time", 1200),
                ("get", f"/{thing_id}/integration-time", 1200),
                # invoke action
                ("post", f"/{thing_id}/disconnect", None),
                ("post", f"/{thing_id}/connect", None),
            ]
        raise NotImplementedError(f"Endpoints for {class_.__name__} not implemented yet")


class TestHTTPObjectProxy(TestCase):
    # later create a TestObjtectProxy class that will test ObjectProxy but just overload the setUp and tearDown methods
    # with the different protocol

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.thing_id = f"test-obj-proxy-{uuid.uuid4().hex[0:8]}"
        cls.port = 60011
        cls.thing = OceanOpticsSpectrometer(id=cls.thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
        cls.thing.run_with_http_server(forked=True, port=cls.port, config={"allow_cors": True})
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        cls.object_proxy = ClientFactory.http(url=f"http://127.0.0.1:{cls.port}/{cls.thing_id}/resources/wot-td")

    @classmethod
    def tearDownClass(cls):
        # stop the thing and server
        TestHTTPServer.stop_server(cls.port, thing_ids=[cls.thing.id])
        cls.object_proxy = None
        super().tearDownClass()

    def test_01_invoke_action(self):
        """Test basic functionality of ObjectProxy with HTTP server."""
        self.assertIsInstance(self.object_proxy, ObjectProxy)
        # Test invoke_action method with reply
        self.assertEqual(self.object_proxy.invoke_action("test_echo", "Hello World!"), "Hello World!")
        # Test invoke_action with dot notation
        self.assertEqual(self.object_proxy.test_echo(fake.chrome()), fake.last)
        self.assertEqual(self.object_proxy.test_echo(fake.sha256()), fake.last)
        self.assertEqual(self.object_proxy.test_echo(fake.address()), fake.last)
        # Test invoke_action with no reply
        self.assertEqual(
            self.object_proxy.invoke_action("test_echo", fake.random_number(), oneway=True),
            None,
        )
        # # Test invoke_action in non blocking mode
        noblock_payload = fake.pylist(20, value_types=[int, float, str, bool])
        noblock_msg_id = self.object_proxy.invoke_action("test_echo", noblock_payload, noblock=True)
        self.assertIsInstance(noblock_msg_id, str)
        self.assertEqual(
            self.object_proxy.invoke_action("test_echo", fake.pylist(20, value_types=[int, float, str, bool])),
            fake.last,
        )
        self.assertEqual(
            self.object_proxy.invoke_action("test_echo", fake.pylist(10, value_types=[int, float, str, bool])),
            fake.last,
        )
        self.assertEqual(self.object_proxy.read_reply(noblock_msg_id), noblock_payload)

    def test_02_rwd_properties(self):
        # test read and write properties
        self.assertEqual(self.object_proxy.read_property("max_intensity"), 16384)
        self.assertEqual(self.object_proxy.write_property("integration_time", 1200), None)
        self.assertEqual(self.object_proxy.read_property("integration_time"), 1200)
        # test read and write properties with dot notation
        self.assertEqual(self.object_proxy.max_intensity, 16384)
        self.assertEqual(self.object_proxy.integration_time, 1200)
        self.object_proxy.integration_time = 1000
        self.assertEqual(self.object_proxy.integration_time, 1000)
        # test oneway write property
        self.assertEqual(self.object_proxy.write_property("integration_time", 800, oneway=True), None)
        self.assertEqual(self.object_proxy.read_property("integration_time"), 800)
        # test noblock read property
        noblock_msg_id = self.object_proxy.read_property("integration_time", noblock=True)
        self.assertIsInstance(noblock_msg_id, str)
        self.assertEqual(self.object_proxy.read_property("max_intensity"), 16384)
        self.assertEqual(self.object_proxy.write_property("integration_time", 1200), None)
        self.assertEqual(self.object_proxy.read_reply(noblock_msg_id), 800)

    def notest_03_rw_multiple_properties(self):
        """Test reading and writing multiple properties at once."""
        # test read multiple properties
        properties = self.object_proxy.read_multiple_properties(["max_intensity", "integration_time"])
        self.assertEqual(properties["max_intensity"], 16384)
        self.assertEqual(properties["integration_time"], 800)

        # test write multiple properties
        new_values = {"integration_time": 1200, "max_intensity": 20000}
        self.object_proxy.write_multiple_properties(new_values)
        properties = self.object_proxy.read_multiple_properties(["max_intensity", "integration_time"])
        self.assertEqual(properties["max_intensity"], 20000)
        self.assertEqual(properties["integration_time"], 1200)

    def test_04_subscribe_event(self):
        """Test subscribing to an event and receiving updates."""
        event_name = "intensity_measurement_event"

        def on_event(data: SSE):
            nonlocal self
            self.assertTrue(isinstance(data.data, dict) and "value" in data.data and "timestamp" in data.data)

        self.object_proxy.subscribe_event(event_name, on_event)
        self.object_proxy.start_acquisition()
        time.sleep(2)  # wait for some events to be generated
        self.object_proxy.stop_acquisition()
        # check if events are kept alive
        time.sleep(20)
        self.object_proxy.start_acquisition()
        time.sleep(2)  # wait for some events to be generated
        self.object_proxy.stop_acquisition()
        self.object_proxy.unsubscribe_event(event_name)


class TestHTTPEndToEnd(TestRPCEndToEnd):
    @classmethod
    def setUpClass(cls):
        cls.http_port = 60012
        super().setUpClass()
        print("Test HTTP Object Proxy End to End")

    @classmethod
    def setUpThing(cls):
        """Set up the thing for the http object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_http_server(forked=True, port=cls.http_port, config={"allow_cors": True})
        time.sleep(2)  # linux machines need a few moments otherwise the clients error

        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def tearDownClass(cls):
        """Test the stop of the http object proxy client"""
        TestHTTPServer.stop_server(port=cls.http_port, thing_ids=[cls.thing_id])
        super().tearDownClass()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.http(
                url=f"http://127.0.0.1:{cls.http_port}/{cls.thing_id}/resources/wot-td", ignore_TD_errors=True
            )
            return cls._client

    def test_04_RW_multiple_properties(self):
        pass


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPObjectProxy))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPEndToEnd))
    return suite


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
