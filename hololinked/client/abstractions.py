"""
MIT License

Copyright (c) 2018 CTIC Centro Tecnologico

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
# copied from wotpy repository

import asyncio
import threading
import typing
import builtins
import logging
from dataclasses import dataclass

from ..td import PropertyAffordance, ActionAffordance, EventAffordance
from ..td.forms import Form
from ..utils import get_current_async_loop
from ..constants import Operations


class ConsumedThingAction:
    # Client side action call abstraction. Subclasss from here to implement protocol specific action call.
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    def __init__(
        self,
        resource: ActionAffordance,
        owner_inst: typing.Any,
        logger: logging.Logger,
        # schema_validator: typing.Type[BaseSchemaValidator] | None = None
    ) -> None:
        """
        Parameters
        ----------
        resource: ActionAffordance
            dataclass TD fragment representing the action (must have forms).
        owner_inst: typing.Optional[typing.Any]
            instance of the owning consumed Thing or `ObjectProxy`
        logger: logging.Logger
            logger instance
        """
        self.resource = resource
        self.owner_inst = owner_inst
        self.logger = logger
        self.schema_validator = None  # schema_validator

    def get_last_return_value(self, raise_exception: bool = False) -> typing.Any:
        """retrieve return value of the last call to the action"""
        raise NotImplementedError("implement get_last_return_value per protocol")

    last_return_value = property(
        fget=get_last_return_value,
        doc="cached return value of the last call to the method",
    )
    """cached return value of the last call to the method"""

    def __call__(self, *args, **kwargs) -> typing.Any:
        """
        Invoke action/method on server

        Parameters
        ----------
        *args: typing.Any
            arguments to the action
        **kwargs: typing.Any
            keyword arguments to the action

        Returns
        -------
        typing.Any
            reply of the action call
        """
        raise NotImplementedError("implement action __call__ per protocol")

    async def async_call(self, *args, **kwargs) -> typing.Any:
        """
        async invoke action on server - asynchronous at the network level, may not necessarily be at the server level.

        Parameters
        ----------
        *args: typing.Any
            arguments to the action
        **kwargs: typing.Any
            keyword arguments to the action

        Returns
        -------
        typing.Any
            reply of the action call
        """
        raise NotImplementedError("implement action async_call per protocol")

    def oneway(self, *args, **kwargs) -> None:
        """
        Only invokes the action on the server and does not wait for reply,
        neither does the server reply to this invokation.

        Parameters
        ----------
        *args: typing.Any
            arguments to the action
        **kwargs: typing.Any
            keyword arguments to the action
        """
        raise NotImplementedError("implement action oneway call per protocol")

    def noblock(self, *args, **kwargs) -> str:
        """
        Invoke the action and collect the reply later. A message ID must be returned by the server to identify the
        invokation.

        Parameters
        ----------
        *args: typing.Any
            arguments to the action
        **kwargs: typing.Any
            keyword arguments to the action

        Returns
        -------
        str
            id of the request or message (UUID4 as string)
        """
        raise NotImplementedError("implement action noblock call per protocol")

    def read_reply(self, message_id: str, timeout: float | int | None = None) -> typing.Any:
        """
        Read the reply of the action call which was scheduled with `noblock`.

        Parameters
        ----------
        message_id: str
            id of the request or message (UUID4 as string)
        timeout: float | int | None
            timeout in seconds to wait for the reply, None means wait indefinitely

        Returns
        -------
        typing.Any
            reply of the action call
        """
        raise NotImplementedError("implement action read_reply per protocol")

    def __hash__(self):
        return hash(self.resource.name)

    def __eq__(self, other):
        if not isinstance(other, ConsumedThingAction):
            return False
        return self.resource.name == other.resource.name


class ConsumedThingProperty:
    # property get set abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(
        self, resource: PropertyAffordance, owner_inst: typing.Optional[typing.Any], logger: logging.Logger
    ) -> None:
        """
        Parameters
        ----------
        resource: PropertyAffordance
            dataclass object TD fragment representing the property (must have forms).
        owner_inst: typing.Optional[typing.Any]
            instance of the owning consumed Thing or `ObjectProxy`
        logger: logging.Logger
            logger instance
        """
        self.resource = resource
        self.owner_inst = owner_inst
        self.logger = logger

    @property  # i.e. cannot have setter
    def last_read_value(self) -> typing.Any:
        """cache of last read value"""
        raise NotImplementedError("implement last_read_value per protocol")

    def set(self, value: typing.Any) -> None:
        """
        Set or write property value.

        Parameters
        ----------
        value: typing.Any
            value to set
        """
        raise NotImplementedError("implement property set per protocol")

    def get(self) -> typing.Any:
        """
        Get or read property value.

        Returns
        -------
        typing.Any
            property value
        """
        raise NotImplementedError("implement property get per protocol")

    async def async_set(self, value: typing.Any) -> None:
        """
        Async set or write property value - asynchronous at the network level, may not necessarily be at the server level.

        Parameters
        ----------
        value: typing.Any
            value to set
        """
        raise NotImplementedError("implement async property set per protocol")

    async def async_get(self) -> typing.Any:
        """
        Async get or read property value - asynchronous at the network level, may not necessarily be at the server level.

        Returns
        -------
        typing.Any
            property value
        """
        raise NotImplementedError("implement async property get per protocol")

    def noblock_get(self) -> str:
        """
        Get or read property value without blocking, i.e. make a request and collect it later and the method returns immediately.
        Server must return a message ID to identify the request.

        Returns
        -------
        str
            id of the request or message (UUID4 as string)
        """
        raise NotImplementedError("implement property noblock get per protocol")

    def noblock_set(self, value: typing.Any) -> str:
        """
        Set or write property value without blocking, i.e. make a request and collect it later and the method returns immediately.
        Server must return a message ID to identify the request.

        Parameters
        ----------
        value: typing.Any
            value to set

        Returns
        -------
        str
            id of the request or message (UUID4 as string)
        """
        raise NotImplementedError("implement property noblock set per protocol")

    def oneway_set(self, value: typing.Any) -> None:
        """
        Set property value without waiting for acknowledgement. The server also does not send any reply.
        There is no guarantee that the property value was set.

        Parameters
        ----------
        value: typing.Any
            value to set
        """
        raise NotImplementedError("implement property oneway set per protocol")

    def observe(self, *callbacks: typing.Callable) -> None:
        """
        Observe property value changes

        Parameters
        ----------
        *callbacks: typing.Callable
            callback to call when property value changes
        """
        # looks like this will be unused. observe property is done via ConsumedThingEvent
        raise NotImplementedError("implement property observe per protocol")

    def unobserve(self) -> None:
        """Stop observing property value changes"""
        # looks like this will be unused, observe property is done via ConsumedThingEvent
        raise NotImplementedError("implement property unobserve per protocol")

    def read_reply(self, message_id: str, timeout: float | int | None = None) -> typing.Any:
        """
        Read the reply of the property get or set which was scheduled with `noblock`.

        Parameters
        ----------
        message_id: str
            id of the request or message (UUID4 as string)
        timeout: float | int | None
            timeout in seconds to wait for the reply, None means wait indefinitely

        Returns
        -------
        typing.Any
            reply of the property get or set
        """
        raise NotImplementedError("implement property read_reply per protocol")


class ConsumedThingEvent:
    # event subscription
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    def __init__(
        self,
        resource: EventAffordance,
        logger: logging.Logger,
        owner_inst: typing.Any,
    ) -> None:
        """
        Parameters
        ----------
        resource: EventAffordance
            dataclass object representing the event
        logger: logging.Logger
            logger instance
        owner_inst: typing.Any
            the parent object that owns this event
        """
        self.resource = resource
        self.logger = logger
        self.owner_inst = owner_inst
        self._subscribed = dict()
        # self._sync_callbacks = []
        # self._async_callbacks = []

    def subscribe(
        self,
        callbacks: list[typing.Callable] | typing.Callable,
        asynch: bool = False,
        concurrent: bool = False,
        deserialize: bool = True,
        # create_new_connection: bool = False,
    ) -> None:
        """
        subscribe to the event

        Parameters
        ----------
        callbacks: typing.List[typing.Callable] | typing.Callable
            callback or list of callbacks to add
        asynch: bool
            whether to start an async(-io task) event listener instead of a threaded listener
        concurrent: bool
            - asyncio - if `True`, each callback is scheduled as a separate task, if `False` they are awaited sequentially.
            - threading - if `True`, each callback is called in a separate thread, if `False` they are called sequentially
        deserialize: bool
            if `False`, event payload is passed to the callbacks as raw bytes, if `True` it is deserialized
        """
        op = Operations.observeproperty if isinstance(self.resource, PropertyAffordance) else Operations.subscribeevent
        form = self.resource.retrieve_form(op, None)
        callbacks = callbacks if isinstance(callbacks, (list, tuple)) else [callbacks]
        # if not create_new_connection:
        #   see tag v0.3.2 for logic
        if form is None:
            raise ValueError(f"No form found for {op} operation for {self.resource.name}")
        if asynch:
            get_current_async_loop().call_soon(
                lambda: asyncio.create_task(self.async_listen(form, callbacks, concurrent, deserialize))
            )
        else:
            _thread = threading.Thread(target=self.listen, args=(form, callbacks, concurrent, deserialize), daemon=True)
            _thread.start()

    def unsubscribe(self):
        """unsubscribe from the event"""
        self._subscribed.clear()
        # self._sync_callbacks.clear()
        # self._async_callbacks.clear()

    def listen(self, form: Form, callbacks: list[typing.Callable], concurrent: bool = True, deserialize: bool = True):
        """
        listen to events and call the callbacks
        """
        raise NotImplementedError("implement listen per protocol")

    async def async_listen(
        self, form: Form, callbacks: list[typing.Callable], concurrent: bool = True, deserialize: bool = True
    ):
        """
        listen to events and call the callbacks
        """
        raise NotImplementedError("implement async_listen per protocol")

    def schedule_callbacks(self, callbacks, event_data: typing.Any, concurrent: bool = False) -> None:
        """
        schedule the callbacks to be called with the event data

        Parameters
        ----------
        event_data: typing.Any
            event data to pass to the callbacks
        concurrent: bool
            whether to run each callback in a separate thread
        """
        for cb in callbacks:
            try:
                if not concurrent:
                    cb(event_data)
                else:
                    threading.Thread(target=cb, args=(event_data,)).start()
            except Exception as ex:
                self.logger.error(f"Error occurred in callback {cb}: {ex}")

    async def async_schedule_callbacks(self, callbacks, event_data: typing.Any, concurrent: bool = False) -> None:
        """
        schedule the callbacks to be called with the event data

        Parameters
        ----------
        event_data: typing.Any
            event data to pass to the callbacks
        concurrent: bool
            whether to run each callback in a separate thread
        """
        loop = get_current_async_loop()
        for cb in callbacks:
            try:
                if concurrent:
                    if asyncio.iscoroutinefunction(cb):
                        loop.create_task(cb(event_data))
                    else:
                        loop.run_in_executor(None, cb, event_data)
                elif asyncio.iscoroutinefunction(cb):
                    await cb(event_data)
                else:
                    cb(event_data)
            except Exception as ex:
                self.logger.error(f"Error occurred in callback {cb}: {ex}")

    def add_callbacks(
        self, callbacks: typing.Union[typing.List[typing.Callable], typing.Callable], asynch: bool = False
    ) -> None:
        """
        add callbacks to the event

        Parameters
        ----------
        *callbacks: typing.List[typing.Callable] | typing.Callable
            callback or list of callbacks to add
        """
        raise NotImplementedError(
            "logic error - cannot add callbacks to reuse event subscription. Unsubscribe and resubscribe with new callbacks"
        )
        # for logic, see tag v0.3.2


def raise_local_exception(error_message: typing.Dict[str, typing.Any]) -> None:
    """
    raises an exception on client side using an exception from server, using a mapping based on exception type
    (currently only python built-in exceptions supported). If the exception type is not found, a generic `Exception` is raised.
    Server traceback is added to the exception notes. Client creates its own traceback which is not usually the cause of the error.

    Parameters
    ----------
    error_message: dict[str, Any]
        exception dictionary made by server with following keys - `type`, `message`, `traceback`, `notes`
    """
    if isinstance(error_message, Exception):
        raise error_message from None
    elif isinstance(error_message, dict) and "exception" in error_message.keys():
        error_message = error_message["exception"]
        message = error_message["message"]
        exc = getattr(builtins, error_message["type"], None)
        if exc is None:
            ex = Exception(message)
        else:
            ex = exc(message)
        error_message["traceback"][0] = f"Server {error_message['traceback'][0]}"
        ex.__notes__ = error_message["traceback"][0:-1]
        raise ex from None
    elif isinstance(error_message, str) and error_message in [
        "invokation",
        "execution",
    ]:
        raise TimeoutError(
            f"{error_message[0].upper()}{error_message[1:]} timeout occured. Server did not respond within specified timeout"
        ) from None
    raise RuntimeError("unknown error occurred on server side") from None


@dataclass
class SSE:
    """
    dataclass representing a server sent event and the argument used to invoke event callbacks.

    Attributes
    ----------
    event: str
        event name, defaults to "message"
    data: Any
        event data, defaults to empty string
    id: Optional[str]
        event id, defaults to None
    retry: Optional[int]
        reconnection time in milliseconds, defaults to None, currently unused.
    """

    __slots__ = ("event", "data", "id", "retry")

    def __init__(self):
        self.clear()

    def clear(self):
        """reset to default/empty values"""
        self.event = "message"  # type: str
        self.data = ""  # type: typing.Any
        self.id = None  # type: typing.Optional[str]
        self.retry = None  # type: typing.Optional[int]

    def flush(self) -> typing.Optional[dict]:
        """obtain the event payload as dictionary and reset to default values"""
        if not self.data and self.id is None:
            return None
        payload = {
            "event": self.event,
            "data": self.data,
            "id": self.id,
            "retry": self.retry,
        }
        # reset to default for next event
        self.clear()
        return payload
