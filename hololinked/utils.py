"""Assorted helpers - networking, asyncio, naming, signature introspection and schema handling."""

import asyncio
import inspect
import os
import re
import sys
import threading
import traceback
import types

from collections.abc import Callable, Coroutine
from dataclasses import asdict
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4


def get_IP_from_interface(interface_name: str = "Ethernet", adapter_name: str | None = None) -> str:
    """
    Get IP address of specified interface.

    Generally necessary when connected to the network through multiple (physical) adapters
    and a server binds to only one adapter at a time.

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

    Raises
    ------
    ValueError
        if the given interface name is not found among the system interfaces
    """
    import ifaddr

    adapters = ifaddr.get_adapters(include_unconfigured=True)
    for adapter in adapters:
        if not adapter_name or adapter_name == adapter.nice_name:
            for ip in adapter.ips:
                if interface_name == ip.nice_name and ip.is_IPv4:
                    return ip.ip  # ty: ignore[invalid-return-type]
    raise ValueError(f"interface name {interface_name} not found in system interfaces.")


def uuid_hex() -> str:
    """
    Generate a random UUID hex string of 8 characters.

    Returns
    -------
    str
        the generated hex string
    """
    return uuid4().hex[:8]


def format_exception_as_json(exc: Exception) -> dict[str, Any]:
    """
    Return exception as a JSON serializable dictionary.

    Returns
    -------
    dict[str, Any]
        the message, type, traceback and notes of the exception
    """
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

    Returns
    -------
    str
        the dashed, lowercase form of the given word
    """
    val = re.sub(r"_+", "-", word.lstrip("_").rstrip("_"))
    return val.replace(" ", "-")


def get_current_async_loop() -> asyncio.AbstractEventLoop:
    """
    Get or automatically create an asnyc loop for the current thread.

    Returns
    -------
    asyncio.AbstractEventLoop
        the event loop of the current thread
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def run_coro_sync(coro: Coroutine) -> Any:
    """
    Try to run coroutine synchronously, raises runtime error if event loop is already running.

    Returns
    -------
    Any
        the return value of the coroutine

    Raises
    ------
    RuntimeError
        if the event loop of the current thread is already running
    """
    loop = get_current_async_loop()
    if loop.is_running():
        raise RuntimeError(
            "asyncio event loop is already running, cannot setup coroutine "
            + f"{coro.__name__} to run sync, please await it."
        )
    else:
        return loop.run_until_complete(coro)


def run_callable_somehow(method: Callable | Coroutine) -> Any:
    """
    Run method if synchronous, or when async, either schedule a coroutine or run it until its complete.

    Returns
    -------
    Any
        the return value when the method is synchronous, otherwise the scheduled task or its result

    Raises
    ------
    TypeError
        if the given method is neither callable nor awaitable
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
    loop = get_current_async_loop()
    if loop.is_running():
        # task =  # check later if lambda is necessary
        loop.create_task(coro)  # ty: ignore[invalid-argument-type]  # narrowed to an awaitable above
    else:
        # task = method
        return loop.run_until_complete(coro)


def complete_pending_tasks_in_current_loop() -> None:
    """Complete all pending tasks in the current asyncio event loop."""
    get_current_async_loop().run_until_complete(
        asyncio.gather(*asyncio.all_tasks(get_current_async_loop())),
    )


async def complete_pending_tasks_in_current_loop_async() -> None:
    """Complete all pending tasks in the current asyncio event loop."""
    await asyncio.gather(*asyncio.all_tasks(get_current_async_loop()))


def cancel_pending_tasks_in_current_loop():
    """Cancel all pending tasks in the current asyncio event loop."""
    loop = get_current_async_loop()
    tasks = asyncio.all_tasks(loop)
    for task in tasks:
        task.cancel()


def print_pending_tasks_in_current_loop():
    """Print all pending tasks in the current asyncio event loop."""
    tasks = asyncio.all_tasks(get_current_async_loop())
    if not tasks:
        print("No pending tasks in the current event loop.")
        return
    for task in tasks:
        print(f"Task: {task}, Status: {task._state}")


def set_global_event_loop_policy(use_uvloop: bool = False) -> None:
    """Set global event loop policy, optionally using uvloop if available and on linux/macos."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if use_uvloop and sys.platform.lower() in [
        "linux",
        "darwin",
        "linux2",
    ]:
        import uvloop  # ty: ignore[unresolved-import]  # POSIX-only optional dependency

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
    Supply to inspect._get_members (not inspect.get_members) to avoid calling __get__ on descriptors.

    Especially useful whey they are hardware attributes that would invoke a hardware read.

    Returns
    -------
    Any
        the attribute value without triggering a descriptor read
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

    Returns
    -------
    bool
        `True` if the method is a classmethod, `False` otherwise
    """
    if isinstance(method, classmethod):
        return True
    bound_to = getattr(method, "__self__", None)
    if not isinstance(bound_to, type):
        # must be bound to a class
        return False
    name = method.__name__  # ty: ignore[unresolved-attribute]  # a bound method always has one
    for cls in bound_to.__mro__:
        descriptor = vars(cls).get(name)
        if descriptor is not None:
            return isinstance(descriptor, classmethod)
    return False


def has_async_def(method: Callable) -> bool:
    """
    Checks if async def is found in method signature.

    Especially useful for class methods.
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
        r"^\s*async\s+def\s+" + re.escape(method.__name__) + r"\s*\(",  # ty: ignore[unresolved-attribute]  # a function always has one
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
    """
    Generate a sanitized filename from a given string and extension.

    Returns
    -------
    str
        the sanitized filename with the extension appended
    """
    # Remove invalid characters from the instance name
    safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", a_string)
    # Collapse consecutive underscores into one
    safe_id = re.sub(r"_+", "_", safe_id)
    # Remove leading and trailing underscores
    safe_id = safe_id.strip("_")

    return f"{safe_id}.{extension}"


def generate_main_script_log_filename(self, app_name: str | None = None) -> str | None:
    """
    Returns the main script filename if available.

    Returns
    -------
    str | None
        the log filename derived from the main script, or a default one
    """
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
    """Presents uniform serialization for pickle and JSON for dataclasses."""

    def json(self):
        """
        Return the dataclass as a dictionary.

        Returns
        -------
        dict
            the dataclass fields keyed by their names
        """
        return asdict(self)  # ty: ignore[invalid-argument-type]  # mixed into dataclasses only

    def __getstate__(self):
        return self.json()

    def __setstate__(self, values: dict):
        for key, value in values.items():
            setattr(self, key, value)


def lazy_module_getattr(module_name: str, lazy: dict[str, str], namespace: dict[str, Any]) -> Callable[[str], Any]:
    """
    Build a PEP 562 module level `__getattr__` that does lazy import.

    Parameters
    ----------
    module_name: str
        `__name__` of the module the `__getattr__` belongs to, also the anchor for relative module paths
    lazy: dict[str, str]
        exported name mapped to the module it is imported from, relative paths anchored at `module_name`
    namespace: dict[str, Any]
        `globals()` of the module, where a resolved attribute is cached

    Returns
    -------
    Callable[[str], Any]
        the function to assign to `__getattr__` in the module
    """

    def __getattr__(name: str) -> Any:
        if name not in lazy:
            raise AttributeError(f"module {module_name!r} has no attribute {name!r}")

        import importlib

        value = getattr(importlib.import_module(lazy[name], package=module_name), name)
        namespace[name] = value  # cache so subsequent access skips __getattr__
        return value

    return __getattr__


class Singleton(type):
    """Enforces a Singleton behavior on a class."""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class MappableSingleton(Singleton):
    """Singleton with dict-like access to attributes."""

    def __setitem__(self, key, value) -> None:
        setattr(self, key, value)

    def __getitem__(self, key) -> Any:
        return getattr(self, key)

    def __contains__(self, key) -> bool:
        return hasattr(self, key)


def forkable(func):
    """
    Decorator to make a function forkable into a separate thread.

    This is useful for functions that need to be run in a separate thread.

    Returns
    -------
    Callable
        the wrapped function, which runs in a new thread when called with `forked=True`
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
    getattr_without_descriptor_read.__name__,
    forkable.__name__,
]
