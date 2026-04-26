"""Concrete implementation of HTTP based consumed property, action or event."""

import asyncio
import contextlib
import threading

from collections.abc import AsyncIterator, Callable, Iterator
from copy import deepcopy
from typing import Any

import httpcore
import httpx
import structlog

from hololinked.client.abstractions import (
    SSE,
    ConsumedThingAction,
    ConsumedThingEvent,
    ConsumedThingProperty,
)
from hololinked.client.exceptions import raise_local_exception
from hololinked.constants import Operations
from hololinked.serializers import Serializers
from hololinked.td.forms import Form
from hololinked.td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)


class HTTPConsumedAffordanceMixin:
    # Mixin class for HTTP consumed affordances

    __slots__ = [
        "__doc__",
        "__name__",
        "__qualname__",
        "_async_http_client",
        "_execution_timeout",
        "_invokation_timeout",
        "_sync_http_client",
        "logger",
        "owner_inst",
        "resource",
        "schema_validator",
    ]  # __slots__ dont support multiple inheritance

    def __init__(
        self,
        sync_client: httpx.Client,
        async_client: httpx.AsyncClient,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
    ) -> None:
        """
        Initialize the HTTP consumed affordance mixin.

        Parameters
        ----------
        sync_client: httpx.Client
            synchronous HTTP client
        async_client: httpx.AsyncClient
            asynchronous HTTP client
        invokation_timeout: int
            timeout for invokation of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        execution_timeout: int
            timeout for execution of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        """
        super().__init__()
        self._sync_http_client = sync_client
        self._async_http_client = async_client
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout

        from hololinked.client import ObjectProxy

        self.owner_inst: ObjectProxy

    def get_body_from_response(
        self,
        response: httpx.Response,
        form: Form,
        raise_exception: bool = True,
    ) -> Any:
        """
        Extract and deserialize the body from an HTTP response.

        Only 200 to 300 status codes, and 304 are considered successful.
        Other response codes raise an error or return None, whichever is appropriate.

        Parameters
        ----------
        response: httpx.Response
            The HTTP response object
        form: Form
            The form used for the request, needed to decide a fallback content type
        raise_exception: bool
            Whether to raise an exception if the response body contains an exception

        Returns
        -------
        Any
            The deserialized body of the response or None

        Raises
        ------
        ValueError
            If the content type of the response is not supported
        """
        if response.status_code >= 200 and response.status_code < 300 or response.status_code == 304:
            body = response.content
            if not body:
                return
            givenContentType = response.headers.get("Content-Type", None)
            serializer = Serializers.content_types.get(givenContentType or form.contentType or "application/json")
            if serializer is None:
                raise ValueError(f"Unsupported content type: {form.contentType}")
            body = serializer.loads(body)
            if isinstance(body, dict) and "exception" in body and raise_exception:
                raise_local_exception(body)
            return body
        response.raise_for_status()
        # return None

    def _merge_auth_headers(self, base: dict[str, str]) -> dict[str, str]:
        """
        Merge authentication headers into the base headers.

        The security scheme must be available on the owner object.

        Parameters
        ----------
        base: dict[str, str]
            The base headers to merge into

        Returns
        -------
        dict[str, str]
            The merged headers with authentication headers included if available
        """
        headers = base or {}

        if not self.owner_inst or self.owner_inst._security is None:
            return headers
        if not any(key.lower() == self.owner_inst._security.http_header_name.lower() for key in headers):
            headers[self.owner_inst._security.http_header_name] = self.owner_inst._security.http_header

        return headers

    def create_http_request(self, form: Form, default_method: str, body: bytes | None = None) -> httpx.Request:
        """
        Create a HTTP request object from the given form and body.

        Adds authentication headers if available.

        Parameters
        ----------
        form: Form
            The form to create the request for
        default_method: str
            The default HTTP method to use if not specified in the form
        body: bytes | None
            The body of the request

        Returns
        -------
        httpx.Request
            The created HTTP request object
        """
        return httpx.Request(
            method=form.htv_methodName or default_method,
            url=form.href,
            content=body,
            headers=self._merge_auth_headers({"Content-Type": form.contentType or "application/json"}),
        )

    def read_reply(self, form: Form, message_id: str, timeout: float | None = None) -> Any:
        """
        Read the reply for a non-blocking action.

        Parameters
        ----------
        form: Form
            The form to use for reading the reply
        message_id: str
            The message ID of the no-block request previously made
        timeout: float | None
            The timeout for waiting for the reply, defaults to the invokation timeout of the client if not specified

        Returns
        -------
        Any
            The deserialized body of the response or None
        """
        form.href = f"{form.href}?messageID={message_id}&timeout={timeout or self._invokation_timeout}"
        form.htv_methodName = "GET"
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)


class HTTPAction(ConsumedThingAction, HTTPConsumedAffordanceMixin):  # noqa: D101
    # An HTTP action, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: httpx.Client,
        async_client: httpx.AsyncClient,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
    ) -> None:
        """
        Initialize the HTTP consumed action.

        Parameters
        ----------
        resource: ActionAffordance
            A dataclass instance representing the action to consume
        sync_client: httpx.Client
            synchronous HTTP client
        async_client: httpx.AsyncClient
            asynchronous HTTP client
        logger: structlog.stdlib.BoundLogger
            Logger instance
        owner_inst: Any
            The parent object that owns this consumer
        invokation_timeout: int
            timeout for invokation of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        execution_timeout: int
            timeout for execution of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        """
        ConsumedThingAction.__init__(self=self, resource=resource, owner_inst=owner_inst, logger=logger)
        HTTPConsumedAffordanceMixin.__init__(
            self=self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )

    async def async_call(self, *args, **kwargs):  # noqa: D102
        form = self.resource.retrieve_form(Operations.invokeaction, None)
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        response = await self._async_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def __call__(self, *args, **kwargs):  # noqa: D102
        form = self.resource.retrieve_form(Operations.invokeaction, None)
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def oneway(self, *args, **kwargs):  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        form.href = f"{form.href}?oneway=true"
        http_request = self.create_http_request(form, "POST", body)
        response = self._sync_http_client.send(http_request)
        # just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form)

    def noblock(self, *args, **kwargs) -> str:  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
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
        self.owner_inst._noblock_messages[message_id] = self
        return message_id

    def read_reply(self, message_id, timeout=None):  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPProperty(ConsumedThingProperty, HTTPConsumedAffordanceMixin):  # noqa: D101
    # An HTTP property, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: PropertyAffordance,
        sync_client: httpx.Client,
        async_client: httpx.AsyncClient,
        logger: structlog.stdlib.BoundLogger,
        owner_inst: Any = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
    ) -> None:
        """
        Initialize the HTTP property consumer.

        Parameters
        ----------
        resource: PropertyAffordance
            A dataclass instance representing the property to consume
        sync_client: httpx.Client
            synchronous HTTP client
        async_client: httpx.AsyncClient
            asynchronous HTTP client
        invokation_timeout: int
            timeout for invokation of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        execution_timeout: int
            timeout for execution of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        owner_inst: Any
            The parent object that owns this consumer
        logger: structlog.stdlib.BoundLogger
            Logger instance
        """
        ConsumedThingProperty.__init__(self=self, resource=resource, owner_inst=owner_inst, logger=logger)
        HTTPConsumedAffordanceMixin.__init__(
            self=self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )
        self._read_reply_op_map = {}  # when a single property has multiple forms which can be invoked noblock

    def get(self) -> Any:  # noqa: D102
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def set(self, value: Any) -> None:  # noqa: D102
        if self.resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self.resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self.resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        response = self._sync_http_client.send(http_request)
        self.get_body_from_response(response, form)
        # Just to ensure the request was successful, no body expected.

    async def async_get(self) -> Any:  # noqa: D102
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        http_request = self.create_http_request(form, "GET", b"")
        response = await self._async_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    async def async_set(self, value: Any) -> None:  # noqa: D102
        if self.resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self.resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self.resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        response = await self._async_http_client.send(http_request)
        # Just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form)

    def oneway_set(self, value: Any) -> None:  # noqa: D102
        if self.resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = deepcopy(self.resource.retrieve_form(Operations.writeproperty, None))
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self.resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        form.href = f"{form.href}?oneway=true"
        http_request = self.create_http_request(form, "PUT", body)
        response = self._sync_http_client.send(http_request)
        # Just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form, raise_exception=False)

    def noblock_get(self) -> str:  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(Operations.readproperty, None))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        form.href = f"{form.href}?noblock=true"
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        if response.headers.get("X-Message-ID", None) is None:
            raise ValueError("The server did not return a message ID for the non-blocking property read.")
        message_id = response.headers["X-Message-ID"]
        self._read_reply_op_map[message_id] = "readproperty"
        self.owner_inst._noblock_messages[message_id] = self
        return message_id

    def noblock_set(self, value) -> str:  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(Operations.writeproperty, None))
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self.resource.name}")
        if self.resource.readOnly:
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
        self.owner_inst._noblock_messages[message_id] = self
        self._read_reply_op_map[message_id] = "writeproperty"
        return message_id

    def read_reply(self, message_id, timeout=None) -> Any:  # noqa: D102
        form = deepcopy(self.resource.retrieve_form(op=self._read_reply_op_map.get(message_id, "readproperty")))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPEvent(ConsumedThingEvent, HTTPConsumedAffordanceMixin):  # noqa: D101
    # An HTTP event, both sync and async,
    # please dont add classdoc

    def __init__(
        self,
        resource: EventAffordance | PropertyAffordance,
        sync_client: httpx.Client,
        async_client: httpx.AsyncClient,
        owner_inst: Any,
        logger: structlog.stdlib.BoundLogger,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
    ) -> None:
        """
        Initialize the HTTP event consumer.

        Parameters
        ----------
        resource: EventAffordance | PropertyAffordance
            A dataclass instance representing the observable property or event to consume
        sync_client: httpx.Client
            synchronous HTTP client
        async_client: httpx.AsyncClient
            asynchronous HTTP client
        invokation_timeout: int
            timeout for invokation of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        execution_timeout: int
            timeout for execution of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        owner_inst: Any
            The parent object that owns this consumer
        logger: structlog.stdlib.BoundLogger
            Logger instance
        """
        ConsumedThingEvent.__init__(self, resource=resource, owner_inst=owner_inst, logger=logger)
        HTTPConsumedAffordanceMixin.__init__(
            self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )

    def listen(  # noqa: D102
        self,
        form: Form,
        callbacks: list[Callable],
        concurrent: bool = True,
        deserialize: bool = True,
    ) -> None:
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        callback_id = threading.get_ident()

        try:
            with self._sync_http_client.stream(
                method="GET",
                url=form.href,
                headers=self._merge_auth_headers({"Accept": "text/event-stream"}),
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
                    except Exception as ex:  # noqa: BLE001
                        self.logger.error(f"Error processing SSE event: {ex}")
        except (httpx.ReadError, httpcore.ReadError):
            pass

    async def async_listen(  # noqa: D102
        self,
        form: Form,
        callbacks: list[Callable],
        concurrent: bool = True,
        deserialize: bool = True,
    ) -> None:
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        callback_id = asyncio.current_task().get_name()  # type: ignore

        try:
            async with self._async_http_client.stream(
                method="GET",
                url=form.href,
                headers=self._merge_auth_headers({"Accept": "text/event-stream"}),
            ) as resp:
                resp.raise_for_status()
                interrupting_event = asyncio.Event()
                self._subscribed[callback_id] = (True, interrupting_event, resp)
                event_data = SSE()
                async for line in self.aiter_lines_interruptible(resp, interrupting_event):
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
                    except Exception as ex:  # noqa: BLE001
                        self.logger.error(f"Error processing SSE event: {ex}")
        except (httpx.ReadError, httpcore.ReadError):
            pass

    async def aiter_lines_interruptible(self, resp: httpx.Response, stop: asyncio.Event) -> AsyncIterator[str]:
        """
        Yield lines from an httpx streaming response, but stop immediately when `stop` is set.

        Works by racing the next __anext__() call against stop.wait().

        Parameters
        ----------
        resp: httpx.Response
            The HTTP response object to read lines from
        stop: asyncio.Event
            The event to wait on for stopping the iteration

        Yields
        ------
        str
            The next line from the response, until stop is set or the stream ends
        """
        it = resp.aiter_lines()
        while not stop.is_set():
            try:
                next_line = asyncio.create_task(it.__anext__())  # type: ignore
                stopper = asyncio.create_task(stop.wait())
                done, _ = await asyncio.wait({next_line, stopper}, return_when=asyncio.FIRST_COMPLETED)

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
        """
        Iterate lines from an httpx streaming response, but stop immediately when `stop` is set.

        Parameters
        ----------
        resp: httpx.Response
            The HTTP response object to read lines from
        stop: threading.Event
            The event to wait on for stopping the iteration

        Yields
        ------
        str
            The next line from the response, until stop is set or the stream ends
        """
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
        """
        Decode a single line of an SSE stream into the given SSE event_data object.

        Parameters
        ----------
        line: str
            The line from the SSE stream to decode
        event_data: SSE
            The SSE event data object to populate
        """
        if line is None or line.startswith(":"):  # comment/heartbeat
            return

        field, _, value = line.partition(":")
        value = value.removeprefix(" ")  # spec: single leading space is stripped

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

    def unsubscribe(self) -> None:
        """Unsubscribe from the event."""
        for callback_id, (subscribed, obj, resp) in list(self._subscribed.items()):
            obj.set()
        return super().unsubscribe()


__all__ = [
    "HTTPAction",
    "HTTPEvent",
    "HTTPProperty",
]
