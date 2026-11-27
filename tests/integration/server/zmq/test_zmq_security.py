"""API key authentication for the ZMQ server and client."""

import datetime

from collections.abc import Generator

import pytest

from testkit.helpers import stop_all_runs
from testkit.things import TestThing

from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy
from hololinked.client.security import APIKeySecurity as ClientAPIKeySecurity
from hololinked.client.security import BasicSecurity
from hololinked.server.security import APIKeySecurity, BcryptBasicSecurity
from hololinked.server.zmq.config import RuntimeConfig
from hololinked.utils import uuid_hex


ACCESS_POINT = "INPROC"


@pytest.fixture(scope="module")
def apikey_scheme() -> tuple[APIKeySecurity, str]:
    """A freshly created key, and the server-side scheme that validates it."""
    keyname = f"zmq-test-apikey-{uuid_hex()}"
    apikey = APIKeySecurity(name=keyname).create(print_value=False)
    return APIKeySecurity(name=keyname), apikey


@pytest.fixture(scope="module")
def secured_thing(apikey_scheme: tuple[APIKeySecurity, str]) -> Generator[TestThing, None, None]:
    scheme, _ = apikey_scheme
    thing = TestThing(id=f"test-zmq-sec-{uuid_hex()}")
    thing.run_with_zmq_server(forked=True, access_points=[ACCESS_POINT], security_schemes=[scheme])
    try:
        yield thing
    finally:
        stop_all_runs()


def connect(thing: TestThing, apikey: str | None = None) -> ObjectProxy:
    return ClientFactory.zmq(
        server_id=thing.id,
        thing_id=thing.id,
        access_point=ACCESS_POINT,
        ignore_TD_errors=True,
        security=ClientAPIKeySecurity(value=apikey) if apikey is not None else None,
    )


def test_01_config_accepts_apikey_and_none(apikey_scheme: tuple[APIKeySecurity, str]):
    scheme, _ = apikey_scheme
    assert RuntimeConfig().security_schemes is None
    assert RuntimeConfig(security_schemes=[scheme]).security_schemes == [scheme]


def test_02_config_rejects_unsupported_scheme():
    with pytest.raises(ValueError, match="APIKeySecurity"):
        RuntimeConfig(security_schemes=[BcryptBasicSecurity(username="someuser", password="somepassword")])


def test_03_client_rejects_unsupported_scheme(secured_thing: TestThing):
    with pytest.raises(ValueError, match="APIKeySecurity"):
        ClientFactory.zmq(
            server_id=secured_thing.id,
            thing_id=secured_thing.id,
            access_point=ACCESS_POINT,
            security=BasicSecurity(username="someuser", password="somepassword"),
        )


def test_04_valid_key(secured_thing: TestThing, apikey_scheme: tuple[APIKeySecurity, str]):
    scheme, apikey = apikey_scheme
    client = connect(secured_thing, apikey)
    client.write_property("number_prop", 5)
    assert client.read_property("number_prop") == 5
    # the TD advertises the scheme the server enforces
    assert client.td["security"] == [scheme.name]
    assert client.td["securityDefinitions"][scheme.name]["scheme"] == "apikey"


@pytest.mark.parametrize(
    "apikey",
    [
        pytest.param(None, id="no-key"),
        pytest.param("wrongapikey", id="plainly-wrong-key"),
        pytest.param("wotdat-abcde.blablabla", id="well-formed-wrong-key"),
    ],
)
def test_05_invalid_key(secured_thing: TestThing, apikey: str | None):
    # the TD fetch is itself an operation, so the client fails while connecting
    with pytest.raises(PermissionError):
        connect(secured_thing, apikey)


def test_06_right_key_with_wrong_id(secured_thing: TestThing, apikey_scheme: tuple[APIKeySecurity, str]):
    _, apikey = apikey_scheme
    with pytest.raises(PermissionError):
        connect(secured_thing, f"wotdat-{apikey.split('-')[1].split('.')[0]}.blablabla")


def test_07_expired_key(secured_thing: TestThing, apikey_scheme: tuple[APIKeySecurity, str]):
    scheme, apikey = apikey_scheme
    client = connect(secured_thing, apikey)
    original_expiry = scheme.record.expiry_at
    scheme.record.expiry_at = datetime.datetime.fromisoformat("2000-01-01T00:00:00")
    try:
        with pytest.raises(PermissionError):
            client.read_property("number_prop")
    finally:
        scheme.record.expiry_at = original_expiry


def test_08_auth_disabled():
    thing = TestThing(id=f"test-zmq-nosec-{uuid_hex()}")
    thing.run_with_zmq_server(forked=True, access_points=[ACCESS_POINT])
    try:
        client = connect(thing)
        assert isinstance(client.read_property("number_prop"), (int, float))
        assert client.td["security"] == ["nosec"]
        assert "nosec" in client.td["securityDefinitions"]
    finally:
        stop_all_runs()