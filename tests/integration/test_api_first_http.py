import itertools

from typing import Generator

import pytest
import requests

from testkit.helpers import hostname_prefix, stop_all_runs, wait_until_server_ready
from testkit.things import OscilloscopeDriver, oscilloscope_TD

from hololinked.core import Thing
from hololinked.metadata.td import ThingModel
from hololinked.utils import uuid_hex


ports = itertools.count(63000)


@pytest.fixture(scope="module")
def oscilloscope() -> Generator[tuple[Thing, int], None, None]:
    port = next(ports)
    thing = ThingModel.from_metadata(oscilloscope_TD).produce(OscilloscopeDriver(), id=f"oscilloscope-{uuid_hex()}")
    thing.run_with_http_server(address="127.0.0.1", port=port, forked=True, print_welcome_message=False)
    try:
        wait_until_server_ready(port=port)
        yield thing, port
    finally:
        stop_all_runs()


@pytest.fixture
def http_client() -> requests.Session:
    with requests.Session() as session:
        yield session


def test_01_read_write_property(oscilloscope, http_client):
    """a generic WoT client sends a bare value for a non-object input."""
    thing, port = oscilloscope
    response = http_client.get(f"{hostname_prefix}:{port}/{thing.id}/time-resolution")
    assert response.status_code == 200
    assert isinstance(response.json(), (int, float))

    response = http_client.put(f"{hostname_prefix}:{port}/{thing.id}/time-resolution", json=2.0)
    assert response.status_code == 200

    response = http_client.get(f"{hostname_prefix}:{port}/{thing.id}/time-resolution")
    assert response.status_code == 200
    assert response.json() == 2.0


def test_02_invoke_action(oscilloscope, http_client):
    thing, port = oscilloscope
    response = http_client.post(f"{hostname_prefix}:{port}/{thing.id}/set-trigger-level", json=0.5)
    assert response.status_code == 200
    assert response.json() == 0.5
    response = http_client.post(f"{hostname_prefix}:{port}/{thing.id}/set-trigger-level", json="x")
    assert response.json()["exception"]["type"] == "ValidationError"  # an error in the body, with status 200


# def test_02_object_input_and_property(oscilloscope):
#     thing, port = oscilloscope
#     response = requests.post(
#         f"{hostname_prefix}:{port}/{thing.id}/configure-channel",
#         json={"channel": 1, "volts_per_division": 0.2},
#     )
#     assert response.status_code == 200
#     assert response.json() == 2.0
#     response = requests.get(f"{hostname_prefix}:{port}/{thing.id}/time-resolution")
#     assert response.status_code == 200
#     assert response.json() == 1.0


# if __name__ == "__main__":
#     pytest.main([__file__, "-v", "-s"])
