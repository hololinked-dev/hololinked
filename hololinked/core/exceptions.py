"""Exception classes."""


class BreakInnerLoop(Exception):
    """Raise to break an inner loop."""


class BreakAllLoops(Exception):
    """Raise to exit all loops."""


class BreakLoop(Exception):
    """Raise and catch to exit a loop from within another function or method."""


class BreakFlow(Exception):
    """Raise to break the flow of the program."""


# TODO - remove unused and reduce number of definitions


class StateMachineError(Exception):
    """Raise to show errors while calling actions or writing properties in wrong state."""


class DatabaseError(Exception):
    """Raise to show database related errors."""


__all__ = ["BreakInnerLoop", "BreakAllLoops", "BreakLoop", "BreakFlow", "StateMachineError", "DatabaseError"]
