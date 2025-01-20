import typing 
from types import FunctionType, MethodType
from enum import EnumMeta, Enum, StrEnum

from ..exceptions import StateMachineError
from .dataklasses import RemoteResourceInfoValidator
from .property import Property
from .properties import ClassSelector, TypedDict, Boolean




class StateMachine:
    """
    A container class for state machine related information. Each ``Thing`` class can only have one state machine  
    instantiated in a reserved class-level attribute ``state_machine``. The ``state`` attribute defined at the ``Thing``
    can be subscribed for state change events from this state machine. 
    """
    initial_state = ClassSelector(default=None, allow_None=True, constant=True, class_=(Enum, str), 
                        doc="initial state of the machine") # type: typing.Union[Enum, str]
    states = ClassSelector(default=None, allow_None=True, constant=True, class_=(EnumMeta, tuple, list),
                        doc="list/enum of allowed states") # type: typing.Union[EnumMeta, tuple, list]
    on_enter = TypedDict(default=None, allow_None=True, key_type=str,
                        doc="""callbacks to execute when a certain state is entered; 
                        specfied as map with state as keys and callbacks as list""") # typing.Dict[str, typing.List[typing.Callable]]
    on_exit = TypedDict(default=None, allow_None=True, key_type=str,
                        doc="""callbacks to execute when certain state is exited; 
                        specfied as map with state as keys and callbacks as list""") # typing.Dict[str, typing.List[typing.Callable]]
    machine = TypedDict(default=None, allow_None=True, item_type=(list, tuple), key_type=str, # i.e. its like JSON
                        doc="the machine specification with state as key and objects as list") # typing.Dict[str, typing.List[typing.Callable, Property]]
    valid = Boolean(default=False, readonly=True, fget=lambda self: self._valid, 
                        doc="internally computed, True if states, initial_states and the machine is valid")
    
    def __init__(self, 
            states : typing.Union[EnumMeta, typing.List[str], typing.Tuple[str]], *, 
            initial_state : typing.Union[StrEnum, str], push_state_change_event : bool = True,
            on_enter : typing.Dict[str, typing.Union[typing.List[typing.Callable], typing.Callable]] = {}, 
            on_exit  : typing.Dict[str, typing.Union[typing.List[typing.Callable], typing.Callable]] = {}, 
            **machine : typing.Dict[str, typing.Union[typing.Callable, Property]]
        ) -> None:
        """
        Parameters
        ----------
        states: Enum
            enumeration of states 
        initial_state: str 
            initial state of machine 
        push_state_change_event : bool, default True
            when the state changes, an event is pushed with the new state
        on_enter: Dict[str, Callable | Property] 
            callbacks to be invoked when a certain state is entered. It is to be specified 
            as a dictionary with the states being the keys
        on_exit: Dict[str, Callable | Property]
            callbacks to be invoked when a certain state is exited. 
            It is to be specified as a dictionary with the states being the keys
        **machine:
            state name: List[Callable, Property]
                directly pass the state name as an argument along with the methods/properties which are allowed to execute 
                in that state
        """
        self._valid = False
        self.on_enter = on_enter
        self.on_exit  = on_exit
        # None cannot be passed in, but constant is necessary. 
        self.states   = states
        self.initial_state = initial_state
        self.machine = machine
        self.push_state_change_event = push_state_change_event
        # if :
        #     self.state_change_event = Event('state-change') 

    def _prepare(self, owner) -> None:
        from .thing import Thing, Property, Action
        assert isinstance(owner, Thing), "state machine can only be attached to a Thing class."
        
        if self.states is None and self.initial_state is None:    
            self._valid = False 
            self._state = None
            return
        elif self.initial_state not in self.states:
            raise AttributeError(f"specified initial state {self.initial_state} not in Enum of states {self.states}.")

        self._state = self._get_machine_compliant_state(self.initial_state)
        self.owner = owner
        owner_properties = owner.parameters.descriptors.values() # same as owner.properties.descriptors.values()
        owner_methods = owner.actions.values()
        
        if isinstance(self.states, list):
            self.__class__.states.constant = False 
            self.states = tuple(self.states) # freeze the list of states
            self.__class__.states.constant = True   
            
        # first validate machine
        for state, objects in self.machine.items():
            if state in self:
                for resource in objects:
                    if isinstance(resource, (Property, Action)):
                        assert isinstance(resource._execution_info_validator, RemoteResourceInfoValidator) # type definition
                        if resource._execution_info_validator.isaction and resource not in owner_methods: 
                            raise AttributeError("Given object {} for state machine does not belong to class {}".format(
                                                                                                resource, owner))
                        if resource._execution_info_validator.isproperty and resource not in owner_properties: 
                            raise AttributeError("Given object {} - {} for state machine does not belong to class {}".format(
                                                                                                resource.name, resource, owner))
                        if resource._execution_info_validator.state is None: 
                            resource._execution_info_validator.state = self._get_machine_compliant_state(state)
                        else: 
                            resource._execution_info_validator.state = resource._execution_info_validator.state + (self._get_machine_compliant_state(state), ) 
                    else: 
                        raise AttributeError(f"Object {resource} was not made remotely accessible," + 
                                    " use state machine with properties and actions only.")
            else:
                raise StateMachineError("Given state {} not in states Enum {}".format(state, self.states.__members__))
            
        # then the callbacks 
        for state, objects in self.on_enter.items():
            if isinstance(objects, list):
                self.on_enter[state] = tuple(objects) 
            elif not isinstance(objects, (list, tuple)):
                self.on_enter[state] = (objects, )
            for obj in self.on_enter[state]: # type: ignore
                if not isinstance(obj, (FunctionType, MethodType)):
                    raise TypeError(f"on_enter accept only methods. Given type {type(obj)}.")

        for state, objects in self.on_exit.items():
            if isinstance(objects, list):
                self.on_exit[state] = tuple(objects) # type: ignore
            elif not isinstance(objects, (list, tuple)):
                self.on_exit[state] = (objects, ) # type: ignore
            for obj in self.on_exit[state]: # type: ignore
                if not isinstance(obj, (FunctionType, MethodType)):
                    raise TypeError(f"on_enter accept only methods. Given type {type(obj)}.")     
        self._valid = True
        
    def __contains__(self, state : typing.Union[str, StrEnum]):
        if isinstance(self.states, EnumMeta) and state in self.states.__members__:
            return True
        elif isinstance(self.states, tuple) and state in self.states:
            return True
        elif self.has_object(state):
            return True
        return False
        
    def _get_machine_compliant_state(self, state) -> typing.Union[StrEnum, str]:
        """
        In case of not using StrEnum or iterable of str, 
        this maps the enum of state to the state name.
        """
        if isinstance(state, str):
            return state 
        if isinstance(state, Enum):
            return state.name
        raise TypeError(f"cannot comply state to a string : {state} which is of type {type(state)}.")
    

    def get_state(self) -> typing.Union[str, StrEnum, None]:
        """
        return the current state. one can also access the property `current state`.
        
        Returns
        -------
        current state: str
        """
        return self._state
        
    def set_state(self, value : typing.Union[str, StrEnum, Enum], push_event : bool = True, 
                skip_callbacks : bool = False) -> None:
        """ 
        set state of state machine. Also triggers state change callbacks if skip_callbacks=False and pushes a state 
        change event when push_event=True. One can also set state using '=' operator of `current_state` property in which case 
        callbacks will be called. If originally an enumeration for the list of allowed states was supplied, 
        then an enumeration member must be used to set state. If a list of strings were supplied, then a string is accepted. 

        Raises
        ------
        ValueError: 
            if the state is not found in the allowed states
        """
    
        if value in self.states:
            previous_state = self._state
            self._state = self._get_machine_compliant_state(value)
            if push_event and self.push_state_change_event and hasattr(self.owner, 'event_publisher'):
                self.owner.state # just acces to trigger the observable event
            if skip_callbacks:
                return 
            if previous_state in self.on_exit:
                for func in self.on_exit[previous_state]:
                    func(self.owner)
            if self._state in self.on_enter:
                for func in self.on_enter[self._state]: 
                    func(self.owner)
        else:   
            raise ValueError("given state '{}' not in set of allowed states : {}.".format(value, self.states))
                
    current_state = property(get_state, set_state, None, 
        doc = """read and write current state of the state machine""")

    def contains_object(self, object : typing.Union[Property, typing.Callable]) -> bool:
        """
        returns True if specified object is found in any of the state machine states. 
        Supply unbound method for checking methods, as state machine is specified at class level
        when the methods are unbound. 
        """
        for objects in self.machine.values():
            if object in objects:
                return True 
        return False
    

