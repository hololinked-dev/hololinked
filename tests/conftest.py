"""pytest configuration and shared fixtures for hololinked tests"""

import asyncio
import logging

from dataclasses import dataclass
from uuid import uuid4

import pytest
import zmq.asyncio

from hololinked.config import global_config
from hololinked.serializers import Serializers
from hololinked.server import stop


@dataclass
class AppIDs:
    """
    Application related IDs generally used by end-user,
    like server, client, and thing IDs.
    """

    server_id: str
    """RPC server ID"""
    client_id: str
    """A client ID"""
    thing_id: str
    """A thing ID"""


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
    yield loop
    loop.close()


@pytest.fixture(autouse=True, scope="module")
def setup_test_environment():
    """Automatically setup test environment for each file"""
    # This fixture runs automatically for every test
    global_config.ZMQ_CONTEXT = zmq.asyncio.Context()
    global_config.LOG_LEVEL = logging.ERROR + 10
    global_config.setup()
    yield
    stop()
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
