import asyncio
import multiprocessing
import threading
import time

from typing import AsyncGenerator, Generator

import pytest

from hololinked.core.exceptions import BreakLoop
from hololinked.server.zmq import brokers
from hololinked.server.zmq.brokers import AsyncZMQClient, AsyncZMQServer, SyncZMQClient
from hololinked.server.zmq.message import (
    ERROR,
    EXIT,
    HANDSHAKE,
    HANDSHAKE_ERROR,
    RequestMessage,
    ResponseMessage,
    SerializableData,
)
from hololinked.utils import format_exception_as_json, get_current_async_loop, uuid_hex


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
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch"):
        client.handshake(timeout=5000)
    assert time.monotonic() - start < 3


def test_05_client_refuses_server_with_mismatching_version(client: SyncZMQClient, server_id: str, client_id: str):
    request = RequestMessage.craft_with_message_type(sender_id=client_id, receiver_id=server_id)
    response = ResponseMessage.craft_with_message_type(request, HANDSHAKE)
    response._header.version = "v2"
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch"):
        client.verify_handshake_response(response)


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
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch"):
        await async_client._handshake(timeout=5000)
    assert time.monotonic() - start < 3
    assert not async_client._handshake_event.is_set()


def stale_error_for(server_id: str, client_id: str) -> ResponseMessage:
    request = RequestMessage.craft_with_message_type(
        sender_id=client_id, receiver_id=server_id, message_type="OPERATION"
    )
    return ResponseMessage.craft_with_message_type(
        request,
        ERROR,
        payload=SerializableData(
            dict(exception=format_exception_as_json(ValueError("error of an earlier request"))),
            content_type="application/json",
        ),
    )


async def test_09_async_client_ignores_stale_error_during_handshake():
    server_id, client_id = f"test-stale-server-{uuid_hex()}", f"test-stale-client-{uuid_hex()}"
    server = AsyncZMQServer(id=server_id)
    client = AsyncZMQClient(id=client_id, server_id=server_id, handshake=False)
    await asyncio.sleep(0.3)
    await server.socket.send_multipart(stale_error_for(server_id, client_id).byte_array)

    async def serve():
        while True:
            await server.async_recv_requests()
            await asyncio.sleep(0.01)

    task = asyncio.create_task(serve())
    start = time.monotonic()
    await client._handshake(timeout=5000)
    assert time.monotonic() - start < 3
    assert client._handshake_event.is_set()
    task.cancel()
    client.exit()
    server.exit()
    await asyncio.sleep(0.2)


def test_10_sync_client_ignores_stale_error_during_handshake():
    server_id, client_id = f"test-stale-server-{uuid_hex()}", f"test-stale-client-{uuid_hex()}"
    ready, stop = threading.Event(), threading.Event()
    client = SyncZMQClient(id=client_id, server_id=server_id, handshake=False)

    def run_server():
        loop = get_current_async_loop()
        server = AsyncZMQServer(id=server_id)

        async def run():
            await asyncio.sleep(0.3)
            await server.socket.send_multipart(stale_error_for(server_id, client_id).byte_array)
            ready.set()
            while not stop.is_set():
                await server.async_recv_requests()
                await asyncio.sleep(0.01)

        loop.run_until_complete(run())
        server.exit()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    assert ready.wait(timeout=3)
    start = time.monotonic()
    client.handshake(timeout=5000)
    assert time.monotonic() - start < 3
    assert client._monitor_socket is not None
    stop.set()
    thread.join(timeout=3)
    client.exit()


def test_11_server_refuses_mismatching_version_with_handshake_error(
    server_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    raw_client_id = f"test-raw-client-{uuid_hex()}"
    raw_client = SyncZMQClient(id=raw_client_id, server_id=server_id, handshake=False)
    monkeypatch.setattr(brokers, "CONTRACT_VERSION", "v2")
    request = RequestMessage.craft_with_message_type(sender_id=raw_client_id, receiver_id=server_id)
    # a ROUTER drops messages sent before the connection is up, so send again like a handshake does
    for _ in range(6):
        raw_client.socket.send_multipart(request.byte_array)
        if raw_client.poller.poll(500):
            break
    else:
        pytest.fail("server did not answer the handshake")
    response = ResponseMessage(raw_client.socket.recv_multipart())
    assert response.type == HANDSHAKE_ERROR
    assert response.id == request.id
    raw_client.exit()


def test_12_client_raises_on_handshake_error_and_ignores_plain_error(
    client: SyncZMQClient, server_id: str, client_id: str
):
    client.verify_handshake_response(stale_error_for(server_id, client_id))
    request = RequestMessage.craft_with_message_type(sender_id=client_id, receiver_id=server_id)
    refusal = ResponseMessage.craft_with_message_type(
        request,
        HANDSHAKE_ERROR,
        payload=SerializableData(
            dict(exception=format_exception_as_json(ConnectionRefusedError("contract version mismatch"))),
            content_type="application/json",
        ),
    )
    with pytest.raises(ConnectionRefusedError, match="contract version mismatch"):
        client.verify_handshake_response(refusal)
