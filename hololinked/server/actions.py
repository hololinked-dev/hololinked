import inspect
import typing
import jsonschema
from enum import Enum
from types import FunctionType, MethodType
from inspect import iscoroutinefunction, getfullargspec

from hololinked.schema_validators.validators import JsonSchemaValidator

from ..param.parameterized import ParameterizedFunction
from ..constants import JSON
from ..config import global_config
from ..utils import has_async_def, issubklass, isclassmethod
from ..exceptions import StateMachineError
from .dataklasses import ActionInfoValidator, ActionResource



class Action:
    """
    Object that models an action.
    """
    __slots__ = ['obj', 'owner', '_execution_info']

    def __init__(self, obj) -> None:
        self.obj = obj

    def __set_name__(self, owner, name):
        self.owner = owner
                
    def __str__(self) -> str:
        return f"<Action({self.owner.__name__}.{self.obj.__name__})>"
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, Action):
            return False
        return self.obj == other.obj
    
    def __hash__(self) -> int:
        return hash(self.obj)
    
    def __get__(self, instance, owner):
        if instance is None and not self._execution_info.isclassmethod:
            return self
        if self._execution_info.iscoroutine:
            return BoundAsyncAction(self.obj, self._execution_info, instance, owner)
        return BoundSyncAction(self.obj, self._execution_info, instance, owner)
    
    def __call__(self, *args, **kwargs):
        raise NotImplementedError(f"Cannot invoke unbound action {self.name} of {self.owner.__name__}." + 
                        " Bound methods must be called, not the action itself. Use the appropriate instance to call the method.")
       
    @property
    def name(self) -> str:
        """name of the action"""
        return self.obj.__name__           
      
    @property
    def execution_info(self) -> ActionInfoValidator:
        return self._execution_info
        
    @execution_info.setter
    def execution_info(self, value: ActionInfoValidator) -> None:
        if not isinstance(value, ActionInfoValidator):
            raise TypeError("execution_info must be of type ActionResource")
        self._execution_info = value # type: ActionResource
    
    def to_affordance(self, owner_inst):
        assert isinstance(owner_inst, self.owner), "owner_inst must be an instance of the owner class"
        from hololinked.td import ActionAffordance
        affordance = ActionAffordance()
        affordance._build(self, owner_inst) 
        return affordance
    


class BoundAction:

    __slots__ = ['obj', 'execution_info', 'owner_inst', 'owner', 'bound_obj']

    def __init__(self, obj: FunctionType, execution_info: ActionInfoValidator, owner_inst, owner) -> None:
        self.obj = obj
        self.execution_info = execution_info
        self.owner = owner
        self.owner_inst = owner_inst
        self.bound_obj = owner if execution_info.isclassmethod else owner_inst

    def __post_init__(self):
        # never called, neither possible to call, only type hinting
        from .thing import ThingMeta, Thing
        # owner class and instance
        self.owner: ThingMeta  
        self.owner_inst: Thing
        self.obj: FunctionType
        # the validator that was used to accept user inputs to this action.
        # stored only for reference, hardly used. 
        self.execution_info_validator: ActionInfoValidator
        self.execution_info: ActionInfoValidator

    def validate_call(self, args, kwargs : typing.Dict[str, typing.Any]) -> None:
        """
        Validate the call to the action, like payload, state machine state etc. 
        Errors are raised as exceptions.
        """
        if self.execution_info.isparameterized and len(args) > 0:
            raise RuntimeError("parameterized functions cannot have positional arguments")
        if self.owner_inst is None:
            return 
        if self.execution_info.state is None or (hasattr(self.owner_inst, 'state_machine') and 
                            self.owner_inst.state_machine.current_state in self.execution_info.state):
            if self.execution_info.schema_validator is not None and len(args) == 0:
                self.execution_info.schema_validator.validate(kwargs)
        else: 
            raise StateMachineError("Thing '{}' is in '{}' state, however command can be executed only in '{}' state".format(
                    self.owner_inst.id, self.owner_inst.state, self.execution_info.state))      
        
    @property
    def name(self) -> str:
        """name of the action"""
        return self.obj.__name__           
        
    def __call__(self, *args, **kwargs):
        raise NotImplementedError("call must be implemented by subclass")
    
    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        raise NotImplementedError("external_call must be implemented by subclass")
    
    def __str__(self):
        return f"<BoundAction({self.owner.__name__}.{self.obj.__name__} of {self.owner_inst.id})>"
    
    def __eq__(self, value):
        if not isinstance(value, BoundAction):
            return False
        return self.obj == value.obj
    
    def __hash__(self):
        return hash(str(self))
    
    def __getattribute__(self, name):
        "Emulate method_getset() in Objects/classobject.c"
        # https://docs.python.org/3/howto/descriptor.html#functions-and-methods
        if name == '__doc__':
            return self.obj.__doc__
        return super().__getattribute__(name)

    def to_affordance(self):
        return Action.to_affordance(self, self.owner_inst or self.owner)

        

class BoundSyncAction(BoundAction):  
    """
    non async(io) action call. The call is passed to the method as-it-is to allow local 
    invocation without state machine checks.
    """
    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return self.__call__(*args, **kwargs)
        
    def __call__(self, *args, **kwargs):
        if self.execution_info.isclassmethod:
            return self.obj(*args, **kwargs)
        return self.obj(self.bound_obj, *args, **kwargs)


class BoundAsyncAction(BoundAction):
    """
    async(io) action call. The call is passed to the method as-it-is to allow local 
    invocation without state machine checks.
    """
    async def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        self.validate_call(args, kwargs)
        return await self.__call__(*args, **kwargs)

    async def __call__(self, *args, **kwargs):
        if self.execution_info.isclassmethod:
            return await self.obj(*args, **kwargs)
        return await self.obj(self.bound_obj, *args, **kwargs)



__action_kw_arguments__ = ['safe', 'idempotent', 'synchronous'] 

def action(
        input_schema : JSON | None = None, 
        output_schema : JSON | None = None, 
        state : str | Enum | None = None, 
        create_task : bool = False, 
        **kwargs
    ) -> Action:
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

        if isclassmethod(original):
            execution_info_validator.iscoroutine = has_async_def(obj)
            execution_info_validator.isclassmethod = True
        elif issubklass(obj, ParameterizedFunction):
            execution_info_validator.iscoroutine = iscoroutinefunction(obj.__call__)
            execution_info_validator.isparameterized = True
        else:
            execution_info_validator.iscoroutine = iscoroutinefunction(obj)
        if global_config.validate_schemas and input_schema:
            execution_info_validator.schema_validator = JsonSchemaValidator(input_schema)
        if global_config.validate_schemas and output_schema:
            jsonschema.Draft7Validator.check_schema(output_schema) 
            # output is not validated by us, so we just check the schema and dont create a validator
 
        final_obj = Action(original) # type: Action
        final_obj.execution_info = execution_info_validator
        return final_obj
    if callable(input_schema):
        raise TypeError("input schema should be a JSON, not a function/method, did you decorate your action wrongly? " +
                        "use @action() instead of @action")
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
        pass 

    @property
    def actions(self) -> typing.Dict[str, Action]:
        """
        All bound actions available on the object. Access `self.__class__.actions` to retrieve unbound actions.
       
        Returns
        -------
        Dict[str, Action]
            dictionary of actions available on the object along with their names as keys
        """
        try:
            return getattr(self, f'_{self.id}_actions')
        except AttributeError:
            actions = dict()
            for name, method in self.__class__.actions.items():
                actions[name] = getattr(self, name)
            setattr(self, f'_{self.id}_actions', actions)
            return actions


    


__all__ = [
    action.__name__,
    Action.__name__
]


