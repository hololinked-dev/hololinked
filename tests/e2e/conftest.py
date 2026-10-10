import time

from typing import Generator

import pytest

from testcontainers.mqtt import (
    MosquittoContainer,  # TODO this will not work from the current release of testcontainers
)
from testkit.helpers import MQTT_ASSETS, mqtt_ssl_context


@pytest.fixture(scope="module")
def mosquitto_container(tmp_path_factory: pytest.TempPathFactory) -> Generator[MosquittoContainer, None, None]:
    data = tmp_path_factory.mktemp("mosquitto-data")
    log = tmp_path_factory.mktemp("mosquitto-log")
    (data / "persisted").mkdir()
    container = MosquittoContainer(
        volumes=[
            (str(MQTT_ASSETS / "mosquitto.conf"), "/mosquitto/config/mosquitto.conf", "ro"),
            (str(MQTT_ASSETS / "passwords.txt"), "/mosquitto/config/passwords.txt", "ro"),
            (str(MQTT_ASSETS / "certs"), "/mosquitto/config/certs", "ro"),
            (str(data), "/mosquitto/data", "rw"),
            (str(log), "/mosquitto/log", "rw"),
        ],
        username="sampleuser",
        password="samplepass",
        mqtt_port=8883,
        ws_port=9001,
        ssl_context=mqtt_ssl_context(),
    )

    # One could in principle retry the tests directly
    for i in range(3):
        exc = None
        try:
            container.start()
            break
        except Exception as ex:
            # some SSL handshake error appears sometimes, but not always
            print(f"\nAttempt {i + 1}: Failed to start Mosquitto container, retrying...")
            exc = ex
        try:
            print(container.get_logs())
        except Exception:
            print("Failed to get container logs")
        try:
            container.stop()
        except Exception:
            pass
        if i == 2:
            raise exc from None
        time.sleep(3)

    yield container
    container.stop()


@pytest.fixture(scope="module")
def mqtt_host(mosquitto_container: MosquittoContainer) -> str:
    return mosquitto_container.get_container_host_ip()


@pytest.fixture(scope="module")
def mqtt_port(mosquitto_container: MosquittoContainer) -> int:
    return int(mosquitto_container.get_exposed_port(8883))


@pytest.fixture(scope="module")
def mqtt_ws_host(mosquitto_container: MosquittoContainer) -> str:
    return mosquitto_container.get_container_host_ip()


@pytest.fixture(scope="module")
def mqtt_ws_port(mosquitto_container: MosquittoContainer) -> int:
    return int(mosquitto_container.get_exposed_port(9001))
