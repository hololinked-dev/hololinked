import zmq
import zmq.asyncio
import sys 
import os
import warnings
import asyncio
import importlib
import typing 
import threading
import logging
import tracemalloc
from collections import deque
from uuid import uuid4


from ..param.parameterized import Undefined
from ..exceptions import *
from ..constants import ZMQ_TRANSPORTS
from ..utils import format_exception_as_json, get_current_async_loop, get_default_logger
from ..config import global_config
from ..protocols.zmq.message import EMPTY_BYTE, PreserializedData, RequestMessage, SerializableData
from ..protocols.zmq.brokers import AsyncZMQServer, BaseZMQServer, EventPublisher
from .thing import Thing, ThingMeta
from .property import Property
from .properties import Boolean, TypedDict
from .actions import Action, action as remote_method
from .logger import ListHandler
from ..serializers import Serializers


if global_config.TRACE_MALLOC:
    tracemalloc.start()

def set_event_loop_policy():
    if sys.platform.lower().startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if global_config.USE_UVLOOP:
        if sys.platform.lower() in ['linux', 'darwin', 'linux2']:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        else:
            warnings.warn("uvloop not supported for windows, using default windows selector loop.", RuntimeWarning)

set_event_loop_policy()



RemoteObject = Thing # reading convenience

class RPCServer(BaseZMQServer):
    """
    The EventLoop class implements a infinite loop where zmq ROUTER sockets listen for messages. Each consumer of the 
    event loop (an instance of Thing) listen on their own ROUTER socket and execute methods or allow read and write
    of attributes upon receiving instructions. Socket listening is implemented in an async (asyncio) fashion. 
  
    Top level ZMQ RPC server used by ``Thing`` and ``Eventloop``. 

    Parameters
    ----------
    id: str
        ``id`` of the server
    server_type: str
        server type metadata
    context: Optional, zmq.asyncio.Context
        ZeroMQ async Context object to use. All sockets except those created by event publisher share this context. 
        Automatically created when None is supplied.
    **kwargs:
        tcp_socket_address: str
            address of the TCP socket, if not given, a random port is chosen
    """
    
    expose = Boolean(default=True, remote=False,
                    doc="""set to False to use the object locally to avoid alloting network resources 
                        of your computer for this object""")

    things = TypedDict(key_type=(str,), item_type=(Thing,), bounds=(0,100), allow_None=True, default=None,
                    doc="list of Things which are being executed", remote=False) # type: typing.Dict[str, Thing]
    
    threaded = Boolean(default=False, remote=False, 
                    doc="set True to run each thing in its own thread")
  

    def __init__(self, *, 
                id: str, 
                things: typing.List[Thing],
                context: zmq.asyncio.Context | None = None, 
                transport: ZMQ_TRANSPORTS = ZMQ_TRANSPORTS.INPROC,
                **kwargs
            ) -> None:
        """
        Parameters
        ----------
        id: str
            instance name of the event loop
        things: List[Thing]
            things to be run/served
        log_level: int
            log level of the event loop logger
        """
        super().__init__(id=id, **kwargs)
        self.uninstantiated_things = dict()
        self.things = dict() 
        for thing in things:
            self.things[thing.id] = thing

        if self.logger is None:
            self.logger =  get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, 
                                                'RPC', 'MIXED', self.id), kwargs.get('log_level', logging.INFO))
            kwargs['logger'] = self.logger
        # contexts and poller
        self._terminate_context = context is None
        self.context = context or zmq.asyncio.Context()
        
       
        self.req_rep_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=transport, 
                                poll_timeout=1000,
                                **kwargs
                            )        
        self.event_publisher = EventPublisher(
                                id=f'{self.id}/event-publisher',
                                transport=transport,
                                **kwargs
                            )        
        
        self.stop_poll = False
        self._server_stopped_event = threading.Event()
        # message serializing deque
        for instance in self.things.values():
            instance._zmq_messages = deque()
            instance._zmq_message_arrived_event = asyncio.Event()
            instance._request_execution_ready_event = threading.Event()
            instance._request_execution_complete_event = threading.Event()
            instance.rpc_server = self
            instance.event_publisher = self.event_publisher 
            # instance._prepare_resources()
     
        
    def __post_init__(self):
        super().__post_init__()
        self.logger.info("Server with name '{}' can be started using run().".format(self.id))   


    async def recv_requests(self, server : AsyncZMQServer):
        """
        Continuously keeps receiving messages from different clients and appends them to a deque to be processed 
        sequentially. Also handles messages that dont need to be queued like HANDSHAKE, EXIT, invokation timeouts etc.
        """
        eventloop = asyncio.get_event_loop()
        while not self.stop_poll:
            request_messages = await server.poll_requests() 
            # when stop poll is set, this will exit with an empty list
            for request_message in request_messages:
                try:
                    # handle invokation timeout
                    invokation_timeout = request_message.server_execution_context.get("invokation_timeout", None)

                    # schedule to tunnel it to thing
                    ready_to_process_event = None
                    timeout_task = None
                    if invokation_timeout is not None:
                        ready_to_process_event = asyncio.Event()
                        timeout_task = asyncio.create_task(
                                                self.process_timeouts(
                                                    request_message=request_message, 
                                                    ready_to_process_event=ready_to_process_event, 
                                                    timeout=invokation_timeout, 
                                                    origin_server=server, 
                                                    timeout_type='invokation'
                                                )
                                            )
                        eventloop.call_soon(lambda : timeout_task)

                except BreakLoop:
                    self.stop()
                    break
                except Exception as ex:
                    # handle invalid message
                    self.logger.error(f"exception occurred for message id '{request_message.id}' - {str(ex)}")
                    invalid_message_task = server._handle_invalid_message(
                                                            request_message=request_message,        
                                                            exception=ex
                                                        )   
                    eventloop.call_soon(lambda: invalid_message_task)
                try:
                    instance = self.things[request_message.thing_id]
                    # append to messages list - message, execution context, event, timeout task, origin socket
                    instance._zmq_messages.append((request_message, ready_to_process_event, timeout_task, server))
                    instance._zmq_message_arrived_event.set() # this was previously outside the else block - reason unknown no
                except KeyError:
                    self.logger.error(f"thing with id '{request_message.thing_id}' not found")
                    await server._handle_error_message(
                                request_message=request_message, 
                                exception=KeyError(f"thing with id '{request_message.thing_id}' not found")
                            )
    
        self.logger.info(f"stopped polling for server '{server.id}' {server.socket_address[0:3].upper() if server.socket_address[0:3] in ['ipc', 'tcp'] else 'INPROC'}")
   

    async def tunnel_message_to_things(self, instance : Thing) -> None:
        """
        message tunneler between external sockets and interal inproc client
        """
        eventloop = get_current_async_loop()
        while not self.stop_poll:
            # wait for message first
            if len(instance._zmq_messages) == 0:
                await instance._zmq_message_arrived_event.wait()
                instance._zmq_message_arrived_event.clear()
                # this means in next loop it wont be in this block as a message arrived  
                continue

            # retrieve from messages list - message, execution context, event, timeout task, origin socket
            request_message, ready_to_process_event, timeout_task, origin_server = instance._zmq_messages.popleft() 
            request_message : RequestMessage
            ready_to_process_event : asyncio.Event
            origin_server : AsyncZMQServer
            server_execution_context = request_message.server_execution_context
            
            # handle invokation timeout
            invokation_timed_out = True 
            if ready_to_process_event is not None: 
                ready_to_process_event.set() # releases timeout task 
                invokation_timed_out = await timeout_task
            if ready_to_process_event is not None and invokation_timed_out:
                # drop call to thing, timeout message was already sent in process_timeouts()
                continue 
            
            # handle execution through thing
            instance._last_operation_request = request_message.thing_execution_info
            instance._request_execution_ready_event.set()
                    
            # schedule an execution timeout
            execution_timeout = server_execution_context.get("execution_timeout", None)
            execution_completed_event = None 
            execution_timeout_task = None
            execution_timed_out = True
            if execution_timeout is not None:
                execution_completed_event = asyncio.Event()
                execution_timeout_task = asyncio.create_task(
                                                        self.process_timeouts(
                                                            request_message=request_message, 
                                                            ready_to_process_event=execution_completed_event,
                                                            timeout=execution_timeout,
                                                            origin_server=origin_server,
                                                            timeout_type='execution'
                                                        )
                                                    )
                eventloop.call_soon(lambda : execution_timeout_task)

            # always wait for reply from thing, since this loop is asyncio task (& in its own thread in RPC server), 
            # timeouts always reach client without truly blocking by the GIL. If reply does not arrive, all other requests
            # get invokation timeout.            
            await eventloop.run_in_executor(None, instance._request_execution_complete_event.wait, None)
            instance._request_execution_complete_event.clear()
            reply = instance._last_operation_reply
            # check if reply is never undefined, Undefined is a sensible placeholder for NotImplemented singleton
            if reply is Undefined:
                # this is a logic error, as the reply should never be undefined
                await origin_server._handle_error_message(
                            request_message=request_message, 
                            exception=RuntimeError("No reply from thing - logic error")
                        )
                continue
            payload, preserialized_payload = reply
            instance._last_operation_reply = Undefined

            # check if execution completed within time
            if execution_completed_event is not None:
                execution_completed_event.set() # releases timeout task
                execution_timed_out = await execution_timeout_task
            if execution_timeout_task is not None and execution_timed_out:
                # drop reply to client as timeout was already sent
                continue
            if server_execution_context.get("oneway", False):
                # drop reply if oneway
                continue 

            # send reply to client            
            await origin_server.async_send_response(
                request_message=request_message,
                payload=payload,
                preserialized_payload=preserialized_payload
            ) 
        self.logger.info("stopped tunneling messages to things")


    async def run_single_thing(self, instance : Thing) -> None: 
        eventloop = get_current_async_loop()
        while not self.stop_poll:
            await eventloop.run_in_executor(None, instance._request_execution_ready_event.wait, None)
           
            try:
                instance._request_execution_ready_event.clear()
                instance._last_operation_reply = Undefined
                operation_request = instance._last_operation_request 
                # operation_request is a tuple of (thing_id, objekt, operation, payload, preserialized_payload, execution_context)
                # fetch it
                if operation_request is Undefined:
                    instance.logger.warning("No operation request found in thing '{}'".format(instance.id))
                    continue
                thing_id, objekt, operation, payload, preserialized_payload, execution_context = operation_request 

                # start activities related to thing execution context
                fetch_execution_logs = execution_context.pop("fetch_execution_logs", False)
                if fetch_execution_logs:
                    list_handler = ListHandler([])
                    list_handler.setLevel(logging.DEBUG)
                    list_handler.setFormatter(instance.logger.handlers[0].formatter)
                    instance.logger.addHandler(list_handler)

                # execute the operation
                reply_payload = await self.execute_once(instance, objekt, operation, payload, preserialized_payload) 
                # reply = (payload, preserialized_payload)
                # set reply
                instance._last_operation_reply = reply_payload

            except (BreakInnerLoop, BreakAllLoops):
                # exit the loop and stop the thing
                instance.logger.info("Thing {} with instance name {} exiting event loop.".format(
                                                            instance.__class__.__name__, instance.id))
                return_value = None
                if fetch_execution_logs:
                    return_value = { 
                        "return_value" : None,
                        "execution_logs" : list_handler.log_list
                    }
                instance._last_operation_reply = (
                    SerializableData(return_value, 'application/json'),
                    PreserializedData(EMPTY_BYTE, 'text/plain')
                )
                return 
            except Exception as ex:
                # error occurred while executing the operation
                instance.logger.error("Thing {} with ID {} produced error : {} - {}.".format(
                                                        instance.__class__.__name__, instance.id, type(ex), ex))
                return_value = dict(exception=format_exception_as_json(ex))
                if fetch_execution_logs:
                    return_value["execution_logs"] = list_handler.log_list
                instance._last_operation_reply = (SerializableData(return_value, 'application/json'), PreserializedData(EMPTY_BYTE, 'text/plain'))
            finally:
                # send reply
                instance._last_operation_request = Undefined
                instance._request_execution_complete_event.set()
                # cleanup
                if fetch_execution_logs:
                    instance.logger.removeHandler(list_handler)
                instance.logger.debug("thing {} with instance name {} completed execution of operation {} on {}".format(
                                                            instance.__class__.__name__, instance.id, operation, objekt))
        self.logger.info("stopped running thing {}".format(instance.id))

   
    async def execute_once(cls, 
                        instance: Thing, 
                        objekt: str, 
                        operation: str,
                        payload: SerializableData,
                        preserialized_payload: PreserializedData
                    ) -> typing.Any:
        # deserializing the payload required to execute the operation
        payload: SerializableData 
        preserialized_payload: PreserializedData
        payload = payload.deserialize() # deserializing the payload
        preserialized_payload = preserialized_payload.value
        instance.logger.debug(f"thing {instance.id} starting execution of operation {operation} on {objekt}")

        if operation == 'readProperty':
            prop = instance.properties[objekt] # type: Property
            return_value = getattr(instance, prop.name) 
        elif operation == 'writeProperty':
            prop = instance.properties[objekt] # type: Property
            final_payload = payload
            if preserialized_payload != EMPTY_BYTE:
                final_payload = preserialized_payload
            return_value = prop.external_set(instance, final_payload)
        elif operation == 'deleteProperty':
            prop = instance.properties[objekt] # type: Property
            del prop # raises NotImplementedError when deletion is not implemented which is mostly the case
        elif operation == 'invokeAction':
            action = instance.actions[objekt] # type: Action
            args = payload.pop('__args__', tuple())
            # payload then become kwargs
            if preserialized_payload != EMPTY_BYTE:
                args = (preserialized_payload,) + args
            # if action.execution_info.iscoroutine:
            #     return_value = await action.external_call(*args, **payload)
            # else:
            return_value = action(*args, **payload) 
        elif operation == 'readMultipleProperties' or operation == 'readAllProperties':
            if objekt is None:
                return_value = instance._get_properties()
            return_value = instance._get_properties(names=objekt)
        elif operation == 'writeMultipleProperties' or operation == 'writeAllProperties':
            return_value = instance._set_properties(payload)
        else:
            raise NotImplementedError(f"Unimplemented execution path for Thing {instance.id} for operation {operation}")

        # handle return value
        if isinstance(return_value, tuple) and len(return_value) == 2 and (
            isinstance(return_value[1], bytes) or 
            isinstance(return_value[1], PreserializedData) 
        ):  
            payload = SerializableData(return_value[0], Serializers.get_serializer_for_objekt(objekt))
            if isinstance(return_value[1], bytes):
                preserialized_payload = PreserializedData(return_value[1], '')
        elif isinstance(return_value, bytes):
            payload = SerializableData(None, content_type='application/json')
            preserialized_payload = PreserializedData(return_value, '')
        else:
            payload = SerializableData(return_value, 'application/json')
            preserialized_payload = PreserializedData(EMPTY_BYTE, 'text/plain')
        return payload, preserialized_payload

    async def process_timeouts(self, 
                            request_message: RequestMessage, 
                            ready_to_process_event: asyncio.Event,
                            origin_server: AsyncZMQServer,
                            timeout: float | int | None, 
                            timeout_type : str
                        ) -> bool:
        """
        replies timeout to client if timeout occured and prevents the message from being executed. 
        """
        try:
            await asyncio.wait_for(ready_to_process_event.wait(), timeout)
            return False 
        except TimeoutError:    
            await origin_server._handle_timeout(request_message, timeout_type)
            return True


    def run_external_message_listener(self):
        """
        Runs ZMQ's sockets which are visible to clients.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        self.logger.info("starting external message listener thread")
        self.stop_poll = False
        eventloop = get_current_async_loop()
        existing_tasks = asyncio.all_tasks(eventloop)
        eventloop.run_until_complete(
            asyncio.gather(
                self.recv_requests(self.req_rep_server),
                *[self.tunnel_message_to_things(thing) for thing in self.things.values()],
                *existing_tasks
            )
        )
        self.logger.info("exiting external listener event loop {}".format(self.id))
        eventloop.close()
    

    def run_things_executor(self, things : typing.List[Thing]):
        """
        Run ZMQ sockets which provide queued instructions to ``Thing``.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        thing_executor_loop = get_current_async_loop()
        self.thing_executor_loop = thing_executor_loop # atomic assignment for thread safety
        self.logger.info(f"starting thing executor loop in thread {threading.get_ident()} for {[obj.id for obj in things]}")
        thing_executor_loop.run_until_complete(
            asyncio.gather(*[self.run_single_thing(instance) for instance in things])
        )
        self.logger.info(f"exiting event loop in thread {threading.get_ident()}")
        thing_executor_loop.close()


    def run(self):
        """
        start the eventloop
        """
        self.logger.info("starting server")
        self._server_stopped_event.clear()
        if not self.threaded:
            _thing_executor = threading.Thread(target=self.run_things_executor, args=(list(self.things.values()),))
            _thing_executor.start()
        else: 
            for thing in self.things.values():
                _thing_executor = threading.Thread(target=self.run_things_executor, args=([thing],))
                _thing_executor.start()
        self.run_external_message_listener()
        if not self.threaded:
            _thing_executor.join()
        self._server_stopped_event.set()
        self.logger.info("server stopped")


    def stop(self):
        """
        stop polling method ``poll()``
        """
        self.stop_poll = True
        self.req_rep_server.stop_polling()
        for instance in self.things.values():
            # quit tunneling messages to things 
            instance._zmq_message_arrived_event.set() 
            instance._request_execution_ready_event.set()
        self._server_stopped_event.wait()


    def exit(self):
        try:
            self.stop()
            if self.req_rep_server is not None:
                self.req_rep_server.exit()
            if self.event_publisher is not None:
                self.event_publisher.exit()
        except:
            pass 
        if self._terminate_context:
            self.context.term()
        self.logger.info("terminated context of socket '{}' of type '{}'".format(self.id, self.__class__))


    # example of overloading
    # @remote_method()
    # def exit(self):
    #     """
    #     Stops the event loop and all its things. Generally, this leads
    #     to exiting the program unless some code follows the ``run()`` method.  
    #     """
    #     for thing in self.things:
    #         thing.exit()
    #     raise BreakAllLoops
    

   


__all__ = [
    RPCServer.__name__
]




class ZMQServer:
    

    def __init__(self, *, id : str, 
                things : typing.Union[Thing, typing.List[typing.Union[Thing]]], # type: ignore - requires covariant types
                protocols : typing.Union[ZMQ_TRANSPORTS, str, typing.List[ZMQ_TRANSPORTS]] = ZMQ_TRANSPORTS.IPC, 
                poll_timeout = 25, context : typing.Union[zmq.asyncio.Context, None] = None, 
                **kwargs
            ) -> None:
        self.inproc_server = self.ipc_server = self.tcp_server = self.event_publisher = None
        
        if isinstance(protocols, str): 
            protocols = [protocols]
        elif not isinstance(protocols, list): 
            raise TypeError(f"unsupported protocols type : {type(protocols)}")
        tcp_socket_address = kwargs.pop('tcp_socket_address', None)
        event_publisher_protocol = None 
        
        # initialise every externally visible protocol          
        if ZMQ_TRANSPORTS.TCP in protocols or "TCP" in protocols:
            self.tcp_server = AsyncZMQServer(id=self.id, server_type=ServerTypes.RPC, 
                                    context=self.context, transport=ZMQ_TRANSPORTS.TCP, poll_timeout=poll_timeout, 
                                    socket_address=tcp_socket_address, **kwargs)
            self.poller.register(self.tcp_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_TRANSPORTS.TCP
        if ZMQ_TRANSPORTS.IPC in protocols or "IPC" in protocols: 
            self.ipc_server = AsyncZMQServer(id=self.id, server_type=ServerTypes.RPC, 
                                    context=self.context, transport=ZMQ_TRANSPORTS.IPC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.ipc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_TRANSPORTS.IPC if not event_publisher_protocol else event_publisher_protocol           
            event_publisher_protocol = "IPC" if not event_publisher_protocol else event_publisher_protocol    

        self.poller = zmq.asyncio.Poller()
        self.poll_timeout = poll_timeout

    
    @property
    def poll_timeout(self) -> int:
        """
        socket polling timeout in milliseconds greater than 0. 
        """
        return self._poll_timeout

    @poll_timeout.setter
    def poll_timeout(self, value) -> None:
        if not isinstance(value, int) or value < 0:
            raise ValueError(("polling period must be an integer greater than 0, not {}.",
                              "Value is considered in milliseconds.".format(value)))
        self._poll_timeout = value 
