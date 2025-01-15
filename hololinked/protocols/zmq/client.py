import logging
import typing
import threading
import warnings
from uuid import uuid4

from ...constants import Operations
from ...serializers import BaseSerializer, Serializers
from ...serializers.payloads import SerializableData, PreserializedData
from ...td import PropertyAffordance, ActionAffordance, EventAffordance
from ...client.abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty, raise_local_exception
from .message import ResponseMessage
from .message import EMPTY_BYTE, REPLY, TIMEOUT, ERROR, INVALID_MESSAGE
from .brokers import SyncZMQClient, AsyncZMQClient, EventConsumer


__error_message_types__ = [TIMEOUT, ERROR, INVALID_MESSAGE]



class ZMQConsumedAffordanceMixin:

    _last_zmq_response: ResponseMessage

    def get_last_return_value(self, raise_exception: bool = False) -> typing.Any:
        """
        cached return value of the last call to the method
        """
        payload = self._last_zmq_response.payload.deserialize()
        preserialized_payload = self._last_zmq_response.preserialized_payload.value
        if self._last_zmq_response.type in __error_message_types__ and raise_exception:
            raise_local_exception(payload)
        if preserialized_payload != EMPTY_BYTE:
            if payload is None:
                return preserialized_payload
            return payload, preserialized_payload
        return payload
    
    @property
    def last_zmq_response(self) -> ResponseMessage:
        """
        cache of last message received for this property
        """
        return self._last_zmq_response
    



class ZMQAction(ConsumedThingAction, ZMQConsumedAffordanceMixin):
    
    __slots__ = ['_zmq_client', '_async_zmq_client', '_invokation_timeout', '_execution_timeout',
                '_schema_validator', '_last_return_value', 
                '_thing_execution_context' 
                ]
    # method call abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, 
                resource: ActionAffordance, 
                sync_client: SyncZMQClient, 
                async_client: AsyncZMQClient | None = None,  
                **kwargs
                # schema_validator: typing.Type[BaseSchemaValidator] | None = None
            ) -> None:
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
        super().__init__(resource, **kwargs)
        self._zmq_client = sync_client
        self._async_zmq_client = async_client
        self._invokation_timeout = kwargs.get('invokation_timeout', 5)
        self._execution_timeout = kwargs.get('execution_timeout', 5)
        self._thing_execution_context = dict(fetch_execution_logs=False) 
   
    last_return_value = property(fget=ZMQConsumedAffordanceMixin.get_last_return_value,
                                doc="cached return value of the last call to the method")
    
    def __call__(self, *args, **kwargs) -> typing.Any:
        """
        execute method/action on server
        """
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._last_zmq_response = self._zmq_client.execute(
                                            thing_id=self._resource.thing_id,
                                            objekt=self._resource.name,
                                            operation=Operations.invokeAction,
                                            payload=SerializableData(kwargs, content_type=self.invokation_form['contentType']), 
                                            server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout, 
                                                    execution_timeout=self._execution_timeout
                                                ),
                                            thing_execution_context=self._thing_execution_context
                                        )
        return self.get_last_return_value(True)
    
    def oneway(self, *args, **kwargs) -> None:
        """
        only issues the method call to the server and does not wait for reply,
        neither does the server reply to this call.  
        """
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._zmq_client.send_request(
                                    thing_id=self._resource.thing_id, 
                                    objekt=self._resource.name,
                                    operation=Operations.invokeAction,
                                    payload=SerializableData(kwargs, content_type=self.invokation_form['contentType']), 
                                    server_execution_context=dict(
                                            invokation_timeout=self._invokation_timeout, 
                                            execution_timeout=self._execution_timeout,
                                            oneway=True
                                        ),
                                    thing_execution_context=self._thing_execution_context
                                )

    def noblock(self, *args, **kwargs) -> str:
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        return self._zmq_client.send_request(
                                    thing_id=self._resource.thing_id, 
                                    objekt=self._resource.name,
                                    operation=Operations.invokeAction,
                                    payload=SerializableData(kwargs, content_type=self.invokation_form['contentType']),
                                    server_execution_context=dict(
                                        invokation_timeout=self._invokation_timeout, 
                                        execution_timeout=self._execution_timeout,
                                    ),
                                    thing_execution_context=self._thing_execution_context    
                                )
     
    async def async_call(self, *args, **kwargs) -> typing.Any:
        """
        async execute method on server
        """
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set True at __init__()")
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._last_zmq_response = await self._async_zmq_client.async_execute(
                                                thing_id=self._resource.thing_id,
                                                objekt=self._resource.name,
                                                operation=Operations.invokeAction,
                                                payload=SerializableData(kwargs, content_type=self.invokation_form['contentType']),
                                                server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout, 
                                                    execution_timeout=self._execution_timeout,
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        return self.get_last_return_value(True)


    
    


class ZMQProperty(ConsumedThingProperty, ZMQConsumedAffordanceMixin):

    __slots__ = ['_zmq_client', '_async_zmq_client', '_invokation_timeout', '_execution_timeout', 
                '_schema_validator', '_last_return_value', 
                '_thing_execution_context'
                ]   
    # property get set abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, 
                resource: PropertyAffordance, 
                sync_client: SyncZMQClient, 
                async_client: AsyncZMQClient | None = None,
                **kwargs    
            ) -> None:
        super().__init__(resource, **kwargs)
        self._zmq_client = sync_client
        self._async_zmq_client = async_client
        self._invokation_timeout = kwargs.get('invokation_timeout', 5)
        self._execution_timeout = kwargs.get('execution_timeout', 5)
        self._schema_validator = None
        self._thing_execution_context = dict(fetch_execution_logs=False)
        
    last_read_value = property(fget=ZMQConsumedAffordanceMixin.get_last_return_value,
                                doc="cached return value of the last call to the method")

    def set(self, value: typing.Any) -> None:
        self._last_zmq_response = self._zmq_client.execute(
                                                thing_id=self._resource.thing_id, 
                                                objekt=self._resource.name,
                                                operation=Operations.writeProperty,
                                                payload=SerializableData(value, content_type=self.write_property_form['contentType']),
                                                server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout,
                                                    execution_timeout=self._execution_timeout
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        self.get_last_return_value(True)
     
    def get(self) -> typing.Any:
        self._last_zmq_response = self._zmq_client.execute(
                                                thing_id=self._resource.thing_id,
                                                objekt=self._resource.name,
                                                operation=Operations.readProperty,
                                                server_execution_context=dict(
                                                    invocation_timeout=self._invokation_timeout,
                                                    execution_timeout=self._execution_timeout
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        return self.get_last_return_value(True) 
    
    async def async_set(self, value: typing.Any) -> None:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        self._last_zmq_response = await self._async_zmq_client.async_execute(
                                                        thing_id=self._resource.thing_id,
                                                        objekt=self._resource.name,
                                                        operation=Operations.writeProperty,
                                                        payload=SerializableData(value, content_type=self.write_property_form['contentType']),
                                                        server_execution_context=dict(
                                                            invokation_timeout=self._invokation_timeout, 
                                                            execution_timeout=self._execution_timeout
                                                        ),
                                                        thing_execution_context=self._thing_execution_context
                                                    )
    
    async def async_get(self) -> typing.Any:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        self._last_zmq_response = await self._async_zmq_client.async_execute(
                                                thing_id=self._resource.thing_id,
                                                objekt=self._resource.name,
                                                operation=Operations.readProperty,
                                                server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout, 
                                                    execution_timeout=self._execution_timeout
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        return self.get_last_return_value(True) 
    
    def noblock_set(self, value : typing.Any) -> None:
        return self._zmq_client.send_request(   
                                        thing_id=self._resource.thing_id,
                                        objekt=self._resource.name,
                                        operation=Operations.writeProperty,
                                        payload=SerializableData(value, content_type=self.write_property_form['contentType']),
                                        server_execution_context=dict(
                                            invokation_timeout=self._invokation_timeout, 
                                            execution_timeout=self._execution_timeout
                                        ),
                                        thing_execution_context=self._thing_execution_context
                                    )
    
    def noblock_get(self) -> None:
        return self._zmq_client.send_request(
                                            thing_id=self._resource.thing_id,
                                            objekt=self._resource.name,
                                            operation=Operations.readProperty,
                                            server_execution_context=dict(
                                                invokation_timeout=self._invokation_timeout, 
                                                execution_timeout=self._execution_timeout
                                            ),
                                            thing_execution_context=self._thing_execution_context
                                        )
    
    
    def oneway_set(self, value: typing.Any) -> None:
        self._zmq_client.send_request(
                                    thing_id=self._resource.thing_id,
                                    objekt=self._resource.name,
                                    operation=Operations.writeProperty,
                                    payload=SerializableData(value, content_type=self.write_property_form['contentType']),
                                    server_execution_context=dict(
                                        invokation_timeout=self._invokation_timeout, 
                                        execution_timeout=self._execution_timeout,
                                        oneway=True
                                    ),
                                )
  


class ZMQEvent(ConsumedThingEvent, ZMQConsumedAffordanceMixin):
    
    __slots__ = ['_zmq_client', '_name', '_obj_name', '_unique_identifier', '_socket_address', '_callbacks',
                    '_serializer', '_subscribed', '_thread', '_thread_callbacks', '_event_consumer', '_logger',
                    '_deserialize']
    # event subscription
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, 
                resource: EventAffordance,
                sync_client: SyncZMQClient, 
                serializer: BaseSerializer = None, 
                logger: logging.Logger = None,
                **kwargs
            ) -> None:
        super().__init__(resource=resource, logger=logger, **kwargs)
        self._zmq_client = sync_client      
        self._serializer = serializer


    def subscribe(self, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable], 
                    thread_callbacks : bool = False, deserialize : bool = True) -> None:
        self._event_consumer = EventConsumer(
                                    'zmq-' + self._unique_identifier if self._serialization_specific else self._unique_identifier, 
                                    self._socket_address, f"{self._name}|RPCEvent|{uuid4()}", b'PROXY',
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


__all__ = [
    ZMQAction.__name__,
    ZMQProperty.__name__,
    ZMQEvent.__name__,
]