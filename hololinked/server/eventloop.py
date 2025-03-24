import sys 
import os
import warnings
import subprocess
import asyncio
import importlib
import typing 
import threading
import logging
import tracemalloc
from uuid import uuid4

from .constants import HTTP_METHODS
from .utils import format_exception_as_json
from .config import global_config
from .zmq_message_brokers import ServerTypes 
from .exceptions import *
from .thing import Thing, ThingMeta
from .property import Property
from .properties import ClassSelector, TypedList, List, Boolean, TypedDict
from .action import action as remote_method
from .logger import ListHandler


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


class Consumer:
    """
    Container class for Thing to pass to eventloop for multiprocessing applications in case 
    of rare needs. 
    """
    object_cls = ClassSelector(default=None, allow_None=True, class_=Thing, isinstance=False,
                            remote=False)
    args = List(default=None, allow_None=True, accept_tuple=True, remote=False)
    kwargs = TypedDict(default=None, allow_None=True, key_type=str, remote=False)
   
    def __init__(self, object_cls : typing.Type[Thing], args : typing.Tuple = tuple(), **kwargs) -> None:
        self.object_cls = object_cls
        self.args = args 
        self.kwargs = kwargs



RemoteObject = Thing # reading convenience

class EventLoop(RemoteObject):
    """
    The EventLoop class implements a infinite loop where zmq ROUTER sockets listen for messages. Each consumer of the 
    event loop (an instance of Thing) listen on their own ROUTER socket and execute methods or allow read and write
    of attributes upon receiving instructions. Socket listening is implemented in an async (asyncio) fashion. 
    """
    server_type = ServerTypes.EVENTLOOP

    expose = Boolean(default=True, remote=False,
                     doc="""set to False to use the object locally to avoid alloting network resources 
                        of your computer for this object""")

    things = TypedList(item_type=(Thing, Consumer), bounds=(0,100), allow_None=True, default=None,
                        doc="list of Things which are being executed", remote=False) #type: typing.List[Thing]
    
    threaded = Boolean(default=False, remote=False, 
                        doc="set True to run each thing in its own thread")
  

    def __init__(self, *, 
                instance_name : str, 
                things : typing.Union[Thing, Consumer, typing.List[typing.Union[Thing, Consumer]]] = list(), # type: ignore - requires covariant types
                log_level : int = logging.INFO, 
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
        super().__init__(instance_name=instance_name, things=things, log_level=log_level, **kwargs)
        things = [] # type: typing.List[Thing]
        if self.expose:
            things.append(self) 
        if self.things is not None:
            for consumer in self.things:
                if isinstance(consumer, Thing):
                    things.append(consumer)
                    consumer.object_info.eventloop_instance_name = self.instance_name
                elif isinstance(consumer, Consumer):
                    instance = consumer.object_cls(*consumer.args, **consumer.kwargs, 
                                            eventloop_name=self.instance_name)
                    things.append(instance) 
        self.things = things # re-assign the instantiated objects as well
        self.uninstantiated_things = dict()
        self._message_listener_methods = []

    def __post_init__(self):
        super().__post_init__()
        self.logger.info("Event loop with name '{}' can be started using EventLoop.run().".format(self.instance_name))   


    # example of overloading
    @remote_method()
    def exit(self):
        """
        Stops the event loop and all its things. Generally, this leads
        to exiting the program unless some code follows the ``run()`` method.  
        """
        for thing in self.things:
            thing.exit()
        raise BreakAllLoops
    

    uninstantiated_things = TypedDict(default=None, allow_None=True, key_type=str,
                        item_type=(Consumer, str), URL_path='/things/uninstantiated')
    
    
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
        

    @remote_method(URL_path='/things', http_method=HTTP_METHODS.POST)
    def import_thing(self, file_name : str, object_name : str):
        """
        import thing from the specified path and return the default 
        properties to be supplied to instantiate the object. 
        """
        consumer = self._import_thing(file_name, object_name) # type: ThingMeta
        id = uuid4()
        self.uninstantiated_things[id] = consumer
        return id
           

    @remote_method(URL_path='/things/instantiate', 
                http_method=HTTP_METHODS.POST) # remember to pass schema with mandatory instance name
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


    @classmethod
    def get_async_loop(cls):
        """
        get or automatically create an asnyc loop for the current thread.
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            # set_event_loop_policy() - why not?
            asyncio.set_event_loop(loop)
        return loop
        

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