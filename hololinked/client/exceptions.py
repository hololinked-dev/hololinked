"""Client side exceptions. Not fully formalized."""

import builtins

from typing import Any


class ReplyNotArrivedError(Exception):
    """Exception raised when a reply is not received in time."""


class BreakLoop(Exception):
    """Raise and catch to exit a loop from within another function or method."""


def raise_local_exception(error_message: dict[str, Any] | str) -> None:
    """
    Raise an exception on client side using an exception type from the server.

    A mapping based on exception type is used, and only python built-in exceptions supported. If the exception type
    is not found, a generic `Exception` is raised. Cross language exceptions are not supported and will be raised
    as a generic exception. Server traceback is added to the exception notes. Client creates its own traceback which is
    not usually the cause of the error.

    Parameters
    ----------
    error_message: dict[str, Any]
        exception dictionary made by server with following keys - `type`, `message`, `traceback`, `notes`

    Raises
    ------
    Exception
        exception based on the server error message, with server traceback in the exception notes
    RuntimeError
        if the error message is not in the expected format, string, dict or native Exception instance.
    TimeoutError
        if the error message is a string indicating a timeout error
    """
    if isinstance(error_message, Exception):
        raise error_message from None
    elif isinstance(error_message, dict) and "exception" in error_message:
        error_message = error_message["exception"]
        message = error_message["message"]
        exc = getattr(builtins, error_message["type"], None)
        if exc is None:
            ex = Exception(message)
        else:
            ex = exc(message)
        error_message["traceback"][0] = f"Server {error_message['traceback'][0]}"
        ex.__notes__ = error_message["traceback"][0:-1]
        raise ex from None
    elif isinstance(error_message, str) and error_message in ["invokation", "execution"]:
        raise TimeoutError(
            f"{error_message[0].upper()}{error_message[1:]} timeout occured. "
            + "Server did not respond within specified timeout"
        ) from None
    raise RuntimeError("unknown error occurred on server side") from None
