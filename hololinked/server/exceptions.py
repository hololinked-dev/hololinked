class BreakInnerLoop(Exception):
    """
    raised to break all inner loop, either of Idler or of RunWith or WithoutStateMachine
    """
    pass

class BreakAllLoops(Exception):
    """
    raised to exit the event loop itself
    """
    pass

class BreakLoop(Exception):
    pass 

class BreakFlow(Exception):
    """
    raised to break the flow of the program
    """
    pass

class StateMachineError(Exception):
    """
    raise to show errors while calling actions or writing properties in wrong state
    """
    pass 

class DatabaseError(Exception):
    """
    raise to show database related errors
    """



__all__ = ['BreakInnerLoop', 'BreakAllLoops', 'StateMachineError']