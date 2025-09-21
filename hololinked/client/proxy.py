import typing
import logging
import base64

from .abstractions import ConsumedThingAction, ConsumedThingProperty, ConsumedThingEvent
from .factory import ClientFactory


class ObjectProxy:
    """
    Procedural client for ``Thing``/``RemoteObject``. Once connected to a server, properties, methods and events are
    dynamically populated. Any of the ZMQ protocols of the server is supported.

    Parameters
    ----------
    id: str
        instance name of the server to connect.
    invokation_timeout: float, int
        timeout to schedule a method call or property read/write in server. execution time wait is controlled by
        ``execution_timeout``. When invokation timeout expires, the method is not executed.
    execution_timeout: float, int
        timeout to return without a reply after scheduling a method call or property read/write. This timer starts
        ticking only after the method has started to execute. Returning a call before end of execution can lead to
        change of state in the server.
    load_thing: bool, default True
        when True, remote object is located and its resources are loaded. Otherwise, only the client is initialised.
    protocol: str
        ZMQ protocol used to connect to server. Unlike the server, only one can be specified.
    **kwargs:
        async_mixin: bool, default False
            whether to use both synchronous and asynchronous clients.
        serializer: BaseSerializer
            use a custom serializer, must be same as the serializer supplied to the server.
        schema_validator: BaseSchemaValidator
            use a schema validator, must be same as the schema validator supplied to the server.
        allow_foreign_attributes: bool, default False
            allows local attributes for proxy apart from properties fetched from the server.
        logger: logging.Logger
            logger instance
        log_level: int
            log level corresponding to logging.Logger when internally created
        handshake_timeout: int
            time in milliseconds to search & handshake server remote object. raises Timeout when expired
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
            "_auth_header",
        ]
    )

    def __init__(self, id: str, **kwargs) -> None:
        self._allow_foreign_attributes = kwargs.get("allow_foreign_attributes", False)
        self._noblock_messages = dict()  # type: typing.Dict[str, ConsumedThingAction | ConsumedThingProperty]
        self._schema_validator = kwargs.get("schema_validator", None)
        self.id = id
        self.logger = kwargs.pop(
            "logger",
            logging.Logger(self.id, level=kwargs.get("log_level", logging.INFO)),
        )
        self.invokation_timeout = kwargs.get("invokation_timeout", 5)
        self.execution_timeout = kwargs.get("execution_timeout", 5)
        self.td = kwargs.get("td", dict())  # type: typing.Dict[str, typing.Any]
        # compose ZMQ client in Proxy client so that all sending and receiving is
        # done by the ZMQ client and not by the Proxy client directly. Proxy client only
        # bothers mainly about __setattr__ and _getattr__
        # ClientFactory.zmq(self, **kwargs)
        self._auth_header = None
        username = kwargs.get("username")
        password = kwargs.get("password")
        if username and password:
            token = f"{username}:{password}".encode("utf-8")
            self._auth_header = {"Authorization": f"Basic {base64.b64encode(token).decode('utf-8')}"}

    def __getattribute__(self, __name: str) -> typing.Any:
        obj = super().__getattribute__(__name)
        if isinstance(obj, ConsumedThingProperty):
            return obj.get()
        return obj

    def __setattr__(self, __name: str, __value: typing.Any) -> None:
        if (
            __name in ObjectProxy._own_attrs
            or (__name not in self.__dict__ and isinstance(__value, ClientFactory.__allowed_attribute_types__))
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

    def __bool__(self) -> bool:
        raise NotImplementedError("Cannot convert ObjectProxy to bool. Use is_connected() instead.")
        # try:
        #     self.zmq_client.handshake(num_of_tries=10)
        #     return True
        # except RuntimeError:
        #     return False

    def __eq__(self, other) -> bool:
        if other is self:
            return True
        return (
            isinstance(other, ObjectProxy)
            and other.id == self.id
            and other.zmq_client.protocol == self.zmq_client.protocol
        )

    def __ne__(self, other) -> bool:
        if other and isinstance(other, ObjectProxy):
            return other.id != self.id or other.zmq_client.protocol != self.zmq_client.protocol
        return True

    def __hash__(self) -> int:
        return hash(self.id)

    def get_invokation_timeout(self) -> typing.Union[float, int]:
        return self._invokation_timeout

    def set_invokation_timeout(self, value: typing.Union[float, int]) -> None:
        if not isinstance(value, (float, int, type(None))):
            raise TypeError(f"Timeout can only be float or int greater than 0, or None. Given type {type(value)}.")
        elif value is not None and value < 0:
            raise ValueError("Timeout must be at least 0 or None, not negative.")
        self._invokation_timeout = value

    invokation_timeout = property(
        fget=get_invokation_timeout,
        fset=set_invokation_timeout,
        doc="Timeout in seconds on server side for invoking a method or read/write property. \
                                Defaults to 5 seconds and network times not considered.",
    )

    def get_execution_timeout(self) -> typing.Union[float, int]:
        return self._execution_timeout

    def set_execution_timeout(self, value: typing.Union[float, int]) -> None:
        if not isinstance(value, (float, int, type(None))):
            raise TypeError(f"Timeout can only be float or int greater than 0, or None. Given type {type(value)}.")
        elif value is not None and value < 0:
            raise ValueError("Timeout must be at least 0 or None, not negative.")
        self._execution_timeout = value

    execution_timeout = property(
        fget=get_execution_timeout,
        fset=set_execution_timeout,
        doc="Timeout in seconds on server side for execution of method or read/write property."
        + "Starts ticking after invokation timeout completes."
        + "Defaults to None (i.e. waits indefinitely until return) and network times not considered.",
    )

    # @abstractmethod
    # def is_supported_interaction(self, td, name):
    #     """Returns True if the any of the Forms for the Interaction
    #     with the given name is supported in this Protocol Binding client."""
    #     raise NotImplementedError()

    def invoke_action(self, name: str, *args, **kwargs) -> typing.Any:
        """
        call a method specified by name on the server with positional/keyword arguments

        Parameters
        ----------
        method: str
            name of the method
        oneway: bool, default False
            only send an instruction to invoke the method but do not fetch the reply.
        noblock: bool, default False
            request a method call but collect the reply later using a reply id
        *args: Any
            arguments for the method
        **kwargs: Dict[str, Any]
            keyword arguments for the method

        Returns
        -------
        Any
            return value of the method call or an id if noblock is True

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
            server raised exception are propagated
        """
        method = getattr(self, name, None)  # type: ConsumedThingAction
        if not isinstance(method, ConsumedThingAction):
            raise AttributeError(f"No remote method named {name} in Thing {self.td['id']}")
        oneway = kwargs.pop("oneway", False)
        noblock = kwargs.pop("noblock", False)
        if noblock:
            return method.noblock(*args, **kwargs)
        elif oneway:
            method.oneway(*args, **kwargs)
        else:
            return method(*args, **kwargs)

    async def async_invoke_action(self, name: str, *args, **kwargs) -> typing.Any:
        """
        async(io) call a method specified by name on the server with positional/keyword
        arguments. noblock and oneway not supported for async calls.

        Parameters
        ----------
        method: str
            name of the method
        *args: Any
            arguments for the method
        **kwargs: Dict[str, Any]
            keyword arguments for the method

        Returns
        -------
        Any
            return value of the method call

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        RuntimeError:
            if async_mixin was False at ``__init__()`` - no asynchronous client was created
        Exception:
            server raised exception are propagated
        """
        method = getattr(self, name, None)  # type: ConsumedThingAction
        if not isinstance(method, ConsumedThingAction):
            raise AttributeError(f"No remote method named {name}")
        return await method.async_call(*args, **kwargs)

    def read_property(self, name: str, noblock: bool = False) -> typing.Any:
        """
        get property specified by name on server.

        Parameters
        ----------
        name: str
            name of the property
        noblock: bool, default False
            request the property get but collect the reply/value later using a reply id

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        if noblock:
            return prop.noblock_get()
        else:
            return prop.get()

    def write_property(self, name: str, value: typing.Any, oneway: bool = False, noblock: bool = False) -> None:
        """
        set property specified by name on server with specified value.

        Parameters
        ----------
        name: str
            name of the property
        value: Any
            value of property to be set
        oneway: bool, default False
            only send an instruction to set the property but do not fetch the reply.
            (irrespective of whether set was successful or not)
        noblock: bool, default False
            request the set property but collect the reply later using a reply id

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
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

    async def async_read_property(self, name: str) -> None:
        """
        async(io) get property specified by name on server.

        Parameters
        ----------
        name: Any
            name of the property to fetch

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        return await prop.async_get()

    async def async_write_property(self, name: str, value: typing.Any) -> None:
        """
        async(io) set property specified by name on server with specified value.
        noblock and oneway not supported for async calls.

        Parameters
        ----------
        name: str
            name of the property
        value: Any
            value of property to be set

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
            server raised exception are propagated
        """
        prop = self.__dict__.get(name, None)  # type: ConsumedThingProperty
        if not isinstance(prop, ConsumedThingProperty):
            raise AttributeError(f"No property named {name}")
        await prop.async_set(value)

    def read_multiple_properties(self, names: typing.List[str], noblock: bool = False) -> typing.Any:
        """
        get properties specified by list of names.

        Parameters
        ----------
        names: List[str]
            names of properties to be fetched
        noblock: bool, default False
            request the fetch but collect the reply later using a reply id

        Returns
        -------
        Dict[str, Any]:
            dictionary with names as keys and values corresponding to those keys
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
        **properties: typing.Dict[str, typing.Any],
    ) -> None:
        """
        set properties whose name is specified by keys of a dictionary

        Parameters
        ----------
        oneway: bool, default False
            only send an instruction to set the property but do not fetch the reply.
            (irrespective of whether set was successful or not)
        noblock: bool, default False
            request the set property but collect the reply later using a reply id
        **properties: Dict[str, Any]
            name and value of properties to be set

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
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

    async def async_read_multiple_properties(self, names: typing.List[str]) -> None:
        """
        async(io) get properties specified by list of names. no block gets are not supported for asyncio.

        Parameters
        ----------
        names: List[str]
            names of properties to be fetched

        Returns
        -------
        Dict[str, Any]:
            dictionary with property names as keys and values corresponding to those keys
        """
        method = getattr(self, "_get_properties", None)  # type: ConsumedThingAction
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        return await method.async_call(names=names)

    async def async_write_multiple_properties(self, **properties: dict[str, typing.Any]) -> None:
        """
        async(io) set properties whose name is specified by keys of a dictionary

        Parameters
        ----------
        values: Dict[str, Any]
            name and value of properties to be set

        Raises
        ------
        AttributeError:
            if no method with specified name found on the server
        Exception:
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
        callbacks: typing.Union[typing.List[typing.Callable], typing.Callable],
        asynch: bool = False,
        concurrent: bool = False,
        deserialize: bool = True,
    ) -> None:
        event = getattr(self, f"{name}_change_event", None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No events for property {name}")
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
        callbacks: Callable | List[Callable]
            one or more callbacks that will be executed
        thread_callbacks: bool
            thread the callbacks otherwise the callbacks will be executed serially
        """
        event = getattr(self, f"{name}_change_event", None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No events for property {name}")
        event.unsubscribe()

    def subscribe_event(
        self,
        name: str,
        callbacks: typing.Union[typing.List[typing.Callable], typing.Callable],
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
            one or more callbacks that will be executed when this event is received
        thread_callbacks: bool
            thread the callbacks otherwise the callbacks will be executed serially
        deserialize: bool
            whether to deserialize the event data before passing it to the callbacks

        Raises
        ------
        AttributeError:
            if no event with specified name is found
        """
        event = getattr(self, name, None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No event named {name}")
        # TODO: fix the logic below to reuse connections when possible
        # if not create_new_connection:
        #     for task_id, subscribed in event._subscribed.items():
        #         if isinstance(task_id, int) and not asynch and subscribed:
        #             event.add_callbacks(callbacks, asynch=asynch)
        #             return
        #         elif isinstance(task_id, str) and asynch and subscribed:
        #             event.add_callbacks(callbacks, asynch=asynch)
        #             return
        #         # or create a new connection
        event.subscribe(
            callbacks,
            asynch=asynch,
            concurrent=concurrent,
            deserialize=deserialize,
            # create_new_connection=create_new_connection,
        )

    def unsubscribe_event(self, name: str):
        """
        Unsubscribe to event specified by name.

        Parameters
        ----------
        name: str
            name of the event

        Raises
        ------
        AttributeError:
            if no event with specified name is found
        """
        event = getattr(self, name, None)  # type: ConsumedThingEvent
        if not isinstance(event, ConsumedThingEvent):
            raise AttributeError(f"No event named {name}")
        event.unsubscribe()

    def read_reply(self, message_id: str, timeout: typing.Optional[float] = 5000) -> typing.Any:
        """
        read reply of no block calls of an action or a property read/write.
        """
        obj = self._noblock_messages.get(message_id, None)
        if not obj:
            raise ValueError("given message id not a one way call or invalid.")
        return obj.read_reply(message_id=message_id, timeout=timeout)

    @property
    def properties(self) -> typing.List[ConsumedThingProperty]:
        """
        list of properties in the server object
        """
        return [prop for prop in self.__dict__.values() if isinstance(prop, ConsumedThingProperty)]

    @property
    def actions(self) -> typing.List[ConsumedThingAction]:
        """
        list of actions in the server object
        """
        return [action for action in self.__dict__.values() if isinstance(action, ConsumedThingAction)]

    @property
    def events(self) -> typing.List[ConsumedThingEvent]:
        """
        list of events in the server object
        """
        return [event for event in self.__dict__.values() if isinstance(event, ConsumedThingEvent)]

    @property
    def thing_id(self) -> str:
        """
        id of the server object
        """
        return self.td.get("id", None)

    @property
    def TD(self) -> typing.Dict[str, typing.Any]:
        """
        Thing description of the server object
        """
        return self.td


__all__ = [ObjectProxy.__name__]
