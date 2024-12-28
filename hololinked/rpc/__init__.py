"""
namespace for pure RPC applications to auto suggest the user. The following were the original names
given until the WoT schema was being generated. The docs then got totally mixed up with two types 
of names and therefore the WoT naming was taken as final. 
"""
import typing
from enum import Enum
from ..server import Thing as RemoteObject, action
from ..constants import USE_OBJECT_NAME, HTTP_METHODS, JSON


def remote_method(URL_path : str = USE_OBJECT_NAME, http_method : str = HTTP_METHODS.POST, 
            state : typing.Optional[typing.Union[str, Enum]] = None, argument_schema : typing.Optional[JSON] = None,
            return_value_schema : typing.Optional[JSON] = None, **kwargs) -> typing.Callable:
    return action(URL_path=URL_path, http_method=http_method, state=state, argument_schema=argument_schema,
                return_value_schema=return_value_schema, **kwargs)