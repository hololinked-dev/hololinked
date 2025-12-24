import base64
import datetime
import itertools
import random
import sys
import time

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

import httpx
import pytest
import requests

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.client.security import APIKeySecurity as ClientAPIKeySecurity
from hololinked.config import global_config
from hololinked.core.zmq.message import (
    PreserializedData,
    SerializableData,
    ServerExecutionContext,
    ThingExecutionContext,
    default_server_execution_context,
)
from hololinked.serializers import (
    BaseSerializer,
    JSONSerializer,
    MsgpackSerializer,
    PickleSerializer,
)
from hololinked.server import stop
from hololinked.server.http import HTTPServer, RPCHandler
from hololinked.server.security import (
    APIKeySecurity,
    Argon2BasicSecurity,
    BcryptBasicSecurity,
    Security,
)
from hololinked.utils import uuid_hex


try:
    from .things import OceanOpticsSpectrometer
except ImportError:
    from things import OceanOpticsSpectrometer


hostname_prefix = "http://127.0.0.1"
readiness_endpoint = "/readiness"
liveness_endpoint = "/liveness"
stop_endpoint = "/stop"
start_acquisition_endpoint = "/start-acquisition"
intensity_measurement_event_endpoint = "/intensity-measurement-event"
stop_acquisition_endpoint = "/stop-acquisition"

count = itertools.count(62000)


@pytest.fixture(scope="module")
def session() -> requests.Session:
    return requests.Session()


@pytest.fixture(scope="function")
def port() -> int:
    global count
    return next(count)


@pytest.fixture(scope="function")
def server(port) -> Generator[HTTPServer, None, None]:
    server = HTTPServer(address="127.0.0.1", port=port)
    server.run(forked=True, print_welcome_message=False)
    wait_until_server_ready(port=port)
    yield server
    stop()


@pytest.fixture(scope="function")
def thing(port: int) -> Generator[OceanOpticsSpectrometer, None, None]:
    thing = OceanOpticsSpectrometer(id=f"test-thing-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    thing.run_with_http_server(
        address="127.0.0.1",
        port=port,
        forked=True,
        print_welcome_message=False,
        config=dict(cors=True),
    )
    wait_until_server_ready(port=port)
    yield thing
    stop()


@contextmanager
def running_thing(
    id_prefix: str,
    port: int = None,
    **http_server_kwargs,
) -> Generator[OceanOpticsSpectrometer, None, None]:
    """same as thing fixture but to use it manually"""
    global count
    port = port or next(count)
    thing = OceanOpticsSpectrometer(id=f"{id_prefix}-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    thing.run_with_http_server(
        address="127.0.0.1",
        port=port,
        forked=True,
        config=dict(cors=True),
        print_welcome_message=False,
        **http_server_kwargs,
    )
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


@pytest.fixture(scope="function")
def object_proxy(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td_endpoint)


def running_thing_endpoints(thing: OceanOpticsSpectrometer) -> list[tuple[str, str, Any]]:
    if thing.__class__ == OceanOpticsSpectrometer:
        return [
            # properties
            ("get", f"/{thing.id}/max-intensity", 16384),
            ("get", f"/{thing.id}/serial-number", "simulation"),
            ("put", f"/{thing.id}/integration-time", 1200),
            ("get", f"/{thing.id}/integration-time", 1200),
            # actions
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


async def test_01_init_run_and_stop(port: int):
    server = HTTPServer(address="127.0.0.1", port=port)
    server.run(forked=True, print_welcome_message=False)
    wait_until_server_ready(port=port)
    await server.async_stop()
    stop()
    time.sleep(2)

    # stop remotely
    server.run(forked=True, print_welcome_message=False)
    wait_until_server_ready(port=port)
    time.sleep(2)
    response = requests.post(f"{hostname_prefix}:{port}{stop_endpoint}")
    assert response.status_code in [200, 201, 202, 204]
    time.sleep(2)
    await server.async_stop()
    stop()


def test_02_add_interaction_affordance(server: HTTPServer):
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
    """
    handler that tests RPC handler functionalities, without executing an operation on a Thing
    Needs to be replaced with a mock
    """

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


@pytest.fixture(scope="function")
def test_rpc_handler_thing(port: int) -> Generator[OceanOpticsSpectrometer, None, None]:
    global_config.ALLOW_PICKLE = True
    with running_thing(
        id_prefix="test-rpc-handler",
        port=port,
        property_handler=TestableRPCHandler,
        action_handler=TestableRPCHandler,
    ) as thing:
        yield thing
    global_config.ALLOW_PICKLE = False


@pytest.mark.parametrize(
    "serializer",
    [
        pytest.param(JSONSerializer(), id="json"),
        pytest.param(MsgpackSerializer(), id="msgpack"),
        pytest.param(PickleSerializer(), id="pickle"),
    ],
)
@pytest.mark.parametrize(
    "endpoint",
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
def test_05_handlers(
    session: requests.Session,
    test_rpc_handler_thing: OceanOpticsSpectrometer,
    port: int,
    serializer: BaseSerializer,
    endpoint: tuple[str, str, Any],
):
    """Test request info and payload decoding in RPC handlers along with content type handling"""

    method, path, body = endpoint
    response = session.request(
        method=method,
        url=f"{hostname_prefix}:{port}/{test_rpc_handler_thing.id}{path}",
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


def do_a_path_e2e(session: requests.Session, endpoint: tuple[str, str, Any], **request_kwargs):
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
    # assert "Access-Control-Allow-Credentials" in response.headers
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
    # assert "Access-Control-Allow-Credentials" in response.headers
    assert "Access-Control-Allow-Headers" in response.headers
    assert "Access-Control-Allow-Methods" in response.headers
    allow_methods = response.headers.get("Access-Control-Allow-Methods", [])
    assert (  # noqa
        method.upper() in allow_methods,
        f"Method {method} not allowed in {allow_methods}",
    )


def do_a_path_invalid_auth_e2e(session: requests.Session, endpoint: tuple[str, str, Any], headers: dict = None):
    method, path, body = endpoint
    response = session.request(
        method=method,
        url=path,
        data=JSONSerializer().dumps(body) if body is not None and method != "get" else None,
        headers=headers,
    )
    assert response.status_code == 401


def do_authenticated_path_e2e(
    session: requests.Session,
    endpoint: tuple[str, str, Any],
    auth_headers: dict[str, str] = None,
    wrong_auth_headers: list[dict[str, str]] = None,
):
    """Test end-to-end with authentication"""
    do_a_path_e2e(session, endpoint, headers=auth_headers)
    for wrong_auth_header in wrong_auth_headers:
        do_a_path_invalid_auth_e2e(session, endpoint, headers=wrong_auth_header)


def test_06_basic_end_to_end(
    thing: OceanOpticsSpectrometer,
    session: requests.Session,
    port: int,
    endpoints: list[tuple[str, str, Any]],
) -> None:
    """basic end-to-end test with the HTTP server using handlers."""
    for method, path, body in endpoints:
        do_a_path_e2e(
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
            do_authenticated_path_e2e(
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
                    {
                        "Content-type": "application/json",
                        # no header
                    },
                ],
            )


def test_08_apikey_security_end_to_end(session: requests.Session, port: int):
    """Test end-to-end with API Key Authentication."""
    keyname = f"e2e-test-apikey-{uuid_hex()}"
    apikey = APIKeySecurity(name=keyname).create(print_value=False)

    security_scheme = APIKeySecurity(name=keyname)
    with running_thing(id_prefix="test-sec", port=port, security_schemes=[security_scheme]) as thing:
        endpoints = running_thing_endpoints(thing)
        for method, path, body in endpoints:
            do_authenticated_path_e2e(
                session=session,
                endpoint=(f"{method}", f"{hostname_prefix}:{port}{path}", body),
                auth_headers={
                    "Content-type": "application/json",
                    "x-api-key": apikey,
                },
                wrong_auth_headers=[
                    {
                        "Content-type": "application/json",
                        "x-api-key": "wrongapikey",
                    },  # plainly wrong key
                    {
                        "Content-type": "application/json",
                        "x-api-key": f"wotdat-{apikey.split('-')[1].split('.')[0]}.blablabla",
                    },  # wrong key with right ID
                    {
                        "Content-type": "application/json",
                        # no header
                    },
                ],
            )
        for method, path, body in endpoints:  # test key expiration
            security_scheme.record.expiry_at = datetime.datetime.fromisoformat("2000-01-01T00:00:00")
            do_a_path_invalid_auth_e2e(
                session,
                (f"{method}", f"{hostname_prefix}:{port}{path}", body),
                headers={
                    "Content-type": "application/json",
                    "x-api-key": apikey,
                },
            )


@pytest.mark.parametrize(
    "security_scheme, headers",
    [
        pytest.param(None, {}, id="no-auth"),
        pytest.param(
            BcryptBasicSecurity(username="someuser", password="somepassword"),
            {
                "Content-type": "application/json",
                "Authorization": f"Basic {base64.b64encode(b'someuser:somepassword').decode('utf-8')}",
            },
            id="bcrypt-basic-auth",
        ),
        pytest.param(
            APIKeySecurity(name="sse-apikey"),
            {
                "Content-type": "application/json",
                "x-api-key": APIKeySecurity(name="sse-apikey").create(print_value=False, override=True),
            },
            id="apikey-auth",
        ),
    ],
)
def test_09_sse(
    session: requests.Session,
    port: int,
    security_scheme: Security | None,
    headers: dict[str, str],
) -> None:
    """Test Server-Sent Events (SSE)"""
    if hasattr(security_scheme, "load"):
        security_scheme.load()  # TODO refactor later, we should not do fixture based specific setup here
    with running_thing(
        id_prefix="test-sse",
        port=port,
        security_schemes=[security_scheme] if security_scheme else None,
    ) as thing:
        response = session.post(f"{hostname_prefix}:{port}/{thing.id}/start-acquisition", headers=headers)
        assert response.status_code == 200
        sse_gen = sse_stream(
            f"{hostname_prefix}:{port}/{thing.id}/intensity-measurement-event",
            headers=headers,
        )
        for _ in range(5):
            evt = next(sse_gen)
            assert "exception" not in evt and "data" in evt
        response = session.post(f"{hostname_prefix}:{port}/{thing.id}/stop-acquisition", headers=headers)
        assert response.status_code == 200


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


async def test_11_object_proxy_basic(object_proxy: ObjectProxy) -> None:
    assert isinstance(object_proxy, ObjectProxy)
    assert object_proxy.test_echo("Hello World!") == "Hello World!"
    assert await object_proxy.async_invoke_action("test_echo", "Hello World!") == "Hello World!"
    assert object_proxy.read_property("max_intensity") == 16384
    assert object_proxy.write_property("integration_time", 1200) is None
    assert object_proxy.read_property("integration_time") == 1200


def test_12_object_proxy_with_basic_auth(port: int) -> None:
    security_scheme = BcryptBasicSecurity(username="cliuser", password="clipass")
    with running_thing(
        id_prefix="test-basic-auth-object-proxy",
        port=port,
        security_schemes=[security_scheme],
    ) as thing:
        td_endpoint = f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td"
        object_proxy = ClientFactory.http(
            url=td_endpoint,
            username="cliuser",
            password="clipass",
        )
        assert len(object_proxy.td["security"]) > 0
        assert security_scheme.name in object_proxy.td["security"]
        assert security_scheme.name in object_proxy.td["securityDefinitions"]

        assert object_proxy.read_property("max_intensity") == 16384

        pytest.raises(httpx.HTTPStatusError, ClientFactory.http, url=td_endpoint)


def test_13_object_proxy_with_apikey(port: int) -> None:
    keyname = f"cli-test-apikey-{uuid_hex()}"
    apikey = APIKeySecurity(name=keyname).create(print_value=False)
    security_scheme = APIKeySecurity(name=keyname)
    with running_thing(
        id_prefix="test-apikey-object-proxy",
        port=port,
        security_schemes=[security_scheme],
    ) as thing:
        td_endpoint = f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td"
        object_proxy = ClientFactory.http(
            url=td_endpoint,
            security=ClientAPIKeySecurity(value=apikey),
        )
        assert len(object_proxy.td["security"]) > 0
        assert security_scheme.name in object_proxy.td["security"]
        assert security_scheme.name in object_proxy.td["securityDefinitions"]

        assert object_proxy.read_property("max_intensity") == 16384

        pytest.raises(httpx.HTTPStatusError, ClientFactory.http, url=td_endpoint)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
