"""
Pytest configuration and shared fixtures for hololinked tests.
"""

import asyncio
import pytest
import zmq.asyncio
import sys
from typing import Generator
from uuid import uuid4
from faker import Faker
from dataclasses import dataclass

from hololinked.config import global_config
from hololinked.serializers import Serializers


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


@pytest.fixture(scope="session")
def fake() -> Faker:
    """Provide a Faker instance for generating test data."""
    return Faker()


@pytest.fixture()
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture()
def zmq_context() -> Generator[zmq.asyncio.Context, None, None]:
    """Setup ZMQ context for test classes."""
    global_config.ZMQ_CONTEXT = zmq.asyncio.Context()
    yield global_config.ZMQ_CONTEXT
    global_config.ZMQ_CONTEXT.term()


@pytest.fixture()
def setup_test_environment(zmq_context, event_loop):
    """Automatically setup test environment for each file"""
    # This fixture runs automatically for every test
    yield
    # Reset serializers after each test
    Serializers().reset()


@pytest.fixture()
def app_ids() -> AppIDs:
    """Generate unique test IDs for server, client, and thing for each test"""
    return AppIDs(
        server_id=f"test-server-{uuid4().hex[:8]}",
        client_id=f"test-client-{uuid4().hex[:8]}",
        thing_id=f"test-thing-{uuid4().hex[:8]}",
    )
