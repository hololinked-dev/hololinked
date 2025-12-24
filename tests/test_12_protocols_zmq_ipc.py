import pytest


try:
    from .test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from .test_11_rpc_e2e import client, thing, thing_model  # noqa: F401
except ImportError:
    from test_11_rpc_e2e import TestRPC_E2E as BaseRPC_E2E  # noqa: F401
    from test_11_rpc_e2e import client, thing, thing_model  # noqa: F401


@pytest.fixture(scope="class")
def access_point(request):
    return "IPC"


@pytest.mark.asyncio(loop_scope="class")
class TestZMQ_IPC_E2E(BaseRPC_E2E):
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
