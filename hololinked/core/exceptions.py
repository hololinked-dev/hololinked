class BreakInnerLoop(Exception):
    """raise to break an inner loop"""

    pass


class BreakAllLoops(Exception):
    """raise to exit all loops"""

    pass


class BreakLoop(Exception):
    """raise and catch to exit a loop from within another function or method"""

    pass


class BreakFlow(Exception):
    """raised to break the flow of the program"""

    pass


# TODO - remove unused and reduce number of definitions


class StateMachineError(Exception):
    """raise to show errors while calling actions or writing properties in wrong state"""

    pass


class DatabaseError(Exception):
    """raise to show database related errors"""


__all__ = ["BreakInnerLoop", "BreakAllLoops", "BreakLoop", "BreakFlow", "StateMachineError", "DatabaseError"]
