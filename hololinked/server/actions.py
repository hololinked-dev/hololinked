import typing
import jsonschema
from enum import Enum
from types import FunctionType, MethodType
from inspect import iscoroutinefunction, getfullargspec

from ..param.parameterized import ParameterizedFunction
from .utils import issubklass, pep8_to_URL_path, isclassmethod
from .dataklasses import ActionInfoValidator
from .constants import USE_OBJECT_NAME, UNSPECIFIED, HTTP_METHODS, JSON
from .config import global_config



__action_kw_arguments__ = ['safe', 'idempotent', 'synchronous'] 


class Action:

    def __init__(self, obj, owner) -> None:
        self.obj = obj
        self.owner = owner

    @property
    def _remote_info(self) -> ActionInfoValidator:
        return self.obj._remote_info
    

class SyncAction(Action):  

    def __call__(self, *args : typing.Any, **kwargs : typing.Any) -> typing.Any:
        return self.obj(*args, **kwargs)


class AsyncAction(Action):

    async def __call__(self, *args : typing.Any, **kwargs : typing.Any) -> typing.Any:
        return await self.obj(*args, **kwargs)



   
def action(URL_path : str = USE_OBJECT_NAME, http_method : str = HTTP_METHODS.POST, 
            state : typing.Optional[typing.Union[str, Enum]] = None, input_schema : typing.Optional[JSON] = None,
            output_schema : typing.Optional[JSON] = None, create_task : bool = False, **kwargs) -> typing.Callable:
    """
    Use this function as a decorate on your methods to make them accessible remotely. For WoT, an action affordance schema 
    for the method is generated.
    
    Parameters
    ----------
    URL_path: str, optional 
        The path of URL under which the object is accessible. defaults to name of the object.
    http_method: str, optional
        HTTP method (GET, POST, PUT etc.). defaults to POST.
    state: str | Tuple[str], optional 
        state machine state under which the object can executed. When not provided,
        the action can be executed under any state.
    input_schema: JSON 
        schema for arguments to validate them.
    output_schema: JSON 
        schema for return value, currently only used to inform clients which is supposed to validate on its won. 
    **kwargs:
        safe: bool 
            indicate in thing description if action is safe to execute 
        idempotent: bool 
            indicate in thing description if action is idempotent (for example, allows HTTP client to cache return value)
        synchronous: bool
            indicate in thing description if action is synchronous (not long running)
    Returns
    -------
    Callable
        returns the callable object as it is
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
        if hasattr(obj, '_remote_info') and not isinstance(obj._remote_info, ActionInfoValidator): 
            raise NameError(
                "variable name '_remote_info' reserved for hololinked package. ",  
                "Please do not assign this variable to any other object except hololinked.server.dataklasses.ActionInfoValidator."
            )             
        else:
            obj._remote_info = ActionInfoValidator() 
        obj_name = obj.__qualname__.split('.')
        if len(obj_name) > 1: # i.e. its a bound method, used by Thing
            if URL_path == USE_OBJECT_NAME: 
                obj._remote_info.URL_path = f'/{pep8_to_URL_path(obj_name[1])}'
            else:
                if not URL_path.startswith('/'):
                    raise ValueError(f"URL_path should start with '/', please add '/' before '{URL_path}'")
                obj._remote_info.URL_path = URL_path
            obj._remote_info.obj_name = obj_name[1] 
        elif len(obj_name) == 1 and isinstance(obj, FunctionType):  # normal unbound function - used by HTTPServer instance
            if URL_path is USE_OBJECT_NAME:
                obj._remote_info.URL_path = f'/{pep8_to_URL_path(obj_name[0])}'
            else:
                if not URL_path.startswith('/'):
                    raise ValueError(f"URL_path should start with '/', please add '/' before '{URL_path}'")
                obj._remote_info.URL_path = URL_path
            obj._remote_info.obj_name = obj_name[0] 
        else:
            raise RuntimeError(f"Undealt option for decorating {obj} or decorators wrongly used")
        if http_method is not UNSPECIFIED:  
            if isinstance(http_method, str):
                obj._remote_info.http_method = (http_method,)
            else:
                obj._remote_info.http_method = http_method 
        if state is not None:
            if isinstance(state, (Enum, str)):
                obj._remote_info.state = (state,)
            else:
                obj._remote_info.state = state     
        if 'request' in getfullargspec(obj).kwonlyargs:
            obj._remote_info.request_as_argument = True
        obj._remote_info.isaction = True
        obj._remote_info.argument_schema = input_schema
        obj._remote_info.return_value_schema = output_schema
        obj._remote_info.obj = original
        obj._remote_info.create_task = create_task
        obj._remote_info.safe = kwargs.get('safe', False)
        obj._remote_info.idempotent = kwargs.get('idempotent', False)
        obj._remote_info.synchronous = kwargs.get('synchronous', False)
        
        if issubklass(obj, ParameterizedFunction):
            obj._remote_info.iscoroutine = iscoroutinefunction(obj.__call__)
            obj._remote_info.isparameterized = True
        else:
            obj._remote_info.iscoroutine = iscoroutinefunction(obj)
            obj._remote_info.isparameterized = False 
        if global_config.validate_schemas and input_schema:
            jsonschema.Draft7Validator.check_schema(input_schema)
        if global_config.validate_schemas and output_schema:
            jsonschema.Draft7Validator.check_schema(output_schema)
        
        return original
    if callable(URL_path):
        raise TypeError("URL_path should be a string, not a function/method, did you decorate your action wrongly?")
    if any(key not in __action_kw_arguments__ for key in kwargs.keys()):
        raise ValueError("Only 'safe', 'idempotent', 'synchronous' are allowed as keyword arguments, " + 
                        f"unknown arguments found {kwargs.keys()}")
    return inner 



__all__ = [
    action.__name__
]


