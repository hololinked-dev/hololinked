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
from .constants import JSON, ZMQ_TRANSPORTS, ServerTypes
from .utils import format_exception_as_json, get_current_async_loop, get_default_logger
from .config import global_config
from .exceptions import *
from .protocols.zmq.message import ERROR, HANDSHAKE, INVALID_MESSAGE, TIMEOUT, ResponseMessage
from .thing import Thing, ThingMeta
from .property import Property
from .properties import TypedList, Boolean, TypedDict
from .actions import Action, action as remote_method
from .logger import ListHandler

# from .protocols.zmq.brokers import (CM_INDEX_ADDRESS, CM_INDEX_CLIENT_TYPE, CM_INDEX_MESSAGE_TYPE, CM_INDEX_MESSAGE_ID, 
#                                 CM_INDEX_SERVER_EXEC_CONTEXT, CM_INDEX_THING_ID)
# from .protocols.zmq.brokers import SM_INDEX_ADDRESS
# from .protocols.zmq.brokers import EXIT, HANDSHAKE, INVALID_MESSAGE, TIMEOUT
# from .protocols.zmq.brokers import HTTP_SERVER, PROXY, TUNNELER 
# from .protocols.zmq.brokers import EMPTY_DICT
from .protocols.zmq.brokers import (AsyncZMQClient, AsyncZMQServer, BaseZMQServer, 
                                  EventPublisher, SyncZMQClient)
from .protocols.zmq.brokers import RequestMessage


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

    things = TypedDict(key_type=(bytes,), item_type=(Thing,), bounds=(0,100), allow_None=True, default=None,
                        doc="list of Things which are being executed", remote=False) # type: typing.Dict[bytes, Thing]
    
    threaded = Boolean(default=False, remote=False, 
                        doc="set True to run each thing in its own thread")
  

    def __init__(self, *, id : str, things : typing.List[Thing],
               context : typing.Union[zmq.asyncio.Context, None] = None, 
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
        self.things = dict() # typing.Dict[bytes, Thing]
        for thing in things:
            self.things[thing.id] = thing

        if self.logger is None:
            self.logger =  get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, 
                                                'RPC', 'MIXED', self.id), kwargs.get('log_level', logging.INFO))
        # contexts and poller
        self._terminate_context = context is None
        self.context = context or zmq.asyncio.Context()

       
        self.inproc_server = AsyncZMQServer(
                                id=self.id, 
                                context=self.context, 
                                transport=ZMQ_TRANSPORTS.INPROC, 
                                **kwargs
                            )        
        self.event_publisher = EventPublisher(
                                id=self.id + '-event-pub',
                                transport=ZMQ_TRANSPORTS.INPROC,
                                logger=self.logger,
                                **kwargs
                            )        
        # message serializing deque
        for instance in self.things.values():
            instance._zmq_messages = deque()
            instance._zmq_messages_event = asyncio.Event()
            instance.rpc_server = self
            instance.event_publisher = self.event_publisher 
            instance._prepare_resources()
     
        
    def __post_init__(self):
        super().__post_init__()
        self.logger.info("Server with name '{}' can be started using run().".format(self.id))   


    async def recv_requests(self, server : AsyncZMQServer):
        """
        Continuously keeps receiving messages from different clients and appends them to a deque to be processed 
        sequentially. Also handles messages that dont need to be queued like HANDSHAKE, EXIT, invokation timeouts etc.
        """
        eventloop = asyncio.get_event_loop()
        socket = server.socket
        while True:
            try:
                raw_message = await socket.recv_multipart()
                request_message = RequestMessage(raw_message)
                
                # handle message types first
                # if message_type == HANDSHAKE:
                #     handshake_task = asyncio.create_task(self._handshake(message, socket))
                #     self.eventloop.call_soon(lambda : handshake_task)
                #     continue 
                # if message_type == EXIT:
                #     break
                
                self.logger.debug(f"received message from client '{request_message.sender_id}' with message id '{request_message.id}', queuing.")
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
                                                invokation_timeout=invokation_timeout, 
                                                origin_socket=socket, 
                                                timeout_type='invokation'
                                            )
                                        )
                    eventloop.call_soon(lambda : timeout_task)
            except Exception as ex:
                # handle invalid message
                self.logger.error(f"exception occurred for message id '{request_message.id}' - {str(ex)}")
                invalid_message_task = asyncio.create_task(
                                            self._handle_invalid_message(
                                                request_message=request_message,
                                                origin_socket=socket,
                                                exception=ex
                                            )
                                        )
                eventloop.call_soon(lambda: invalid_message_task)
            else:
                instance = self.things[request_message.thing_id]
                # append to messages list - message, execution context, event, timeout task, origin socket
                instance._zmq_messages.append((request_message, ready_to_process_event, timeout_task, socket))
                instance._zmq_messages_event.set() # this was previously outside the else block - reason unknown now
        self.logger.info(f"stopped polling for server '{server.identity}' {server.socket_address[0:3].upper() if server.socket_address[0:3] in ['ipc', 'tcp'] else 'INPROC'}")
           
 
    async def tunnel_message_to_things(self, instance : Thing) -> None:
        """
        message tunneler between external sockets and interal inproc client
        """
        eventloop = asyncio.get_event_loop()
        while not self.stop_poll:
            # wait for message first
            if len(instance._zmq_messages) == 0:
                await instance._zmq_messages_event.wait()
                instance._zmq_messages_event.clear()
                # this means in next loop it wont be in this block as a message arrived  
                continue

            # retrieve from messages list - message, execution context, event, timeout task, origin socket
            request_message, ready_to_process_event, timeout_task, origin_socket = instance._zmq_messages.popleft() 
            request_message : RequestMessage
            ready_to_process_event : asyncio.Event
            origin_socket : zmq.Socket | zmq.asyncio.Socket
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
            instance._message_execution_event.set()
                    
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
                                                            origin_socket=origin_socket,
                                                            timeout_type='execution'
                                                        )
                                                    )
                eventloop.call_soon(lambda : execution_timeout_task)

            # always wait for reply from thing, since this loop is asyncio task (& in its own thread in RPC server), 
            # timeouts always reach client without truly blocking by the GIL. If reply does not arrive, all other requests
            # get invokation timeout.            
            await eventloop.run_in_executor(None, instance._message_execution_event.wait, tuple())
            instance._message_execution_event.clear()
            reply = instance._last_operation_reply

            # check if reply is never undefined, Undefined is a sensible placeholder for NotImplemented singleton
            if reply is Undefined:
                # this is a logic error, as the reply should never be undefined
                await self._handle_error_message(
                            request_message=request_message, 
                            origin_socket=origin_socket, 
                            exception=RuntimeError("No reply from thing - logic error")
                        )
                continue
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
            response_message = ResponseMessage.craft_reply_from_request(
                                            request_message=request_message,
                                            payload=reply
                                        )
            await origin_socket.send_multipart(response_message.byte_array)    
        self.logger.info("stopped tunneling messages to things")


    async def run_single_thing(self, instance : Thing) -> None: 
        while True:
            await self.eventloop.run_in_executor(None, instance._message_execution_event.wait, tuple())
            instance._message_execution_event.clear()
            instance._last_operation_reply = Undefined
            operation_request = instance._last_operation_request 
            if operation_request is Undefined:
                raise RuntimeError("No operation request found in thing '{}'".format(instance.id))

            thing_id, objekt, operation, payload, preserialized_payload, execution_context = operation_request  
            instance.logger.debug(f"thing {instance.id} with {thing_id} starting execution of operation {operation} on {objekt}")

            fetch_execution_logs = execution_context.pop("fetch_execution_logs", False)
            if fetch_execution_logs:
                list_handler = ListHandler([])
                list_handler.setLevel(logging.DEBUG)
                list_handler.setFormatter(instance.logger.handlers[0].formatter)
                instance.logger.addHandler(list_handler)
            try:
                return_value = await self.execute_once(instance, objekt, operation, payload, preserialized_payload) 
                if fetch_execution_logs:
                    return_value = {
                        "return_value" : return_value,
                        "execution_logs" : list_handler.log_list
                    }
                await instance._last_operation_request = return_value
            except (BreakInnerLoop, BreakAllLoops):
                instance.logger.info("Thing {} with instance name {} exiting event loop.".format(
                                                        instance.__class__.__name__, instance.id))
                return_value = None
                if fetch_execution_logs:
                    return_value = { 
                        "return_value" : None,
                        "execution_logs" : list_handler.log_list
                    }
                instance._last_operation_reply = return_value
                return 
            except Exception as ex:
                instance.logger.error("Thing {} with ID {} produced error : {}.".format(
                                                        instance.__class__.__name__, instance.id, ex))
                return_value = dict(exception=format_exception_as_json(ex))
                if fetch_execution_logs:
                    return_value["execution_logs"] = list_handler.log_list
                instance._last_operation_reply = return_value
            finally:
                instance._last_operation_request = Undefined
                instance._message_execution_event.set()
                if fetch_execution_logs:
                    instance.logger.removeHandler(list_handler)

   
    async def execute_once(cls, 
                        instance: Thing, 
                        objekt: str, 
                        operation: str,
                        payload: typing.Any,
                        preserialized_payload: bytes
                    ) -> typing.Any:
        if operation == 'readProperty':
            prop = instance.properties[objekt] # type: Property
            return getattr(instance, prop.name) 
        elif operation == 'writeProperty':
            prop = instance.properties[objekt] # type: Property
            return prop.external_set(instance, payload) # external set has state machine logic inside
        elif operation == 'deleteProperty':
            prop = instance.properties[objekt] # type: Property
            del prop # raises NotImplementedError when deletion is not implemented which is mostly the case
        elif operation == 'invokeAction':
            action = instance.actions[objekt] # type: Action
            args = payload.pop('__args__', tuple())
            # payload then become kwargs
            if action.execution_info.iscoroutine:
                return await action.external_call(*args, **payload) 
            else:
                return action.external_call(*args, **payload) 
        elif operation == 'readMultipleProperties' or operation == 'readAllProperties':
            if objekt is None:
                return instance._get_properties()
            return instance._get_properties(names=objekt)
        elif operation == 'writeMultipleProperties' or operation == 'writeAllProperties':
            return instance._set_properties(payload)
        # elif operation == b'dataResponse': # no operation defined yet for dataResponse to events in Thing Description
        #     from .events import CriticalEvent
        #     event = instance.events[objekt] # type: CriticalEvent, this name "CriticalEvent" needs to change, may be just plain Event
        #     return event._set_acknowledgement(**payload)
        raise NotImplementedError("Unimplemented execution path for Thing {} for operation {}".format(
                                                                        instance.id, operation))


    async def process_timeouts(self, 
                            request_message: RequestMessage, 
                            ready_to_process_event: asyncio.Event,
                            origin_socket: zmq.asyncio.Socket, 
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
            response_message = ResponseMessage.craft_with_message_type(                 
                                                request_message=request_message,
                                                message_type=TIMEOUT, 
                                                data=timeout_type
                                            )
            await origin_socket.send_multipart(response_message.byte_array)
            self.logger.debug("sent timeout message to client '{}'".format(request_message.sender_id))   
            return True


    async def _handle_invalid_message(self, 
                                request_message: RequestMessage, 
                                origin_socket: zmq.Socket, 
                                exception: Exception
                            ) -> None:
        response_message = ResponseMessage.craft_with_message_type(
                                            request_message=request_message,
                                            message_type=INVALID_MESSAGE,
                                            data=exception
                                        )
        await origin_socket.send_multipart(response_message.byte_array)          
        self.logger.info(f"sent exception message to client '{response_message.receiver_id}'." +
                            f" exception - {str(exception)}") 	
    

    async def _handle_error_message(self, 
                                request_message: RequestMessage,
                                origin_socket : zmq.Socket, 
                                exception: Exception
                            ) -> None:
        response_message = ResponseMessage.craft_with_message_type(
                                                            request_message=request_message,
                                                            message_type=ERROR,
                                                            data=exception
                                                        )
        await origin_socket.send_multipart(response_message.byte_array)    
        self.logger.info(f"sent exception message to client '{response_message.receiver_id}'." +
                            f" exception - {str(exception)}")
        

    async def _handshake(self, 
                        request_message: RequestMessage,
                        origin_socket: zmq.Socket
                    ) -> None:
        response_message = ResponseMessage.craft_with_message_type(
                                            request_message=request_message,
                                            message_type=HANDSHAKE
                                        )
        
        await origin_socket.send_multipart(response_message.byte_array)
        self.logger.info("sent handshake to client '{}'".format(request_message.sender_id))


    def run_external_message_listener(self):
        """
        Runs ZMQ's sockets which are visible to clients.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        self.request_listener_loop = get_current_async_loop()
        futures = []
        futures.append(self.poll())
        futures.append(self.tunnel_message_to_things())
        self.logger.info("starting external message listener thread")
        self.request_listener_loop.run_until_complete(asyncio.gather(*futures))
        # pending_tasks = asyncio.all_tasks(self.request_listener_loop)
        # self.request_listener_loop.run_until_complete(asyncio.gather(*pending_tasks))
        self.logger.info("exiting external listener event loop {}".format(self.id))
        self.request_listener_loop.close()
    

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
            asyncio.gather(*[self.run_single_target(instance) for instance in things])
        )
        self.logger.info(f"exiting event loop in thread {threading.get_ident()}")
        thing_executor_loop.close()


    async def poll(self):
        """
        poll for messages and append them to messages list to pass them to ``Eventloop``/``Thing``'s inproc 
        server using an inner inproc client. Registers the messages for timeout calculation.
        """
        self.stop_poll = False
        self.eventloop = asyncio.get_event_loop()
        if self.inproc_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_requests(self.inproc_server)))
        if self.ipc_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_requests(self.ipc_server)))
        if self.tcp_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_requests(self.tcp_server)))
       

    def stop_polling(self):
        """
        stop polling method ``poll()``
        """
        # self.stop_poll = True
        # instance._messages_event.set()
        # if self.inproc_server is not None:
        #     def kill_inproc_server(id, context, logger):
        #         # this function does not work when written fully async - reason is unknown
        #         try: 
        #             event_loop = asyncio.get_event_loop()
        #         except RuntimeError:
        #             event_loop = asyncio.new_event_loop()
        #             asyncio.set_event_loop(event_loop)
        #         temp_inproc_client = AsyncZMQClient(server_id=id,
        #                                     identity=f'{self.id}-inproc-killer',
        #                                     context=context, client_type=PROXY, transport=ZMQ_TRANSPORTS.INPROC, 
        #                                     logger=logger) 
        #         event_loop.run_until_complete(temp_inproc_client.handshake_complete())
        #         event_loop.run_until_complete(temp_inproc_client.socket.send_multipart(temp_inproc_client.craft_empty_message_with_type(EXIT)))
        #         temp_inproc_client.exit()
        #     threading.Thread(target=kill_inproc_server, args=(self.id, self.context, self.logger), daemon=True).start()
        # if self.ipc_server is not None:
        #     temp_client = SyncZMQClient(server_id=self.id, identity=f'{self.id}-ipc-killer',
        #                             client_type=PROXY, transport=ZMQ_TRANSPORTS.IPC, logger=self.logger) 
        #     temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
        #     temp_client.exit()
        # if self.tcp_server is not None:
        #     socket_address = self.tcp_server.socket_address
        #     if '/*:' in self.tcp_server.socket_address:
        #         socket_address = self.tcp_server.socket_address.replace('*', 'localhost')
        #     # print("TCP socket address", self.tcp_server.socket_address)
        #     temp_client = SyncZMQClient(server_id=self.id, identity=f'{self.id}-tcp-killer',
        #                             client_type=PROXY, transport=ZMQ_TRANSPORTS.TCP, logger=self.logger,
        #                             socket_address=socket_address)
        #     temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
        #     temp_client.exit()   
        raise NotImplementedError("stop_polling() not implemented yet")

    def exit(self):
        self.stop_poll = True
        for socket in list(self.poller._map.keys()): # iterating over keys will cause dictionary size change during iteration
            try:
                self.poller.unregister(socket)
            except Exception as ex:
                self.logger.warning(f"could not unregister socket from polling - {str(ex)}") # does not give info about socket
        try:
            if self.inproc_server is not None:
                self.inproc_server.exit()
            if self.ipc_server is not None:
                self.ipc_server.exit()
            if self.tcp_server is not None:
                self.tcp_server.exit()
            if self.inner_inproc_client is not None:
                self.inner_inproc_client.exit()
            if self.event_publisher is not None:
                self.event_publisher.exit()
        except:
            pass 
        # if self._terminate_context:
        #     self.context.term()
        self.logger.info("terminated context of socket '{}' of type '{}'".format(self.id, self.__class__))


    async def handshake_complete(self):
        """
        handles inproc client's handshake with ``Thing``'s inproc server
        """
        await self.inner_inproc_client.handshake_complete()


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
    

    uninstantiated_things = TypedDict(default=None, allow_None=True, key_type=str,
                                            item_type=str)
    
    
    @classmethod
    def _import_thing(cls, file_name : str, object_name : str):
        """
        import a thing specified by ``object_name`` from its 
        script or module. 

        Parameters
        ----------
        file_name : str
            file or module path 
        object_name : str
            name of ``Thing`` class to be imported
        """
        module_name = file_name.split(os.sep)[-1]
        spec = importlib.util.spec_from_file_location(module_name, file_name)
        if spec is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:     
            module = importlib.import_module(module_name, file_name.split(os.sep)[0])
        consumer = getattr(module, object_name) 
        if issubclass(consumer, Thing):
            return consumer 
        else:
            raise ValueError(f"object name {object_name} in {file_name} not a subclass of Thing.", 
                            f" Only subclasses are accepted (not even instances). Given object : {consumer}")
        

    @remote_method()
    def import_thing(self, file_name : str, object_name : str):
        """
        import thing from the specified path and return the default 
        properties to be supplied to instantiate the object. 
        """
        consumer = self._import_thing(file_name, object_name) # type: ThingMeta
        id = uuid4()
        self.uninstantiated_things[id] = consumer
        return id
           

    @remote_method() # remember to pass schema with mandatory instance name
    def instantiate(self, id : str, kwargs : typing.Dict = {}):      
        """
        Instantiate the thing that was imported with given arguments 
        and add to the event loop
        """
        consumer = self.uninstantiated_things[id]
        instance = consumer(**kwargs, eventloop_name=self.id) # type: Thing
        self.things.append(instance)
        rpc_server = instance.rpc_server
        self.request_listener_loop.call_soon(asyncio.create_task(lambda : rpc_server.poll()))
        self.request_listener_loop.call_soon(asyncio.create_task(lambda : rpc_server.tunnel_message_to_things()))
        if not self.threaded:
            self.thing_executor_loop.call_soon(asyncio.create_task(lambda : self.run_single_target(instance)))
        else: 
            _thing_executor = threading.Thread(target=self.run_things_executor, args=([instance],))
            _thing_executor.start()


    def run(self):
        """
        start the eventloop
        """
        if not self.threaded:
            _thing_executor = threading.Thread(target=self.run_things_executor, args=(self.things,))
            _thing_executor.start()
        else: 
            for thing in self.things:
                _thing_executor = threading.Thread(target=self.run_things_executor, args=([thing],))
                _thing_executor.start()
        self.run_external_message_listener()
        if not self.threaded:
            _thing_executor.join()



    def run_external_message_listener(self):
        """
        Runs ZMQ's sockets which are visible to clients.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        self.request_listener_loop = self.get_async_loop()
        rpc_servers = [thing.rpc_server for thing in self.things]
        futures = []
        for rpc_server in rpc_servers:
            futures.append(rpc_server.poll())
            futures.append(rpc_server.tunnel_message_to_things())
        self.logger.info("starting external message listener thread")
        self.request_listener_loop.run_until_complete(asyncio.gather(*futures))
        pending_tasks = asyncio.all_tasks(self.request_listener_loop)
        self.request_listener_loop.run_until_complete(asyncio.gather(*pending_tasks))
        self.logger.info("exiting external listener event loop {}".format(self.instance_name))
        self.request_listener_loop.close()
    

    def run_things_executor(self, things):
        """
        Run ZMQ sockets which provide queued instructions to ``Thing``.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        thing_executor_loop = self.get_async_loop()
        self.thing_executor_loop = thing_executor_loop # atomic assignment for thread safety
        self.logger.info(f"starting thing executor loop in thread {threading.get_ident()} for {[obj.instance_name for obj in things]}")
        thing_executor_loop.run_until_complete(
            asyncio.gather(*[self.run_single_target(instance) for instance in things])
        )
        self.logger.info(f"exiting event loop in thread {threading.get_ident()}")
        thing_executor_loop.close()


    @classmethod
    async def run_single_target(cls, instance : Thing) -> None: 
        instance_name = instance.instance_name
        while True:
            instructions = await instance.message_broker.async_recv_instructions()
            for instruction in instructions:
                client, _, client_type, _, msg_id, _, instruction_str, arguments, context = instruction
                oneway = context.pop('oneway', False)
                fetch_execution_logs = context.pop("fetch_execution_logs", False)
                if fetch_execution_logs:
                    list_handler = ListHandler([])
                    list_handler.setLevel(logging.DEBUG)
                    list_handler.setFormatter(instance.logger.handlers[0].formatter)
                    instance.logger.addHandler(list_handler)
                try:
                    instance.logger.debug(f"client {client} of client type {client_type} issued instruction " +
                                f"{instruction_str} with message id {msg_id}. starting execution.")
                    return_value = await cls.execute_once(instance_name, instance, instruction_str, arguments) #type: ignore 
                    if oneway:
                        await instance.message_broker.async_send_reply_with_message_type(instruction, b'ONEWAY', None)
                        continue
                    if fetch_execution_logs:
                        return_value = {
                            "returnValue" : return_value,
                            "execution_logs" : list_handler.log_list
                        }
                    await instance.message_broker.async_send_reply(instruction, return_value)
                    # Also catches exception in sending messages like serialization error
                except (BreakInnerLoop, BreakAllLoops):
                    instance.logger.info("Thing {} with instance name {} exiting event loop.".format(
                                                            instance.__class__.__name__, instance_name))
                    if oneway:
                        await instance.message_broker.async_send_reply_with_message_type(instruction, b'ONEWAY', None)
                        continue
                    return_value = None
                    if fetch_execution_logs:
                        return_value = { 
                            "returnValue" : None,
                            "execution_logs" : list_handler.log_list
                        }
                    await instance.message_broker.async_send_reply(instruction, return_value)
                    return 
                except Exception as ex:
                    instance.logger.error("Thing {} with instance name {} produced error : {}.".format(
                                                            instance.__class__.__name__, instance_name, ex))
                    if oneway:
                        await instance.message_broker.async_send_reply_with_message_type(instruction, b'ONEWAY', None)
                        continue
                    return_value = dict(exception= format_exception_as_json(ex))
                    if fetch_execution_logs:
                        return_value["execution_logs"] = list_handler.log_list
                    await instance.message_broker.async_send_reply_with_message_type(instruction, 
                                                                    b'EXCEPTION', return_value)
                finally:
                    if fetch_execution_logs:
                        instance.logger.removeHandler(list_handler)

    @classmethod
    async def execute_once(cls, instance_name : str, instance : Thing, instruction_str : str, 
                           arguments : typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        resource = instance.instance_resources.get(instruction_str, None) 
        if resource is None:
            raise AttributeError(f"unknown remote resource represented by instruction {instruction_str}")
        if resource.isaction:      
            if resource.state is None or (hasattr(instance, 'state_machine') and 
                            instance.state_machine.current_state in resource.state):
                # Note that because we actually find the resource within __prepare_instance__, its already bound
                # and we dont have to separately bind it. 
                if arguments is None:
                    arguments = dict()
                args = arguments.pop('__args__', tuple())
                if len(args) == 0 and resource.schema_validator is not None:
                    resource.schema_validator.validate(arguments)
                
                func = resource.obj
                if resource.iscoroutine:
                    if resource.isparameterized:
                        if len(args) > 0:
                            raise RuntimeError("parameterized functions cannot have positional arguments")
                        return await func(resource.bound_obj, *args, **arguments)
                    return await func(*args, **arguments) # arguments then become kwargs
                else:
                    if resource.isparameterized:
                        if len(args) > 0:
                            raise RuntimeError("parameterized functions cannot have positional arguments")
                        return func(resource.bound_obj, *args, **arguments)
                    return func(*args, **arguments) # arguments then become kwargs
            else: 
                raise StateMachineError("Thing '{}' is in '{}' state, however command can be executed only in '{}' state".format(
                        instance_name, instance.state, resource.state))
        
        elif resource.isproperty:
            action = instruction_str.split('/')[-1]
            prop = resource.obj # type: Property
            owner_inst = resource.bound_obj # type: Thing
            if action == "write": 
                if resource.state is None or (hasattr(instance, 'state_machine') and  
                                        instance.state_machine.current_state in resource.state):
                    if isinstance(arguments, dict) and len(arguments) == 1 and 'value' in arguments:
                        return prop.__set__(owner_inst, arguments['value'])
                    return prop.__set__(owner_inst, arguments)
                else: 
                    raise StateMachineError("Thing {} is in `{}` state, however attribute can be written only in `{}` state".format(
                        instance_name, instance.state_machine.current_state, resource.state))
            elif action == "read":
                return prop.__get__(owner_inst, type(owner_inst))             
            elif action == "delete":
                if prop.fdel is not None:
                    return prop.fdel() # this may not be correct yet
                raise NotImplementedError("This property does not support deletion")
        raise NotImplementedError("Unimplemented execution path for Thing {} for instruction {}".format(instance_name, instruction_str))


def fork_empty_eventloop(instance_name : str, logfile : typing.Union[str, None] = None, python_command : str = 'python',
                        condaenv : typing.Union[str, None] = None, prefix_command : typing.Union[str, None] = None):
    command_str = '{}{}{}-c "from hololinked.server import EventLoop; E = EventLoop({}); E.run();"'.format(
        f'{prefix_command} ' if prefix_command is not None else '',
        f'call conda activate {condaenv} && ' if condaenv is not None else '',
        f'{python_command} ',
        f"instance_name = '{instance_name}', logfile = '{logfile}'"
    )
    print(f"command to invoke : {command_str}")
    subprocess.Popen(
        command_str, 
        shell = True
    )


# class ForkedEventLoop:

#     def __init__(self, instance_name : str, things : Union[Thing, Consumer, List[Union[Thing, Consumer]]], 
#                 log_level : int = logging.INFO, **kwargs):
#         self.subprocess = Process(target = forked_eventloop, kwargs = dict(
#                         instance_name = instance_name, 
#                         things = things, 
#                         log_level = log_level,
#                         **kwargs
#                     ))
    
#     def start(self):
#         self.Process.start()



__all__ = ['EventLoop', 'Consumer', 'fork_empty_eventloop']
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
