import base64
import itertools
import logging
import random
import sys
import time

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

import pytest
import requests

from hololinked.core.zmq.message import (
    PreserializedData,
    SerializableData,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
)
from hololinked.logger import setup_logging
from hololinked.serializers import BaseSerializer, JSONSerializer, MsgpackSerializer, PickleSerializer
from hololinked.server import stop
from hololinked.server.http import HTTPServer
from hololinked.server.http.handlers import RPCHandler
from hololinked.server.security import Argon2BasicSecurity, BcryptBasicSecurity, Security
from hololinked.utils import uuid_hex


try:
    from .test_11_rpc_e2e import TestRPCEndToEnd
    from .things import OceanOpticsSpectrometer, TestThing
    from .utils import fake
except ImportError:
    from things import OceanOpticsSpectrometer


setup_logging(log_level=logging.ERROR + 10)


hostname_prefix = "http://127.0.0.1"
readiness_endpoint = "/readiness"
liveness_endpoint = "/liveness"
stop_endpoint = "/stop"
count = itertools.count(60001)


@pytest.fixture(scope="module")
def session() -> requests.Session:
    return requests.Session()


@pytest.fixture(scope="function")
def port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="function")
def server(port) -> Generator[HTTPServer, None, None]:
    server = HTTPServer(port=port)
    server.run(forked=True)
    wait_until_server_ready(port=port)
    yield server
    stop()


@pytest.fixture(scope="function")
def thing(port: int) -> Generator[OceanOpticsSpectrometer, None, None]:
    thing = OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    thing.run_with_http_server(port=port, forked=True, config=dict(cors=True))
    wait_until_server_ready(port=port)
    yield thing
    stop()


@contextmanager
def running_thing(
    id_prefix: str,
    port: int = None,
    **http_server_kwargs,
) -> Generator[OceanOpticsSpectrometer, None, None]:
    global count
    port = port or next(count)
    thing = OceanOpticsSpectrometer(id=f"{id_prefix}-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    thing.run_with_http_server(port=port, forked=True, config=dict(cors=True), **http_server_kwargs)
    wait_until_server_ready(port=port)
    try:
        yield thing
    finally:
        stop()


@pytest.fixture(scope="function")
def endpoints(thing: OceanOpticsSpectrometer) -> list[tuple[str, str, Any]]:
    return running_thing_endpoints(thing)


@pytest.fixture(scope="function")
def td_endpoint(thing: OceanOpticsSpectrometer, port: int) -> str:
    return f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td"


def running_thing_endpoints(thing: OceanOpticsSpectrometer) -> list[tuple[str, str, Any]]:
    if thing.__class__ == OceanOpticsSpectrometer:
        return [
            ("get", f"/{thing.id}/max-intensity", 16384),
            ("get", f"/{thing.id}/serial-number", "simulation"),
            ("put", f"/{thing.id}/integration-time", 1200),
            ("get", f"/{thing.id}/integration-time", 1200),
            ("post", f"/{thing.id}/disconnect", None),
            ("post", f"/{thing.id}/connect", None),
        ]
    raise NotImplementedError(f"endpoints cannot be generated for {thing.__class__}")


def wait_until_server_ready(port: int, tries: int = 10) -> None:
    session = requests.Session()
    for _ in range(tries):
        try:
            response = session.get(f"{hostname_prefix}:{port}{liveness_endpoint}")
            if response.status_code in [200, 201, 202, 204]:
                response = session.get(f"{hostname_prefix}:{port}{readiness_endpoint}")
                if response.status_code in [200, 201, 202, 204]:
                    return
        except Exception:
            pass
        time.sleep(1)
    print(f"Server on port {port} not ready after {tries} tries, you need to retrigger this test job")
    sys.exit(1)


def sse_stream(url: str, chunk_size: int = 2048, **kwargs):
    with requests.get(url, stream=True, **kwargs) as resp:
        resp.raise_for_status()
        buffer = ""  # type: str
        for chunk in resp.iter_content(chunk_size=chunk_size, decode_unicode=True):
            buffer += chunk
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                event = {}
                for line in raw_event.splitlines():
                    if not line or line.startswith(":"):
                        continue
                    if ":" in line:
                        field, value = line.split(":", 1)
                        event.setdefault(field, "")
                        event[field] += value.lstrip()
                yield event


def notest_01_init_run_and_stop(port: int):
    server = HTTPServer(port=port)
    server.run(forked=True)
    wait_until_server_ready(port=port)
    server.stop()
    stop()
    time.sleep(2)

    # stop remotely
    server.run(forked=True)
    wait_until_server_ready(port=port)
    time.sleep(2)
    response = requests.post(f"{hostname_prefix}:{port}{stop_endpoint}")
    assert response.status_code in [200, 201, 202, 204]
    time.sleep(2)
    server.stop()
    stop()


def notest_02_add_interaction_affordance(server: HTTPServer):
    server.add_property("/max-intensity", OceanOpticsSpectrometer.max_intensity)
    server.add_action("/connect", OceanOpticsSpectrometer.connect)
    server.add_event("/intensity/event", OceanOpticsSpectrometer.intensity_measurement_event)
    assert "/max-intensity" in server.router
    assert "/connect" in server.router
    assert "/intensity/event" in server.router
    # replacing interaction affordances on an existing URL path causes a warning
    with pytest.warns(UserWarning):
        server.add_property("/max-intensity", OceanOpticsSpectrometer.last_intensity)
    with pytest.warns(UserWarning):
        server.add_action("/connect", OceanOpticsSpectrometer.disconnect)
    with pytest.warns(UserWarning):
        server.add_event("/intensity/event", OceanOpticsSpectrometer.intensity_measurement_event)


# tests 03 & 04 removed as they need more work to be done


class TestableRPCHandler(RPCHandler):
    """handler that tests RPC handler functionalities, without executing an operation on a Thing"""

    @dataclass
    class LatestRequestInfo:
        server_execution_context: ServerExecutionContext | dict[str, Any]
        thing_execution_context: ThingExecutionContext | dict[str, Any]
        payload: SerializableData
        preserialized_payload: PreserializedData

    latest_request_info: LatestRequestInfo

    def update_latest_request_info(self) -> None:
        server_execution_context, thing_execution_context, _, _ = self.get_execution_parameters()
        payload, preserialized_payload = self.get_request_payload()
        TestableRPCHandler.latest_request_info = TestableRPCHandler.LatestRequestInfo(
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
        await self.handle_through_thing("invokeaction")


@pytest.mark.parametrize("serializer", [JSONSerializer(), MsgpackSerializer(), PickleSerializer()])
@pytest.mark.parametrize(
    "paths",
    [
        pytest.param(("get", "/integration-time", None), id="get without params"),
        pytest.param(("get", "/integration-time?fetchExecutionLogs=true", None), id="get with fetchExecutionLogs"),
        pytest.param(
            ("get", "/integration-time?fetchExecutionLogs=true&oneway=true", None),
            id="get with fetchExecutionLogs and oneway",
        ),
        pytest.param(
            ("get", "/integration-time?oneway=true&invokationTimeout=100", None),
            id="get with oneway and invokationTimeout",
        ),
        pytest.param(
            (
                "get",
                "/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true",
                None,
            ),
            id="get with all params",
        ),
        pytest.param(("put", "/integration-time", 1200), id="put without params"),
        pytest.param(
            ("put", "/integration-time?fetchExecutionLogs=true", {"a": 1, "b": 2}), id="put with fetchExecutionLogs"
        ),
        pytest.param(
            ("put", "/integration-time?fetchExecutionLogs=true&oneway=true", [1, 2, 3]),
            id="put with fetchExecutionLogs and oneway",
        ),
        pytest.param(
            ("put", "/integration-time?oneway=true&invokationTimeout=100", "abcd"),
            id="put with oneway and invokationTimeout",
        ),
        pytest.param(
            (
                "put",
                "/integration-time?invokationTimeout=100&executionTimeout=120&fetchExecutionLogs=true",
                True,
            ),
            id="put with all params",
        ),
    ],
)
def notest_05_handlers(port: int, session: requests.Session, serializer: BaseSerializer, paths: tuple[str, str, Any]):
    """Test request info and payload decoding in RPC handlers along with content type handling"""

    method, path, body = paths
    response = session.request(
        method=method,
        url=f"{hostname_prefix}:{port}{path}",
        data=serializer.dumps(body) if body is not None else None,
        headers={"Content-Type": serializer.content_type},
    )
    assert response.status_code in [200, 201, 202, 204]
    # test ThingExecutionContext
    assert isinstance(TestableRPCHandler.latest_request_info.thing_execution_context, ThingExecutionContext)
    if "fetchExecutionLogs" in path:
        assert TestableRPCHandler.latest_request_info.thing_execution_context.fetchExecutionLogs
    else:
        assert not TestableRPCHandler.latest_request_info.thing_execution_context.fetchExecutionLogs
    # test ServerExecutionContext
    assert isinstance(TestableRPCHandler.latest_request_info.server_execution_context, ServerExecutionContext)
    if "oneway" in path:
        assert TestableRPCHandler.latest_request_info.server_execution_context.oneway
    else:
        assert not TestableRPCHandler.latest_request_info.server_execution_context.oneway
    if "invokationTimeout" in path:
        assert TestableRPCHandler.latest_request_info.server_execution_context.invokationTimeout == 100
    else:
        assert (
            TestableRPCHandler.latest_request_info.server_execution_context.invokationTimeout
            == default_server_execution_context.invokationTimeout
        )
    if "executionTimeout" in path:
        assert TestableRPCHandler.latest_request_info.server_execution_context.executionTimeout == 120
    else:
        assert (
            TestableRPCHandler.latest_request_info.server_execution_context.executionTimeout
            == default_server_execution_context.executionTimeout
        )
    assert TestableRPCHandler.latest_request_info.payload.deserialize() == body


def do_handlers_end_to_end(session: requests.Session, endpoint: tuple[str, str, Any], **request_kwargs):
    """
    basic end-to-end test with the HTTP server using handlers.
    Auth & other features not included, only invokation of interaction affordances.
    """
    method, path, body = endpoint
    # request will go through the Thing object
    response = session.request(
        method=method,
        url=path,
        data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
        **request_kwargs,
    )
    assert response.status_code in [200, 201, 202, 204]
    # check if the response body is as expected
    if body and method != "put":
        assert response.json() == body
    # check headers
    assert "Access-Control-Allow-Origin" in response.headers
    assert "Access-Control-Allow-Credentials" in response.headers
    assert "Content-Type" in response.headers

    # test unsupported HTTP methods
    response = session.request(
        method="post" if method in ["get", "put"] else random.choice(["put", "delete"]) if method == "post" else method,
        # get and put become post and post becomes put
        # i.e swap the default HTTP method with an unsupported one to generate 405
        url=path,
        data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
        **request_kwargs,
    )
    assert response.status_code == 405

    # check options for supported HTTP methods
    response = session.options(path, **request_kwargs)
    assert response.status_code in [200, 201, 202, 204]
    assert "Access-Control-Allow-Origin" in response.headers
    assert "Access-Control-Allow-Credentials" in response.headers
    assert "Access-Control-Allow-Headers" in response.headers
    assert "Access-Control-Allow-Methods" in response.headers
    allow_methods = response.headers.get("Access-Control-Allow-Methods", [])
    assert (  # noqa
        method.upper() in allow_methods,
        f"Method {method} not allowed in {allow_methods}",
    )


def do_invalid_auth_end_to_end(session: requests.Session, endpoint: tuple[str, str, Any], headers: dict = None):
    method, path, body = endpoint
    response = session.request(
        method=method,
        url=path,
        data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
        headers=headers,
    )
    assert response.status_code == 401


def do_authenticated_endpoint_end_to_end(
    session: requests.Session,
    endpoint: tuple[str, str, Any],
    auth_headers: dict[str, str] = None,
    wrong_auth_headers: list[dict[str, str]] = None,
):
    """Test end-to-end with authentication"""
    do_handlers_end_to_end(session, endpoint, headers=auth_headers)
    for wrong_auth_header in wrong_auth_headers:
        do_invalid_auth_end_to_end(session, endpoint, headers=wrong_auth_header)


def notest_06_basic_end_to_end(
    thing: OceanOpticsSpectrometer,
    session: requests.Session,
    port: int,
    endpoints: list[tuple[str, str, Any]],
) -> None:
    """basic end-to-end test with the HTTP server using handlers."""
    for method, path, body in endpoints:
        do_handlers_end_to_end(
            session=session,
            endpoint=(method, f"{hostname_prefix}:{port}{path}", body),
            headers={"Content-Type": "application/json"},
        )


@pytest.mark.parametrize(
    "security_scheme",
    [
        BcryptBasicSecurity(username="someuser", password="somepassword"),
        Argon2BasicSecurity(username="someuser", password="somepassword"),
    ],
)
def test_07_basic_security_end_to_end(session: requests.Session, port: int, security_scheme: Security):
    """Test end-to-end with Basic Authentication."""
    with running_thing(id_prefix="test-sec", port=port, security_schemes=[security_scheme]) as thing:
        endpoints = running_thing_endpoints(thing)
        for method, path, body in endpoints:
            do_authenticated_endpoint_end_to_end(
                session=session,
                endpoint=(f"{method}", f"{hostname_prefix}:{port}{path}", body),
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


@pytest.mark.parametrize(
    "security_scheme",
    [
        None,
        BcryptBasicSecurity(username="someuser", password="somepassword"),
    ],
)
def test_09_sse(session: requests.Session, security_scheme: Security | None, port: int) -> None:
    """Test Server-Sent Events (SSE)"""
    with running_thing(
        id_prefix="test-sse",
        port=port,
        security_schemes=[security_scheme] if security_scheme else None,
    ) as thing:
        headers = dict()
        if security_scheme:
            headers = {
                "Content-type": "application/json",
                "Authorization": f"Basic {base64.b64encode(b'someuser:somepassword').decode('utf-8')}",
            }
        response = session.post(f"{hostname_prefix}:{port}/{thing.id}/start-acquisition", headers=headers)
        assert response.status_code == 200
        sse_gen = sse_stream(
            f"{hostname_prefix}:{port}/{thing.id}/intensity-measurement-event",
            headers=headers,
        )
        for i in range(5):
            evt = next(sse_gen)
            assert "exception" not in evt
        response = session.post(f"{hostname_prefix}:{port}/{thing.id}/stop-acquisition", headers=headers)


def test_10_forms_generation(session: requests.Session, td_endpoint: str) -> None:
    response = session.get(td_endpoint)

    assert response.status_code == 200
    td = response.json()

    assert "properties" in td
    assert "actions" in td
    assert "events" in td
    assert len(td["properties"]) >= 0
    assert len(td["actions"]) >= 0
    assert len(td["events"]) >= 0
    for interaction in list(td["properties"].values()) + list(td["actions"].values()) + list(td["events"].values()):
        assert "forms" in interaction
        assert len(interaction["forms"]) > 0
        for form in interaction["forms"]:
            assert "href" in form
            assert "htv:methodName" in form
            assert "contentType" in form
            assert "op" in form


#     def test_11_object_proxy_basic(self):
#         thing_id = f"test-obj-proxy-{uuid.uuid4().hex[0:8]}"
#         port = 60010
#         thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
#         thing.run_with_http_server(forked=True, port=port, config={"cors": True})
#         self.wait_until_server_ready(port=port)

#         object_proxy = ClientFactory.http(url=f"http://127.0.0.1:{port}/{thing_id}/resources/wot-td")
#         self.assertIsInstance(object_proxy, ObjectProxy)
#         self.assertEqual(object_proxy.test_echo("Hello World!"), "Hello World!")
#         self.assertEqual(
#             asyncio.run(object_proxy.async_invoke_action("test_echo", "Hello World!")),
#             "Hello World!",
#         )
#         self.assertEqual(object_proxy.read_property("max_intensity"), 16384)
#         self.assertEqual(object_proxy.write_property("integration_time", 1200), None)
#         self.assertEqual(object_proxy.read_property("integration_time"), 1200)
#         self.stop_server(port=port, thing_ids=[thing_id])

#     def notest_12_object_proxy_with_basic_auth(self):
#         security_scheme = BcryptBasicSecurity(username="cliuser", password="clipass")
#         port = 60013
#         thing_id = f"test-basic-proxy-{uuid.uuid4().hex[0:8]}"
#         thing = OceanOpticsSpectrometer(id=thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
#         thing.run_with_http_server(
#             forked=True,
#             port=port,
#             config={"cors": True},
#             security_schemes=[security_scheme],
#         )
#         self.wait_until_server_ready(port=port)

#         object_proxy = ClientFactory.http(
#             url=f"http://127.0.0.1:{port}/{thing_id}/resources/wot-td",
#             username="cliuser",
#             password="clipass",
#         )
#         self.assertEqual(object_proxy.read_property("max_intensity"), 16384)
#         headers = {}
#         token = base64.b64encode("cliuser:clipass".encode("utf-8")).decode("ascii")
#         headers["Authorization"] = f"Basic {token}"
#         self.stop_server(port=port, thing_ids=[thing_id], headers=headers)


# class TestHTTPObjectProxy(TestCase):
#     # later create a TestObjtectProxy class that will test ObjectProxy but just overload the setUp and tearDown methods
#     # with the different protocol

#     @classmethod
#     def setUpClass(cls):
#         super().setUpClass()
#         cls.thing_id = f"test-obj-proxy-{uuid.uuid4().hex[0:8]}"
#         cls.port = 60011
#         cls.thing = OceanOpticsSpectrometer(id=cls.thing_id, serial_number="simulation", log_level=logging.ERROR + 10)
#         cls.thing.run_with_http_server(forked=True, port=cls.port, config={"cors": True})
#         TestHTTPServer.wait_until_server_ready(port=cls.port)

#         cls.object_proxy = ClientFactory.http(url=f"http://127.0.0.1:{cls.port}/{cls.thing_id}/resources/wot-td")

#     @classmethod
#     def tearDownClass(cls):
#         # stop the thing and server
#         TestHTTPServer.stop_server(cls.port, thing_ids=[cls.thing.id])
#         cls.object_proxy = None
#         super().tearDownClass()

#     def test_01_invoke_action(self):
#         """Test basic functionality of ObjectProxy with HTTP server."""
#         self.assertIsInstance(self.object_proxy, ObjectProxy)
#         # Test invoke_action method with reply
#         self.assertEqual(self.object_proxy.invoke_action("test_echo", "Hello World!"), "Hello World!")
#         # Test invoke_action with dot notation
#         self.assertEqual(self.object_proxy.test_echo(fake.chrome()), fake.last)
#         self.assertEqual(self.object_proxy.test_echo(fake.sha256()), fake.last)
#         self.assertEqual(self.object_proxy.test_echo(fake.address()), fake.last)
#         # Test invoke_action with no reply
#         self.assertEqual(
#             self.object_proxy.invoke_action("test_echo", fake.random_number(), oneway=True),
#             None,
#         )
#         # # Test invoke_action in non blocking mode
#         noblock_payload = fake.pylist(20, value_types=[int, float, str, bool])
#         noblock_msg_id = self.object_proxy.invoke_action("test_echo", noblock_payload, noblock=True)
#         self.assertIsInstance(noblock_msg_id, str)
#         self.assertEqual(
#             self.object_proxy.invoke_action("test_echo", fake.pylist(20, value_types=[int, float, str, bool])),
#             fake.last,
#         )
#         self.assertEqual(
#             self.object_proxy.invoke_action("test_echo", fake.pylist(10, value_types=[int, float, str, bool])),
#             fake.last,
#         )
#         self.assertEqual(self.object_proxy.read_reply(noblock_msg_id), noblock_payload)

#     def test_02_rwd_properties(self):
#         # test read and write properties
#         self.assertEqual(self.object_proxy.read_property("max_intensity"), 16384)
#         self.assertEqual(self.object_proxy.write_property("integration_time", 1200), None)
#         self.assertEqual(self.object_proxy.read_property("integration_time"), 1200)
#         # test read and write properties with dot notation
#         self.assertEqual(self.object_proxy.max_intensity, 16384)
#         self.assertEqual(self.object_proxy.integration_time, 1200)
#         self.object_proxy.integration_time = 1000
#         self.assertEqual(self.object_proxy.integration_time, 1000)
#         # test oneway write property
#         self.assertEqual(self.object_proxy.write_property("integration_time", 800, oneway=True), None)
#         self.assertEqual(self.object_proxy.read_property("integration_time"), 800)
#         # test noblock read property
#         noblock_msg_id = self.object_proxy.read_property("integration_time", noblock=True)
#         self.assertIsInstance(noblock_msg_id, str)
#         self.assertEqual(self.object_proxy.read_property("max_intensity"), 16384)
#         self.assertEqual(self.object_proxy.write_property("integration_time", 1200), None)
#         self.assertEqual(self.object_proxy.read_reply(noblock_msg_id), 800)

#     def notest_03_rw_multiple_properties(self):
#         """Test reading and writing multiple properties at once."""
#         # test read multiple properties
#         properties = self.object_proxy.read_multiple_properties(["max_intensity", "integration_time"])
#         self.assertEqual(properties["max_intensity"], 16384)
#         self.assertEqual(properties["integration_time"], 800)

#         # test write multiple properties
#         new_values = {"integration_time": 1200, "max_intensity": 20000}
#         self.object_proxy.write_multiple_properties(new_values)
#         properties = self.object_proxy.read_multiple_properties(["max_intensity", "integration_time"])
#         self.assertEqual(properties["max_intensity"], 20000)
#         self.assertEqual(properties["integration_time"], 1200)

#     def test_04_subscribe_event(self):
#         """Test subscribing to an event and receiving updates."""
#         event_name = "intensity_measurement_event"

#         def on_event(data: SSE):
#             nonlocal self
#             self.assertTrue(isinstance(data.data, dict) and "value" in data.data and "timestamp" in data.data)

#         self.object_proxy.subscribe_event(event_name, on_event)
#         self.object_proxy.start_acquisition()
#         time.sleep(2)  # wait for some events to be generated
#         self.object_proxy.stop_acquisition()
#         # check if events are kept alive
#         time.sleep(20)
#         self.object_proxy.start_acquisition()
#         time.sleep(2)  # wait for some events to be generated
#         self.object_proxy.stop_acquisition()
#         self.object_proxy.unsubscribe_event(event_name)


# class TestHTTPEndToEnd(TestRPCEndToEnd):
#     @classmethod
#     def setUpClass(cls):
#         cls.http_port = 60012
#         super().setUpClass()
#         print("Test HTTP Object Proxy End to End")

#     @classmethod
#     def setUpThing(cls):
#         """Set up the thing for the http object proxy client"""
#         cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
#         cls.thing.run_with_http_server(forked=True, port=cls.http_port, config={"cors": True})
#         TestHTTPServer.wait_until_server_ready(port=cls.http_port)

#         cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

#     @classmethod
#     def tearDownClass(cls):
#         """Test the stop of the http object proxy client"""
#         TestHTTPServer.stop_server(port=cls.http_port, thing_ids=[cls.thing_id])
#         super().tearDownClass()

#     @classmethod
#     def get_client(cls):
#         try:
#             if cls._client is not None:
#                 return cls._client
#             raise AttributeError()
#         except AttributeError:
#             cls._client = ClientFactory.http(
#                 url=f"http://127.0.0.1:{cls.http_port}/{cls.thing_id}/resources/wot-td", ignore_TD_errors=True
#             )
#             return cls._client

#     def test_04_RW_multiple_properties(self):
#         pass
