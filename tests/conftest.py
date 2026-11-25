"""pytest configuration and shared fixtures for hololinked tests"""

import asyncio
import logging
import sys

from pathlib import Path
from uuid import uuid4

import pytest
import zmq.asyncio

from testkit.helpers import AppIDs, stop_all_runs

from hololinked import Serializers
from hololinked.config import global_config


TEST_LAYERS = ("unit", "integration", "e2e")

TEST_FILE_ORDER = {
    "unit": [
        "test_utils.py",
        "test_serializers.py",
        "test_schema_validators.py",
        "server/zmq/test_message.py",
        "server/zmq/test_socket.py",
        "server/test_custom_topics.py",
        "core/test_thing_init.py",
        "core/test_properties.py",
        "core/test_actions.py",
        "core/test_events.py",
        "metadata/test_file_loading.py",
        "metadata/td/test_data_schema.py",
        "metadata/td/test_dataschema_to_model.py",
        "metadata/td/test_affordance_to_descriptor.py",
        "test_thing_description.py",
        "core/test_api_first.py",
        "test_config.py",
    ],
    "integration": [
        "server/zmq/test_brokers.py",
        "server/zmq/test_message_version.py",
        "server/zmq/test_rpc_server.py",
        "test_http_server.py",
        "test_api_first_http.py",
    ],
    "e2e": [
        "zmq/test_inproc.py",
        "zmq/test_ipc.py",
        "zmq/test_tcp.py",
        "test_http.py",
        "test_mqtt.py",
        "test_multi_protocol.py",
    ],
}


def test_order_key(path: Path, rootdir: Path) -> tuple[int, int]:
    try:
        layer, *rest = path.relative_to(rootdir).parts
    except ValueError:
        return len(TEST_LAYERS), 0
    files = TEST_FILE_ORDER.get(layer, [])
    file = "/".join(rest)
    return (
        TEST_LAYERS.index(layer) if layer in TEST_LAYERS else len(TEST_LAYERS),
        files.index(file) if file in files else len(files),
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """
    "Mark every test with the layer it was collected from, so `-m unit` and friends work,
    and sort tests by layer and then by `TEST_FILE_ORDER`
    """
    rootdir = config.rootpath / "tests"
    for item in items:
        try:
            layer = item.path.relative_to(rootdir).parts[0]
        except ValueError:
            continue
        if layer in TEST_LAYERS:
            item.add_marker(getattr(pytest.mark, layer))
    items.sort(key=lambda item: test_order_key(item.path, rootdir))

    if sys.platform == "win32":
        skip_mqtt = pytest.mark.skip(reason="an MQTT broker is not available on Windows")
        for item in items:
            if "mqtt" in item.keywords:
                item.add_marker(skip_mqtt)


@pytest.fixture(scope="session", autouse=True)
def cleanup_temp_files():
    """Fixture to cleanup temporary files after all tests are done"""
    global_config.cleanup_temp_dirs(cleanup_databases=True)


@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
def setup_test_environment():
    """Automatically setup test environment for each file"""
    # This fixture runs automatically for every test
    global_config.ZMQ_CONTEXT = zmq.asyncio.Context()
    global_config.LOG_LEVEL = logging.ERROR + 10
    global_config.setup()
    yield
    stop_all_runs()
    # Reset serializers after each test
    Serializers().reset()
    global_config.ZMQ_CONTEXT.destroy(linger=0)
    global_config.ZMQ_CONTEXT.term()


@pytest.fixture()
def app_ids() -> AppIDs:
    """Generate unique test IDs for server, client, and thing for each test"""
    return AppIDs(
        server_id=f"test-server-{uuid4().hex[:8]}",
        client_id=f"test-client-{uuid4().hex[:8]}",
        thing_id=f"test-thing-{uuid4().hex[:8]}",
    )
