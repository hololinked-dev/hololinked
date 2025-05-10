import asyncio
import logging
import typing
import threading
import warnings
import traceback
from uuid import uuid4


from ...utils import get_current_async_loop
from ...constants import Operations
from ...serializers import BaseSerializer, Serializers
from ...serializers.payloads import SerializableData, PreserializedData
from ...td import PropertyAffordance, ActionAffordance, EventAffordance
from ...client.abstractions import ConsumedThingAction, ConsumedThingEvent, ConsumedThingProperty, raise_local_exception
from ...core.zmq.message import ResponseMessage
from ...core.zmq.message import EMPTY_BYTE, REPLY, TIMEOUT, ERROR, INVALID_MESSAGE
from ...core.zmq.brokers import SyncZMQClient, AsyncZMQClient, EventConsumer, AsyncEventConsumer



__error_message_types__ = [TIMEOUT, ERROR, INVALID_MESSAGE]


class ZMQConsumedAffordanceMixin:

    __slots__ = ['_resource', '_schema_validator', '__name__', '__qualname__', '__doc__',
                '_sync_zmq_client', '_async_zmq_client', '_invokation_timeout', '_execution_timeout',
                '_thing_execution_context', '_last_zmq_response' ]  # __slots__ dont support multiple inheritance

    def __init__(self, 
                sync_client: SyncZMQClient, 
                async_client: AsyncZMQClient | None = None,  
                **kwargs
                # schema_validator: typing.Type[BaseSchemaValidator] | None = None
            ) -> None:
        self._sync_zmq_client = sync_client
        self._async_zmq_client = async_client
        self._invokation_timeout = kwargs.get('invokation_timeout', 5)
        self._execution_timeout = kwargs.get('execution_timeout', 5)
        self._thing_execution_context = dict(fetch_execution_logs=False) 
        self._last_zmq_response = None # type: typing.Optional[ResponseMessage]

    def get_last_return_value(self, raise_exception: bool = False) -> typing.Any:
        """
        cached return value of the last call to the method
        """
        if self._last_zmq_response is None:
            raise RuntimeError("No last response available. Did you make an operation?")
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
        resource: ActionAffordance
            dataclass object representing the action
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_zmq_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        """
        ConsumedThingAction.__init__(self, resource=resource)
        ZMQConsumedAffordanceMixin.__init__(self, sync_client=sync_client, async_client=async_client, **kwargs)
        self._resource # type: ActionAffordance

    last_return_value = property(fget=ZMQConsumedAffordanceMixin.get_last_return_value,
                                doc="cached return value of the last call to the method")
    
    def __call__(self, *args, **kwargs) -> typing.Any:
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._last_zmq_response = self._sync_zmq_client.execute(
                                            thing_id=self._resource.thing_id,
                                            objekt=self._resource.name,
                                            operation=Operations.invokeAction,
                                            payload=SerializableData(
                                                value=kwargs, 
                                                content_type=self._resource.retrieve_form('invokeAction', {}).get(
                                                                                'contentType', 'application/json') 
                                            ),
                                            server_execution_context=dict(
                                                invokation_timeout=self._invokation_timeout, 
                                                execution_timeout=self._execution_timeout
                                            ),
                                            thing_execution_context=self._thing_execution_context
                                        )
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, True)
    
    async def async_call(self, *args, **kwargs) -> typing.Any:
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
                                                payload=SerializableData(
                                                    value=kwargs, 
                                                    content_type=self._resource.retrieve_form('invokeAction', {}).get(
                                                                                'contentType', 'application/json')
                                                ),
                                                server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout, 
                                                    execution_timeout=self._execution_timeout,
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, True)
    
    def oneway(self, *args, **kwargs) -> None:
        if len(args) > 0: 
            kwargs["__args__"] = args
        elif self._schema_validator:
            self._schema_validator.validate(kwargs)
        self._sync_zmq_client.send_request(
                                    thing_id=self._resource.thing_id, 
                                    objekt=self._resource.name,
                                    operation=Operations.invokeAction,
                                    payload=SerializableData(
                                        value=kwargs, 
                                        content_type=self._resource.retrieve_form('invokeAction', {}).get(
                                                                        'contentType', 'application/json') 
                                    ), 
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
        return self._sync_zmq_client.send_request(
                                    thing_id=self._resource.thing_id, 
                                    objekt=self._resource.name,
                                    operation=Operations.invokeAction,
                                    payload=SerializableData(
                                        value=kwargs, 
                                        content_type=self._resource.retrieve_form('invokeAction', {}).get(
                                                                        'contentType', 'application/json')
                                    ),
                                    server_execution_context=dict(
                                        invokation_timeout=self._invokation_timeout, 
                                        execution_timeout=self._execution_timeout,
                                    ),
                                    thing_execution_context=self._thing_execution_context    
                                )
     

    
class ZMQProperty(ConsumedThingProperty, ZMQConsumedAffordanceMixin):

    # property get set abstraction
    # Dont add doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, 
                resource: PropertyAffordance, 
                sync_client: SyncZMQClient, 
                async_client: AsyncZMQClient | None = None,
                **kwargs    
            ) -> None:
        """
        Parameters
        ----------
        resource: PropertyAffordance
            dataclass object representing the property
        sync_client: SyncZMQClient
            synchronous ZMQ client
        async_client: AsyncZMQClient
            asynchronous ZMQ client for async calls
        """
        ConsumedThingProperty.__init__(self, resource=resource) 
        ZMQConsumedAffordanceMixin.__init__(self, sync_client=sync_client, async_client=async_client, **kwargs)
        self._resource # type: PropertyAffordance
        
    last_read_value = property(fget=ZMQConsumedAffordanceMixin.get_last_return_value,
                                doc="cached return value of the last call to the method")

    def set(self, value: typing.Any) -> None:
        self._last_zmq_response = self._sync_zmq_client.execute(
                                                thing_id=self._resource.thing_id, 
                                                objekt=self._resource.name,
                                                operation=Operations.writeProperty,
                                                payload=SerializableData(
                                                    value=value, 
                                                    content_type=self._resource.retrieve_form('writeProperty', {}).get(
                                                                                    'contentType', 'application/json')
                                                ),
                                                server_execution_context=dict(
                                                    invokation_timeout=self._invokation_timeout,
                                                    execution_timeout=self._execution_timeout
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        ZMQConsumedAffordanceMixin.get_last_return_value(self, True)
     
    def get(self) -> typing.Any:
        self._last_zmq_response = self._sync_zmq_client.execute(
                                                thing_id=self._resource.thing_id,
                                                objekt=self._resource.name,
                                                operation=Operations.readProperty,
                                                server_execution_context=dict(
                                                    invocation_timeout=self._invokation_timeout,
                                                    execution_timeout=self._execution_timeout
                                                ),
                                                thing_execution_context=self._thing_execution_context
                                            )
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, True) 
    
    async def async_set(self, value: typing.Any) -> None:
        if not self._async_zmq_client:
            raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
        self._last_zmq_response = await self._async_zmq_client.async_execute(
                                                        thing_id=self._resource.thing_id,
                                                        objekt=self._resource.name,
                                                        operation=Operations.writeProperty,
                                                        payload=SerializableData(
                                                            value=value, 
                                                            content_type=self._resource.retrieve_form('writeProperty', {}).get(
                                                                                            'contentType', 'application/json')
                                                        ),
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
        return ZMQConsumedAffordanceMixin.get_last_return_value(self, True) 
        
    def oneway_set(self, value: typing.Any) -> None:
        self._sync_zmq_client.send_request(
                                    thing_id=self._resource.thing_id,
                                    objekt=self._resource.name,
                                    operation=Operations.writeProperty,
                                    payload=SerializableData(
                                        value=value, 
                                        content_type=self._resource.retrieve_form('writeProperty', {}).get(
                                                                            'contentType', 'application/json')
                                    ),
                                    server_execution_context=dict(
                                        invokation_timeout=self._invokation_timeout, 
                                        execution_timeout=self._execution_timeout,
                                        oneway=True
                                    ),
                                )
        
    def noblock_get(self) -> None:
        return self._sync_zmq_client.send_request(
                                            thing_id=self._resource.thing_id,
                                            objekt=self._resource.name,
                                            operation=Operations.readProperty,
                                            server_execution_context=dict(
                                                invokation_timeout=self._invokation_timeout, 
                                                execution_timeout=self._execution_timeout
                                            ),
                                            thing_execution_context=self._thing_execution_context
                                        )
  


class ZMQEvent(ConsumedThingEvent, ZMQConsumedAffordanceMixin):
    
    __slots__ = ['__name__', '__qualname__', '__doc__', 
                '_sync_zmq_client', '_async_zmq_client', '_default_scheduling_mode', 
                '_event_consumer', '_callbacks',
                '_serializer', '_subscribed', '_thread', '_thread_callbacks', '_logger', '_deserialize']

    # event subscription
    # Dont add class doc otherwise __doc__ in slots will conflict with class variable

    def __init__(self, 
                resource: EventAffordance,
                sync_zmq_client: EventConsumer,
                async_zmq_client: AsyncEventConsumer | None = None,
                default_scheduling_mode: str = 'sync',
                logger: logging.Logger = None,
                **kwargs
            ) -> None:
        super().__init__(resource=resource, logger=logger, **kwargs)
        self._sync_zmq_client = sync_zmq_client
        self._async_zmq_client = async_zmq_client
        self._default_scheduling_mode = default_scheduling_mode
        self._thread = None
        
    def subscribe(self, 
                callbacks: typing.Union[typing.List[typing.Callable], typing.Callable], 
                thread_callbacks: bool = False, 
                deserialize: bool = True
            ) -> None:
        if self._default_scheduling_mode == 'sync':
            self._sync_zmq_client.subscribe()
        elif self._default_scheduling_mode == 'async':
            self._async_zmq_client.subscribe()
        else:
            raise ValueError(f"Invalid scheduling mode: {self._default_scheduling_mode}. Must be 'sync' or 'async'.")
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
        while self._subscribed:
            try:
                event_message = self._sync_zmq_client.receive()
                self._last_zmq_response = event_message
                value = self.get_last_return_value(raise_exception=True)
                if value == 'INTERRUPT':
                    break
                for cb in self._callbacks: 
                    if not self._thread_callbacks:
                        cb(value)
                    else: 
                        threading.Thread(target=cb, args=(value,)).start()
            except Exception as ex:
                import traceback
                # traceback.print_exc()
                # TODO: some minor bug here within the umq receive loop when the loop is interrupted
                # uncomment the above line to see the traceback
                warnings.warn(f"Uncaught exception from {self._resource.name} event - {str(ex)}\n{traceback.print_exc()}", 
                                category=RuntimeWarning)


    async def async_listen(self):
        while self._subscribed:
            try:
                event_message = await self._async_zmq_client.receive()
                self._last_zmq_response = event_message
                value = self.get_last_return_value(raise_exception=True)
                if value == 'INTERRUPT':
                    break
                for cb in self._callbacks: 
                    if not self._thread_callbacks:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(value)
                        else:
                            cb(value)
                    else: 
                        threading.Thread(target=cb, args=(value,)).start()
            except Exception as ex:
                # 
                # traceback.print_exc()
                # if "There is no current event loop in thread" and not self._subscribed:
                #     # TODO: some minor bug here within the umq receive loop when the loop is interrupted
                #     # uncomment the above line to see the traceback
                #    pass 
                # else: 
                warnings.warn(f"Uncaught exception from {self._resource.name} event - {str(ex)}\n{traceback.print_exc()}", 
                                category=RuntimeWarning)        
        
    def unsubscribe(self, join_thread: bool = True) -> None:
        self._subscribed = False
        self._sync_zmq_client.interrupt()
        if join_thread and self._thread is not None and self._thread.is_alive():
            self._thread.join()
            self._thread = None


__all__ = [
    ZMQAction.__name__,
    ZMQProperty.__name__,
    ZMQEvent.__name__,
]