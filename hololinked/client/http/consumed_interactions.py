"""
Classes that contain the client logic for the HTTP protocol.
"""

import asyncio
import contextlib
import threading

from copy import deepcopy
from typing import Any, AsyncIterator, Callable, Iterator

import httpcore
import httpx
import structlog

from ...constants import Operations
from ...serializers import Serializers
from ...td.forms import Form
from ...td.interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    PropertyAffordance,
)
from ..abstractions import (
    SSE,
    ConsumedThingAction,
    ConsumedThingEvent,
    ConsumedThingProperty,
    raise_local_exception,
)


class HTTPConsumedAffordanceMixin:
    # Mixin class for HTTP consumed affordances

    def __init__(
        self,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
    ) -> None:
        """
        Parameters
        ----------
        invokation_timeout: int
            timeout for invokation of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        execution_timeout: int
            timeout for execution of an operation, other timeouts are specified while creating the client
            in `ClientFactory`
        sync_client: httpx.Client
            synchronous HTTP client
        async_client: httpx.AsyncClient
            asynchronous HTTP client
        """
        super().__init__()
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._sync_http_client = sync_client
        self._async_http_client = async_client

        from .. import ObjectProxy  # noqa: F401

        self.owner_inst: ObjectProxy

    def get_body_from_response(
        self,
        response: httpx.Response,
        form: Form,
        raise_exception: bool = True,
    ) -> Any:
        """
        Extracts and deserializes the body from an HTTP response.
        Only 200 to 300 status codes, and 304 are considered successful.
        Other response codes raise an error or return None.

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
        Merge authentication headers into the base headers. The security scheme must be available on the owner object.

        Parameters
        ----------
        base: dict[str, str]
            The base headers to merge into
        """
        headers = base or {}

        if not self.owner_inst or self.owner_inst._security is None:
            return headers
        if not any(key.lower() == self.owner_inst._security.http_header_name.lower() for key in headers.keys()):
            headers[self.owner_inst._security.http_header_name] = self.owner_inst._security.http_header

        return headers

    def create_http_request(self, form: Form, default_method: str, body: bytes | None = None) -> httpx.Request:
        """
        Creates a HTTP request object from the given form and body. Adds authentication headers if available.

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

    def read_reply(self, form: Form, message_id: str, timeout: float = None) -> Any:
        """
        Read the reply for a non-blocking action

        Parameters
        ----------
        form: Form
            The form to use for reading the reply
        message_id: str
            The message ID of the no-block request previously made
        timeout: float
            The timeout for waiting for the reply

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


class HTTPAction(ConsumedThingAction, HTTPConsumedAffordanceMixin):
    # An HTTP action, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        owner_inst: Any = None,
        logger: structlog.stdlib.BoundLogger = None,
    ) -> None:
        """
        Parameters
        ----------
        resource: ActionAffordance
            A dataclass instance representing the action to consume
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
        ConsumedThingAction.__init__(self=self, resource=resource, owner_inst=owner_inst, logger=logger)
        HTTPConsumedAffordanceMixin.__init__(
            self=self,
            sync_client=sync_client,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )

    async def async_call(self, *args, **kwargs):
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

    def __call__(self, *args, **kwargs):
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

    def oneway(self, *args, **kwargs):
        """Invoke the action without waiting for a response."""
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
        return None

    def noblock(self, *args, **kwargs) -> str:
        """Invoke the action in non-blocking mode."""
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

    def read_reply(self, message_id, timeout=None):
        form = deepcopy(self.resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPProperty(ConsumedThingProperty, HTTPConsumedAffordanceMixin):
    # An HTTP property, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: ActionAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        owner_inst: Any = None,
        logger: structlog.stdlib.BoundLogger = None,
    ) -> None:
        """
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
        self._read_reply_op_map = dict()

    def get(self) -> Any:
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        http_request = self.create_http_request(form, "GET", None)
        response = self._sync_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    def set(self, value: Any) -> None:
        """Synchronous set of the property value."""
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
        return None

    async def async_get(self) -> Any:
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        http_request = self.create_http_request(form, "GET", b"")
        response = await self._async_http_client.send(http_request)
        return self.get_body_from_response(response, form)

    async def async_set(self, value: Any) -> None:
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
        return None

    def oneway_set(self, value: Any) -> None:
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
        return None

    def noblock_get(self) -> str:
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

    def noblock_set(self, value) -> str:
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

    def read_reply(self, message_id, timeout=None) -> Any:
        form = deepcopy(self.resource.retrieve_form(op=self._read_reply_op_map.get(message_id, "readproperty")))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class HTTPEvent(ConsumedThingEvent, HTTPConsumedAffordanceMixin):
    # An HTTP event, both sync and async,
    # please dont add classdoc

    def __init__(
        self,
        resource: EventAffordance | PropertyAffordance,
        sync_client: httpx.Client = None,
        async_client: httpx.AsyncClient = None,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        owner_inst: Any = None,
        logger: structlog.stdlib.BoundLogger = None,
    ) -> None:
        """
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

    def listen(self, form: Form, callbacks: list[Callable], concurrent: bool = False, deserialize: bool = True) -> None:
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
                    except Exception as ex:
                        self.logger.error(f"Error processing SSE event: {ex}")
        except (httpx.ReadError, httpcore.ReadError):
            pass

    async def async_listen(
        self,
        form: Form,
        callbacks: list[Callable],
        concurrent: bool = False,
        deserialize: bool = True,
    ) -> None:
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        callback_id = asyncio.current_task().get_name()

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
        """iterate lines from an httpx streaming response, but stop immediately when `stop` is set"""
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
        """decode a single line of an SSE stream into the given SSE event_data object"""
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

    def unsubscribe(self) -> None:
        """Unsubscribe from the event."""
        for callback_id, (subscribed, obj, resp) in list(self._subscribed.items()):
            obj.set()
        return super().unsubscribe()


__all__ = [HTTPProperty.__name__, HTTPAction.__name__, HTTPEvent.__name__]
