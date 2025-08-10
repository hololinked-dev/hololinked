"""
Classes that contain the client logic for the HTTP protocol.
"""
import asyncio
import threading
import tornado.httpclient
from typing import Any, Callable
from copy import deepcopy
from tornado.simple_httpclient import HTTPTimeoutError, HTTPStreamClosedError

from ...utils import get_current_async_loop
from ...constants import Operations
from ..abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty, raise_local_exception
from ...td.interaction_affordance import ActionAffordance, EventAffordance
from ...td.forms import Form
from ...serializers import Serializers



class HTTPConsumedAffordanceMixin:
    """Implementation of the protocol client interface for the HTTP protocol."""

    def __init__(self,
                connect_timeout: int = 60,
                request_timeout: int = 60,
                invokation_timeout: int = 5,
                execution_timeout: int = 5,
                **kwargs
            ) -> None:
        super().__init__()
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._sync_http_client = tornado.httpclient.HTTPClient()
        self._async_http_client = tornado.httpclient.AsyncHTTPClient()

    
    def get_body_from_response(self, 
                            response: tornado.httpclient.HTTPResponse,
                            form: Form,   
                            raise_exception: bool = True
                            ) -> Any:
        if response.code >= 200 and response.code < 300:
            body = response.body
            if not body:
                return
            serializer = Serializers.content_types.get(form.contentType or "application/json")
            if serializer is None:
                raise ValueError(f"Unsupported content type: {form.contentType}")
            body = serializer.loads(body)
            if isinstance(body, dict) and 'exception' in body and raise_exception:
                raise_local_exception(body)
            return body
        raise Exception(f"status code {response.code}")

    def create_http_request(self, form: Form, default_method: str, body: bytes | None = None) -> tornado.httpclient.HTTPRequest:
        """Creates an HTTP request for the given form and body."""
        return tornado.httpclient.HTTPRequest(
            form.href,
            method=form.htv_methodName or default_method,
            body=body,
            headers={"Content-Type": "application/json"},
            connect_timeout=self._connect_timeout,
            request_timeout=self._request_timeout,
        )
    
    def read_reply(self, form: Form, message_id: str, timeout = None):
        """Read the reply for a non-blocking action."""
        form.href = f'{form.href}?messageID={message_id}&timeout={timeout or self._invokation_timeout}'
        form.htv_methodName = "GET"
        http_request = self.create_http_request(form, "GET", None)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
    

class HTTPAction(ConsumedThingAction, HTTPConsumedAffordanceMixin):

    def __init__(self,
                resource: ActionAffordance,
                connect_timeout: int = 60,
                request_timeout: int = 60,
                invokation_timeout: int = 5,
                execution_timeout: int = 5,
                **kwargs
            ) -> None:
        ConsumedThingAction.__init__(self=self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
                        self=self,
                        connect_timeout=connect_timeout,
                        request_timeout=request_timeout,
                        invokation_timeout=invokation_timeout,
                        execution_timeout=execution_timeout,
                        **kwargs
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
        try:
            response = await self._async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
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
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
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
        form.href = f'{form.href}?oneway=true'
        http_request = self.create_http_request(form, "POST", body)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        # we still do it like this only to ensure our logic is consistent, oneway actions do not expect a body
        return self.get_body_from_response(response, form)
    
    def noblock(self, *args, **kwargs) -> str:
        """Invoke the action in non-blocking mode."""
        form = deepcopy(self._resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args: 
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        form.href = f'{form.href}?noblock=true'
        http_request = self.create_http_request(form, "POST", body)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        assert response.headers.get('X-Message-ID', None) is not None, \
            "The server did not return a message ID for the non-blocking action."
        message_id = response.headers['X-Message-ID']
        self._owner_inst._noblock_messages[message_id] = self
        return message_id
    
    def read_reply(self, message_id, timeout = None):
        form = deepcopy(self._resource.retrieve_form(Operations.invokeaction, None))
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)

    
        
class HTTPProperty(ConsumedThingProperty, HTTPConsumedAffordanceMixin):

    def __init__(self,
                resource: ActionAffordance,
                connect_timeout: int = 60,
                request_timeout: int = 60,
                invokation_timeout: int = 5,
                execution_timeout: int = 5,
                **kwargs
            ) -> None:
        ConsumedThingProperty.__init__(self=self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
                        self=self,
                        connect_timeout=connect_timeout,
                        request_timeout=request_timeout,
                        invokation_timeout=invokation_timeout,
                        execution_timeout=execution_timeout,
                        **kwargs
                    )
        self._read_reply_op_map = dict()
        
    async def set(self, value: Any) -> None:
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        try:
            response = await self._async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        self.get_body_from_response(response, form) # Just to ensure the request was successful, no body expected.
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
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        self.get_body_from_response(response, form)
        return None

    async def get(self):
        form = self._resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", b'')
        try:
            response = await self._async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
        
    def get(self):
        form = self._resource.retrieve_form(Operations.readproperty, None)
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", None)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
    
    def oneway_set(self, value: Any) -> None:
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(Operations.writeproperty, None)
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        form.href = f'{form.href}?oneway=true'
        http_request = self.create_http_request(form, "PUT", body)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        # we still do it like this only to ensure our logic is consistent, oneway actions do not expect a body
        return self.get_body_from_response(response, form, raise_exception=False)
    
    def noblock_get(self) -> str:
        form = deepcopy(self._resource.retrieve_form(Operations.readproperty, None))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        form.href = f'{form.href}?noblock=true'
        http_request = self.create_http_request(form, "GET", None)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        assert response.headers.get('X-Message-ID', None) is not None, \
            "The server did not return a message ID for the non-blocking property read."
        message_id = response.headers['X-Message-ID']
        self._read_reply_op_map[message_id] = 'readproperty'
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
        form.href = f'{form.href}?noblock=true'
        http_request = self.create_http_request(form, "PUT", body)
        try:
            response = self._sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex: 
            raise TimeoutError(str(ex)) from None
        assert response.headers.get('X-Message-ID', None) is not None, \
            "The server did not return a message ID for the non-blocking property write."
        message_id = response.headers['X-Message-ID']
        self._owner_inst._noblock_messages[message_id] = self
        self._read_reply_op_map[message_id] = 'writeproperty'
        return message_id

    def read_reply(self, message_id, timeout = None):
        form = deepcopy(self._resource.retrieve_form(op=self._read_reply_op_map.get(message_id, 'readproperty')))
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        return HTTPConsumedAffordanceMixin.read_reply(self, form, message_id, timeout)
        


class HTTPEvent(ConsumedThingEvent, HTTPConsumedAffordanceMixin):

    def __init__(self, 
                resource: EventAffordance,
                default_scheduling_mode: str = 'sync',
                connect_timeout: int = 60,
                request_timeout: int = 60,
                invokation_timeout: int = 5,
                execution_timeout: int = 5,
                **kwargs
            ) -> None:
        ConsumedThingEvent.__init__(self, resource=resource, **kwargs)
        HTTPConsumedAffordanceMixin.__init__(
                            self,
                            connect_timeout=connect_timeout,
                            request_timeout=request_timeout,
                            invokation_timeout=invokation_timeout,
                            execution_timeout=execution_timeout,
                            **kwargs
                        )
        self._default_scheduling_mode = default_scheduling_mode
        self._thread = None


    def subscribe(self, 
                callbacks: list[Callable] | Callable, 
                thread_callbacks: bool = False, 
                deserialize: bool = True
            ) -> None:
        if not self._default_scheduling_mode in ['sync', 'async']:
            raise ValueError(f"Invalid scheduling mode: {self._default_scheduling_mode}. Must be 'sync' or 'async'.")
        form = self._resource.retrieve_form(Operations.subscribeevent, None)
        if form is None:
            raise ValueError(f"No form found for subscribeevent operation for {self._resource.name}")
        self.add_callbacks(callbacks)
        self._subscribed = True
        self._deserialize = deserialize
        self._thread_callbacks = thread_callbacks
        if self._default_scheduling_mode == 'sync':
            self._thread = threading.Thread(target=self.listen)
            self._thread.start()
        else:
            get_current_async_loop().call_soon(lambda: asyncio.create_task(self.async_listen()))

    def listen(self):
        form = self._resource.retrieve_form(Operations.subscribeevent, None)
        if form is None:
            raise ValueError(f"No form found for subscribeevent operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        buffer = ""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def on_chunk(chunk: bytes):
            """process incoming SSE chunks"""
            nonlocal self, serializer, buffer

            if not self._subscribed:
                self._logger.debug("Unsubscribed from the event stream, stopping processing.")
                self._sync_http_client.close()
                return
            
            buffer += chunk.decode('utf-8')
            # split events on the SSE separator: two newlines
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                event = {}
                for line in raw_event.splitlines():
                    # skip comments
                    if not line or line.startswith(":"):
                        continue
                    if ":" in line:
                        field, value = line.split(":", 1)
                        event.setdefault(field, "")
                        # strip leading space after colon
                        event[field] += value.lstrip()
                if "data" in event:
                    # if the event has a data field, it is an event, and its also a string, so we need to cast it to bytes
                    value = serializer.loads(event["data"].encode('utf-8'))
                    for cb in self._callbacks: 
                        if not self._thread_callbacks:
                            cb(value)
                        else: 
                            threading.Thread(target=cb, args=(value,)).start()
                else:
                    self._logger.warning(f"Received an invalid SSE event: {raw_event}")
            
        request = tornado.httpclient.HTTPRequest(
            form.href,
            method="GET",
            headers={"Accept": "text/event-stream"},
            request_timeout=self._request_timeout,
            connect_timeout=self._connect_timeout,  
            streaming_callback=on_chunk,
        )
        try:
            while self._subscribed:
                try:
                    response = self._sync_http_client.fetch(request, raise_error=False)
                    if response.code < 200 or response.code >= 300:
                        raise Exception(f"Failed to subscribe to SSE stream: {response.code}")
                except HTTPTimeoutError as ex:
                    pass 
        except HTTPStreamClosedError as ex:
            self._logger.debug(f"HTTP stream closed: {str(ex)}")
        finally:
            tasks = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in tasks:
                task.cancel()
            loop.close()
            self._sync_http_client.close() # can close twice sometimes, seems to be OK
            
    def unsubscribe(self, join_thread: bool = True):
        """
        Unsubscribe from the event. 
        Its inherently a little slower due to the nature of HTTP, please wait until the request timeout is reached.
        """
        self._subscribed = False
        if self._thread and join_thread:
            self._thread.join()
            self._thread = None
  

__all__ = [
    HTTPProperty.__name__,
    HTTPAction.__name__,
    HTTPEvent.__name__
]