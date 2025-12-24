import asyncio
import multiprocessing
import threading

from dataclasses import dataclass
from typing import Generator

import pytest

from hololinked.core.exceptions import BreakLoop
from hololinked.core.zmq.brokers import (
    AsyncZMQClient,
    AsyncZMQServer,
    MessageMappedZMQClientPool,
    SyncZMQClient,
)
from hololinked.core.zmq.message import (
    ERROR,
    EXIT,
    HANDSHAKE,
    INVALID_MESSAGE,
    REPLY,
    TIMEOUT,
    RequestMessage,
    ResponseMessage,
    SerializableData,
)
from hololinked.utils import get_current_async_loop, uuid_hex


try:
    from .conftest import AppIDs as MessageAppIDs
    from .test_01_message import validate_response_message
except ImportError:
    from conftest import AppIDs as MessageAppIDs
    from test_01_message import validate_response_message


@dataclass
class AppIDs:
    """
    Application related IDs generally used by end-user,
    like server, client, and thing IDs.
    """

    server_id: str
    """RPC server ID"""
    thing_id: str
    """A thing ID"""
    sync_client_id: str
    """A synchronous client ID"""
    async_client_id: str
    """An asynchronous client ID"""
    msg_mapped_async_client_id: str
    """A message-mapped asynchronous client ID"""


@pytest.fixture(scope="module")
def app_ids() -> AppIDs:
    """Generate unique test IDs for server, client, and thing for each test"""
    return AppIDs(
        server_id=f"test-server-{uuid_hex()}",
        thing_id=f"test-thing-{uuid_hex()}",
        sync_client_id=f"test-sync-client-{uuid_hex()}",
        async_client_id=f"test-async-client-{uuid_hex()}",
        msg_mapped_async_client_id=f"test-mapped-async-client-{uuid_hex()}",
    )


@pytest.fixture(scope="module")
def server(app_ids: AppIDs) -> Generator[AsyncZMQServer, None, None]:
    server = AsyncZMQServer(id=app_ids.server_id)
    yield server
    # exit written in thread
    # server.exit()


@pytest.fixture(scope="module")
def sync_client(app_ids: AppIDs) -> Generator[SyncZMQClient, None, None]:
    client = SyncZMQClient(id=app_ids.sync_client_id, server_id=app_ids.server_id, handshake=False)
    yield client
    client.exit()


@pytest.fixture(scope="module")
def async_client(app_ids: AppIDs) -> Generator[AsyncZMQClient, None, None]:
    client = AsyncZMQClient(id=app_ids.async_client_id, server_id=app_ids.server_id, handshake=False)
    yield client
    client.exit()


@pytest.fixture(scope="module")
def message_mapped_client(app_ids: AppIDs) -> Generator[MessageMappedZMQClientPool, None, None]:
    client = MessageMappedZMQClientPool(
        id="client-pool",
        client_ids=[app_ids.msg_mapped_async_client_id],
        server_ids=[app_ids.server_id],
        handshake=False,
    )
    client._client_to_thing_map[app_ids.msg_mapped_async_client_id] = app_ids.thing_id
    client._thing_to_client_map[app_ids.thing_id] = app_ids.msg_mapped_async_client_id
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
    if done_queue:
        done_queue.put(True)


@pytest.fixture(scope="module", autouse=True)
def start_server(server: AsyncZMQServer, sync_client: SyncZMQClient, app_ids: AppIDs):
    done_queue = multiprocessing.Queue()
    thread = threading.Thread(target=run_zmq_server, args=(server, done_queue), daemon=True)
    thread.start()
    yield thread
    request_message = RequestMessage.craft_with_message_type(
        receiver_id=app_ids.server_id,
        sender_id=app_ids.sync_client_id,
        message_type=EXIT,
    )
    sync_client.socket.send_multipart(request_message.byte_array)
    done = done_queue.get(timeout=3)
    if done:
        thread.join()
    else:
        print("Server did not properly process exit request")


def test_01_01_sync_client_handshake_complete(sync_client: SyncZMQClient):
    sync_client.handshake()
    assert sync_client._monitor_socket is not None
    assert sync_client._monitor_socket in sync_client.poller


async def test_01_02_sync_client_basic_message_contract_types(
    sync_client: SyncZMQClient,
    server: AsyncZMQServer,
    app_ids: AppIDs,
) -> None:
    active_app_ids = MessageAppIDs(
        server_id=app_ids.server_id, thing_id=app_ids.thing_id, client_id=app_ids.sync_client_id
    )
    request_message = RequestMessage.craft_from_arguments(
        receiver_id=app_ids.server_id,
        sender_id=app_ids.sync_client_id,
        thing_id=app_ids.thing_id,
        objekt="some_prop",
        operation="readproperty",
    )

    await server._handle_timeout(request_message, timeout_type="execution")
    await server._handle_invalid_message(request_message, SerializableData(Exception("test")))
    await server._handshake(request_message)
    await server._handle_error_message(request_message, Exception("test"))
    await server.async_send_response(request_message)
    await server.async_send_response_with_message_type(request_message, ERROR, SerializableData(Exception("test")))

    msg = sync_client.recv_response(request_message.id)
    assert msg.type == TIMEOUT
    validate_response_message(msg, app_ids=active_app_ids)

    msg = sync_client.recv_response(request_message.id)
    assert msg.type == INVALID_MESSAGE
    validate_response_message(msg, app_ids=active_app_ids)

    msg = sync_client.socket.recv_multipart()
    response_message = ResponseMessage(msg)
    assert response_message.type == HANDSHAKE
    validate_response_message(response_message, app_ids=active_app_ids)

    msg = sync_client.recv_response(request_message.id)
    assert msg.type == ERROR
    validate_response_message(msg, app_ids=active_app_ids)

    msg = sync_client.recv_response(request_message.id)
    assert msg.type == REPLY
    validate_response_message(msg, app_ids=active_app_ids)

    msg = sync_client.recv_response(request_message.id)
    assert msg.type == ERROR
    validate_response_message(msg, app_ids=active_app_ids)
    sync_client.handshake()


async def test_01_03_sync_client_polling(sync_client: SyncZMQClient, server: AsyncZMQServer):
    done = asyncio.Future()

    async def verify_poll_stopped():
        await server.poll_requests()
        server.poll_timeout = 1000
        await server.poll_requests()
        done.set_result(True)

    async def stop_poll():
        await asyncio.sleep(0.1)
        server.stop_polling()
        await asyncio.sleep(0.1)
        server.stop_polling()

    await asyncio.gather(verify_poll_stopped(), stop_poll())
    await done
    assert server.poll_timeout == 1000
    sync_client.handshake()


async def test_async_client_handshake_complete(async_client: AsyncZMQClient):
    async_client.handshake()
    await async_client.handshake_complete()
    assert async_client._monitor_socket is not None
    assert async_client._monitor_socket in async_client.poller


async def test_02_01_async_client_message_contract_types(
    async_client: AsyncZMQClient,
    server: AsyncZMQServer,
    app_ids: AppIDs,
) -> None:
    active_app_ids = MessageAppIDs(
        server_id=app_ids.server_id,
        thing_id=app_ids.thing_id,
        client_id=app_ids.async_client_id,
    )

    request_message = RequestMessage.craft_from_arguments(
        receiver_id=app_ids.server_id,
        sender_id=app_ids.async_client_id,
        thing_id=app_ids.thing_id,
        objekt="some_prop",
        operation="readproperty",
    )

    await server._handle_timeout(request_message, timeout_type="invokation")
    await server._handle_invalid_message(request_message, SerializableData(Exception("test1")))
    await server._handshake(request_message)
    await server._handle_error_message(request_message, Exception("test2"))
    await server.async_send_response(request_message)
    await server.async_send_response_with_message_type(request_message, ERROR, SerializableData(Exception("test3")))

    msg = await async_client.async_recv_response(request_message.id)
    assert msg.type == TIMEOUT
    validate_response_message(msg, app_ids=active_app_ids)

    msg = await async_client.async_recv_response(request_message.id)
    assert msg.type == INVALID_MESSAGE
    validate_response_message(msg, app_ids=active_app_ids)

    msg = await async_client.socket.recv_multipart()
    response_message = ResponseMessage(msg)
    assert response_message.type == HANDSHAKE
    validate_response_message(response_message, app_ids=active_app_ids)

    msg = await async_client.async_recv_response(request_message.id)
    assert msg.type == ERROR
    validate_response_message(msg, app_ids=active_app_ids)

    msg = await async_client.async_recv_response(request_message.id)
    assert msg.type == REPLY
    validate_response_message(msg, app_ids=active_app_ids)

    msg = await async_client.async_recv_response(request_message.id)
    assert msg.type == ERROR
    validate_response_message(msg, app_ids=active_app_ids)


async def test_03_01_mapped_handshake_complete(message_mapped_client: MessageMappedZMQClientPool):
    message_mapped_client.handshake()
    await message_mapped_client.handshake_complete()
    for client in message_mapped_client.pool.values():
        assert client._monitor_socket is not None
        assert client._monitor_socket in message_mapped_client.poller


async def test_mapped_message_contract_types(
    message_mapped_client: MessageMappedZMQClientPool,
    server: AsyncZMQServer,
    app_ids: AppIDs,
) -> None:
    active_app_ids = MessageAppIDs(
        server_id=app_ids.server_id,
        thing_id=app_ids.thing_id,
        client_id=app_ids.msg_mapped_async_client_id,
    )
    request_message = RequestMessage.craft_from_arguments(
        receiver_id=app_ids.server_id,
        sender_id=app_ids.msg_mapped_async_client_id,
        thing_id=app_ids.thing_id,
        objekt="some_prop",
        operation="readproperty",
    )

    message_mapped_client.start_polling()

    message_mapped_client.events_map[request_message.id] = message_mapped_client.event_pool.pop()
    await server._handle_timeout(request_message, timeout_type="invokation")
    msg = await message_mapped_client.async_recv_response(app_ids.thing_id, request_message.id)
    assert msg.type == TIMEOUT
    validate_response_message(msg, app_ids=active_app_ids)

    message_mapped_client.events_map[request_message.id] = message_mapped_client.event_pool.pop()
    await server._handle_invalid_message(request_message, SerializableData(Exception("test")))
    msg = await message_mapped_client.async_recv_response(app_ids.thing_id, request_message.id)
    assert msg.type == INVALID_MESSAGE
    validate_response_message(msg, app_ids=active_app_ids)

    message_mapped_client.events_map[request_message.id] = message_mapped_client.event_pool.pop()
    await server._handshake(request_message)
    msg = await message_mapped_client.pool[app_ids.msg_mapped_async_client_id].socket.recv_multipart()
    response_message = ResponseMessage(msg)
    assert response_message.type == HANDSHAKE
    validate_response_message(response_message, app_ids=active_app_ids)

    message_mapped_client.events_map[request_message.id] = message_mapped_client.event_pool.pop()
    await server.async_send_response(request_message)
    msg = await message_mapped_client.async_recv_response(app_ids.thing_id, request_message.id)
    assert msg.type == REPLY
    validate_response_message(msg, app_ids=active_app_ids)

    message_mapped_client.events_map[request_message.id] = message_mapped_client.event_pool.pop()
    await server.async_send_response_with_message_type(request_message, ERROR, SerializableData(Exception("test")))
    msg = await message_mapped_client.async_recv_response(app_ids.thing_id, request_message.id)
    assert msg.type == ERROR
    validate_response_message(msg, app_ids=active_app_ids)

    message_mapped_client.stop_polling()


async def test_03_02_mapped_verify_polling(message_mapped_client: MessageMappedZMQClientPool):
    done = asyncio.Future()

    async def verify_poll_stopped():
        await message_mapped_client.poll_responses()
        message_mapped_client.poll_timeout = 1000
        await message_mapped_client.poll_responses()
        done.set_result(True)

    async def stop_poll():
        await asyncio.sleep(0.1)
        message_mapped_client.stop_polling()
        await asyncio.sleep(0.1)
        message_mapped_client.stop_polling()

    await asyncio.gather(verify_poll_stopped(), stop_poll())
    await done
    assert message_mapped_client.poll_timeout == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
