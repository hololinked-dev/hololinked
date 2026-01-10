import asyncio
import inspect
import os
import re
import sys
import threading
import traceback
import types
import typing

from collections import OrderedDict
from dataclasses import asdict
from functools import wraps
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, Callable, Coroutine, Sequence, Type
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, RootModel, create_model


def get_IP_from_interface(interface_name: str = "Ethernet", adapter_name: str | None = None) -> str:
    """
    Get IP address of specified interface. Generally necessary when connected to the network
    through multiple adapters and a server binds to only one adapter at a time.

    Parameters
    ----------
    interface_name: str
        Ethernet, Wifi etc., system recognisable
    adapter_name: optional, str
        name of the adapter if available

    Returns
    -------
    str:
        IP address of the interface
    """
    import ifaddr

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


def uuid_hex() -> str:
    """generate a random UUID hex string of 8 characters"""
    return uuid4().hex[:8]


def format_exception_as_json(exc: Exception) -> dict[str, Any]:
    """return exception as a JSON serializable dictionary"""
    return dict(
        message=str(exc),
        type=repr(exc).split("(", 1)[0],
        traceback=traceback.format_exc().splitlines(),
        notes=exc.__notes__ if hasattr(exc, "__notes__") else None,
    )


def pep8_to_dashed_name(word: str) -> str:
    """
    Make an dashed, lowercase form from the expression in the string.

    Example::

        >>> pep8_to_dashed_URL("device_type")
        'device-type'
    """
    val = re.sub(r"_+", "-", word.lstrip("_").rstrip("_"))
    return val.replace(" ", "-")


def get_current_async_loop() -> asyncio.AbstractEventLoop:
    """get or automatically create an asnyc loop for the current thread"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_coro_sync(coro: Coroutine) -> Any:
    """try to run coroutine synchronously, raises runtime error if event loop is already running"""
    eventloop = get_current_async_loop()
    if eventloop.is_running():
        raise RuntimeError(
            "asyncio event loop is already running, cannot setup coroutine "
            + f"{coro.__name__} to run sync, please await it."
        )
    else:
        return eventloop.run_until_complete(coro)


def run_callable_somehow(method: Callable | Coroutine) -> Any:
    """
    run method if synchronous, or when async, either schedule a coroutine
    or run it until its complete
    """
    if inspect.isawaitable(method):
        coro = method  # already a coroutine/awaitable object
    elif callable(method):
        result = method()  # call it
        if inspect.isawaitable(result):
            coro = result
        else:
            return result  # truly synchronous
    else:
        raise TypeError("method must be a callable or an awaitable")
    eventloop = get_current_async_loop()
    if eventloop.is_running():
        # task =  # check later if lambda is necessary
        eventloop.create_task(coro)
    else:
        # task = method
        return eventloop.run_until_complete(coro)


def complete_pending_tasks_in_current_loop() -> None:
    """Complete all pending tasks in the current asyncio event loop"""
    get_current_async_loop().run_until_complete(
        asyncio.gather(*asyncio.all_tasks(get_current_async_loop())),
    )


async def complete_pending_tasks_in_current_loop_async() -> None:
    """Complete all pending tasks in the current asyncio event loop"""
    await asyncio.gather(*asyncio.all_tasks(get_current_async_loop()))


def cancel_pending_tasks_in_current_loop():
    """Cancel all pending tasks in the current asyncio event loop"""
    loop = get_current_async_loop()
    tasks = asyncio.all_tasks(loop)
    for task in tasks:
        task.cancel()


def print_pending_tasks_in_current_loop():
    """Print all pending tasks in the current asyncio event loop"""
    tasks = asyncio.all_tasks(get_current_async_loop())
    if not tasks:
        print("No pending tasks in the current event loop.")
        return
    for task in tasks:
        print(f"Task: {task}, Status: {task._state}")


def set_global_event_loop_policy(use_uvloop: bool = False) -> None:
    """set global event loop policy, optionally using uvloop if available and on linux/macos"""
    if sys.platform.lower().startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if use_uvloop and sys.platform.lower() in [
        "linux",
        "darwin",
        "linux2",
    ]:
        import uvloop

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def get_signature(callable: Callable) -> tuple[list[str], list[type]]:
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


def getattr_without_descriptor_read(instance: Any, key: str) -> Any:
    """
    supply to inspect._get_members (not inspect.get_members) to avoid calling
    __get__ on descriptors, especially whey they are hardware attributes that would
    invoke a hardware read.
    """
    if key in instance.__dict__:
        return instance.__dict__[key]
    mro = mro = (instance.__class__,) + inspect.getmro(instance.__class__)
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
    return getattr(instance, key, None)  # we can deal with None where we use this getter, so dont raise AttributeError


def isclassmethod(method: Callable) -> bool:
    """
    Returns `True` if the method is a classmethod, `False` otherwise.
    https://stackoverflow.com/questions/19227724/check-if-a-function-uses-classmethod
    """
    if isinstance(method, classmethod):
        return True
    bound_to = getattr(method, "__self__", None)
    if not isinstance(bound_to, type):
        # must be bound to a class
        return False
    name = method.__name__
    for cls in bound_to.__mro__:
        descriptor = vars(cls).get(name)
        if descriptor is not None:
            return isinstance(descriptor, classmethod)
    return False


def has_async_def(method: Callable) -> bool:
    """
    Checks if async def is found in method signature. Especially useful for class methods.
    https://github.com/python/cpython/issues/100224#issuecomment-2000895467

    Parameters
    ----------
    method: Callable
        function or method

    Returns
    -------
    bool
        True if async def is found in method signature, False otherwise
    """
    source = inspect.getsource(method)
    if re.search(
        r"^\s*async\s+def\s+" + re.escape(method.__name__) + r"\s*\(",
        source,
        re.MULTILINE,
    ):
        return True
    return False


def issubklass(obj: Any, cls: Any) -> bool:
    """
    Safely check if `obj` is a subclass of `cls`.

    Parameters
    ----------
    obj: Any
        The object to check if it's a subclass.
    cls: Any
        The class (or tuple of classes) to compare against.

    Returns
    -------
    bool
        True if `obj` is a subclass of `cls`, False otherwise.
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


def get_sanitized_filename_from_random_string(a_string: str, extension: str) -> str:
    """Generate a sanitized filename from a given string and extension"""
    # Remove invalid characters from the instance name
    safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", a_string)
    # Collapse consecutive underscores into one
    safe_id = re.sub(r"_+", "_", safe_id)
    # Remove leading and trailing underscores
    safe_id = safe_id.strip("_")

    return f"{safe_id}.{extension}"


def generate_main_script_log_filename(self, app_name: str | None = None) -> str | None:
    """returns the main script filename if available"""
    import __main__

    if not app_name:
        file = getattr(__main__, "__file__", None)
        if not file:
            filename = Path.cwd().name
        else:
            file = os.path.splitext(os.path.basename(file))
            filename = file[0]
    else:
        filename = app_name
    if filename:
        return get_sanitized_filename_from_random_string(filename, extension="log")
    return "hololinked.log"


class SerializableDataclass:
    """Presents uniform serialization for pickle and JSON for dataclasses"""

    def json(self):
        return asdict(self)

    def __getstate__(self):
        return self.json()

    def __setstate__(self, values: dict):
        for key, value in values.items():
            setattr(self, key, value)


class Singleton(type):
    """Enforces a Singleton behavior on a class"""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class MappableSingleton(Singleton):
    """Singleton with dict-like access to attributes"""

    def __setitem__(self, key, value) -> None:
        setattr(self, key, value)

    def __getitem__(self, key) -> Any:
        return getattr(self, key)

    def __contains__(self, key) -> bool:
        return hasattr(self, key)


def get_input_model_from_signature(
    func: Callable,
    remove_first_positional_arg: bool = False,
    ignore: Sequence[str] | None = None,
    model_for_empty_annotations: bool = False,
) -> Type[BaseModel] | None:
    """
    Create a pydantic model for a function's signature.

    Parameters
    ----------
    func: Callable
        The function for which to create the pydantic model.
    remove_first_positional_arg: bool, optional
        Remove the first argument from the model. This is appropriate for methods,
        as the first argument, self, is baked in when it's called, but is present
        in the signature.
    ignore: Sequence[str], optional
        Ignore arguments that have the specified name.
    model_for_empty_annotations: bool, optional
        If True, create a model even if there are no annotations.

    Returns
    -------
    Type[BaseModel] or None
        A pydantic model class describing the input parameters, or None if there are no parameters.
    """
    parameters = OrderedDict(signature(func).parameters)  # type: OrderedDict[str, Parameter]
    if len(parameters) == 0:
        return None

    if all(p.annotation is Parameter.empty for p in parameters.values()) and not model_for_empty_annotations:
        return None

    if remove_first_positional_arg:
        name, parameter = next(iter((parameters.items())))  # get the first parameter
        if parameter.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
            raise ValueError("Can't remove first positional argument: there is none.")
        del parameters[name]

    # fields is a dictionary of tuples of (type, default) that defines the input model
    type_hints = typing.get_type_hints(func, include_extras=True)
    fields = {}  # type: dict[str, tuple[type, Any]]
    for name, p in parameters.items():
        if ignore and name in ignore:
            continue
        if p.kind == Parameter.VAR_KEYWORD:
            p_type = typing.Annotated[
                typing.Dict[str, typing.Any] if p.annotation is Parameter.empty else type_hints[name],
                Parameter.VAR_KEYWORD,
            ]
            default = dict() if p.default is Parameter.empty else p.default
        elif p.kind == Parameter.VAR_POSITIONAL:
            p_type = typing.Annotated[
                typing.Tuple if p.annotation is Parameter.empty else type_hints[name],
                Parameter.VAR_POSITIONAL,
            ]
            default = tuple() if p.default is Parameter.empty else p.default
        else:
            # `type_hints` does more processing than p.annotation - but will
            # not have entries for missing annotations.
            p_type = typing.Any if p.annotation is Parameter.empty else type_hints[name]
            # pydantic uses `...` to represent missing defaults (i.e. required params)
            default = Field(...) if p.default is Parameter.empty else p.default
        fields[name] = (p_type, default)

    # If there are no fields, we don't want to return a model
    if len(fields) == 0:
        return None

    model = create_model(  # type: ignore[call-overload]
        f"{func.__name__}_input",
        **fields,
        __config__=ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=True),
    )
    return model


def get_return_type_from_signature(func: Callable) -> RootModel | None:
    """Determine the return type of a function."""
    sig = inspect.signature(func)
    if sig.return_annotation == inspect.Signature.empty:
        return None  # type: ignore[return-value]
    else:
        # We use `get_type_hints` rather than just `sig.return_annotation`
        # because it resolves forward references, etc.
        type_hints = typing.get_type_hints(func, include_extras=True)
        from .core.property import wrap_plain_types_in_rootmodel

        if (
            "return" not in type_hints
            or type_hints["return"] is typing.Any
            or type_hints["return"] is None
            or type_hints["return"] is type(None)
        ):
            return None

        return wrap_plain_types_in_rootmodel(type_hints["return"])


def pydantic_validate_args_kwargs(
    model: Type[BaseModel],
    args: tuple = tuple(),
    kwargs: dict = dict(),
) -> None:
    """
    Validate and separate *args and **kwargs according to the fields of the given pydantic model.

    Parameters
    ----------
    model: Type[BaseModel]
        The pydantic model class to validate against.
    *args: tuple
        Positional arguments to validate.
    **kwargs: dict
        Keyword arguments to validate.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        If the arguments do not match the model's fields.
    ValidationError
        If the arguments are invalid
    """

    field_names = list(model.model_fields.keys())
    data = {}

    # Assign positional arguments to the corresponding fields
    for i, arg in enumerate(args):
        if i >= len(field_names):
            raise ValueError(f"Too many positional arguments. Expected at most {len(field_names)}.")
        field_name = field_names[i]
        if Parameter.VAR_POSITIONAL in model.model_fields[field_name].metadata:
            if typing.get_origin(model.model_fields[field_name].annotation) is list:
                data[field_name] = list(args[i:])
            else:
                data[field_name] = args[i:]  # *args become end of positional arguments
            break
        elif field_name in data:
            raise ValueError(f"Multiple values for argument '{field_name}'.")
        data[field_name] = arg

    extra_kwargs = {}
    # Assign keyword arguments to the corresponding fields
    for key, value in kwargs.items():
        if key in data or key in extra_kwargs:  # Check for duplicate arguments
            raise ValueError(f"Multiple values for argument '{key}'.")
        if key in field_names:
            data[key] = value
        else:
            extra_kwargs[key] = value

    if extra_kwargs:
        for i in range(len(field_names)):
            if Parameter.VAR_KEYWORD in model.model_fields[field_names[i]].metadata:
                data[field_names[i]] = extra_kwargs
                break
            elif i == len(field_names) - 1:
                raise ValueError(f"Unexpected keyword arguments: {', '.join(extra_kwargs.keys())}")
    # Validate and create the model instance
    model.model_validate(data)


def json_schema_merge_args_to_kwargs(schema: dict, args: tuple = tuple(), kwargs: dict = dict()) -> dict[str, Any]:
    """
    Merge positional arguments into keyword arguments according to the schema.

    Parameters
    ----------
    schema: dict
        The JSON schema to validate against.
    args: tuple
        Positional arguments to merge.
    kwargs: dict
        Keyword arguments to merge.

    Returns
    -------
    dict
        The merged arguments as a dictionary, usually a JSON
    """
    if schema["type"] != "object":
        raise ValueError("Schema must be an object.")

    field_names = list(OrderedDict(schema["properties"]).keys())
    data = {}

    for i, arg in enumerate(args):
        if i >= len(field_names):
            raise ValueError(f"Too many positional arguments. Expected at most {len(field_names)}.")
        field_name = field_names[i]
        if field_name in data:
            raise ValueError(f"Multiple values for argument '{field_name}'.")
        data[field_name] = arg

    extra_kwargs = {}
    # Assign keyword arguments to the corresponding fields
    for key, value in kwargs.items():
        if key in data or key in extra_kwargs:  # Check for duplicate arguments
            raise ValueError(f"Multiple values for argument '{key}'.")
        if key in field_names:
            data[key] = value
        else:
            extra_kwargs[key] = value

    if extra_kwargs:
        data.update(extra_kwargs)
    return data


def forkable(func):
    """
    Decorator to make a function forkable into a separate thread.
    This is useful for functions that need to be run in a separate thread.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        forked = kwargs.get("forked", False)  # Extract 'fork' argument, default to False
        if forked:
            thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
            thread.start()
            return thread
        else:
            return func(*args, **kwargs)

    return wrapper


def get_all_sub_things_recusively(thing) -> list:
    """get all sub things recursively from a thing"""
    sub_things = [thing]
    for sub_thing in thing.sub_things.values():
        sub_things.extend(get_all_sub_things_recusively(sub_thing))
    return sub_things


def get_socket_type_name(socket_type):
    from .constants import ZMQSocketType

    try:
        return ZMQSocketType(socket_type).name
    except ValueError:
        return "UNKNOWN"


__all__ = [
    get_IP_from_interface.__name__,
    format_exception_as_json.__name__,
    pep8_to_dashed_name.__name__,
    run_coro_sync.__name__,
    run_callable_somehow.__name__,
    complete_pending_tasks_in_current_loop.__name__,
    get_current_async_loop.__name__,
    set_global_event_loop_policy.__name__,
    get_signature.__name__,
    isclassmethod.__name__,
    issubklass.__name__,
    get_input_model_from_signature.__name__,
    pydantic_validate_args_kwargs.__name__,
    get_return_type_from_signature.__name__,
    getattr_without_descriptor_read.__name__,
    forkable.__name__,
    get_socket_type_name.__name__,
]
