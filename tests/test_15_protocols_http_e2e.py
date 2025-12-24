from typing import Any, Generator

import pytest

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.server import stop
from hololinked.utils import uuid_hex


try:
    from .test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from .test_11_rpc_e2e import client, thing, thing_model  # noqa: F401
    from .test_14_protocols_http import hostname_prefix, wait_until_server_ready
    from .things import TestThing
except ImportError:
    from test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from test_11_rpc_e2e import client, thing, thing_model  # noqa: F401
    from test_14_protocols_http import hostname_prefix, wait_until_server_ready
    from things import TestThing


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
    wait_until_server_ready(port=port)
    yield thing
    stop()


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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
