#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Classes that contain the client logic for the HTTP protocol.
"""
import asyncio
import json
import tornado.httpclient
from typing import Any
from tornado.simple_httpclient import HTTPTimeoutError

from ..abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty, raise_local_exception
from ...td.interaction_affordance import ActionAffordance
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
        self.sync_http_client = tornado.httpclient.HTTPClient()
        self.async_http_client = tornado.httpclient.AsyncHTTPClient()

    
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
            if isinstance(body, dict) and 'exception' in body:
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
        form = self._resource.retrieve_form(op='invokeaction')
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args: 
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        try:
            response = await self.async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
        
    def __call__(self, *args, **kwargs):
        form = self._resource.retrieve_form(op='invokeaction')
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        if args: 
            kwargs.update({"__args__": args})
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(kwargs)
        http_request = self.create_http_request(form, "POST", body)
        try:
            response = self.sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
            

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
        
    async def set(self, value: Any) -> None:
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(op='writeproperty')
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        try:
            response = await self.async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        self.get_body_from_response(response, form) # Just to ensure the request was successful, no body expected.
        return None

    def set(self, value: Any) -> None:
        """Synchronous set of the property value."""
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(op='writeproperty')
        if form is None:
            raise ValueError(f"No form found for writeproperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.contentType or "application/json")
        body = serializer.dumps(value)
        http_request = self.create_http_request(form, "PUT", body)
        try:
            response = self.sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        self.get_body_from_response(response, form)
        return None

    async def get(self):
        form = self._resource.retrieve_form(op='readproperty')
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", b'')
        try:
            response = await self.async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
        
    def get(self):
        form = self._resource.retrieve_form(op='readproperty')
        if form is None:
            raise ValueError(f"No form found for readproperty operation for {self._resource.name}")
        http_request = self.create_http_request(form, "GET", None)
        try:
            response = self.sync_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response, form)
        
    
   
class HTTPEvent(ConsumedThingEvent):

    def on_event(self, td, name):
        """Subscribes to an event on a remote Thing.
        Returns an Observable."""

        href = self.pick_http_href(td, td.get_event_forms(name))

        if href is None:
            raise FormNotFoundException()

        def subscribe(observer):
            """Subscription function to observe events using the HTTP protocol."""

            state = {"active": True}

            @handle_observer_finalization(observer)
            async def callback():
                http_client = tornado.httpclient.AsyncHTTPClient()
                http_request = tornado.httpclient.HTTPRequest(href, method="GET")

                while state["active"]:
                    try:
                        response = await http_client.fetch(http_request)
                        payload = json.loads(response.body).get("payload")
                        observer.on_next(EmittedEvent(init=payload, name=name))
                    except HTTPTimeoutError:
                        pass

            def unsubscribe():
                state["active"] = False

            asyncio.create_task(callback())

            return unsubscribe

        return Observable.create(subscribe)

    def on_property_change(self, td, name):
        """Subscribes to property changes on a remote Thing.
        Returns an Observable"""

        href = self.pick_http_href(
            td, td.get_property_forms(name), op=InteractionVerbs.OBSERVE_PROPERTY
        )

        if href is None:
            raise FormNotFoundException()

        def subscribe(observer):
            """Subscription function to observe property updates using the HTTP protocol."""

            state = {"active": True}

            @handle_observer_finalization(observer)
            async def callback():
                http_client = tornado.httpclient.AsyncHTTPClient()
                http_request = tornado.httpclient.HTTPRequest(href, method="GET")

                while state["active"]:
                    try:
                        response = await http_client.fetch(http_request)
                        value = json.loads(response.body)
                        value = value.get("value", value)
                        init = PropertyChangeEventInit(name=name, value=value)
                        observer.on_next(PropertyChangeEmittedEvent(init=init))
                    except HTTPTimeoutError:
                        pass

            def unsubscribe():
                state["active"] = False

            asyncio.create_task(callback())

            return unsubscribe

        return Observable.create(subscribe)


__all__ = [
    HTTPProperty.__name__,
    HTTPAction.__name__,
    HTTPEvent.__name__
]