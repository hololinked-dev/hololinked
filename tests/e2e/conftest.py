import os
import time

from typing import Generator

import pytest

from testcontainers.mqtt import (
    MosquittoContainer,  # TODO this will not work from the current release of testcontainers
)
from testkit.helpers import mqtt_ssl_context


@pytest.fixture(scope="module")
def mosquitto_container() -> Generator[MosquittoContainer, None, None]:
    container = MosquittoContainer(
        volumes=[
            (
                os.path.abspath("daq-system-infrastructure/conf/mosquitto.conf"),
                "/mosquitto/config/mosquitto.conf",
                "ro",
            ),
            (os.path.abspath("daq-system-infrastructure/conf/passwords.txt"), "/mosquitto/config/passwords.txt", "ro"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto"), "/mosquitto/data", "rw"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto/log"), "/mosquitto/log", "rw"),
            (os.path.abspath("daq-system-infrastructure/data/mosquitto/persisted"), "/mosquitto/data/persisted", "rw"),
            (os.path.abspath("daq-system-infrastructure/certs"), "/mosquitto/config/certs", "ro"),
        ],
        username="sampleuser",
        password="samplepass",
        mqtt_port=8883,
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
