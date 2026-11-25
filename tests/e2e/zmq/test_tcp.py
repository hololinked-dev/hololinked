import pytest

from testkit.suites import TestRPC_E2E as BaseRPC_E2E


@pytest.fixture(scope="class")
def access_point(request):
    return "tcp://*:61000"


@pytest.mark.asyncio(loop_scope="class")
class TestZMQ_TCP_E2E(BaseRPC_E2E):
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
