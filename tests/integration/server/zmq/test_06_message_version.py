import asyncio
import multiprocessing
import threading
import time

from typing import AsyncGenerator, Generator

import pytest

from hololinked import Serializers
from hololinked.core.exceptions import BreakLoop
from hololinked.server.zmq import brokers
from hololinked.server.zmq.brokers import AsyncZMQClient, AsyncZMQServer, SyncZMQClient
from hololinked.server.zmq.message import (
    CONTRACT_VERSION,
    EXIT,
    HANDSHAKE,
    RequestHeader,
    RequestMessage,
    ResponseHeader,
    ResponseMessage,
)
from hololinked.utils import get_current_async_loop, uuid_hex


@pytest.fixture(scope="module")
def server_id() -> str:
    return f"test-version-server-{uuid_hex()}"


@pytest.fixture(scope="module")
def client_id() -> str:
    return f"test-version-client-{uuid_hex()}"


@pytest.fixture(scope="module")
def server(server_id: str) -> AsyncZMQServer:
    return AsyncZMQServer(id=server_id)


@pytest.fixture(scope="module")
def client(server_id: str, client_id: str) -> Generator[SyncZMQClient, None, None]:
    client = SyncZMQClient(id=client_id, server_id=server_id, handshake=False)
    yield client
    client.exit()


def run_zmq_server(server: AsyncZMQServer, done_queue: multiprocessing.Queue) -> None:
    event_loop = get_current_async_loop()

    async def run():
        while True:
            try:
                messages = await server.async_recv_requests()
                for message in messages:
                    if message.type == EXIT:
                        server.exit()
                        break
                await asyncio.sleep(0.01)
            except BreakLoop:
                break

    event_loop.run_until_complete(run())
    event_loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(event_loop)))
    done_queue.put(True)


@pytest.fixture(scope="module", autouse=True)
def start_server(server: AsyncZMQServer, client: SyncZMQClient, server_id: str, client_id: str):
    done_queue = multiprocessing.Queue()
    thread = threading.Thread(target=run_zmq_server, args=(server, done_queue), daemon=True)
    thread.start()
    yield thread
    exit_message = RequestMessage.craft_with_message_type(
        receiver_id=server_id,
        sender_id=client_id,
        message_type=EXIT,
    )
    client.socket.send_multipart(exit_message.byte_array)
    if done_queue.get(timeout=3):
        thread.join()


def test_01_request_header_has_timestamp_version_and_authorization(server_id: str, client_id: str):
    before = time.time_ns() // 1000
    message = RequestMessage.craft_with_message_type(sender_id=client_id, receiver_id=server_id)
    after = time.time_ns() // 1000

    header = RequestHeader(**Serializers.json.loads(message.byte_array[2]))
    assert isinstance(header.timestamp, int)
    assert before <= header.timestamp <= after
    assert header.version == CONTRACT_VERSION
    assert header.authorization == ""


def test_02_response_header_has_timestamp_version_and_authorization(server_id: str, client_id: str):
    request = RequestMessage.craft_with_message_type(sender_id=client_id, receiver_id=server_id)
    before = time.time_ns() // 1000
    response = ResponseMessage.craft_reply_from_request(request)
    after = time.time_ns() // 1000

    header = ResponseHeader(**Serializers.json.loads(response.byte_array[2]))
    assert isinstance(header.timestamp, int)
    assert before <= header.timestamp <= after
    assert header.version == CONTRACT_VERSION
    assert header.authorization == ""


def test_03_handshake_with_matching_version(client: SyncZMQClient):
    client.handshake(timeout=5000)
    assert client._monitor_socket is not None


def test_04_handshake_with_mismatching_version_is_refused_instantly(
    client: SyncZMQClient,
    monkeypatch: pytest.MonkeyPatch,
):
    # server and client share this module, so the server expects v2 while the client still sends v1
    monkeypatch.setattr(brokers, "CONTRACT_VERSION", "v2")
    start = time.monotonic()
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch") as excinfo:
        client.handshake(timeout=5000)
    assert time.monotonic() - start < 3
    # the exception was raised on the server and mapped on the client, server traceback is in the notes
    assert any("_handshake" in note for note in excinfo.value.__notes__)


def test_05_client_refuses_server_with_mismatching_version(client: SyncZMQClient, server_id: str, client_id: str):
    request = RequestMessage.craft_with_message_type(sender_id=client_id, receiver_id=server_id)
    response = ResponseMessage.craft_with_message_type(request, HANDSHAKE)
    response._header.version = "v2"
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch"):
        client.verify_handshake_response(response, {request.id})


def test_06_handshake_works_again_after_refusal(client: SyncZMQClient):
    client.handshake(timeout=5000)


@pytest.fixture
async def async_client(server_id: str) -> AsyncGenerator[AsyncZMQClient, None]:
    async_client = AsyncZMQClient(id=f"test-version-async-client-{uuid_hex()}", server_id=server_id, handshake=False)
    yield async_client
    async_client.exit()
    # monitor socket address is derived from the socket and may still be held for a moment after close
    await asyncio.sleep(0.2)


async def test_07_async_client_handshake_with_matching_version(async_client: AsyncZMQClient):
    await async_client._handshake(timeout=5000)
    assert async_client._handshake_event.is_set()


async def test_08_async_client_handshake_with_mismatching_version_is_refused_instantly(
    async_client: AsyncZMQClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(brokers, "CONTRACT_VERSION", "v2")
    start = time.monotonic()
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch") as excinfo:
        await async_client._handshake(timeout=5000)
    assert time.monotonic() - start < 3
    assert any("_handshake" in note for note in excinfo.value.__notes__)
    assert not async_client._handshake_event.is_set()
