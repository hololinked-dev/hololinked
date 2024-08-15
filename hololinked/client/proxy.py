import threading 
import warnings
import typing 
import logging
import uuid


from ..server.config import global_config
from ..server.constants import JSON, CommonRPC, ServerMessage, ResourceTypes, ZMQ_PROTOCOLS
from ..server.serializers import BaseSerializer
from ..server.dataklasses import ZMQResource, ServerSentEvent
from ..server.zmq_message_brokers import AsyncZMQClient, SyncZMQClient, EventConsumer, PROXY
from ..server.schema_validators import BaseSchemaValidator


class ObjectProxy:
    """
    Procedural client for ``Thing``/``RemoteObject``. Once connected to a server, properties, methods and events are 
    dynamically populated. Any of the ZMQ protocols of the server is supported. 

    Parameters
    ----------
    instance_name: str
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

    _own_attrs = frozenset([
        '__annotations__',
        'zmq_client', 'async_zmq_client', '_allow_foreign_attributes',
        'identity', 'instance_name', 'logger', 'execution_timeout', 'invokation_timeout', 
        '_execution_timeout', '_invokation_timeout', '_events', '_noblock_messages',
        '_schema_validator'
    ])

    def __init__(self, instance_name : str, protocol : str = ZMQ_PROTOCOLS.IPC, invokation_timeout : float = 5, 
                    load_thing = True, **kwargs) -> None:
        self._allow_foreign_attributes = kwargs.get('allow_foreign_attributes', False)
        self.instance_name = instance_name
        self.invokation_timeout = invokation_timeout
        self.execution_timeout = kwargs.get("execution_timeout", None)
        self.identity = f"{instance_name}|{uuid.uuid4()}"
        self.logger = kwargs.pop('logger', logging.Logger(self.identity, level=kwargs.get('log_level', logging.INFO)))
        self._noblock_messages = dict()
        self._schema_validator = kwargs.get('schema_validator', None)
        # compose ZMQ client in Proxy client so that all sending and receiving is
        # done by the ZMQ client and not by the Proxy client directly. Proxy client only 
        # bothers mainly about __setattr__ and _getattr__
        self.async_zmq_client = None    
        self.zmq_client = SyncZMQClient(instance_name, self.identity, client_type=PROXY, protocol=protocol, 
                                            zmq_serializer=kwargs.get('serializer', None), handshake=load_thing,
                                            logger=self.logger, **kwargs)
        if kwargs.get("async_mixin", False):
            self.async_zmq_client = AsyncZMQClient(instance_name, self.identity + '|async', client_type=PROXY, protocol=protocol, 
                                            zmq_serializer=kwargs.get('serializer', None), handshake=load_thing,
                                            logger=self.logger, **kwargs)
        if load_thing:
            self.load_thing()

    def __getattribute__(self, __name: str) -> typing.Any:
        obj = super().__getattribute__(__name)
        if isinstance(obj, _Property):
            return obj.get()
        return obj

    def __setattr__(self, __name : str, __value : typing.Any) -> None:
        if (__name in ObjectProxy._own_attrs or (__name not in self.__dict__ and 
                isinstance(__value, __allowed_attribute_types__)) or self._allow_foreign_attributes):
            # allowed attribute types are _Property and _RemoteMethod defined after this class
            return super(ObjectProxy, self).__setattr__(__name, __value)
        elif __name in self.__dict__:
            obj = self.__dict__[__name]
            if isinstance(obj, _Property):
                obj.set(value=__value)
                return
            raise AttributeError(f"Cannot set attribute {__name} again to ObjectProxy for {self.instance_name}.")
        raise AttributeError(f"Cannot set foreign attribute {__name} to ObjectProxy for {self.instance_name}. Given attribute not found in server object.")

    def __repr__(self) -> str:
        return f'ObjectProxy {self.identity}'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def __bool__(self) -> bool: 
        try: 
            self.zmq_client.handshake(num_of_tries=10)
            return True
        except RuntimeError:
            return False

    def __eq__(self, other) -> bool:
        if other is self:
            return True
        return (isinstance(other, ObjectProxy) and other.instance_name == self.instance_name and 
                other.zmq_client.protocol == self.zmq_client.protocol)

    def __ne__(self, other) -> bool:
        if other and isinstance(other, ObjectProxy):
            return (other.instance_name != self.instance_name or 
                    other.zmq_client.protocol != self.zmq_client.protocol)
        return True

    def __hash__(self) -> int:
        return hash(self.identity)
    
    def get_invokation_timeout(self) -> typing.Union[float, int]:
        return self._invokation_timeout 
    
    def set_invokation_timeout(self, value : typing.Union[float, int]) -> None:
        if not isinstance(value, (float, int, type(None))):
            raise TypeError(f"Timeout can only be float or int greater than 0, or None. Given type {type(value)}.")
        elif value is not None and value < 0:
            raise ValueError("Timeout must be at least 0 or None, not negative.")
        self._invokation_timeout = value
    
    invokation_timeout = property(fget=get_invokation_timeout, fset=set_invokation_timeout,
                        doc="Timeout in seconds on server side for invoking a method or read/write property. \
                                Defaults to 5 seconds and network times not considered."
    )

    def get_execution_timeout(self) -> typing.Union[float, int]:
        return self._execution_timeout 
    
    def set_execution_timeout(self, value : typing.Union[float, int]) -> None:
        if not isinstance(value, (float, int, type(None))):
            raise TypeError(f"Timeout can only be float or int greater than 0, or None. Given type {type(value)}.")
        elif value is not None and value < 0:
            raise ValueError("Timeout must be at least 0 or None, not negative.")
        self._execution_timeout = value
    
    execution_timeout = property(fget=get_execution_timeout, fset=set_execution_timeout,
                            doc="Timeout in seconds on server side for execution of method or read/write property." +
                                "Starts ticking after invokation timeout completes." + 
                                "Defaults to None (i.e. waits indefinitely until return) and network times not considered."
    )


    def invoke_action(self, method : str, oneway : bool = False, noblock : bool = False, 
                                *args, **kwargs) -> typing.Any:
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
        method = getattr(self, method, None) # type: _RemoteMethod 
        if not isinstance(method, _RemoteMethod):
            raise AttributeError(f"No remote method named {method}")
        if oneway:
            method.oneway(*args, **kwargs)
        elif noblock:
            msg_id = method.noblock(*args, **kwargs)
            self._noblock_messages[msg_id] = method
            return msg_id
        else:
            return method(*args, **kwargs)


    async def async_invoke_action(self, method : str, *args, **kwargs) -> typing.Any:
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
        method = getattr(self, method, None) # type: _RemoteMethod 
        if not isinstance(method, _RemoteMethod):
            raise AttributeError(f"No remote method named {method}")
        return await method.async_call(*args, **kwargs)


    def read_property(self, name : str, noblock : bool = False) -> typing.Any:
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
        prop = self.__dict__.get(name, None) # type: _Property
        if not isinstance(prop, _Property):
            raise AttributeError(f"No property named {prop}")
        if noblock:
            msg_id = prop.noblock_get()
            self._noblock_messages[msg_id] = prop
            return msg_id
        else:
            return prop.get()


    def write_property(self, name : str, value : typing.Any, oneway : bool = False, 
                        noblock : bool = False) -> None:
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
        prop = self.__dict__.get(name, None) # type: _Property
        if not isinstance(prop, _Property):
            raise AttributeError(f"No property named {prop}")
        if oneway:
            prop.oneway_set(value)
        elif noblock:
            msg_id = prop.noblock_set(value)
            self._noblock_messages[msg_id] = prop
            return msg_id
        else:
            prop.set(value)


    async def async_read_property(self, name : str) -> None:
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
        prop = self.__dict__.get(name, None) # type: _Property
        if not isinstance(prop, _Property):
            raise AttributeError(f"No property named {prop}")
        return await prop.async_get()
    

    async def async_write_property(self, name : str, value : typing.Any) -> None:
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
        prop = self.__dict__.get(name, None) # type: _Property
        if not isinstance(prop, _Property):
            raise AttributeError(f"No property named {prop}")
        await prop.async_set(value)


    def read_multiple_properties(self, names : typing.List[str], noblock : bool = False) -> typing.Any:
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
        method = getattr(self, '_get_properties', None) # type: _RemoteMethod
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        if noblock:
            msg_id = method.noblock(names=names)
            self._noblock_messages[msg_id] = method
            return msg_id
        else:
            return method(names=names)
        
    
    def write_multiple_properties(self, oneway : bool = False, noblock : bool = False,
                       **properties : typing.Dict[str, typing.Any]) -> None:
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
        method = getattr(self, '_set_properties', None) # type: _RemoteMethod
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        if oneway:
            method.oneway(**properties)
        elif noblock:
            msg_id = method.noblock(**properties)
            self._noblock_messages[msg_id] = method
            return msg_id
        else:
            return method(**properties)
        

    async def async_read_multiple_properties(self, names) -> None:
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
        method = getattr(self, '_get_properties', None) # type: _RemoteMethod
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        return await method.async_call(names=names)


    async def async_write_multiple_properties(self, **properties) -> None:
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
        method = getattr(self, '_set_properties', None) # type: _RemoteMethod
        if not method:
            raise RuntimeError("Client did not load server resources correctly. Report issue at github.")
        await method.async_call(**properties)


    def subscribe_event(self, name : str, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable],
                        thread_callbacks : bool = False, deserialize : bool = True) -> None:
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
        
        Raises
        ------
        AttributeError: 
            if no event with specified name is found
        """
        event = getattr(self, name, None) # type: _Event
        if not isinstance(event, _Event):
            raise AttributeError(f"No event named {name}")
        event._deserialize = deserialize
        if event._subscribed:
            event.add_callbacks(callbacks)
        else: 
            event.subscribe(callbacks, thread_callbacks, deserialize)
       

    def unsubscribe_event(self, name : str):
        """
        Unsubscribe to event specified by name. 

        Parameters
        ----------
        name: str
            name of the event 
        callbacks: Callable | List[Callable]
            one or more callbacks that will be executed when this event is received
        thread_callbacks: bool
            thread the callbacks otherwise the callbacks will be executed serially
        
        Raises
        ------
        AttributeError: 
            if no event with specified name is found
        """
        event = getattr(self, name, None) # type: _Event
        if not isinstance(event, _Event):
            raise AttributeError(f"No event named {name}")
        event.unsubscribe()

    
    def read_reply(self, message_id : bytes, timeout : typing.Optional[float] = 5000) -> typing.Any:
        """
        read reply of no block calls of an action or a property read/write.
        """
        obj = self._noblock_messages.get(message_id, None) 
        if not obj:
            raise ValueError('given message id not a one way call or invalid.')
        reply = self.zmq_client._reply_cache.get(message_id, None)
        if not reply: 
            reply = self.zmq_client.recv_reply(message_id=message_id, timeout=timeout,
                                    raise_client_side_exception=True)
        if not reply:
            raise ReplyNotArrivedError(f"could not fetch reply within timeout for message id '{message_id}'")
        if isinstance(obj, _RemoteMethod):
            obj._last_return_value = reply 
            return obj.last_return_value # note the missing underscore
        elif isinstance(obj, _Property):
            obj._last_value = reply 
            return obj.last_read_value


    def load_thing(self):
        """
        Get exposed resources from server (methods, properties, events) and remember them as attributes of the proxy.
        """
        fetch = _RemoteMethod(self.zmq_client, CommonRPC.zmq_resource_read(instance_name=self.instance_name), 
                                    invokation_timeout=self._invokation_timeout) # type: _RemoteMethod
        reply = fetch() # type: typing.Dict[str, typing.Dict[str, typing.Any]]

        for name, data in reply.items():
            if isinstance(data, dict):
                try:
                    if data["what"] == ResourceTypes.EVENT:
                        data = ServerSentEvent(**data)
                    else:
                        data = ZMQResource(**data)
                except Exception as ex:
                    ex.add_note("Did you correctly configure your serializer? " + 
                            "This exception occurs when given serializer does not work the same way as server serializer")
                    raise ex from None
            elif not isinstance(data, (ZMQResource, ServerSentEvent)):
                raise RuntimeError("Logic error - deserialized info about server not instance of hololinked.server.data_classes.ZMQResource")
            if data.what == ResourceTypes.ACTION:
                _add_method(self, _RemoteMethod(self.zmq_client, data.instruction, self.invokation_timeout, 
                                                self.execution_timeout, data.argument_schema, self.async_zmq_client, self._schema_validator), data)
            elif data.what == ResourceTypes.PROPERTY:
                _add_property(self, _Property(self.zmq_client, data.instruction, self.invokation_timeout,
                                                self.execution_timeout, self.async_zmq_client), data)
            elif data.what == ResourceTypes.EVENT:
                assert isinstance(data, ServerSentEvent)
                event = _Event(self.zmq_client, data.name, data.obj_name, data.unique_identifier, data.socket_address, 
                            serialization_specific=data.serialization_specific, serializer=self.zmq_client.zmq_serializer, logger=self.logger)
                _add_event(self, event, data)
                self.__dict__[data.name] = event 


    


# SM = Server Message
SM_INDEX_ADDRESS = ServerMessage.ADDRESS.value
SM_INDEX_SERVER_TYPE = ServerMessage.SERVER_TYPE.value
SM_INDEX_MESSAGE_TYPE = ServerMessage.MESSAGE_TYPE.value
SM_INDEX_MESSAGE_ID = ServerMessage.MESSAGE_ID.value
SM_INDEX_DATA = ServerMessage.DATA.value
SM_INDEX_ENCODED_DATA = ServerMessage.ENCODED_DATA.value

class _RemoteMethod:
    
    __slots__ = ['_zmq_client', '_async_zmq_client', '_instruction', '_invokation_timeout', '_execution_timeout',
                 '_schema', '_schema_validator', '_last_return_value', '__name__', '__qualname__', '__doc__']
    # method call abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, sync_client : SyncZMQClient, instruction : str, invokation_timeout : typing.Optional[float] = 5, 
                    execution_timeout : typing.Optional[float] = None, argument_schema : typing.Optional[JSON] = None,
                    async_client : typing.Optional[AsyncZMQClient] = None, 
                    schema_validator : typing.Optional[typing.Type[BaseSchemaValidator]] = None) -> None:
        """
        Parameters
        ----------
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_zmq_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        instruction: str
            The instruction needed to call the method        
        """
        self._zmq_client = sync_client
        self._async_zmq_client = async_client
        self._instruction = instruction
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._schema = argument_schema
        self._schema_validator = schema_validator(self._schema) if schema_validator and argument_schema and global_config.validate_schema_on_client else None
    
    @property # i.e. cannot have setter
    def last_return_value(self):
        """
        cached return value of the last call to the method
        """
        if len(self._last_return_value[SM_INDEX_ENCODED_DATA]) > 0:
            return self._last_return_value[SM_INDEX_ENCODED_DATA]
        return self._last_return_value[SM_INDEX_DATA]
    
    @property
    def last_zmq_message(self) -> typing.List:
        return self._last_return_value
    
    def __call__(self, *args, **kwargs) -> typing.Any:
        """
        execute method on server
        """
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._last_return_value = self._zmq_client.execute(instruction=self._instruction, arguments=kwargs, 
                                    invokation_timeout=self._invokation_timeout, execution_timeout=self._execution_timeout,
                                    raise_client_side_exception=True, argument_schema=self._schema)
        return self.last_return_value # note the missing underscore
    
    def oneway(self, *args, **kwargs) -> None:
        """
        only issues the method call to the server and does not wait for reply,
        neither does the server reply to this call.  
        """
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._zmq_client.send_instruction(instruction=self._instruction, arguments=kwargs, 
                                        invokation_timeout=self._invokation_timeout, execution_timeout=None,
                                        context=dict(oneway=True), argument_schema=self._schema)

    def noblock(self, *args, **kwargs) -> None:
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        return self._zmq_client.send_instruction(instruction=self._instruction, arguments=kwargs, 
                                invokation_timeout=self._invokation_timeout, execution_timeout=self._execution_timeout,
                                argument_schema=self._schema)
     
    async def async_call(self, *args, **kwargs):
        """
        async execute method on server
        """
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._last_return_value = await self._async_zmq_client.async_execute(instruction=self._instruction, 
                                        arguments=kwargs, invokation_timeout=self._invokation_timeout, 
                                        raise_client_side_exception=True,
                                        argument_schema=self._schema)
        return self.last_return_value # note the missing underscore

    
class _Property:

    __slots__ = ['_zmq_client', '_async_zmq_client', '_read_instruction', '_write_instruction', 
                '_invokation_timeout', '_execution_timeout', '_last_value', '__name__', '__doc__']   
    # property get set abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, client : SyncZMQClient, instruction : str, invokation_timeout : typing.Optional[float] = 5, 
                    execution_timeout : typing.Optional[float] = None, async_client : typing.Optional[AsyncZMQClient] = None) -> None:
        self._zmq_client = client
        self._async_zmq_client = async_client
        self._invokation_timeout = invokation_timeout
        self._execution_timeout = execution_timeout
        self._read_instruction = instruction + '/read'
        self._write_instruction = instruction + '/write'

    @property # i.e. cannot have setter
    def last_read_value(self) -> typing.Any:
        """
        cache of last read value
        """
        if len(self._last_value[SM_INDEX_ENCODED_DATA]) > 0:
            return self._last_value[SM_INDEX_ENCODED_DATA]
        return self._last_value[SM_INDEX_DATA]
    
    @property
    def last_zmq_message(self) -> typing.List:
        """
        cache of last message received for this property
        """
        return self._last_value
    
    def set(self, value : typing.Any) -> None:
        self._last_value = self._zmq_client.execute(self._write_instruction, dict(value=value),
                                                        raise_client_side_exception=True)
     
    def get(self) -> typing.Any:
        self._last_value = self._zmq_client.execute(self._read_instruction, 
                                                invokation_timeout=self._invokation_timeout, 
                                                raise_client_side_exception=True)
        return self.last_read_value 
    
    async def async_set(self, value : typing.Any) -> None:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        self._last_value = await self._async_zmq_client.async_execute(self._write_instruction, dict(value=value),
                                                        invokation_timeout=self._invokation_timeout, 
                                                        execution_timeout=self._execution_timeout,
                                                        raise_client_side_exception=True)
    
    async def async_get(self) -> typing.Any:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        self._last_value = await self._async_zmq_client.async_execute(self._read_instruction,
                                                invokation_timeout=self._invokation_timeout, 
                                                execution_timeout=self._execution_timeout,
                                                raise_client_side_exception=True)
        return self.last_read_value 
    
    def noblock_get(self) -> None:
        return self._zmq_client.send_instruction(self._read_instruction,
                                            invokation_timeout=self._invokation_timeout, 
                                            execution_timeout=self._execution_timeout)
    
    def noblock_set(self, value : typing.Any) -> None:
        return self._zmq_client.send_instruction(self._write_instruction, dict(value=value), 
                                            invokation_timeout=self._invokation_timeout, 
                                            execution_timeout=self._execution_timeout)
    
    def oneway_set(self, value : typing.Any) -> None:
        self._zmq_client.send_instruction(self._write_instruction, dict(value=value), 
                                            invokation_timeout=self._invokation_timeout, 
                                            execution_timeout=self._execution_timeout)
  


class _Event:
    
    __slots__ = ['_zmq_client', '_name', '_obj_name', '_unique_identifier', '_socket_address', '_callbacks', '_serialization_specific',
                    '_serializer', '_subscribed', '_thread', '_thread_callbacks', '_event_consumer', '_logger', '_deserialize']
    # event subscription
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, client : SyncZMQClient, name : str, obj_name : str, unique_identifier : str, socket : str, 
                    serialization_specific : bool = False, serializer : BaseSerializer = None, logger : logging.Logger = None) -> None:
        self._zmq_client = client
        self._name = name
        self._obj_name = obj_name
        self._unique_identifier = unique_identifier
        self._socket_address = socket
        self._serialization_specific = serialization_specific
        self._callbacks = None 
        self._serializer = serializer
        self._logger = logger 
        self._subscribed = False
        self._deserialize = True

    def add_callbacks(self, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable]) -> None:
        if not self._callbacks:
            self._callbacks = [] 
        if isinstance(callbacks, list):
            self._callbacks.extend(callbacks)
        else:
            self._callbacks.append(callbacks)

    def subscribe(self, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable], 
                    thread_callbacks : bool = False, deserialize : bool = True) -> None:
        self._event_consumer = EventConsumer(
                                    'zmq-' + self._unique_identifier if self._serialization_specific else self._unique_identifier, 
                                    self._socket_address, f"{self._name}|RPCEvent|{uuid.uuid4()}", b'PROXY',
                                    zmq_serializer=self._serializer, logger=self._logger
                                )
        self.add_callbacks(callbacks) 
        self._subscribed = True
        self._deserialize = deserialize
        self._thread_callbacks = thread_callbacks
        self._thread = threading.Thread(target=self.listen)
        self._thread.start()

    def listen(self):
        while self._subscribed:
            try:
                data = self._event_consumer.receive(deserialize=self._deserialize)
                if data == 'INTERRUPT':
                    break
                for cb in self._callbacks: 
                    if not self._thread_callbacks:
                        cb(data)
                    else: 
                        threading.Thread(target=cb, args=(data,)).start()
            except Exception as ex:
                print(ex)
                warnings.warn(f"Uncaught exception from {self._name} event - {str(ex)}", 
                                category=RuntimeWarning)
        try:
            self._event_consumer.exit()
        except:
            pass
       

    def unsubscribe(self, join_thread : bool = True):
        self._subscribed = False
        self._event_consumer.interrupt()
        if join_thread:
            self._thread.join()
            
            



__allowed_attribute_types__ = (_Property, _RemoteMethod, _Event)
__WRAPPER_ASSIGNMENTS__ =  ('__name__', '__qualname__', '__doc__')

def _add_method(client_obj : ObjectProxy, method : _RemoteMethod, func_info : ZMQResource) -> None:
    if not func_info.top_owner:
        return 
        raise RuntimeError("logic error")
    for dunder in __WRAPPER_ASSIGNMENTS__:
        if dunder == '__qualname__':
            info = '{}.{}'.format(client_obj.__class__.__name__, func_info.get_dunder_attr(dunder).split('.')[1])
        else:
            info = func_info.get_dunder_attr(dunder)
        setattr(method, dunder, info)
    client_obj.__setattr__(func_info.obj_name, method)

def _add_property(client_obj : ObjectProxy, property : _Property, property_info : ZMQResource) -> None:
    if not property_info.top_owner:
        return
        raise RuntimeError("logic error")
    for attr in ['__doc__', '__name__']: 
        # just to imitate _add_method logic
        setattr(property, attr, property_info.get_dunder_attr(attr))
    client_obj.__setattr__(property_info.obj_name, property)

def _add_event(client_obj : ObjectProxy, event : _Event, event_info : ServerSentEvent) -> None:
    setattr(client_obj, event_info.obj_name, event)
    


class ReplyNotArrivedError(Exception):
    pass 


__all__ = ['ObjectProxy']

