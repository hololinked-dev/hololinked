from typing import Any, Generator

import pytest

from testkit.helpers import stop_all_runs
from testkit.things import TestThing

from hololinked.client.factory import ClientFactory
from hololinked.client.proxy import ObjectProxy
from hololinked.utils import uuid_hex


@pytest.fixture(scope="class")
def thing(access_point) -> Generator[TestThing, None, None]:
    thing_id = f"test-thing-{uuid_hex()}"
    thing = TestThing(id=thing_id)
    thing.run_with_zmq_server(forked=True, access_points=[access_point])
    try:
        yield thing
    finally:
        stop_all_runs()


@pytest.fixture(scope="class")
def thing_model(thing: TestThing) -> dict[str, Any]:
    return thing.get_thing_model(ignore_errors=True).json()


@pytest.fixture(scope="class")
def client(thing: TestThing, access_point: str) -> Generator[ObjectProxy, None, None]:
    client = ClientFactory.zmq(
        server_id=thing.id,
        thing_id=thing.id,
        access_point=access_point.replace("*", "localhost"),
        ignore_TD_errors=True,
    )
    yield client
    # client.close()
