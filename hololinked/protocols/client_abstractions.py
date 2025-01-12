# import typing
# from ..td import PropertyAffordance, ActionAffordance, EventAffordance



# class Action:
    
#     __slots__ = ['_zmq_client', '_async_zmq_client', '_resource_info', '_invokation_timeout', '_execution_timeout',
#                 '_schema', '_schema_validator', '_last_return_value', '__name__', '__qualname__', '__doc__',
#                 '_thing_execution_context' 
#                 ]
#     # method call abstraction
#     # Dont add doc otherwise __doc__ in slots will conflict with class variable

#     def __init__(self, 
#                 resource: ActionAffordance, 
#                 sync_client: SyncZMQClient, 
#                 async_client: AsyncZMQClient | None = None,  
#                 schema_validator: typing.Type[BaseSchemaValidator] | None = None
#             ) -> None:
#         """
#         Parameters
#         ----------
#         sync_client: SyncZMQClient
#             synchronous ZMQ client
#         async_zmq_client: AsyncZMQClient
#             asynchronous ZMQ client for async calls
#         instruction: str
#             The instruction needed to call the method        
#         """
#         self._zmq_client = sync_client
#         self._async_zmq_client = async_client
#         self._invokation_timeout = invokation_timeout
#         self._execution_timeout = execution_timeout
#         self._resource_info = resource_info
#         self._resource_info.is_client_representation = True
#         self._schema_validator = schema_validator(resource_info.argument_schema) if (schema_validator and 
#                                                                     resource_info.argument_schema and 
#                                                                     global_config.validate_schema_on_client) else None
#         self._thing_execution_context = dict(fetch_execution_logs=False) 
   
#     def get_last_return_value(self, raise_exception: bool = False) -> typing.Any:
#         """
#         cached return value of the last call to the method
#         """
#         payload = self._last_return_value.payload.deserialize() 
#         preserialized_payload = self._last_return_value.preserialized_payload.value
#         if preserialized_payload != EMPTY_BYTE:
#             if payload is None:
#                 return preserialized_payload
#             return payload, preserialized_payload
#         elif self._last_return_value.type != REPLY and raise_exception:
#             raise_local_exception(payload)
#         return payload
    
#     last_return_value = property(fget=get_last_return_value,
#                                 doc="cached return value of the last call to the method")
    
#     @property
#     def last_zmq_message(self) -> ResponseMessage:
#         return self._last_return_value
    
#     def __call__(self, *args, **kwargs) -> typing.Any:
#         """
#         execute method/action on server
#         """
#         if len(args) > 0: 
#             kwargs["__args__"] = args
#         elif self._schema_validator:
#             self._schema_validator.validate(kwargs)
#         self._last_return_value = self._zmq_client.execute(
#                                             thing_id=self._resource_info.id,
#                                             objekt=self._resource_info.obj_name,
#                                             operation=Operations.invokeAction,
#                                             payload=SerializableData(kwargs, 'application/json'), 
#                                             server_execution_context=dict(
#                                                 invokation_timeout=self._invokation_timeout, 
#                                                 execution_timeout=self._execution_timeout
#                                             ),
#                                             thing_execution_context=self._thing_execution_context
#                                         )
#         return self.get_last_return_value(True) # note the missing underscore
    
#     def oneway(self, *args, **kwargs) -> None:
#         """
#         only issues the method call to the server and does not wait for reply,
#         neither does the server reply to this call.  
#         """
#         if len(args) > 0: 
#             kwargs["__args__"] = args
#         elif self._schema_validator:
#             self._schema_validator.validate(kwargs)
#         self._zmq_client.send_request(
#                                     thing_id=self._resource_info.id, 
#                                     objekt=self._resource_info.obj_name,
#                                     operation=Operations.invokeAction,
#                                     payload=SerializableData(kwargs, 'application/json'), 
#                                     server_execution_context=dict(
#                                             invokation_timeout=self._invokation_timeout, 
#                                             execution_timeout=self._execution_timeout,
#                                             oneway=True
#                                         ),
#                                     thing_execution_context=self._thing_execution_context
#                                 )

#     def noblock(self, *args, **kwargs) -> None:
#         if len(args) > 0: 
#             kwargs["__args__"] = args
#         elif self._schema_validator:
#             self._schema_validator.validate(kwargs)
#         return self._zmq_client.send_request(
#                                     thing_id=self._resource_info.id, 
#                                     objekt=self._resource_info.obj_name,
#                                     operation=Operations.invokeAction,
#                                     arguments=kwargs, 
#                                     server_execution_context=dict(
#                                         invokation_timeout=self._invokation_timeout, 
#                                         execution_timeout=self._execution_timeout,
#                                         ),
#                                     thing_execution_context=self._thing_execution_context    
#                                 )
     
#     async def async_call(self, *args, **kwargs):
#         """
#         async execute method on server
#         """
#         if not self._async_zmq_client:
#             raise RuntimeError("async calls not possible as async_mixin was not set True at __init__()")
#         if len(args) > 0: 
#             kwargs["__args__"] = args
#         elif self._schema_validator:
#             self._schema_validator.validate(kwargs)
#         self._last_return_value = await self._async_zmq_client.async_execute(
#                                                 thing_id=self._resource_info.id,
#                                                 objekt=self._resource_info.obj_name,
#                                                 operation=Operations.invokeAction,
#                                                 payload=SerializableData(kwargs, 'application/json'),
#                                                 server_execution_context=dict(
#                                                     invokation_timeout=self._invokation_timeout, 
#                                                     execution_timeout=self._execution_timeout,
#                                                 ),
#                                                 thing_execution_context=self._thing_execution_context
#                                             )
#         return self.get_last_return_value(True) # note the missing underscore



# class Property:

#     __slots__ = ['_zmq_client', '_async_zmq_client', '_resource_info', 
#                 '_invokation_timeout', '_execution_timeout', '_last_return_value', '__name__', '__doc__']   
#     # property get set abstraction
#     # Dont add doc otherwise __doc__ in slots will conflict with class variable

#     def __init__(self, sync_client : SyncZMQClient, resource_info : ZMQResource, 
#                     invokation_timeout : typing.Optional[float] = 5, execution_timeout : typing.Optional[float] = None, 
#                     async_client : typing.Optional[AsyncZMQClient] = None) -> None:
#         self._zmq_client = sync_client
#         self._async_zmq_client = async_client
#         self._invokation_timeout = invokation_timeout
#         self._execution_timeout = execution_timeout
#         self._resource_info = resource_info
#         self._resource_info.is_client_representation = True

#     # @property # i.e. cannot have setter
#     # def last_read_value(self) -> typing.Any:
#     #     """
#     #     cache of last read value
#     #     """
#     #     if len(self._last_value[SM_INDEX_ENCODED_DATA]) > 0:
#     #         return self._last_value[SM_INDEX_ENCODED_DATA]
#     #         # property should either be encoded or not encoded
#     #     return self._last_value[SM_INDEX_DATA]
    

#     def get_last_return_value(self, raise_exception: bool = False) -> typing.Any:
#         """
#         cached return value of the last call to the method
#         """
#         payload = self._last_return_value.payload.deserialize() 
#         preserialized_payload = self._last_return_value.preserialized_payload.value
#         if preserialized_payload != EMPTY_BYTE:
#             if payload is None:
#                 return preserialized_payload
#             return payload, preserialized_payload
#         elif self._last_return_value.type != REPLY and raise_exception:
#             raise_local_exception(payload)
#         return payload
    
#     last_return_value = property(fget=get_last_return_value,
#                                 doc="cached return value of the last call to the method")


#     @property
#     def last_zmq_message(self) -> typing.List:
#         """
#         cache of last message received for this property
#         """
#         return self._last_return_value
    
#     def set(self, value : typing.Any) -> None:
#         self._last_return_value = self._zmq_client.execute(
#                                                 thing_id=self._resource_info.id, 
#                                                 objekt=self._resource_info.obj_name,
#                                                 operation=Operations.writeProperty,
#                                                 payload=SerializableData(value, 'application/json'),
#                                                 server_execution_context=dict(
#                                                     invokation_timeout=self._invokation_timeout,
#                                                     execution_timeout=self._execution_timeout
#                                                 ),
#                                             )
#         self.get_last_return_value(True)
     
#     def get(self) -> typing.Any:
#         self._last_return_value = self._zmq_client.execute(
#                                                 thing_id=self._resource_info.id,
#                                                 objekt=self._resource_info.obj_name,
#                                                 operation=Operations.readProperty,
#                                                 server_execution_context=dict(
#                                                     invocation_timeout=self._invokation_timeout,
#                                                     execution_timeout=self._execution_timeout
#                                                 ), 
#                                             )
#         return self.get_last_return_value(True) 
    
#     async def async_set(self, value : typing.Any) -> None:
#         if not self._async_zmq_client:
#             raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
#         self._last_return_value = await self._async_zmq_client.async_execute(
#                                                         thing_id=self._resource_info.id,
#                                                         objekt=self._resource_info.obj_name,
#                                                         operation=Operations.writeProperty,
#                                                         payload=SerializableData(value, 'application/json'),
#                                                         server_execution_context=dict(
#                                                             invokation_timeout=self._invokation_timeout, 
#                                                             execution_timeout=self._execution_timeout
#                                                         ),
#                                                     )
    
#     async def async_get(self) -> typing.Any:
#         if not self._async_zmq_client:
#             raise RuntimeError("async calls not possible as async_mixin was not set at __init__()")
#         self._last_return_value = await self._async_zmq_client.async_execute(
#                                                 thing_id=self._resource_info.id,
#                                                 objekt=self._resource_info.obj_name,
#                                                 operation=Operations.readProperty,
#                                                 server_execution_context=dict(
#                                                     invokation_timeout=self._invokation_timeout, 
#                                                     execution_timeout=self._execution_timeout
#                                                 ),
#                                             )
#         return self.get_last_return_value(True) 
    
#     def noblock_get(self) -> None:
#         return self._zmq_client.send_request(
#                                             thing_id=self._resource_info.id,
#                                             objekt=self._resource_info.obj_name,
#                                             operation=Operations.readProperty,
#                                             server_execution_context=dict(
#                                                 invokation_timeout=self._invokation_timeout, 
#                                                 execution_timeout=self._execution_timeout
#                                             )
#                                         )
    
#     def noblock_set(self, value : typing.Any) -> None:
#         return self._zmq_client.send_request(   
#                                         thing_id=self._resource_info.id,
#                                         objekt=self._resource_info.obj_name,
#                                         operation=Operations.writeProperty,
#                                         payload=SerializableData(value, 'application/json'),
#                                         server_execution_context=dict(
#                                             invokation_timeout=self._invokation_timeout, 
#                                             execution_timeout=self._execution_timeout
#                                         )
#                                     )
    
#     def oneway_set(self, value : typing.Any) -> None:
#         self._zmq_client.send_request(
#                                     thing_id=self._resource_info.obj_name,
#                                     objekt=self._resource_info.obj_name,
#                                     operation=Operations.writeProperty,
#                                     payload=SerializableData(value, 'application/json'),
#                                     server_execution_context=dict(
#                                         invokation_timeout=self._invokation_timeout, 
#                                         execution_timeout=self._execution_timeout
#                                     ))
  


# class Event:
    
#     __slots__ = ['_zmq_client', '_name', '_obj_name', '_unique_identifier', '_socket_address', '_callbacks',
#                     '_serializer', '_subscribed', '_thread', '_thread_callbacks', '_event_consumer', '_logger',
#                     '_deserialize']
#     # event subscription
#     # Dont add class doc otherwise __doc__ in slots will conflict with class variable

#     def __init__(self, client : SyncZMQClient, name : str, obj_name : str, unique_identifier : str, socket : str, 
#                     serialization_specific : bool = False, serializer : BaseSerializer = None, logger : logging.Logger = None) -> None:
#         self._zmq_client = client
#         self._name = name
#         self._obj_name = obj_name
#         self._unique_identifier = unique_identifier
#         self._socket_address = socket
#         self._serialization_specific = serialization_specific
#         self._callbacks = None 
#         self._serializer = serializer
#         self._logger = logger 
#         self._subscribed = False
#         self._deserialize = True

#     def add_callbacks(self, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable]) -> None:
#         if not self._callbacks:
#             self._callbacks = [] 
#         if isinstance(callbacks, list):
#             self._callbacks.extend(callbacks)
#         else:
#             self._callbacks.append(callbacks)

#     def subscribe(self, callbacks : typing.Union[typing.List[typing.Callable], typing.Callable], 
#                     thread_callbacks : bool = False, deserialize : bool = True) -> None:
#         self._event_consumer = EventConsumer(
#                                     'zmq-' + self._unique_identifier if self._serialization_specific else self._unique_identifier, 
#                                     self._socket_address, f"{self._name}|RPCEvent|{uuid.uuid4()}", b'PROXY',
#                                     zmq_serializer=self._serializer, logger=self._logger
#                                 )
#         self.add_callbacks(callbacks) 
#         self._subscribed = True
#         self._deserialize = deserialize
#         self._thread_callbacks = thread_callbacks
#         self._thread = threading.Thread(target=self.listen)
#         self._thread.start()

#     def listen(self):
#         while self._subscribed:
#             try:
#                 data = self._event_consumer.receive(deserialize=self._deserialize)
#                 if data == 'INTERRUPT':
#                     break
#                 for cb in self._callbacks: 
#                     if not self._thread_callbacks:
#                         cb(data)
#                     else: 
#                         threading.Thread(target=cb, args=(data,)).start()
#             except Exception as ex:
#                 print(ex)
#                 warnings.warn(f"Uncaught exception from {self._name} event - {str(ex)}", 
#                                 category=RuntimeWarning)
#         try:
#             self._event_consumer.exit()
#         except:
#             pass
       

#     def unsubscribe(self, join_thread : bool = True):
#         self._subscribed = False
#         self._event_consumer.interrupt()
#         if join_thread:
#             self._thread.join()

import typing
import builtins

def raise_local_exception(error_message : typing.Dict[str, typing.Any]) -> None:
    """
    raises an exception on client side using an exception from server by mapping it to the correct one based on type.

    Parameters
    ----------
    exception: Dict[str, Any]
        exception dictionary made by server with following keys - type, message, traceback, notes

    """
    if isinstance(error_message, Exception):
        raise error_message from None
    elif isinstance(error_message, dict) and 'exception' in error_message.keys():
        exc = getattr(builtins, error_message["type"], None)
        message = error_message["message"]
        if exc is None:
            ex = error_message(message)
        else: 
            ex = exc(message)
        error_message["traceback"][0] = f"Server {error_message['traceback'][0]}"
        ex.__notes__ = error_message["traceback"][0:-1]
        raise ex from None 
    elif isinstance(error_message, str) and error_message in ['invokation', 'execution']:
        raise TimeoutError(f"{error_message[0].upper()}{error_message[1:]} timeout occured. Server did not respond within specified timeout") from None
    raise RuntimeError("unknown error occurred on server side") from None