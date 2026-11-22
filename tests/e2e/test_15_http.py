from typing import Any, Generator
from urllib.parse import urlsplit, urlunsplit

import pytest
import requests

from testkit.helpers import hostname_prefix, stop_all_runs, wait_until_server_ready
from testkit.suites import TestRPC_E2E as BaseRPC_E2E
from testkit.things import TestThing

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.utils import uuid_hex


@pytest.fixture(scope="class")
def port() -> int:
    return 63000


@pytest.fixture(scope="class")
def thing(port: int) -> Generator[TestThing, None, None]:
    thing = TestThing(id=f"test-thing-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    thing.run_with_http_server(
        address="127.0.0.1",
        port=port,
        forked=True,
        print_welcome_message=False,
        config=dict(cors=True),
    )
    try:
        wait_until_server_ready(port=port)
        yield thing
    finally:
        stop_all_runs()


@pytest.fixture(scope="class")
def thing_model(thing: TestThing) -> dict[str, Any]:
    return thing.get_thing_model(ignore_errors=True).json()


@pytest.fixture(scope="class")
def td_endpoint(thing: TestThing, port: int) -> str:
    return f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td"


@pytest.fixture(scope="class")
def client(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.http(url=td_endpoint, ignore_TD_errors=True)


@pytest.mark.asyncio(loop_scope="class")
class TestHTTP_E2E(BaseRPC_E2E):
    def test_14_rw_multiple_properties(self, client: ObjectProxy):
        pass

    def test_15_http_action_error_status(self, thing: TestThing, port: int):
        td_url = f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td?ignore_errors=true"
        td_response = requests.get(td_url)
        assert td_response.status_code == 200

        td = td_response.json()
        action_form = td["actions"]["set_non_remote_number_prop"]["forms"][0]
        parsed_url = urlsplit(action_form["href"])
        action_url = urlunsplit(
            (
                parsed_url.scheme,
                f"127.0.0.1:{port}",
                parsed_url.path,
                parsed_url.query,
                parsed_url.fragment,
            )
        )

        response = requests.post(action_url, json={"__args__": [5]})
        assert response.status_code == 200

        response = requests.post(action_url, json={"__args__": [-1]})
        assert response.status_code == 500
        assert response.json()["exception"]["type"] == "ValueError"
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
