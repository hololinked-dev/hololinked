from typing import NoReturn
from contextlib import contextmanager


def raise_TypeError(message, parameter) -> NoReturn:
    owner_str = ""
    if isinstance(parameter, Parameter):
        owner_str = f" Owner info : {parameter.owner}, parameter name : {parameter.name}."
    elif issubclass(parameter, Parameter):
        owner_str = ""
    raise TypeError(message + owner_str)


def raise_ValueError(message, parameter) -> NoReturn:    
    owner_str = ""
    if isinstance(parameter, Parameter):
        owner_str = f" Owner info : {parameter.owner}, parameter name : {parameter.name}."
    elif issubclass(parameter, Parameter):
        owner_str = ""
    raise ValueError(message + owner_str)


def get_iterable_printfriendly_repr(iterable):
    # This method can be called before __init__ has called
    # super's __init__, so there may not be any name set yet.
    items = []
    limiter = "]"
    length = 0
    for item in iterable:
        string = str(item)
        length += len(string)
        if length < 200:
            items.append(string)
        else:
            limiter = ", ...]"
            break
    items = "[" + ", ".join(items) + limiter
    return items


@contextmanager
def exceptions_summarized():
    """Useful utility for writing docs that need to show expected errors.
    Shows exception only, concisely, without a traceback.
    """
    try:
        yield
    except Exception:
        import sys

        etype, value, tb = sys.exc_info()
        print("{}: {}".format(etype.__name__, value), file=sys.stderr)


from .parameterized import Parameter

__all__ = ["raise_TypeError", "raise_ValueError", "get_iterable_printfriendly_repr"]
