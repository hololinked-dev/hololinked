import sys
import logging
import re 
import asyncio
import inspect
import typing
import asyncio
import types
import traceback
import typing
import ifaddr
from dataclasses import asdict


def get_IP_from_interface(interface_name : str = 'Ethernet', adapter_name = None) -> str:
    """
    Get IP address of specified interface. Generally necessary when connected to the network
    through multiple adapters and a server binds to only one adapter at a time. 

    Parameters
    ----------
    interface_name: str
        Ethernet, Wifi etc. 
    adapter_name: optional, str
        name of the adapter if available

    Returns
    -------
    str: 
        IP address of the interface
    """
    adapters = ifaddr.get_adapters(include_unconfigured=True)
    for adapter in adapters:
        if not adapter_name:
            for ip in adapter.ips:
                if interface_name == ip.nice_name:
                    if ip.is_IPv4:
                        return ip.ip
        elif adapter_name == adapter.nice_name:
            for ip in adapter.ips:
                if interface_name == ip.nice_name:
                    if ip.is_IPv4:
                        return ip.ip
    raise ValueError(f"interface name {interface_name} not found in system interfaces.")
            

def format_exception_as_json(exc : Exception) -> typing.Dict[str, typing.Any]: 
    """
    return exception as a JSON serializable dictionary
    """
    return {
        "message" : str(exc),
        "type" : repr(exc).split('(', 1)[0],
        "traceback" : traceback.format_exc().splitlines(),
        "notes" : exc.__notes__ if hasattr(exc, "__notes__") else None 
    }


def pep8_to_dashed_name(word : str) -> str: 
    """
    Make an underscored, lowercase form from the expression in the string.
    Example::
        >>> pep8_to_dashed_URL("device_type")
        'device-type'
    """
    val = re.sub(r'_+', '-', word.lstrip('_').rstrip('_'))
    return val.replace(' ', '-')


def get_default_logger(name : str, log_level : int = logging.INFO, log_file = None,
                format : str = '%(levelname)-8s - %(asctime)s:%(msecs)03d - %(name)s - %(message)s' ) -> logging.Logger:
    """
    the default logger used by most of hololinked package, when arguments are not modified.
    StreamHandler is always created, pass log_file for a FileHandler as well.

    Parameters
    ----------
    name: str 
        name of logger
    log_level: int 
        log level
    log_file: str
        valid path to file
    format: str
        log format

    Returns
    -------
    logging.Logger:
        created logger
    """
    logger = logging.getLogger(name) 
    logger.setLevel(log_level)
    default_handler = logging.StreamHandler(sys.stdout)
    default_handler.setFormatter(logging.Formatter(format, datefmt='%Y-%m-%dT%H:%M:%S'))
    logger.addHandler(default_handler)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format, datefmt='%Y-%m-%dT%H:%M:%S'))
        logger.addHandler(file_handler)
    return logger


def run_coro_sync(coro : typing.Coroutine):
    """
    run coroutine synchronously
    """
    try:
        eventloop = asyncio.get_event_loop()
    except RuntimeError:
        eventloop = asyncio.new_event_loop()
        asyncio.set_event_loop(eventloop)
    if eventloop.is_running():
        raise RuntimeError(f"asyncio event loop is already running, cannot setup coroutine {coro.__name__} to run sync, please await it.")
        # not the same as RuntimeError catch above.  
    else:
        return eventloop.run_until_complete(coro)


def run_callable_somehow(method : typing.Union[typing.Callable, typing.Coroutine]) -> typing.Any:
    """
    run method if synchronous, or when async, either schedule a coroutine or run it until its complete
    """
    if not (asyncio.iscoroutinefunction(method) or asyncio.iscoroutine(method)):
        return method()
    try:
        eventloop = asyncio.get_event_loop()
    except RuntimeError:
        eventloop = asyncio.new_event_loop()
        asyncio.set_event_loop(eventloop)
    if asyncio.iscoroutinefunction(method):
        coro = method()
    else:
        coro = method
    if eventloop.is_running():    
        # task =  # check later if lambda is necessary
        eventloop.create_task(coro)
    else:
        # task = method
        return eventloop.run_until_complete(coro)


def get_signature(callable : typing.Callable) -> typing.Tuple[typing.List[str], typing.List[type]]: 
    """
    Retrieve the names and types of arguments based on annotations for the given callable.

    Parameters
    ----------
    callable: Callable
        function or method (not tested with __call__)
    
    Returns
    -------
    tuple: List[str], List[type]
        arguments name and types respectively
    """
    arg_names = []
    arg_types = []

    for param in inspect.signature(callable).parameters.values():
        arg_name = param.name
        arg_type = param.annotation if param.annotation != inspect.Parameter.empty else None

        arg_names.append(arg_name)
        arg_types.append(arg_type)

    return arg_names, arg_types


def getattr_without_descriptor_read(instance, key):
    """
    supply to inspect._get_members (not inspect.get_members) to avoid calling 
    __get__ on hardware attributes
    """
    if key in instance.__dict__:
        return instance.__dict__[key]
    mro =  mro = (instance.__class__,) + inspect.getmro(instance.__class__)
    for base in mro:
        if key in base.__dict__:
            value = base.__dict__[key]
            if isinstance(value, types.FunctionType):
                method = getattr(instance, key, None)
                if isinstance(method, types.MethodType):
                    return method 
            return value 
    # for descriptor, first try to find it in class dict or instance dict (for instance descriptors (per_instance_descriptor=True))
    # and then getattr from the instance. For descriptors/property, it will be mostly at above two levels.
    return getattr(instance, key, None) # we can deal with None where we use this getter, so dont raise AttributeError  


def isclassmethod(method):
    """https://stackoverflow.com/questions/19227724/check-if-a-function-uses-classmethod"""
    bound_to = getattr(method, '__self__', None)
    if not isinstance(bound_to, type):
        # must be bound to a class
        return False
    name = method.__name__
    for cls in bound_to.__mro__:
        descriptor = vars(cls).get(name)
        if descriptor is not None:
            return isinstance(descriptor, classmethod)
    return False


def issubklass(obj, cls):
    """
    Safely check if `obj` is a subclass of `cls`.

    Parameters:
    obj: The object to check if it's a subclass.
    cls: The class (or tuple of classes) to compare against.

    Returns:
    bool: True if `obj` is a subclass of `cls`, False otherwise.
    """
    try:
        # Check if obj is a class or a tuple of classes
        if isinstance(obj, type):
            return issubclass(obj, cls)
        elif isinstance(obj, tuple):
            # Ensure all elements in the tuple are classes
            return all(isinstance(o, type) for o in obj) and issubclass(obj, cls)
        else:
            return False
    except TypeError:
        return False
    

def get_a_filename_from_instance(thing: type, extension: str = 'json') -> str:
    class_name = thing.__class__.__name__

    # Remove invalid characters from the instance name
    safe_instance_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', '_', thing.instance_name)
    # Collapse consecutive underscores into one
    safe_instance_name = re.sub(r'_+', '_', safe_instance_name)
    # Remove leading and trailing underscores
    safe_instance_name = safe_instance_name.strip('_')

    filename = f"{class_name}-{safe_instance_name or '_'}.{extension}"
    return filename
  


def get_current_async_loop():
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


class SerializableDataclass:
    """
    Presents uniform serialization for serializers using getstate and setstate and json 
    serialization.
    """
    def json(self):
        return asdict(self)

    def __getstate__(self):
        return self.json()
    
    def __setstate__(self, values : typing.Dict):
        for key, value in values.items():
            setattr(self, key, value)


class Singleton:
    """
    A metaclass for creating singleton classes.
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            # If an instance does not exist, create one and store it.
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]




__all__ = [
    get_IP_from_interface.__name__,
    format_exception_as_json.__name__,
    pep8_to_dashed_name.__name__,
    get_default_logger.__name__,
    run_coro_sync.__name__,
    run_callable_somehow.__name__,
    get_signature.__name__,
    isclassmethod.__name__,
    issubklass.__name__,
    get_current_async_loop.__name__
]

