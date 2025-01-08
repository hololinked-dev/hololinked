import functools
import inspect
import typing
import jsonschema
from enum import Enum
from types import FunctionType, MethodType
from inspect import iscoroutinefunction, getfullargspec

from ..param.parameterized import ParameterizedFunction
from ..constants import JSON
from ..config import global_config
from ..utils import getattr_without_descriptor_read, issubklass, isclassmethod
from ..exceptions import StateMachineError
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
        self._execution_info : ActionResource
      
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
        
    def external_call(self, *args, **kwargs):
        """validated call to the action with state machine and payload checks"""
        raise NotImplementedError("external_call must be implemented by subclass")

    @property
    def name(self) -> str:
        """name of the action"""
        return self.obj.__name__           


    

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


try:
    from pydantic import BaseModel, ConfigDict, Field, RootModel
    from pydantic.main import create_model
    from inspect import Parameter, signature
    from collections import OrderedDict

    class EmptyObject(BaseModel):
        model_config = ConfigDict(extra="allow")

    class StrictEmptyObject(EmptyObject):
        model_config = ConfigDict(extra="forbid")

    class EmptyInput(RootModel):
        root: EmptyObject | None = None

    class StrictEmptyInput(EmptyInput):
        root: StrictEmptyObject | None = None

    def input_model_from_signature(
        func: typing.Callable,
        remove_first_positional_arg: bool = False,
        ignore: typing.Sequence[str] | None = None,
    ) -> type[BaseModel]:
        """Create a pydantic model for a function's signature.

        This is deliberately quite a lot more basic than
        `pydantic.decorator.ValidatedFunction` because it is designed
        to handle JSON input. That means that we don't want positional
        arguments, unless there's exactly one (in which case we have a
        single value, not an object, and this may or may not be supported).

        This will fail for position-only arguments, though that may change
        in the future.

        :param remove_first_positional_arg: Remove the first argument from the
            model (this is appropriate for methods, as the first argument,
            self, is baked in when it's called, but is present in the
            signature).
        :param ignore: Ignore arguments that have the specified name.
            This is useful for e.g. dependencies that are injected by LabThings.
        :returns: A pydantic model class describing the input parameters

        TODO: deal with (or exclude) functions with a single positional parameter
        """
        parameters = OrderedDict(signature(func).parameters) # type: OrderedDict[str, Parameter]
        if remove_first_positional_arg:
            name, parameter = next(iter((parameters.items())))  # get the first parameter
            if parameter.kind in (Parameter.KEYWORD_ONLY, Parameter.VAR_KEYWORD):
                raise ValueError("Can't remove first positional argument: there is none.")
            del parameters[name]

        # Raise errors if positional-only or variable positional args are present
        if any(p.kind == Parameter.VAR_POSITIONAL for p in parameters.values()):
            raise TypeError(
                f"{func.__name__} accepts extra positional arguments, "
                "which is not supported."
            )
        if any(p.kind == Parameter.POSITIONAL_ONLY for p in parameters.values()):
            raise TypeError(
                f"{func.__name__} has positional-only arguments which are not supported."
            )

        # The line below determines if we accept arbitrary extra parameters (**kwargs)
        takes_v_kwargs = False  # will be updated later
        # fields is a dictionary of tuples of (type, default) that defines the input model
        type_hints = typing.get_type_hints(func, include_extras=True)
        fields = {} # type: typing.Dict[str, typing.Tuple[type, typing.Any]]
        for name, p in parameters.items():
            if ignore and name in ignore:
                continue
            if p.kind == Parameter.VAR_KEYWORD:
                takes_v_kwargs = True  # we accept arbitrary extra arguments
                continue  # **kwargs should not appear in the schema
            # `type_hints` does more processing than p.annotation - but will
            # not have entries for missing annotations.
            p_type = typing.Any if p.annotation is Parameter.empty else type_hints[name]
            # pydantic uses `...` to represent missing defaults (i.e. required params)
            default = Field(...) if p.default is Parameter.empty else p.default
            fields[name] = (p_type, default)
        model = create_model(  # type: ignore[call-overload]
            f"{func.__name__}_input",
            model_config=ConfigDict(extra="allow" if takes_v_kwargs else "forbid"),
            **fields,
        )
        # If there are no fields, we use a RootModel to allow none as well as {}
        if len(fields) == 0:
            return EmptyInput if takes_v_kwargs else StrictEmptyInput
        return model
    
    def return_type(func: typing.Callable) -> typing.Type:
        """Determine the return type of a function."""
        sig = inspect.signature(func)
        if sig.return_annotation == inspect.Signature.empty:
            return Any  # type: ignore[return-value]
        else:
            # We use `get_type_hints` rather than just `sig.return_annotation`
            # because it resolves forward references, etc.
            type_hints = typing.get_type_hints(func, include_extras=True)
            return type_hints["return"]

except ImportError:
    def input_model_from_signature(
        func: typing.Callable,
        remove_first_positional_arg: bool = False,
        ignore: typing.Sequence[str] | None = None,
    ) -> type[BaseModel]:
        raise ImportError("pydantic is required for this feature")
   

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


