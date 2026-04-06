import socket
import time

from typing import Any, Generator

import pytest

from hololinked.client import ClientFactory, ObjectProxy
from hololinked.server import run, stop
from hololinked.server.coap import CoAPServer
from hololinked.utils import uuid_hex


try:
    from .test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from .things import TestThing
except ImportError:
    from test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from things import TestThing


hostname_prefix = f"coap://{socket.gethostname()}"


@pytest.fixture(scope="class")
def port() -> int:
    return 60000


def wait_until_server_ready(port: int, timeout: int = 10) -> None:
    time.sleep(2)


@pytest.fixture(scope="class")
def thing(port: int) -> Generator[TestThing, None, None]:
    thing = TestThing(id=f"test-thing-{uuid_hex()}", serial_number="simulation")
    print()  # TODO, can be removed when tornado logs respect level
    server = CoAPServer(address="0.0.0.0", port=port)
    server.add_thing(thing)
    run(server, forked=True, print_welcome_message=False)
    wait_until_server_ready(port=port)
    yield thing
    stop()


@pytest.fixture(scope="class")
def thing_model(thing: TestThing) -> dict[str, Any]:
    model = thing.get_thing_model(ignore_errors=True).json()
    model["events"] = dict()
    return model


@pytest.fixture(scope="class")
def td_endpoint(thing: TestThing, port: int) -> str:
    return f"{hostname_prefix}:{port}/{thing.id}/resources/wot-td?ignore_errors=true"


@pytest.fixture(scope="class")
def client(td_endpoint: str) -> "ObjectProxy":
    return ClientFactory.coap(url=td_endpoint, ignore_TD_errors=True)


@pytest.mark.asyncio(loop_scope="class")
class TestCoAP_E2E(BaseRPC_E2E):
    def test_14_rw_multiple_properties(self, client: ObjectProxy):
        pass

    def test_15_subscribe_event(self, client: ObjectProxy):
        pass

    @pytest.mark.parametrize(
        "prop, prospective_values, op",
        [
            pytest.param(
                "observable_list_prop",
                [
                    [1, 2, 3, 4, 5],
                    ["a", "b", "c", "d", "e"],
                    [1, "a", 2, "b", 3],
                ],
                "write",
                id="observable-list-prop",
            ),
            pytest.param(
                "observable_readonly_prop",
                [1, 2, 3, 4, 5],
                "read",
                id="observable-readonly-prop",
            ),
        ],
    )
    def test_16_observe_properties(self, client: ObjectProxy, prop: str, prospective_values: Any, op: str):
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
