"""
Classes that contain the client logic for the CoAP protocol.
"""

import asyncio

from copy import deepcopy
from typing import Any

import structlog

from aiocoap import Context, Message
from aiocoap.numbers.codes import Code
from aiocoap.options import OptionNumber, Options  # noqa: F401
from aiocoap.protocol import Request

from hololinked.client.abstractions import (
    ConsumedThingAction,
    ConsumedThingProperty,
    raise_local_exception,
)
from hololinked.client.coap.utils import (
    CoAPCodeToContentTypeStr,
    ContentTypeStrToCoAPCode,
)
from hololinked.constants import Operations
from hololinked.serializers import Serializers
from hololinked.td.forms import Form
from hololinked.td.interaction_affordance import ActionAffordance


class CoAPConsumedAffordanceMixin:
    # Mixin class for CoAP consumed affordances

    def __init__(
        self,
        invokation_timeout: int = 5,
        execution_timeout: int = 5,
        async_client: Context = None,
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
        async_client: Context
            asynchronous CoAP client
        """
        super().__init__()
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._async_coap_client = async_client

        from .. import ObjectProxy  # noqa: F401

        self.owner_inst: ObjectProxy

    def get_body_from_response(
        self,
        response: Request,
        form: Form,
        raise_exception: bool = True,
    ) -> Any:
        """
        Extracts and deserializes the body from an CoAP response.
        Only 200 to 300 status codes, and 304 are considered successful.
        Other response codes raise an error or return None.

        Parameters
        ----------
        response: Request
            The CoAP response object
        form: Form
            The form used for the request, needed to decide a fallback content type
        raise_exception: bool
            Whether to raise an exception if the response body contains an exception

        Returns
        -------
        Any
            The deserialized body of the response or None
        """
        code = response.code  # type: Code
        if not code.is_successful():
            raise ValueError(f"Received error response with code {code} and payload {response.payload}")
        elif code == Code.VALID or code == Code.DELETED or code == Code.CONTINUE or code == Code.CREATED:
            return None
        elif code == Code.CONTENT or code == Code.CHANGED:
            body = response.payload
            if not body:
                return
            body = self._deserialize_response(response, form)
            if isinstance(body, dict) and "exception" in body and raise_exception:
                raise_local_exception(body)
            return body
        elif code == Code.SERVICE_UNAVAILABLE:
            if response.body:
                body = self._deserialize_response(response, form)
                if isinstance(body, dict) and "exception" in body and raise_exception:
                    raise_local_exception(body)
            raise Exception(
                f"Server is unavailable to process the request{' , body: ' + str(body) if response.body else ''}"
            )
        elif code in Code._member_map_:
            raise Exception(f"Unexpected response code {Code[code]}")
        raise Exception(f"Unexpected response code {code}")

    def _deserialize_response(self, response: Request, form: Form) -> Any:
        """
        Deserialize the response body using the content type specified in the response or form.

        Parameters
        ----------
        response: Request
            The CoAP response object
        form: Form
            The form used for the request, needed to decide a fallback content type

        Returns
        -------
        Any
            The deserialized body of the response or None
        """
        body = response.payload
        if not body:
            return None
        opt = response.opt  # type: Options
        if CoAPCodeToContentTypeStr.supports(opt.content_format):
            givenContentType = CoAPCodeToContentTypeStr.get(opt.content_format)
        else:
            givenContentType = form.contentType or "application/json"
        serializer = Serializers.content_types.get(givenContentType)
        if serializer is None:
            raise ValueError(f"Unsupported content type: {form.contentType}")
        body = serializer.loads(body)
        return body

    def _credentials(self, base: dict[str, str]) -> dict[str, str]:
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
        if not any(key.lower() == self.owner_inst._security.coap_header_name.lower() for key in headers.keys()):
            headers[self.owner_inst._security.coap_header_name] = self.owner_inst._security.coap_header

        return headers

    def create_coap_request(self, form: Form, default_method: str, body: bytes | None = None) -> Message:
        """
        Creates a CoAP request object from the given form and body. Adds authentication headers if available.

        Parameters
        ----------
        form: Form
            The form to create the request for
        default_method: str
            The default CoAP method to use if not specified in the form
        body: bytes | None
            The body of the request

        Returns
        -------
        Message
            The created CoAP request object
        """
        if form.cov_method is not None:
            if form.cov_method in Code._member_map_:
                method = Code[form.cov_method]
            else:
                raise ValueError(f"Invalid CoAP method specified in form: {form.cov_method}")
        else:
            method = Code[default_method]
        if body is None:
            body = b""
        if form.contentType and not ContentTypeStrToCoAPCode.supports(form.contentType):
            raise ValueError(f"Unsupported content type: {form.contentType}")
        return Message(
            code=method,
            uri=form.href,
            payload=body,
            # add opts below
            content_format=ContentTypeStrToCoAPCode.get(form.contentType or "application/json"),
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
        form.cov_method = "GET"
        coap_request = self.create_coap_request(form, "GET", None)
        response = self._async_coap_client.send(coap_request)
        return self.get_body_from_response(response, form)


class CoAPAction(ConsumedThingAction, CoAPConsumedAffordanceMixin):
    # An CoAP action, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: ActionAffordance,
        async_client: Context = None,
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
        async_client: Context
            asynchronous CoAP client
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
        CoAPConsumedAffordanceMixin.__init__(
            self=self,
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
        coap_request = self.create_coap_request(form, "POST", body)
        response = await self._async_coap_client.request(coap_request).response
        return self.get_body_from_response(response, form)

    def __call__(self, *args, **kwargs):
        form = self.resource.retrieve_form(Operations.invokeaction, None)
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        if args:
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        coap_request = self.create_coap_request(form, "POST", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
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
        coap_request = self.create_coap_request(form, "POST", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
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
        coap_request = self.create_coap_request(form, "POST", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
        if response.headers.get("X-Message-ID", None) is None:
            raise ValueError("The server did not return a message ID for the non-blocking action.")
        message_id = response.headers["X-Message-ID"]
        self.owner_inst._noblock_messages[message_id] = self
        return message_id

    def read_reply(self, message_id, timeout=None):
        form = deepcopy(self.resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self.resource.name}")
        return CoAPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


class CoAPProperty(ConsumedThingProperty, CoAPConsumedAffordanceMixin):
    # An CoAP property, both sync and async
    # please dont add classdoc

    def __init__(
        self,
        resource: ActionAffordance,
        async_client: Context = None,
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
        async_client: Context
            asynchronous CoAP client
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
        CoAPConsumedAffordanceMixin.__init__(
            self=self,
            async_client=async_client,
            invokation_timeout=invokation_timeout,
            execution_timeout=execution_timeout,
        )
        self._read_reply_op_map = dict()

    def get(self) -> Any:
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        coap_request = self.create_coap_request(form, "GET", None)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
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
        coap_request = self.create_coap_request(form, "PUT", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
        self.get_body_from_response(response, form)
        # Just to ensure the request was successful, no body expected.
        return None

    async def async_get(self) -> Any:
        form = self.resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        coap_request = self.create_coap_request(form, "GET", b"")
        response = await self._async_coap_client.request(coap_request).response
        return self.get_body_from_response(response, form)

    async def async_set(self, value: Any) -> None:
        if self.resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self.resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self.resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        coap_request = self.create_coap_request(form, "PUT", body)
        response = await self._async_coap_client.request(coap_request).response
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
        coap_request = self.create_coap_request(form, "PUT", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
        # Just to ensure the request was successful, no body expected.
        self.get_body_from_response(response, form, raise_exception=False)
        return None

    def noblock_get(self) -> str:
        raise NotImplementedError
        form = deepcopy(self.resource.retrieve_form(Operations.readproperty, None))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self.resource.name}")
        form.href = f"{form.href}?noblock=true"
        coap_request = self.create_coap_request(form, "GET", None)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
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
        coap_request = self.create_coap_request(form, "PUT", body)
        response = asyncio.run(self._async_coap_client.request(coap_request).response)
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
        return CoAPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)


# class CoAPEvent(ConsumedThingEvent, CoAPConsumedAffordanceMixin):
#     # An CoAP event, both sync and async,
#     # please dont add classdoc

#     def __init__(
#         self,
#         resource: EventAffordance | PropertyAffordance,
#         sync_client: httpx.Client = None,
#         async_client: httpx.AsyncClient = None,
#         invokation_timeout: int = 5,
#         execution_timeout: int = 5,
#         owner_inst: Any = None,
#         logger: structlog.stdlib.BoundLogger = None,
#     ) -> None:
#         """
#         Parameters
#         ----------
#         resource: EventAffordance | PropertyAffordance
#             A dataclass instance representing the observable property or event to consume
#         sync_client: httpx.Client
#             synchronous CoAP client
#         async_client: httpx.AsyncClient
#             asynchronous CoAP client
#         invokation_timeout: int
#             timeout for invokation of an operation, other timeouts are specified while creating the client
#             in `ClientFactory`
#         execution_timeout: int
#             timeout for execution of an operation, other timeouts are specified while creating the client
#             in `ClientFactory`
#         owner_inst: Any
#             The parent object that owns this consumer
#         logger: structlog.stdlib.BoundLogger
#             Logger instance
#         """
#         ConsumedThingEvent.__init__(self, resource=resource, owner_inst=owner_inst, logger=logger)
#         CoAPConsumedAffordanceMixin.__init__(
#             self,
#             sync_client=sync_client,
#             async_client=async_client,
#             invokation_timeout=invokation_timeout,
#             execution_timeout=execution_timeout,
#         )

#     def listen(self, form: Form, callbacks: list[Callable], concurrent: bool = False, deserialize: bool = True) -> None:
#         serializer = Serializers.content_types.get(form.contentType or "application/json")
#         callback_id = threading.get_ident()

#         try:
#             with self._sync_http_client.stream(
#                 method="GET",
#                 url=form.href,
#                 headers=self._merge_auth_headers({"Accept": "text/event-stream"}),
#             ) as resp:
#                 resp.raise_for_status()
#                 interrupting_event = threading.Event()
#                 self._subscribed[callback_id] = (True, interrupting_event, resp)
#                 event_data = SSE()
#                 for line in self.iter_lines_interruptible(resp, interrupting_event):
#                     try:
#                         if not self._subscribed.get(callback_id, (False, None))[0] or interrupting_event.is_set():
#                             # when value is popped, consider unsubscribed
#                             break

#                         if line == "":
#                             if not event_data.data:
#                                 self.logger.warning(f"Received an invalid SSE event: {line}")
#                                 continue
#                             if deserialize:
#                                 event_data.data = serializer.loads(event_data.data.encode("utf-8"))
#                             self.schedule_callbacks(callbacks, event_data, concurrent)
#                             event_data = SSE()
#                             continue

#                         self.decode_chunk(line, event_data)
#                     except Exception as ex:
#                         self.logger.error(f"Error processing SSE event: {ex}")
#         except (httpx.ReadError, httpcore.ReadError):
#             pass

#     async def async_listen(
#         self,
#         form: Form,
#         callbacks: list[Callable],
#         concurrent: bool = False,
#         deserialize: bool = True,
#     ) -> None:
#         serializer = Serializers.content_types.get(form.contentType or "application/json")
#         callback_id = asyncio.current_task().get_name()

#         try:
#             async with self._async_http_client.stream(
#                 method="GET",
#                 url=form.href,
#                 headers=self._merge_auth_headers({"Accept": "text/event-stream"}),
#             ) as resp:
#                 resp.raise_for_status()
#                 interrupting_event = asyncio.Event()
#                 self._subscribed[callback_id] = (True, interrupting_event, resp)
#                 event_data = SSE()
#                 async for line in self.aiter_lines_interruptible(resp, interrupting_event, resp):
#                     try:
#                         if not self._subscribed.get(callback_id, (False, None))[0] or interrupting_event.is_set():
#                             # when value is popped, consider unsubscribed
#                             break

#                         if line == "":
#                             if not event_data.data:
#                                 self.logger.warning(f"Received an invalid SSE event: {line}")
#                                 continue
#                             if deserialize:
#                                 event_data.data = serializer.loads(event_data.data.encode("utf-8"))
#                             await self.async_schedule_callbacks(callbacks, event_data, concurrent)
#                             event_data = SSE()
#                             continue

#                         self.decode_chunk(line, event_data)
#                     except Exception as ex:
#                         self.logger.error(f"Error processing SSE event: {ex}")
#         except (httpx.ReadError, httpcore.ReadError):
#             pass

#     async def aiter_lines_interruptible(self, resp: httpx.Response, stop: asyncio.Event) -> AsyncIterator[str]:
#         """
#         Yield lines from an httpx streaming response, but stop immediately when `stop` is set.
#         Works by racing the next __anext__() call against stop.wait().
#         """
#         it = resp.aiter_lines()
#         while not stop.is_set():
#             try:
#                 next_line = asyncio.create_task(it.__anext__())
#                 stopper = asyncio.create_task(stop.wait())
#                 done, pending = await asyncio.wait({next_line, stopper}, return_when=asyncio.FIRST_COMPLETED)

#                 if stopper in done:
#                     next_line.cancel()
#                     with contextlib.suppress(asyncio.CancelledError):
#                         await next_line
#                     break

#                 stopper.cancel()
#                 with contextlib.suppress(asyncio.CancelledError):
#                     await stopper
#                 yield next_line.result()

#             except (httpx.ReadTimeout, httpcore.ReadTimeout):
#                 continue

#             except StopAsyncIteration:
#                 # remote closed the stream
#                 return

#     def iter_lines_interruptible(self, resp: httpx.Response, stop: threading.Event) -> Iterator[str]:
#         """iterate lines from an httpx streaming response, but stop immediately when `stop` is set"""
#         it = resp.iter_lines()
#         # Using a dedicated stream scope inside the thread
#         while not stop.is_set():
#             try:
#                 next_line = next(it)
#             except (httpx.ReadTimeout, httpcore.ReadTimeout):
#                 continue
#             except StopIteration:
#                 break
#             yield next_line

#     def decode_chunk(self, line: str, event_data: "SSE") -> None:
#         """decode a single line of an SSE stream into the given SSE event_data object"""
#         if line is None or line.startswith(":"):  # comment/heartbeat
#             return

#         field, _, value = line.partition(":")
#         if value.startswith(" "):
#             value = value[1:]  # spec: single leading space is stripped

#         if field == "event":
#             event_data.event = value or "message"
#         elif field == "data":
#             event_data.data += value
#         elif field == "id":
#             event_data.id = value or None
#         elif field == "retry":
#             try:
#                 event_data.retry = int(value)
#             except ValueError:
#                 self.logger.warning(f"Invalid retry value: {value}")

#     def unsubscribe(self) -> None:
#         """Unsubscribe from the event."""
#         for callback_id, (subscribed, obj, resp) in list(self._subscribed.items()):
#             obj.set()
#         return super().unsubscribe()


__all__ = [CoAPProperty.__name__, CoAPAction.__name__]
