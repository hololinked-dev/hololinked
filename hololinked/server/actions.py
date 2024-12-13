import functools
import inspect
import typing
import jsonschema
from enum import Enum
from types import FunctionType, MethodType
from inspect import iscoroutinefunction, getfullargspec

from ..param.parameterized import ParameterizedFunction
from .constants import JSON
from .config import global_config
from .utils import getattr_without_descriptor_read, issubklass, isclassmethod
from .exceptions import StateMachineError
from .dataklasses import ActionInfoValidator, ActionResource


__action_kw_arguments__ = ['safe', 'idempotent', 'synchronous'] 


class Action:
    """
    Object that models an action.
    """
    __slots__ = ['obj', 'owner', 'owner_inst', 
                '_execution_info', '_execution_info_validator']

    def __init__(self, obj) -> None:
        self.obj = obj

    def __post_init__(self):
        # never called, neither possible to call, only type hinting
        from .thing import Thing, ThingMeta
        # owner class and instance
        self.owner : ThingMeta  
        self.owner_inst : Thing
        # the validator that was used to accept user inputs to this action.
        # stored only for reference, hardly used. 
        self._execution_info_validator : ActionInfoValidator
        
    @property
    def execution_info(self) -> ActionResource:
        return self._execution_info
    
    @execution_info.setter
    def execution_info(self, value : ActionResource) -> None:
        if not isinstance(value, ActionResource):
            raise TypeError("execution_info must be of type ActionResource")
        self._execution_info = value
    
    def validate_call(self, args, kwargs : typing.Dict[str, typing.Any]) -> None:
        """
        Validate the call to the action, like payload, state machine state etc. 
        Errors are raised as exceptions.
        """
        if self._execution_info.state is None or (hasattr(self.owner_inst, 'state_machine') and 
                            self.owner_inst.state_machine.current_state in self._execution_info.state):
                # Note that because we actually find the resource within __prepare_self.owner_inst__, its already bound
                # and we dont have to separately bind it. 
                if self._execution_info.schema_validator is not None and len(args) == 0:
                    self._execution_info.schema_validator.validate(kwargs)
        else: 
            raise StateMachineError("Thing '{}' is in '{}' state, however command can be executed only in '{}' state".format(
                    self.owner_inst.id, self.owner_inst.state, self._execution_info.state))      
        if self._execution_info.isparameterized and len(args) > 0:
            raise RuntimeError("parameterized functions cannot have positional arguments")
            

class SyncAction(Action):  
    """
    non async(io) action call. The call is passed to the method as-it-is to allow local 
    invocation without state machine checks.
    """
    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return self(*args, **kwargs)
        
    def __call__(self, *args, **kwargs):
        return self.obj(self.owner_inst, *args, **kwargs)


class AsyncAction(Action):
    """
    async(io) action call. The call is passed to the method as-it-is to allow local 
    invocation without state machine checks.
    """
    async def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return await self(*args, **kwargs)

    async def __call__(self, *args, **kwargs):
        return await self.obj(self.owner_inst, *args, **kwargs)


   
def action(input_schema : JSON | None = None, output_schema : JSON | None = None, 
        state : str | Enum | None = None, create_task : bool = False, **kwargs) -> Action:
    """
    decorate on your methods with this function to make them accessible remotely or create 'actions' out of them. 
    
    Parameters
    ----------
    input_schema: JSON 
        schema for arguments to validate them.
    output_schema: JSON 
        schema for return value, currently only used to inform clients which is supposed to validate on its won. 
    state: str | Tuple[str], optional 
        state machine state under which the object can executed. When not provided,
        the action can be executed under any state.
    **kwargs:
        - safe: bool, 
            indicate in thing description if action is safe to execute 
        - idempotent: bool, 
            indicate in thing description if action is idempotent (for example, allows HTTP client to cache return value)
        - synchronous: bool,
            indicate in thing description if action is synchronous (not long running)

    Returns
    -------
    Callable
        returns the callable object wrapped in an ``Action`` object
    """
    
    def inner(obj):
        original = obj
        if (not isinstance(obj, (FunctionType, MethodType)) and not isclassmethod(obj) and 
            not issubklass(obj, ParameterizedFunction)):
                raise TypeError(f"target for action or is not a function/method. Given type {type(obj)}") from None 
        if isclassmethod(obj):
            obj = obj.__func__
        if obj.__name__.startswith('__'):
            raise ValueError(f"dunder objects cannot become remote : {obj.__name__}")
        if hasattr(obj, '_execution_info_validator') and not isinstance(obj._execution_info_validator, ActionInfoValidator): 
            raise NameError(
                "variable name '_execution_info_validator' reserved for hololinked package. ",  
                "Please do not assign this variable to any other object except hololinked.server.dataklasses.ActionInfoValidator."
            )             
        else:
            execution_info_validator = ActionInfoValidator() 
        if state is not None:
            if isinstance(state, (Enum, str)):
                execution_info_validator.state = (state,)
            else:
                execution_info_validator.state = state     
        if 'request' in getfullargspec(obj).kwonlyargs:
            execution_info_validator.request_as_argument = True
        execution_info_validator.isaction = True
        execution_info_validator.argument_schema = input_schema
        execution_info_validator.return_value_schema = output_schema
        execution_info_validator.obj = original
        execution_info_validator.create_task = create_task
        execution_info_validator.safe = kwargs.get('safe', False)
        execution_info_validator.idempotent = kwargs.get('idempotent', False)
        execution_info_validator.synchronous = kwargs.get('synchronous', False)

        if issubklass(obj, ParameterizedFunction):
            execution_info_validator.iscoroutine = iscoroutinefunction(obj.__call__)
            execution_info_validator.isparameterized = True
        else:
            execution_info_validator.iscoroutine = iscoroutinefunction(obj)
            execution_info_validator.isparameterized = False 
        if global_config.validate_schemas and input_schema:
            jsonschema.Draft7Validator.check_schema(input_schema)
        if global_config.validate_schemas and output_schema:
            jsonschema.Draft7Validator.check_schema(output_schema)

        if execution_info_validator.iscoroutine:
            final_obj = functools.wraps(original)(AsyncAction(original)) # type: Action
        else:
            final_obj = functools.wraps(original)(SyncAction(original)) # type: Action
        final_obj._execution_info_validator = execution_info_validator
        return final_obj
    if callable(input_schema):
        raise TypeError("input schema should be a JSON, not a function/method, did you decorate your action wrongly? " +
                        "use @action() instead of @action.")
    if any(key not in __action_kw_arguments__ for key in kwargs.keys()):
        raise ValueError("Only 'safe', 'idempotent', 'synchronous' are allowed as keyword arguments, " + 
                        f"unknown arguments found {kwargs.keys()}")
    return inner 



class RemoteInvokable:
    """
    Base class providing additional functionality related to actions, 
    it is not meant to be subclassed directly by the end-user.
    """

    def __init__(self):
        self.id : str
        super().__init__()
        self._prepare()


    def _prepare(self) -> None:
        """update owner of actions"""
        for action in self.actions.values():
            action.owner = self.__class__
            action.owner_inst = self


    @property
    def actions(self) -> typing.Dict[str, Action]:
        """
        a dictionary with all the actions of the object as values (methods that are decorated with ``action``) and 
        their names as keys.
        """
        try:
            return getattr(self, f'_{self.id}_actions')
        except AttributeError:
            actions = dict()
            for name, method in inspect._getmembers(
                        self, 
                        lambda f : inspect.ismethod(f) or (hasattr(f, '__execution_info_validator') and 
                                    isinstance(f.__execution_info_validator, ActionInfoValidator)) or \
                                    isinstance(f, Action) or issubklass(f, ParameterizedFunction),  
                        getattr_without_descriptor_read
                    ): 
                if hasattr(method, '__execution_info_validator'):
                    actions[name] = method
                elif isinstance(method, Action) or issubklass(method, ParameterizedFunction):
                    actions[name] = method
            setattr(self, f'_{self.id}_actions', actions)
            return actions


__all__ = [
    action.__name__
]


