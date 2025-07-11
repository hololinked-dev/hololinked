#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Classes that contain the client logic for the HTTP protocol.
"""
import asyncio
import json
import logging
import time
import urllib.parse as parse
import tornado.httpclient
from typing import Any
from tornado.simple_httpclient import HTTPTimeoutError
from ..abstractions import ConsumedThingAction, ConsumedThingProperty
from ...td.interaction_affordance import ActionAffordance
from ...serializers import Serializers



class HTTPConsumedAffordanceMixin:
    """Implementation of the protocol client interface for the HTTP protocol."""

    JSON_HEADERS = {"Content-Type": "application/json"}
    DEFAULT_CON_TIMEOUT = 60
    DEFAULT_REQ_TIMEOUT = 60

    def __init__(self,
                resource: ActionAffordance,
                connect_timeout: int = 60,
                request_timeout: int = 60,
                invokation_timeout: int = 5,
                execution_timeout: int = 5,
                **kwargs
            ) -> None:
        super().__init__(resource, **kwargs)
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self.async_http_client = tornado.httpclient.AsyncHTTPClient()

    @classmethod
    def get_body_from_response(self, response: tornado.httpclient.HTTPResponse):
        if response.code >= 200 and response.code < 300:
            if response.body:
                return response.body
            return
        raise Exception(f"status code {response.code}")

      

class HTTPAction(ConsumedThingAction, HTTPConsumedAffordanceMixin):

    async def async_call(self, *args, **kwargs):
        now = time.time()
        form = self._resource.retrieve_form(op='invokeAction')
        if form is None:
            raise ValueError(f"No form found for invokeAction operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.get("contentType", "application/json"))
        if args: 
            kwargs.update({"__args__": args})
        body = serializer.dumps(kwargs)
        try:
            http_request = tornado.httpclient.HTTPRequest(
                form["href"] ,
                method=form.get("htv:methodName", "POST"),
                body=body,
                headers=self.JSON_HEADERS,
                connect_timeout=self._connect_timeout,
                request_timeout=self._invokation_timeout,
            )
            response = await self.async_http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response)
        
            

class HTTPProperty(ConsumedThingProperty, HTTPConsumedAffordanceMixin):

    async def write_property(self, value: Any) -> None:
        """Updates the value of a Property on a remote Thing.
        Returns a Future."""
        if self._resource.readOnly:
            raise NotImplementedError("This property is not writable")
        form = self._resource.retrieve_form(op='writeProperty')
        if form is None:
            raise ValueError(f"No form found for writeProperty operation for {self._resource.name}")
        serializer = Serializers.content_types.get(form.get("contentType", "application/json"))
        body = serializer.dumps({"value": value})
        try:
            http_request = tornado.httpclient.HTTPRequest(
                form["href"],
                method=form.get("htv:methodName", "PUT"),
                body=body,
                headers=self.JSON_HEADERS,
                connect_timeout=self._connect_timeout,
                request_timeout=self._request_timeout,
            )
            response = await self.http_client.fetch(http_request)
        except HTTPTimeoutError as ex:
            raise TimeoutError(str(ex)) from None
        return self.get_body_from_response(response)

    async def read_property(self, td, name, timeout=None):
        """Reads the value of a Property on a remote Thing.
        Returns a Future."""

        con_timeout = timeout if timeout else self._connect_timeout
        req_timeout = timeout if timeout else self._request_timeout

        href = self.pick_http_href(td, td.get_property_forms(name))

        if href is None:
            raise FormNotFoundException()

        http_client = tornado.httpclient.AsyncHTTPClient()

        try:
            http_request = tornado.httpclient.HTTPRequest(
                href,
                method="GET",
                connect_timeout=con_timeout,
                request_timeout=req_timeout,
            )
        except HTTPTimeoutError as ex:
            raise ClientRequestTimeout from ex

        response = await http_client.fetch(http_request)
        result = json.loads(response.body)
        result = result.get("value", result)

        return result
    

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

    def on_td_change(self, url):
        """Subscribes to Thing Description changes on a remote Thing.
        Returns an Observable."""

        raise NotImplementedError


__all__ = [
    HTTPProperty.__name__,
    HTTPAction.__name__,
    HTTPEvent.__name__
]