"""
Classes that contain the client logic for the HTTP protocol.
"""

import asyncio
import contextlib
import threading
import httpcore
import httpx
from typing import Any, AsyncIterator, Callable, Iterator
from copy import deepcopy

from ...constants import Operations
from ..abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty, raise_local_exception, SSE
from ...td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ...td.forms import Form
from ...serializers import Serializers


class HTTPConsumedAffordanceMixin:
    """Implementation of the protocol client interface for the HTTP protocol."""

    def __init__(
        self,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
    ) -> None:
        super().__init__()
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._sync_http_client = sync_client
        self._async_http_client = async_client

    def get_body_from_response(
        self,
        response: httpx.Response,
        form: Form,
        raise_exception: bool = True,
    ) -> Any:
        if response.status_code >= 200 and response.status_code < 300:
            body = response.content
            if not body:
                return
            serializer = Serializers.content_types.get(form.contentType or "application/json")
            if serializer is None:
                raise ValueError(f"Unsupported content type: {form.contentType}")
            body = serializer.loads(body)
            if isinstance(body, dict) and "exception" in body and raise_exception:
                raise_local_exception(body)
            return body
        response.raise_for_status()

    def _merge_auth_headers(self, base: dict | None = None):
        headers = dict(base or {})

        # Avoid truthiness on ObjectProxy
        owner = getattr(self, "_owner_inst", None)
        if owner is None:
            owner = getattr(self, "owner", None)

        auth = getattr(owner, "_auth_header", None) if owner is not None else None

        # Normalize present header names (case-insensitive)
        present = {k.lower() for k in headers}

        if auth:
            if isinstance(auth, dict):
                # Merge key-by-key if caller stored a header dict
                for k, v in auth.items():
                    if k.lower() not in present:
                        headers[k] = v
            elif isinstance(auth, str):
                # Caller stored just the value: "Basic abcd=="
                if "authorization" not in present:
                    headers["Authorization"] = auth
            else:
                # Ignore unexpected types instead of crashing
                pass

        return headers

    def create_http_request(self, form: Form, default_method: str, body: bytes | None = None) -> httpx.Request:
        """Creates an HTTP request for the given form and body."""
        return httpx.Request(
            method=form.htv_methodName or default_method,
            url=form.href,
            content=body,
            headers=self._merge_auth_headers({"Content-Type": form.contentType or "application/json"}),
        )

    def read_reply(self, form: Form, message_id: str, timeout=None):
        """Read the reply for a non-blocking action."""
        form.href = f"{form.href}?messageID={message_id}&timeout={timeout or self._invokation_timeout}"
        form.htv_methodName = "GET"
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)


class HTTPAction(ConsumedThingAction, HTTPConsumedAffordanceMixin):
    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        **kwargs,
    ) -> None:
        ConsumedThingAction.__init__(self=self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
            self=self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )

    async def async_call(self, *args, **kwargs):
        form = self._resource.retrieve_form(Operations.invokeaction, None)
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        response = await self._async_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def __call__(self, *args, **kwargs):
        form = self._resource.retrieve_form(Operations.invokeaction, None)
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def oneway(self, *args, **kwargs):
        """Invoke the action without waiting for a response."""
        form = deepcopy(self._resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        form.href = f"{form.href}?oneway=true"
        http_request = self.create_http_request(form, "POST", body)
        response = self._sync_http_client.send(http_request)
        # just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form)
        return None

    def noblock(self, *args, **kwargs) -> str:
        """Invoke the action in non-blocking mode."""
        form = deepcopy(self._resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        form.href = f"{form.href}?noblock=true"
        http_request = self.create_http_request(form, "POST", body)
        response = self._sync_http_client.send(http_request)
        if response.headers.get("X-Message-ID", None) is None:
            raise ValueError("The server did not return a message ID for the non-blocking action.")
        message_id = response.headers["X-Message-ID"]
        self._owner_inst._noblock_messages[message_id] = self
        return message_id

    def read_reply(self, message_id, timeout=None):
        form = deepcopy(self._resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPProperty(ConsumedThingProperty, HTTPConsumedAffordanceMixin):
    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        **kwargs,
    ) -> None:
        ConsumedThingProperty.__init__(self=self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
            self=self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )
        self._read_reply_op_map = dict()

    async def async_set(self, value: Any) -> None:
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        response = await self._async_http_client.send(http_request)
        # Just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form)
        return None

    def set(self, value: Any) -> None:
        """Synchronous set of the property value."""
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        response = self._sync_http_client.send(http_request)
        self.get_body_from_response(response, form)
        # Just to ensure the request was successful, no body expected.
        return None

    async def async_get(self):
        form = self._resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", b"")
        response = await self._async_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def get(self):
        form = self._resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def oneway_set(self, value: Any) -> None:
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = deepcopy(self._resource.retrieve_form(Operations.writeproperty, None))
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        form.href = f"{form.href}?oneway=true"
        http_request = self.create_http_request(form, "PUT", body)
        response = self._sync_http_client.send(http_request)
        # Just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form, raise_exception=False)
        return None

    def noblock_get(self) -> str:
        form = deepcopy(self._resource.retrieve_form(Operations.readproperty, None))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        form.href = f"{form.href}?noblock=true"
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        if response.headers.get("X-Message-ID", None) is None:
            raise ValueError("The server did not return a message ID for the non-blocking property read.")
        message_id = response.headers["X-Message-ID"]
        self._read_reply_op_map[message_id] = "readproperty"
        self._owner_inst._noblock_messages[message_id] = self
        return message_id

    def noblock_set(self, value):
        form = deepcopy(self._resource.retrieve_form(Operations.writeproperty, None))
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        form.href = f"{form.href}?noblock=true"
        http_request = self.create_http_request(form, "PUT", body)
        response = self._sync_http_client.send(http_request)
        if response.headers.get("X-Message-ID", None) is None:
            raise ValueError(
                "The server did not return a message ID for the non-blocking property write. "
                + f" response headers: {response.headers}, code {response.status_code}"
            )
        message_id = response.headers["X-Message-ID"]
        self._owner_inst._noblock_messages[message_id] = self
        self._read_reply_op_map[message_id] = "writeproperty"
        return message_id

    def read_reply(self, message_id, timeout=None):
        form = deepcopy(self._resource.retrieve_form(op=self._read_reply_op_map.get(message_id, "readproperty")))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPEvent(ConsumedThingEvent, HTTPConsumedAffordanceMixin):
    def __init__(
        self,
        resource: EventAffordance | PropertyAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        **kwargs,
    ) -> None:
        ConsumedThingEvent.__init__(self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
            self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )

    def listen(self, form: Form, callbacks: list[Callable], concurrent: bool = False, deserialize: bool = True):
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        callback_id = threading.get_ident()

        try:
            with self._sync_http_client.stream(
                method="GET", url=form.href, headers=self._merge_auth_headers({"Accept": "text/event-stream"})
            ) as resp:
                resp.raise_for_status()
                interrupting_event = threading.Event()
                self._subscribed[callback_id] = (True, interrupting_event, resp)
                event_data = SSE()
                for line in self.iter_lines_interruptible(resp, interrupting_event):
                    try:
                        if not self._subscribed.get(callback_id, (False, None))[0] or interrupting_event.is_set():
                            # when value is popped, consider unsubscribed
                            break

                        if line == "":
                            if not event_data.data:
                                self.logger.warning(f"Received an invalid SSE event: {line}")
                                continue
                            if deserialize:
                                event_data.data = serializer.loads(event_data.data.encode("utf-8"))
                            self.schedule_callbacks(callbacks, event_data, concurrent)
                            event_data = SSE()
                            continue

                        self.decode_chunk(line, event_data)
                    except Exception as ex:
                        self.logger.error(f"Error processing SSE event: {ex}")
        except (httpx.ReadError, httpcore.ReadError):
            pass

    async def async_listen(
        self, form: Form, callbacks: list[Callable], concurrent: bool = False, deserialize: bool = True
    ):
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        callback_id = asyncio.current_task().get_name()

        try:
            async with self._async_http_client.stream(
                method="GET", url=form.href, headers=self._merge_auth_headers({"Accept": "text/event-stream"})
            ) as resp:
                resp.raise_for_status()
                interrupting_event = asyncio.Event()
                self._subscribed[callback_id] = (True, interrupting_event, resp)
                event_data = SSE()
                async for line in self.aiter_lines_interruptible(resp, interrupting_event, resp):
                    try:
                        if not self._subscribed.get(callback_id, (False, None))[0] or interrupting_event.is_set():
                            # when value is popped, consider unsubscribed
                            break

                        if line == "":
                            if not event_data.data:
                                self.logger.warning(f"Received an invalid SSE event: {line}")
                                continue
                            if deserialize:
                                event_data.data = serializer.loads(event_data.data.encode("utf-8"))
                            await self.async_schedule_callbacks(callbacks, event_data, concurrent)
                            event_data = SSE()
                            continue

                        self.decode_chunk(line, event_data)
                    except Exception as ex:
                        self.logger.error(f"Error processing SSE event: {ex}")
        except (httpx.ReadError, httpcore.ReadError):
            pass

    async def aiter_lines_interruptible(self, resp: httpx.Response, stop: asyncio.Event) -> AsyncIterator[str]:
        """
        Yield lines from an httpx streaming response, but stop immediately when `stop` is set.
        Works by racing the next __anext__() call against stop.wait().
        """
        it = resp.aiter_lines()
        while not stop.is_set():
            try:
                next_line = asyncio.create_task(it.__anext__())
                stopper = asyncio.create_task(stop.wait())
                done, pending = await asyncio.wait({next_line, stopper}, return_when=asyncio.FIRST_COMPLETED)

                if stopper in done:
                    next_line.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await next_line
                    break

                stopper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stopper
                yield next_line.result()

            except (httpx.ReadTimeout, httpcore.ReadTimeout):
                continue

            except StopAsyncIteration:
                # remote closed the stream
                return

    def iter_lines_interruptible(self, resp: httpx.Response, stop: threading.Event) -> Iterator[str]:
        it = resp.iter_lines()
        # Using a dedicated stream scope inside the thread
        while not stop.is_set():
            try:
                next_line = next(it)
            except (httpx.ReadTimeout, httpcore.ReadTimeout):
                continue
            except StopIteration:
                break
            yield next_line

    def decode_chunk(self, line: str, event_data: "SSE") -> None:
        if line is None or line.startswith(":"):  # comment/heartbeat
            return

        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]  # spec: single leading space is stripped

        if field == "event":
            event_data.event = value or "message"
        elif field == "data":
            event_data.data += value
        elif field == "id":
            event_data.id = value or None
        elif field == "retry":
            try:
                event_data.retry = int(value)
            except ValueError:
                self.logger.warning(f"Invalid retry value: {value}")

    def unsubscribe(self):
        """Unsubscribe from the event."""
        for callback_id, (subscribed, obj, resp) in list(self._subscribed.items()):
            obj.set()
        return super().unsubscribe()


__all__ = [HTTPProperty.__name__, HTTPAction.__name__, HTTPEvent.__name__]
