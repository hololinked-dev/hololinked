class ReplyNotArrivedError(Exception):
    """Exception raised when a reply is not received in time."""

    pass


class BreakLoop(Exception):
    """raise and catch to exit a loop from within another function or method"""

    pass
