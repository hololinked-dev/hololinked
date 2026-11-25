import pytest

from testkit.suites import TestRPC_E2E as BaseRPC_E2E


@pytest.fixture(scope="class")
def access_point(request):
    return "IPC"


@pytest.mark.asyncio(loop_scope="class")
class TestZMQ_IPC_E2E(BaseRPC_E2E):
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
