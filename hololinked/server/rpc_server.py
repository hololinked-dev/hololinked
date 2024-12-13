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


from .constants import JSON, ZMQ_PROTOCOLS, ServerTypes
from .utils import format_exception_as_json, get_current_async_loop, get_default_logger
from .config import global_config
from .exceptions import *
from .thing import Thing, ThingMeta
from .property import Property
from .properties import TypedList, Boolean, TypedDict
from .actions import Action, action as remote_method
from .logger import ListHandler

from .zmq_message_brokers import (CM_INDEX_ADDRESS, CM_INDEX_CLIENT_TYPE, CM_INDEX_MESSAGE_TYPE, CM_INDEX_MESSAGE_ID, 
                                CM_INDEX_SERVER_EXEC_CONTEXT, CM_INDEX_THING_ID)
from .zmq_message_brokers import SM_INDEX_ADDRESS
from .zmq_message_brokers import EXIT, HANDSHAKE, INVALID_MESSAGE, TIMEOUT
from .zmq_message_brokers import HTTP_SERVER, PROXY, TUNNELER 
from .zmq_message_brokers import EMPTY_DICT
from .zmq_message_brokers import (AsyncZMQClient, AsyncZMQServer, BaseZMQServer, 
                                  EventPublisher, SyncZMQClient)



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
    instance_name: str
        ``instance_name`` of the server
    server_type: str
        server type metadata
    context: Optional, zmq.asyncio.Context
        ZeroMQ async Context object to use. All sockets except those created by event publisher share this context. 
        Automatically created when None is supplied.
    protocols: List[str, Enum], default [ZMQ_PROTOCOLS.TCP, ZMQ_PROTOCOLS.IPC, ZMQ_PROTOCOLS.INPROC]
        all ZeroMQ sockets where messages can be passed to the RPC server. Use TCP for network access,
        IPC for multi-process applications, and INPROC for multi-threaded applications. Use multiple or all for 
        broader access, requests will be any queued before executing. 
    poll_timeout: int, default 25
        time in milliseconds to poll the sockets specified under ``procotols``. Useful for calling ``stop_polling()``
        where the max delay to stop polling will be ``poll_timeout``
    **kwargs:
        tcp_socket_address: str
            address of the TCP socket, if not given, a random port is chosen
    """
    
    expose = Boolean(default=True, remote=False,
                     doc="""set to False to use the object locally to avoid alloting network resources 
                        of your computer for this object""")

    things = TypedList(item_type=(Thing,), bounds=(0,100), allow_None=True, default=None,
                        doc="list of Things which are being executed", remote=False) # type: typing.List[Thing]
    
    threaded = Boolean(default=False, remote=False, 
                        doc="set True to run each thing in its own thread")
  

    def __init__(self, *, instance_name : str, 
                things : typing.Union[Thing, typing.List[typing.Union[Thing]]], # type: ignore - requires covariant types
                protocols : typing.Union[ZMQ_PROTOCOLS, str, typing.List[ZMQ_PROTOCOLS]] = ZMQ_PROTOCOLS.IPC, 
                poll_timeout = 25, context : typing.Union[zmq.asyncio.Context, None] = None, 
                **kwargs
            ) -> None:
        """
        Parameters
        ----------
        instance_name: str
            instance name of the event loop
        things: List[Thing]
            things to be run/served
        log_level: int
            log level of the event loop logger
        """
        BaseZMQServer.__init__(self, instance_name=instance_name, server_type=ServerTypes.RPC.value, 
                                **kwargs)
        self.things = things
        kwargs["http_serializer"] = self.http_serializer
        kwargs["zmq_serializer"] = self.zmq_serializer
        # RemoteObject.__init__(self, instance_name=instance_name, logger=self.logger, things=things,
        #                         logger_remote_access=False, **kwargs)
        # if self.expose:
        #     self.things.append(self)      
        self.uninstantiated_things = dict()

        if isinstance(protocols, str): 
            protocols = [protocols]
        elif not isinstance(protocols, list): 
            raise TypeError(f"unsupported protocols type : {type(protocols)}")
        tcp_socket_address = kwargs.pop('tcp_socket_address', None)
        
        self.inproc_server = self.ipc_server = self.tcp_server = self.event_publisher = None
        event_publisher_protocol = None 
        if self.logger is None:
            self.logger =  get_default_logger('{}|{}|{}|{}'.format(self.__class__.__name__, 
                                                'RPC', 'MIXED', self.instance_name), kwargs.get('log_level', logging.INFO))
        # contexts and poller
        self._terminate_context = context is None
        self.context = context or zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.poll_timeout = poll_timeout
        # initialise every externally visible protocol
        if ZMQ_PROTOCOLS.TCP in protocols or "TCP" in protocols:
            self.tcp_server = AsyncZMQServer(instance_name=self.instance_name, server_type=ServerTypes.RPC, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.TCP, poll_timeout=poll_timeout, 
                                    socket_address=tcp_socket_address, **kwargs)
            self.poller.register(self.tcp_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.TCP
        if ZMQ_PROTOCOLS.IPC in protocols or "IPC" in protocols: 
            self.ipc_server = AsyncZMQServer(instance_name=self.instance_name, server_type=ServerTypes.RPC, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.IPC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.ipc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.IPC if not event_publisher_protocol else event_publisher_protocol              
        if ZMQ_PROTOCOLS.INPROC in protocols or "INPROC" in protocols: 
            self.inproc_server = AsyncZMQServer(instance_name=self.instance_name, server_type=ServerTypes.RPC, 
                                    context=self.context, protocol=ZMQ_PROTOCOLS.INPROC, poll_timeout=poll_timeout, **kwargs)
            self.poller.register(self.inproc_server.socket, zmq.POLLIN)
            event_publisher_protocol = ZMQ_PROTOCOLS.INPROC if not event_publisher_protocol else event_publisher_protocol    
        self.event_publisher = EventPublisher(
                            instance_name=self.instance_name + '-event-pub',
                            protocol=event_publisher_protocol,
                            zmq_serializer=self.zmq_serializer,
                            http_serializer=self.http_serializer,
                            logger=self.logger
                        )        
        # message serializing broker
        self.inner_inproc_client = AsyncZMQClient(
                                        server_instance_name=f'{self.instance_name}/inner', 
                                        identity=f'{self.instance_name}/tunneler',
                                        client_type=TUNNELER, 
                                        context=self.context, 
                                        protocol=ZMQ_PROTOCOLS.INPROC, 
                                        handshake=False, # handshake manually done later when event loop is run
                                        logger=self.logger
                                    )
        for instance in self.things:
            instance.message_broker = AsyncZMQServer(
                                        instance_name=f'{instance.instance_name}/inner', # hardcoded be very careful
                                        server_type=ServerTypes.THING,
                                        context=self.context,
                                        protocol=ZMQ_PROTOCOLS.INPROC,
                                        logger=self.logger,
                                        poll_timeout=poll_timeout,
                                        **kwargs
                                    ) 
            instance.rpc_server = self
            instance.event_publisher = self.event_publisher 
            instance._prepare_resources()
        # # append to messages list - message, execution context, event, timeout task, origin socket
        self._messages = deque() # type: deque[typing.Tuple[typing.List[bytes], typing.Dict[str, typing.Any], asyncio.Event, asyncio.Future, zmq.Socket]]
        self._messages_event = asyncio.Event()
        
        
    def __post_init__(self):
        super().__post_init__()
        self.logger.info("Server with name '{}' can be started using run().".format(self.instance_name))   


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


    async def run_single_target(self, instance : Thing) -> None: 
        while True:
            messages = await instance.message_broker.async_recv_requests()
            for message in messages:
                client, mty_byte_1, client_type, msg_type, msg_id, server_execution_context, mty_byte_2, thing_id, objekt, operation, arguments, execution_context = message
                fetch_execution_logs = execution_context.pop("fetch_execution_logs", False)
                if fetch_execution_logs:
                    list_handler = ListHandler([])
                    list_handler.setLevel(logging.DEBUG)
                    list_handler.setFormatter(instance.logger.handlers[0].formatter)
                    instance.logger.addHandler(list_handler)
                try:
                    instance.logger.debug(f"client {client} of client type {client_type} issued operation " +
                                f"{operation} with message id {msg_id}. starting execution.")
                    return_value = await self.execute_once(instance, objekt, operation,  arguments) 
                    if fetch_execution_logs:
                        return_value = {
                            "return_value" : return_value,
                            "execution_logs" : list_handler.log_list
                        }
                    await instance.message_broker.async_send_response(message, return_value)
                    # Also catches exception in sending messages like serialization error
                except (BreakInnerLoop, BreakAllLoops):
                    instance.logger.info("Thing {} with instance name {} exiting event loop.".format(
                                                            instance.__class__.__name__, instance.instance_name))
                    return_value = None
                    if fetch_execution_logs:
                        return_value = { 
                            "return_value" : None,
                            "execution_logs" : list_handler.log_list
                        }
                    await instance.message_broker.async_send_response(message, return_value)
                    return 
                except Exception as ex:
                    instance.logger.error("Thing {} with instance name {} produced error : {}.".format(
                                                            instance.__class__.__name__, instance.instance_name, ex))
                    return_value = dict(exception=format_exception_as_json(ex))
                    if fetch_execution_logs:
                        return_value["execution_logs"] = list_handler.log_list
                    await instance.message_broker.async_send_response_with_message_type(message, 
                                                                    b'EXCEPTION', return_value)
                finally:
                    if fetch_execution_logs:
                        instance.logger.removeHandler(list_handler)

   
    async def execute_once(cls, instance : Thing, objekt : typing.Optional[str], operation : str,
                               arguments : typing.Dict[str, typing.Any]) -> typing.Any:
        if operation == b'readProperty':
            prop = instance.properties[objekt] # type: Property
            return prop.__get__(instance, type(instance))        
        elif operation == b'writeProperty':
            prop = instance.properties[objekt] # type: Property
            return prop.external_set(instance, arguments) # external set has state machine logic inside
        elif operation == b'deleteProperty':
            prop = instance.properties[objekt] # type: Property
            del prop # raises NotImplementedError when deletion is not implemented which is mostly the case
        elif operation == b'invokeAction':
            action = instance.actions[objekt] # type: Action
            args = arguments.pop('__args__', tuple())
            # arguments then become kwargs
            assert action.validate_call(args, arguments) # state machine and schema validation, must return True
            if action.execution_info.iscoroutine:
                return await action(*args, **arguments) 
            else:
                return action(*args, **arguments) 
        elif operation == b'readMultipleProperties' or operation == b'readAllProperties':
            if objekt is None:
                return instance._get_properties()
            return instance._get_properties(names=objekt)
        elif operation == b'writeMultipleProperties' or operation == b'writeAllProperties':
            return instance._set_properties(arguments)
        # elif operation == b'dataResponse': # no operation defined yet for dataResponse to events in Thing Description
        #     from .events import CriticalEvent
        #     event = instance.events[objekt] # type: CriticalEvent, this name "CriticalEvent" needs to change, may be just plain Event
        #     return event._set_acknowledgement(**arguments)
        raise NotImplementedError("Unimplemented execution path for Thing {} for operation {}".format(
                                                                        instance.instance_name, operation))
    
        
    def _get_server_execution_context_client_message(self, message : typing.Tuple[bytes]) -> JSON:
        """
        Unlike ``parse_client_message()``, this method only retrieves the timeout parameter
        """
        client_type = message[CM_INDEX_CLIENT_TYPE]
        if client_type == PROXY:
            return self.zmq_serializer.loads(message[CM_INDEX_SERVER_EXEC_CONTEXT]) 
        elif client_type == HTTP_SERVER:
            return self.http_serializer.loads(message[CM_INDEX_SERVER_EXEC_CONTEXT])
       

    async def recv_request(self, server : AsyncZMQServer):
        eventloop = asyncio.get_event_loop()
        socket = server.socket
        while True:
            try:
                message = await socket.recv_multipart()
                # handle message types first
                if message[CM_INDEX_MESSAGE_TYPE] == HANDSHAKE:
                    handshake_task = asyncio.create_task(self._handshake(message, socket))
                    self.eventloop.call_soon(lambda : handshake_task)
                    continue 
                if message[CM_INDEX_MESSAGE_TYPE] == EXIT:
                    break

                # handle invokation timeout
                execution_context = self._get_server_execution_context_client_message(message)
                invokation_timeout = execution_context.get("invokation_timeout", None)

                # schedule to tunnel it to thing
                ready_to_process_event = None
                timeout_task = None
                if invokation_timeout is not None:
                    ready_to_process_event = asyncio.Event()
                    timeout_task = asyncio.create_task(self.process_timeouts(message, 
                                                ready_to_process_event, invokation_timeout, socket, 'invokation'))
                    eventloop.call_soon(lambda : timeout_task)
            except Exception as ex:
                # handle invalid message
                self.logger.error(f"exception occurred for message id '{message[CM_INDEX_MESSAGE_ID]}' - {str(ex)}")
                invalid_message_task = asyncio.create_task(self._handle_invalid_message(original_client_message=message,
                                                            exception=ex, originating_socket=socket))
                eventloop.call_soon(lambda: invalid_message_task)
            else:
                # append to messages list - message, execution context, event, timeout task, origin socket
                self._messages.append((message, execution_context, ready_to_process_event, timeout_task, socket))
            self._messages_event.set()
        self.logger.info(f"stopped polling for server '{server.identity}' {server.socket_address[0:3].upper() if server.socket_address[0:3] in ['ipc', 'tcp'] else 'INPROC'}")
           
 
    async def tunnel_message_to_things(self):
        """
        message tunneler between external sockets and interal inproc client
        """
        while not self.stop_poll:
            if len(self._messages) == 0:
                await self._messages_event.wait()
                self._messages_event.clear()
                # this means in next loop it wont be in this block as a message arrived  
                continue
            # retrieve from messages list - message, execution context, event, timeout task, origin socket
            message, execution_context, ready_to_process_event, timeout_task, origin_socket = self._messages.popleft()
            invokation_timed_out = True 
            if ready_to_process_event is not None: 
                ready_to_process_event.set() # releases timeout task 
                invokation_timed_out = await timeout_task
            if ready_to_process_event is not None and invokation_timed_out:
                # drop call to thing
                continue 
            # handle execution through thing
            original_address = message[CM_INDEX_ADDRESS]
            message[CM_INDEX_ADDRESS] = message[CM_INDEX_THING_ID] # replace address
            await self.inner_inproc_client.socket.send_multipart(message)
            # schedule an execution timeout
            execution_timeout = execution_context.get("execution_timeout", None)
            execution_completed_event = None 
            execution_timeout_task = None
            execution_timed_out = True
            if execution_timeout is not None:
                execution_completed_event = asyncio.Event()
                execution_timeout_task = asyncio.create_task(self.process_timeouts(message, 
                                        execution_completed_event, execution_timeout, origin_socket, 'execution'))
                self.eventloop.call_soon(lambda : execution_timeout_task)
            # always wait for reply from thing, since this loop is asyncio task (& in its own thread in RPC server), 
            # timeouts always reach client without truly blocking by the GIL. If reply does not arrive, all other requests
            # get invokation timeout.
            reply = await self.inner_inproc_client.socket.recv_multipart()
            reply[SM_INDEX_ADDRESS] = original_address
            # check if execution completed within time
            if execution_completed_event is not None:
                execution_completed_event.set() # releases timeout task
                execution_timed_out = await execution_timeout_task
            if execution_timeout_task is not None and execution_timed_out:
                # drop reply to client as timeout was already sent
                continue
            # send reply to client if necessary
            if execution_context.get("oneway", False):
                continue 
            await origin_socket.send_multipart(reply)    
        self.logger.info("stopped tunneling messages to things")


    async def process_timeouts(self, original_client_message : typing.List, ready_to_process_event : asyncio.Event,
                               timeout : typing.Optional[float], origin_socket : zmq.Socket, timeout_typ : str) -> bool:
        """
        replies timeout to client if timeout occured and prevents the message from being executed. 
        """
        try:
            await asyncio.wait_for(ready_to_process_event.wait(), timeout)
            return False 
        except TimeoutError:    
            await origin_socket.send_multipart(self.craft_response_from_arguments(
                address=original_client_message[CM_INDEX_ADDRESS], client_type=original_client_message[CM_INDEX_CLIENT_TYPE], 
                message_type=TIMEOUT, message_id=original_client_message[CM_INDEX_MESSAGE_ID], data=timeout_typ
            ))
            return True


    async def _handle_invalid_message(self, original_client_message: typing.List[bytes], 
                                exception: Exception, originating_socket : zmq.Socket) -> None:
        await originating_socket.send_multipart(self.craft_response_from_arguments(
                            original_client_message[CM_INDEX_ADDRESS], original_client_message[CM_INDEX_CLIENT_TYPE], 
                            INVALID_MESSAGE, original_client_message[CM_INDEX_MESSAGE_ID], exception))
        self.logger.info(f"sent exception message to client '{original_client_message[CM_INDEX_ADDRESS]}'." +
                            f" exception - {str(exception)}") 	
    

    async def _handshake(self, original_client_message: typing.List[bytes],
                                    originating_socket : zmq.Socket) -> None:
        await originating_socket.send_multipart(self.craft_response_from_arguments(
                original_client_message[CM_INDEX_ADDRESS], 
                original_client_message[CM_INDEX_CLIENT_TYPE], HANDSHAKE, original_client_message[CM_INDEX_MESSAGE_ID],
                EMPTY_DICT))
        self.logger.info("sent handshake to client '{}'".format(original_client_message[CM_INDEX_ADDRESS]))


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
        pending_tasks = asyncio.all_tasks(self.request_listener_loop)
        self.request_listener_loop.run_until_complete(asyncio.gather(*pending_tasks))
        self.logger.info("exiting external listener event loop {}".format(self.instance_name))
        self.request_listener_loop.close()
    

    def run_things_executor(self, things : typing.List[Thing]):
        """
        Run ZMQ sockets which provide queued instructions to ``Thing``.
        This method is automatically called by ``run()`` method. 
        Please dont call this method when the async loop is already running. 
        """
        thing_executor_loop = get_current_async_loop()
        self.thing_executor_loop = thing_executor_loop # atomic assignment for thread safety
        self.logger.info(f"starting thing executor loop in thread {threading.get_ident()} for {[obj.instance_name for obj in things]}")
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
        self.inner_inproc_client.handshake()
        await self.inner_inproc_client.handshake_complete()
        if self.inproc_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_request(self.inproc_server)))
        if self.ipc_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_request(self.ipc_server)))
        if self.tcp_server:
            self.eventloop.call_soon(lambda : asyncio.create_task(self.recv_request(self.tcp_server)))
       

    def stop_polling(self):
        """
        stop polling method ``poll()``
        """
        self.stop_poll = True
        self._messages_event.set()
        if self.inproc_server is not None:
            def kill_inproc_server(instance_name, context, logger):
                # this function does not work when written fully async - reason is unknown
                try: 
                    event_loop = asyncio.get_event_loop()
                except RuntimeError:
                    event_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(event_loop)
                temp_inproc_client = AsyncZMQClient(server_instance_name=instance_name,
                                            identity=f'{self.instance_name}-inproc-killer',
                                            context=context, client_type=PROXY, protocol=ZMQ_PROTOCOLS.INPROC, 
                                            logger=logger) 
                event_loop.run_until_complete(temp_inproc_client.handshake_complete())
                event_loop.run_until_complete(temp_inproc_client.socket.send_multipart(temp_inproc_client.craft_empty_message_with_type(EXIT)))
                temp_inproc_client.exit()
            threading.Thread(target=kill_inproc_server, args=(self.instance_name, self.context, self.logger), daemon=True).start()
        if self.ipc_server is not None:
            temp_client = SyncZMQClient(server_instance_name=self.instance_name, identity=f'{self.instance_name}-ipc-killer',
                                    client_type=PROXY, protocol=ZMQ_PROTOCOLS.IPC, logger=self.logger) 
            temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
            temp_client.exit()
        if self.tcp_server is not None:
            socket_address = self.tcp_server.socket_address
            if '/*:' in self.tcp_server.socket_address:
                socket_address = self.tcp_server.socket_address.replace('*', 'localhost')
            # print("TCP socket address", self.tcp_server.socket_address)
            temp_client = SyncZMQClient(server_instance_name=self.instance_name, identity=f'{self.instance_name}-tcp-killer',
                                    client_type=PROXY, protocol=ZMQ_PROTOCOLS.TCP, logger=self.logger,
                                    socket_address=socket_address)
            temp_client.socket.send_multipart(temp_client.craft_empty_message_with_type(EXIT))
            temp_client.exit()   


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
        self.logger.info("terminated context of socket '{}' of type '{}'".format(self.instance_name, self.__class__))


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
        instance = consumer(**kwargs, eventloop_name=self.instance_name) # type: Thing
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
