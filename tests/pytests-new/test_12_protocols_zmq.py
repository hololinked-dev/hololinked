import logging
import pytest
import uuid
from hololinked.client import ClientFactory
from hololinked.logger import setup_logging

try:
    from .things import TestThing
except ImportError:
    from things import TestThing

setup_logging(log_level=logging.ERROR + 10)


# --- Pytest conversion ---


@pytest.fixture(
    scope="module",
    params=[
        ("tcp://*:5557", "tcp://localhost:5557", False),
        ("tcp://*:6000", "tcp://localhost:6000", True),
        ("inproc", "inproc", False),
        ("inproc", "inproc", True),
    ],
)
def zmq_config(request):
    """
    Yields (access_points, client_url, is_async)
    """
    return request.param


@pytest.fixture(scope="function")
def thing_id():
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def server_id():
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def thing(zmq_config, thing_id):
    access_points, _, _ = zmq_config
    t = TestThing(id=thing_id)
    t.run_with_zmq_server(forked=True, access_points=access_points)
    return t


@pytest.fixture(scope="function")
def thing_model(thing):
    return thing.get_thing_model(ignore_errors=True).json()


@pytest.fixture(scope="function")
def zmq_client(zmq_config, server_id, thing_id):
    _, client_url, _ = zmq_config
    client = ClientFactory.zmq(
        server_id,
        thing_id,
        client_url,
        ignore_TD_errors=True,
    )
    return client


@pytest.fixture(scope="function")
def zmq_async_client(zmq_config, server_id, thing_id):
    _, client_url, _ = zmq_config
    client = ClientFactory.zmq(
        server_id,
        thing_id,
        client_url,
        ignore_TD_errors=True,
    )
    return client


def _is_async(zmq_config):
    return zmq_config[2]


@pytest.mark.parametrize(
    "method_name",
    [
        "test_basic_call",
        "test_property_access",
        "test_method_with_args",
        "test_error_handling",
        "test_model_consistency",
    ],
)
def test_zmq_protocols(zmq_config, thing, thing_model, zmq_client, zmq_async_client, method_name):
    """
    Run all protocol tests for each ZMQ config and method.
    """
    is_async = _is_async(zmq_config)
    # Import the test logic from the original test_11_rpc_e2e
    try:
        from .test_11_rpc_e2e import TestRPCEndToEnd, TestRPCEndToEndAsync
    except ImportError:
        from test_11_rpc_e2e import TestRPCEndToEnd, TestRPCEndToEndAsync

    if is_async:
        test_obj = TestRPCEndToEndAsync()
        test_obj.thing = thing
        test_obj.thing_model = thing_model
        test_obj._client = zmq_async_client
        test_obj.server_id = zmq_async_client.server_id
        test_obj.thing_id = zmq_async_client.thing_id
    else:
        test_obj = TestRPCEndToEnd()
        test_obj.thing = thing
        test_obj.thing_model = thing_model
        test_obj._client = zmq_client
        test_obj.server_id = zmq_client.server_id
        test_obj.thing_id = zmq_client.thing_id

    # Call the method
    test_method = getattr(test_obj, method_name)
    if is_async and hasattr(test_method, "__await__"):
        import asyncio

        asyncio.run(test_method())
    else:
        test_method()
