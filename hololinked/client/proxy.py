from typing import Any, Callable

import structlog

from .abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty
from .security import APIKeySecurity, BasicSecurity  # noqa: F401


class ObjectProxy:
    """
    Procedural/scripting client for `Thing`. Once connected to a server, properties, methods and events are loaded and
    dynamically populated. Can be used with any supported protocol binding.

    Use `ClientFactory` to create an instance of this class instead of directly creating it.
    """

    _own_attrs = frozenset(
        [
            "__annotations__",
            "_allow_foreign_attributes",
            "id",
            "logger",
            "td",
            "execution_timeout",
            "invokation_timeout",
            "_execution_timeout",
            "_invokation_timeout",
            "_events",
            "_noblock_messages",
            "_schema_validator",
            "_security",
        ]
    )

    __allowed_attribute_types__ = (
        ConsumedThingProperty,
        ConsumedThingAction,
        ConsumedThingEvent,
    )

    def __init__(self, id: str, **kwargs) -> None:
        """
        Parameters
        ----------
        id: str
            unique id for the client
        **kwargs:
            additional keyword arguments:

            - `allow_foreign_attributes`: `bool`, default `False`.
                allows local attributes apart from resources fetched from the server.
            - `logger`: `structlog.stdlib.BoundLogger`, default `None`.
                logger instance
            - `td`: `dict[str, Any]`, default `dict()`.
                Thing Description of the consumed Thing
            - `security`: `BasicSecurity` | `APIKeySecurity`, optional.
                security scheme to be used for authentication
        """
        self.id = id
        self._allow_foreign_attributes = kwargs.get("allow_foreign_attributes", False)
        self._noblock_messages = dict()  # type: dict[str, ConsumedThingAction | ConsumedThingProperty]
        self._schema_validator = kwargs.get("schema_validator", None)
        self._security = kwargs.get("security", None)  # type: BasicSecurity | APIKeySecurity | None
        self.logger = kwargs.pop("logger", structlog.get_logger())
        self.td = kwargs.get("td", dict())  # type: dict[str, Any]

    def __getattribute__(self, __name: str) -> Any:
        obj = super().__getattribute__(__name)
        if isinstance(obj, ConsumedThingProperty):
            return obj.get()
        return obj

    def __setattr__(self, __name: str, __value: Any) -> None:
        if (
            __name in ObjectProxy._own_attrs
            or (__name not in self.__dict__ and isinstance(__value, ObjectProxy.__allowed_attribute_types__))
            or self._allow_foreign_attributes
        ):
            # allowed attribute types are ConsumedThingProperty and ConsumedThingAction defined after this class
            return super(ObjectProxy, self).__setattr__(__name, __value)
        elif __name in self.__dict__:
            obj = self.__dict__[__name]
            if isinstance(obj, ConsumedThingProperty):
                obj.set(value=__value)
                return
            raise AttributeError(f"Cannot set attribute {__name} again to ObjectProxy for {self.id}.")
        raise AttributeError(
            f"Cannot set foreign attribute {__name} to ObjectProxy for {self.id}. Given attribute not found in server object."
        )

    def __repr__(self) -> str:
        return f"ObjectProxy {self.id}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def __eq__(self, other) -> bool:
        if other is self:
            return True
        return isinstance(other, ObjectProxy) and other.id == self.id and other.TD == self.TD

    def __ne__(self, other) -> bool:
        if other and isinstance(other, ObjectProxy):
            return other.id != self.id or other.TD != self.TD
        return True

    def __hash__(self) -> int:
        return hash(self.id)

    # @abstractmethod
    # def is_supported_interaction(self, td, name):
    #     """Returns True if the any of the Forms for the Interaction
    #     with the given name is supported in this Protocol Binding client."""
    #     raise NotImplementedError()

    def invoke_action(self, name: str, *args, **kwargs) -> Any:
        """
        invoke an action specified by name on the server with positional/keyword arguments

        Parameters
        ----------
        name: str
            name of the action
        oneway: bool, optional, default False
            only send an instruction to invoke the action but do not fetch the reply.
            only accepted as keyword argument.
        noblock: bool, optional, default False
            schedule an action invokation but collect the reply later using a reply id.
            only accepted as keyword argument.
        *args: Any
            arguments for the action
        **kwargs: dict[str, Any]
            keyword arguments for the action

        Returns
        -------
        Any
            return value of the action call or a message id if `noblock` is True

        Raises
        ------
        AttributeError
            if action with specified name not found in the Thing Description
        Exception
            server raised exception are propagated
        """
        action = getattr(self, name, None)  # type: ConsumedThingAction
        if not isinstance(action, ConsumedThingAction):
            raise AttributeError(f"No action named {name} in Thing {self.td['id']}")
        oneway = kwargs.pop("oneway", False)
        noblock = kwargs.pop("noblock", False)
        if noblock:
            return action.noblock(*args, **kwargs)
        elif oneway:
            action.oneway(*args, **kwargs)
        else:
            return action(*args, **kwargs)

    async def async_invoke_action(self, name: str, *args, **kwargs) -> Any:
        """
        async(io) call an action specified by name on the server with positional/keyword
        arguments. `noblock` and `oneway` are not supported for async calls.

        Parameters
        ----------
        name: str
            name of the action
        *args: Any
            arguments for the action
        **kwargs: dict[str, Any]
            keyword arguments for the action

        Returns
        -------
        Any
            return value of the action call

        Raises
        ------
        AttributeError
            if action with specified name not found in the Thing Description
        Exception
            server raised exception are propagated
        """
        action = getattr(self, name, None)  # type: ConsumedThingAction
        if not isinstance(action, ConsumedThingAction):
            raise AttributeError(f"No remote action named {name}")
        return await action.async_call(*args, **kwargs)

    def read_property(self, name: str, noblock: bool = False) -> Any:
        """
        read property specified by name on server.

        Parameters
        ----------
        name: str
            name of the property
        noblock: bool, default False
            request the property but collect the reply/value later using a reply id

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        if noblock:
            return prop.noblock_get()
        else:
            return prop.get()

    def write_property(self, name: str, value: Any, oneway: bool = False, noblock: bool = False) -> None:
        """
        write property specified by name on server with given value.

        Parameters
        ----------
        name: str
            name of the property
        value: Any
            value of property to be set
        oneway: bool, default False
            only send an instruction to write the property but do not fetch the reply.
            (irrespective of whether write was successful or not)
        noblock: bool, default False
            request the write property but collect the reply later using a reply id

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        if oneway:
            prop.oneway_set(value)
        elif noblock:
            return prop.noblock_set(value)
        else:
            prop.set(value)

    async def async_read_property(self, name: str) -> Any:
        """
        async(io) read property specified by name on server.
        `noblock` and `oneway` are not supported for async calls.

        Parameters
        ----------
        name: Any
            name of the property to fetch

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        return await prop.async_get()

    async def async_write_property(self, name: str, value: Any) -> None:
        """
        async(io) write property specified by name on server with specified value.
        `noblock` and `oneway` are not supported for async calls.

        Parameters
        ----------
        name: str
            name of the property
        value: Any
            value of the property to be written

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        await prop.async_set(value)

    def read_multiple_properties(self, names: list[str], noblock: bool = False) -> dict[str, Any]:
        """
        read properties specified by list of names.

        Parameters
        ----------
        names: List[str]
            names of properties to be fetched
        noblock: bool, default False
            request the fetch but collect the reply later using a reply id

        Returns
        -------
        dict[str, Any]
            dictionary with names as keys and values corresponding to those keys

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        method = getattr(self, "_get_properties", None)  # type: ConsumedThingAction
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        if noblock:
            return method.noblock(names=names)
        else:
            return method(names=names)

    def write_multiple_properties(
        self,
        oneway: bool = False,
        noblock: bool = False,
        **properties: dict[str, Any],
    ) -> None:
        """
        write properties whose name is specified as keyword arguments

        Parameters
        ----------
        oneway: bool, default False
            only send an instruction to write the property but do not fetch the reply.
            (irrespective of whether write was successful or not)
        noblock: bool, default False
            request the write property but collect the reply later using a reply id
        **properties: Dict[str, Any]
            name and value of properties to be written

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        if len(properties) == 0:
            raise ValueError("no properties given to set_properties")
        method = getattr(self, "_set_properties", None)  # type: ConsumedThingAction
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        if oneway:
            method.oneway(**properties)
        elif noblock:
            return method.noblock(**properties)
        else:
            return method(**properties)

    async def async_read_multiple_properties(self, names: list[str]) -> dict[str, Any]:
        """
        async(io) read properties specified by list of names. `noblock` reads are not supported for asyncio.

        Parameters
        ----------
        names: List[str]
            names of properties to be fetched

        Returns
        -------
        dict[str, Any]
            dictionary with property names as keys and values corresponding to those keys
        """
        # TODO, actually noblock could be fine for async calls too
        method = getattr(self, "_get_properties", None)  # type: ConsumedThingAction
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        return await method.async_call(names=names)

    async def async_write_multiple_properties(self, **properties: dict[str, Any]) -> None:
        """
        async(io) write properties whose name is specified by keys of a dictionary

        Parameters
        ----------
        properties: dict[str, Any]
            name and value of properties to be written

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description
        Exception
            server raised exception are propagated
        """
        if len(properties) == 0:
            raise ValueError("no properties given to set_properties")
        method = getattr(self, "_set_properties", None)  # type: ConsumedThingAction
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        await method.async_call(**properties)

    def observe_property(
        self,
        name: str,
        callbacks: list[Callable] | Callable,
        asynch: bool = False,
        concurrent: bool = False,
        deserialize: bool = True,
    ) -> None:
        """
        observe a property specified by name for change events.

        Parameters
        ----------
        name: str
            name of the property
        callbacks: Callable | List[Callable]
            one or more callbacks that will be executed when the property changes
        asynch: bool
            whether the event should be listened as an asyncio task
        concurrent: bool
            - when asynch is `False`, whether to thread each of the callbacks otherwise the callbacks will be executed serially
            - when asynch is `True`, whether to create a new task for each callback otherwise the callbacks will be awaited serially
        deserialize: bool
            whether to deserialize the event data before passing it to the callbacks

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description or if the property is not observable
        """
        event = getattr(self, f"{name}_change_event", None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No events for property {name} or property not found")
        self.subscribe_event(
            name=f"{name}_change_event",
            callbacks=callbacks,
            asynch=asynch,
            concurrent=concurrent,
            deserialize=deserialize,
        )

    def unobserve_property(self, name: str) -> None:
        """
        Unsubscribe to property specified by name.

        Parameters
        ----------
        name: str
            name of the property

        Raises
        ------
        AttributeError
            if no property with specified name found in the Thing Description or if the property is not observable
        """
        event = getattr(self, f"{name}_change_event", None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No events for property {name} or property not found")
        event.unsubscribe()

    def subscribe_event(
        self,
        name: str,
        callbacks: list[Callable] | Callable,
        asynch: bool = False,
        concurrent: bool = False,
        deserialize: bool = True,
        # create_new_connection: bool = False,
    ) -> None:
        """
        Subscribe to event specified by name. Events are listened in separate threads and supplied callbacks are
        are also called in those threads.

        Parameters
        ----------
        name: str
            name of the event, either the object name used in the server or the name specified in the name argument of
            the Event object
        callbacks: Callable | List[Callable]
            one or more callbacks that will be executed when the event is received
        asynch: bool
            whether the event should be listened as an asyncio task
        concurrent: bool
            - when asynch is `False`, whether to thread the callbacks otherwise the callbacks will be executed serially
            - when asynch is `True`, whether to create a new task for each callback otherwise the callbacks will be awaited serially
        deserialize: bool
            whether to deserialize the event data before passing it to the callbacks

        Raises
        ------
        AttributeError
            if no event with specified name is found
        """
        event = getattr(self, name, None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No event named {name}")
        # TODO: fix the logic below to reuse connections when possible
        # if not create_new_connection:
        # see logic in tag v0.3.2
        event.subscribe(
            callbacks,
            asynch=asynch,
            concurrent=concurrent,
            deserialize=deserialize,
            # create_new_connection=create_new_connection,
        )

    def unsubscribe_event(self, name: str) -> None:
        """
        Unsubscribe to event specified by name.

        Parameters
        ----------
        name: str
            name of the event

        Raises
        ------
        AttributeError
            if no event with specified name is found
        """
        event = getattr(self, name, None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No event named {name}")
        event.unsubscribe()

    def read_reply(self, message_id: str, timeout: float | None = 5.0) -> Any:
        """
        read reply of no block calls of an action or a property read/write.

        Parameters
        ----------
        message_id: str
            id returned by the no block call
        timeout: float, optional, default 5.0
            time to wait for a reply before raising TimeoutError. None waits indefinitely.
        """
        obj = self._noblock_messages.get(message_id, None)
        if not obj:
            raise ValueError("given message id not a one way call or invalid.")
        return obj.read_reply(message_id=message_id, timeout=timeout)

    @property
    def properties(self) -> list[ConsumedThingProperty]:
        """list of properties that were consumed from the Thing Description"""
        return [prop for prop in self.__dict__.values() if isinstance(prop, ConsumedThingProperty)]

    @property
    def actions(self) -> list[ConsumedThingAction]:
        """list of actions that were consumed from the Thing Description"""
        return [action for action in self.__dict__.values() if isinstance(action, ConsumedThingAction)]

    @property
    def events(self) -> list[ConsumedThingEvent]:
        """list of events that were consumed from the Thing Description"""
        return [event for event in self.__dict__.values() if isinstance(event, ConsumedThingEvent)]

    @property
    def thing_id(self) -> str:
        """thing ID this client is connected to"""
        return self.td.get("id", None)

    @property
    def TD(self) -> dict[str, Any]:
        """Thing Description of the consuimed thing"""
        return self.td


__all__ = [ObjectProxy.__name__]
