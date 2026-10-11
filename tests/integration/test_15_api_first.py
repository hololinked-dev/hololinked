import itertools

from typing import Generator

import pytest
import requests

from testkit.helpers import hostname_prefix, stop_all_runs, wait_until_server_ready

from hololinked.core import Thing
from hololinked.metadata.td import ThingModel
from hololinked.utils import uuid_hex


ports = itertools.count(63000)

TD = {
    "title": "Amplifier",
    "properties": {"gain": {"type": "number", "minimum": 0}},
    "actions": {
        "double": {"input": {"type": "number"}, "output": {"type": "number"}},
        "scale": {
            "input": {
                "type": "object",
                "properties": {"value": {"type": "number"}, "factor": {"type": "number"}},
                "required": ["value", "factor"],
            },
        },
    },
}


class AmplifierDriver:
    def __init__(self) -> None:
        self.gain = 1.5

    def double(self, value: float) -> float:
        return value * 2

    def scale(self, value: float, factor: float) -> float:
        return value * factor


@pytest.fixture(scope="module")
def amplifier() -> Generator[tuple[Thing, int], None, None]:
    port = next(ports)
    thing = ThingModel.from_metadata(TD).produce(AmplifierDriver(), id=f"amplifier-{uuid_hex()}")
    thing.run_with_http_server(address="127.0.0.1", port=port, forked=True, print_welcome_message=False)
    try:
        wait_until_server_ready(port=port)
        yield thing, port
    finally:
        stop_all_runs()


def test_01_single_value_input(amplifier):
    """a generic WoT client sends a bare value for a non-object input."""
    thing, port = amplifier
    response = requests.post(f"{hostname_prefix}:{port}/{thing.id}/double", json=5)
    assert response.status_code == 200
    assert response.json() == 10
    response = requests.post(f"{hostname_prefix}:{port}/{thing.id}/double", json="x")
    assert "validation error" in response.json()["exception"]["message"]  # an error in the body, with status 200


def test_02_object_input_and_property(amplifier):
    thing, port = amplifier
    response = requests.post(f"{hostname_prefix}:{port}/{thing.id}/scale", json={"value": 2, "factor": 3})
    assert response.status_code == 200
    assert response.json() == 6
    response = requests.get(f"{hostname_prefix}:{port}/{thing.id}/gain")
    assert response.status_code == 200
    assert response.json() == 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
