#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import ssl
import threading

from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from testcontainers.core.container import DockerContainer
from testcontainers.core.utils import setup_logger
from testcontainers.core.waiting_utils import WaitStrategy


if TYPE_CHECKING:
    from paho.mqtt.client import Client, ReasonCode
    from paho.mqtt.enums import MQTTErrorCode


logger = setup_logger(__name__)


class MQTTClientAvailabilityWaitStrategy(WaitStrategy):
    """
    Wait strategy for older versions of Mosquitto, or when one would
    like to wait for a client connection instead of log messages.
    """

    def wait_until_ready(self, container: "MosquittoContainer") -> None:
        container.get_client()
        logger.info("MQTT client is connected, container is ready")


class MosquittoContainer(DockerContainer):
    """
    Specialization of DockerContainer for MQTT broker Mosquitto.
    Example:

        .. doctest::

            >>> from testcontainers.mqtt import MosquittoContainer

            >>> with MosquittoContainer() as mosquitto_broker:
            ...     mqtt_client = mosquitto_broker.get_client()
    """

    TESTCONTAINERS_CLIENT_ID_PREFIX = "TESTCONTAINERS-CLIENT"
    DEFAULT_CONFIG_FILE = "testcontainers-mosquitto-default-configuration.conf"

    def __init__(
        self,
        image: str = "eclipse-mosquitto:latest",
        config_file: str | None = None,
        mqtt_port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ssl_context: Optional[ssl.SSLContext] = None,
        paho_client_kwargs: Optional[dict] = None,
        **kwargs,
    ) -> None:
        """
        Initialize a MosquittoContainer.

        The default wait strategy for this container is a client availability check.
        You need to create your own wait strategy if you want, for example, to wait for specific log messages
        instead of client availability.

        Args:
            image (str):
                The docker image to use. Defaults to 'eclipse-mosquitto:latest'.
            config_file (str, optional):
                Path to a 'mosquitto.conf' file. Defaults to a built-in minimalistic config file that allows
                anonymous connections and exposes the default non-SSL MQTT port 1883.
                Use the 'volumes' argument to mount your own config file, for example:
                ``>> volumes=[("path/to/your/mosquitto.conf", "/mosquitto/config/mosquitto.conf", "ro")].``
            mqtt_port (int):
                The port to expose for MQTT connections inside the container. Defaults to 1883.
                Use the base class 'ports' mapping to override.
            username (str, optional):
                Optional username for MQTT authentication. Defaults to None.
            password (str, optional):
                Optional password for MQTT authentication. Defaults to None.
            ssl_context (ssl.SSLContext, optional):
                Optional SSL context for secure MQTT connections. Defaults to None (no SSL).
            **kwargs:
                Additional keyword arguments passed to the DockerContainer base class.
                Supports an additional ``broker_connect_timeout`` argument to specify how long to wait for
                the MQTT client to connect to the broker for the default wait strategy, defaulting to 30 seconds.
        """
        if config_file is None:
            config_file = Path(__file__).parent / MosquittoContainer.DEFAULT_CONFIG_FILE  # default config file

        super().__init__(
            image,
            ports=kwargs.pop("ports", (mqtt_port,)),
            volumes=kwargs.pop("volumes", [(config_file, "/mosquitto/config/mosquitto.conf", "ro")]),
            **kwargs,
        )

        self.client: Optional["Client"] = None  # noqa: UP037  # reusable client context
        self.config_file = config_file
        self.mqtt_port = mqtt_port
        self.username = username
        self.password = password
        self.broker_connect_timeout = kwargs.pop("broker_connect_timeout", 30)
        self.paho_client_kwargs = paho_client_kwargs or dict()
        self.ssl_context = ssl_context
        self._connected_event = threading.Event()

        if self._wait_strategy is None:
            self._wait_strategy = MQTTClientAvailabilityWaitStrategy()

    def get_client(self) -> "Client":
        """
        Creates and connects a client, caching the result in `self.client`
        returning that if it exists.

        Connection attempts are retried using `@wait_container_is_ready`.

        Returns:
            a client from the paho library
        """
        if self.client is not None:
            if self.client.is_connected():
                return self.client
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.client = None

        client, err = self.new_client()
        # 0 is a conventional "success" value in C, which is falsy in python
        if err:
            # retry, maybe it is not available yet
            raise ConnectionError(f"Failed to establish a connection: {err}")
        if not client.is_connected():
            raise TimeoutError("The Paho MQTT secondary thread has not connected yet!")

        self.client = client
        return client

    def new_client(self, **kwargs) -> tuple["Client", "MQTTErrorCode"]:
        """
        Get a paho.mqtt client connected to this container.
        Check the returned object is_connected() method before use

        Usage of this method is required for versions <2;
        versions >=2 will wait for log messages to determine container readiness.
        There is no way to pass arguments to new_client in versions <2,
        please use an up-to-date version.

        Args:
            **kwargs: Keyword arguments passed to `paho.mqtt.client`.

        Returns:
            client: MQTT client to connect to the container.
            error: an error code or MQTT_ERR_SUCCESS.
        """
        try:
            from paho.mqtt.client import CallbackAPIVersion, Client
            from paho.mqtt.enums import MQTTErrorCode
        except ImportError as ex:
            raise ImportError("'pip install paho-mqtt' required for MosquittoContainer.new_client") from ex

        err = MQTTErrorCode.MQTT_ERR_SUCCESS

        self._connected_event.clear()

        def on_connect(
            client,
            userdata: "MosquittoContainer",
            flags,
            reason_code: "ReasonCode",
            properties=None,
        ) -> None:
            # TODO update signature
            # reason_code == 0 means success
            if reason_code.getName().lower() == "success":
                userdata._connected_event.set()

        client = Client(
            client_id=f"{MosquittoContainer.TESTCONTAINERS_CLIENT_ID_PREFIX}-{uuid4().hex[0:8]}",
            callback_api_version=CallbackAPIVersion.VERSION2,
            userdata=self,
            **kwargs,
            **self.paho_client_kwargs,
        )
        if self.ssl_context is not None:
            client.tls_set_context(self.ssl_context)
        if self.username and self.password:
            client.username_pw_set(self.username, self.password)
        client.on_connect = on_connect

        client.loop_start()  # start loop BEFORE/around connect so CONNACK can be processed

        try:
            err = client.connect(self.get_container_host_ip(), int(self.get_exposed_port(self.mqtt_port)))
        except Exception:
            client.loop_stop()
            raise

        self._connected_event.wait(timeout=self.broker_connect_timeout)  # wait for on_connect
        if not self._connected_event.is_set():
            client.loop_stop()
            raise TimeoutError("Timed out while waiting for MQTT client to connect to the broker container.")

        return client, err

    def stop(self, force: bool = True, delete_volume: bool = True) -> None:
        if self.client is not None:
            self.client.disconnect()
            self.client = None  # force recreation of the client object at next start()
        super().stop(force, delete_volume)

    def publish_message(self, topic: str, payload: str, timeout: int = 2) -> None:
        ret = self.get_client().publish(topic, payload)
        ret.wait_for_publish(timeout=timeout)
        if not ret.is_published():
            raise RuntimeError(f"Could not publish a message on topic {topic} to Mosquitto broker: {ret}")
