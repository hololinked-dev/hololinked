"""
Pytest configuration and shared fixtures for hololinked tests.
"""
import asyncio
import pytest
import zmq.asyncio
from uuid import uuid4
from faker import Faker

from hololinked.config import global_config


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="class")
def zmq_context():
    """Setup ZMQ context for test classes."""
    global_config.ZMQ_CONTEXT = zmq.asyncio.Context()
    yield global_config.ZMQ_CONTEXT
    # Cleanup is handled by the context manager


@pytest.fixture(scope="class")
def test_ids():
    """Generate unique test IDs for each test class."""
    return {
        "server_id": f"test-server-{uuid4().hex[:8]}",
        "client_id": f"test-client-{uuid4().hex[:8]}",
        "thing_id": f"test-thing-{uuid4().hex[:8]}"
    }


@pytest.fixture(scope="session")
def fake():
    """Provide a Faker instance for generating test data."""
    return Faker()


@pytest.fixture(autouse=True)
def setup_test_environment(zmq_context):
    """Automatically setup test environment for each test."""
    # This fixture runs automatically for every test
    pass


def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "order: mark test to run in a specific order"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add ordering markers."""
    # Add order markers based on test file names
    for item in items:
        if "test_01_" in item.nodeid:
            item.add_marker(pytest.mark.order(1))
        elif "test_00_" in item.nodeid:
            item.add_marker(pytest.mark.order(0))
