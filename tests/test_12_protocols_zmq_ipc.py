import pytest


try:
    from .test_11_rpc_e2e import TestRPC_E2E, client, thing, thing_model  # noqa: F401
except ImportError:
    from test_11_rpc_e2e import TestRPC_E2E, client, thing, thing_model  # noqa: F401


@pytest.fixture(scope="class")
def access_point(request):
    return "IPC"
