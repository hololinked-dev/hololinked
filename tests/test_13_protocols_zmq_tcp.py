import logging

import pytest

from hololinked.logger import setup_logging


try:
    from .test_11_rpc_e2e import TestRPC_E2E, client, thing, thing_model  # noqa: F401
except ImportError:
    from test_11_rpc_e2e import TestRPC_E2E, client, thing, thing_model  # noqa: F401

setup_logging(log_level=logging.ERROR + 10)


@pytest.fixture(scope="class")
def access_point(request):
    return "tcp://*:5556"
