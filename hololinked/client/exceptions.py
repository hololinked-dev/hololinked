"""Exceptions."""


class ReplyNotArrivedError(Exception):
    """Exception raised when a reply is not received in time."""

    pass


class BreakLoop(Exception):
    """Raise and catch to exit a loop from within another function or method."""

    pass
