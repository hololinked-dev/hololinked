"""pytest configuration and shared fixtures for hololinked tests"""

import asyncio
import logging
import sys

from uuid import uuid4

import pytest
import zmq.asyncio

from testkit.helpers import AppIDs, stop_all_runs

from hololinked import Serializers
from hololinked.config import global_config


LAYER_MARKERS = ("unit", "integration", "e2e")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every test with the layer it was collected from, so `-m unit` and friends work"""
    rootdir = config.rootpath / "tests"
    for item in items:
        try:
            layer = item.path.relative_to(rootdir).parts[0]
        except ValueError:
            continue
        if layer in LAYER_MARKERS:
            item.add_marker(getattr(pytest.mark, layer))

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
