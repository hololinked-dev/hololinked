import typing
from types import FunctionType, MethodType
from enum import EnumMeta, Enum, StrEnum

from ..param import edit_constant
from ..exceptions import StateMachineError
from .property import Property
from .properties import ClassSelector, TypedDict, Boolean
from .thing import Thing
from .meta import ThingMeta
from .actions import Action


class StateMachine:
    """
    A finite state machine to constrain property and action execution. Each `Thing` class can only have one state machine
    instantiated in a reserved class-level attribute named `state_machine`. Other instantiations are not respected.
    The `state` attribute defined as a `Thing`'s property reflects the current state of the state machine and
    can be subscribed for state change events. When `state_machine` is accessed by a `Thing` instance,
    a `BoundFSM` object is returned.
    """

    initial_state = ClassSelector(
        default=None, allow_None=True, constant=True, class_=(Enum, str), doc="initial state of the machine"
    )  # type: typing.Union[Enum, str]
    states = ClassSelector(
        default=None, allow_None=True, constant=True, class_=(EnumMeta, tuple, list), doc="list/enum of allowed states"
    )  # type: typing.Union[EnumMeta, tuple, list]
    on_enter = TypedDict(
        default=None,
        allow_None=True,
        key_type=str,
        doc="""callbacks to execute when a certain state is entered; 
                        specfied as map with state as keys and callbacks as list""",
    )  # type: typing.Dict[str, typing.List[typing.Callable]]
    on_exit = TypedDict(
        default=None,
        allow_None=True,
        key_type=str,
        doc="""callbacks to execute when certain state is exited; 
                        specfied as map with state as keys and callbacks as list""",
    )  # type: typing.Dict[str, typing.List[typing.Callable]]
    machine = TypedDict(
        default=None,
        allow_None=True,
        item_type=(list, tuple),
        key_type=str,  # i.e. its like JSON
        doc="the machine specification with state as key and objects as list",
    )  # type: typing.Dict[str, typing.List[typing.Callable, Property]]
    valid = Boolean(
        default=False,
        readonly=True,
        fget=lambda self: self._valid,
        doc="internally computed, True if states, initial_states and the machine is valid",
    )

    def __init__(
        self,
        states: EnumMeta | typing.List[str] | typing.Tuple[str],
        *,
        initial_state: StrEnum | str,
        push_state_change_event: bool = True,
        on_enter: typing.Dict[str, typing.List[typing.Callable] | typing.Callable] = None,
        on_exit: typing.Dict[str, typing.List[typing.Callable] | typing.Callable] = None,
        **machine: typing.Dict[str, typing.Callable | Property],
    ) -> None:
        """
        Parameters
        ----------
        states: EnumMeta | List[str] | Tuple[str]
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
        self._valid = False  #
        self.name = None
        self.on_enter = on_enter
        self.on_exit = on_exit
        # None cannot be passed in, but constant is necessary.
        self.states = states
        self.initial_state = initial_state
        self.machine = machine
        self.push_state_change_event = push_state_change_event

    def __set_name__(self, owner: ThingMeta, name: str) -> None:
        self.name = name
        self.owner = owner

    def validate(self, owner: Thing) -> None:
        # cannot merge this with __set_name__ because descriptor objects are not ready at that time.
        # reason - metaclass __init__ is called after __set_name__ of descriptors, therefore the new "proper" desriptor
        # registries are available only after that. Until then only the inherited descriptor registries are available,
        # which do not correctly account the subclass's objects.

        if self.states is None and self.initial_state is None:
            self._valid = False
            return
        elif self.initial_state not in self.states:
            raise AttributeError(f"specified initial state {self.initial_state} not in Enum of states {self.states}.")

        # owner._state_machine_state = self._get_machine_compliant_state(self.initial_state)
        owner_properties = owner.properties.get_descriptors(recreate=True).values()
        owner_methods = owner.actions.get_descriptors(recreate=True).values()

        if isinstance(self.states, list):
            with edit_constant(self.__class__.states):  # type: ignore
                self.states = tuple(self.states)  # freeze the list of states

        # first validate machine
        for state, objects in self.machine.items():
            if state in self:
                for resource in objects:
                    if isinstance(resource, Action):
                        if resource not in owner_methods:
                            raise AttributeError(
                                "Given object {} for state machine does not belong to class {}".format(resource, owner)
                            )
                    elif isinstance(resource, Property):
                        if resource not in owner_properties:
                            raise AttributeError(
                                "Given object {} for state machine does not belong to class {}".format(resource, owner)
                            )
                        continue  # for now
                    else:
                        raise AttributeError(
                            f"Object {resource} was not made remotely accessible,"
                            + " use state machine with properties and actions only."
                        )
                    if resource.execution_info.state is None:
                        resource.execution_info.state = self._get_machine_compliant_state(state)
                    else:
                        resource.execution_info.state = resource._execution_info.state + (
                            self._get_machine_compliant_state(state),
                        )
            else:
                raise StateMachineError(
                    "Given state {} not in allowed states ({})".format(state, self.states.__members__)
                )

        # then the callbacks
        if self.on_enter is None:
            self.on_enter = {}
        for state, objects in self.on_enter.items():
            if isinstance(objects, list):
                self.on_enter[state] = tuple(objects)
            elif not isinstance(objects, (list, tuple)):
                self.on_enter[state] = (objects,)
            for obj in self.on_enter[state]:  # type: ignore
                if not isinstance(obj, (FunctionType, MethodType)):
                    raise TypeError(f"on_enter accept only methods. Given type {type(obj)}.")

        if self.on_exit is None:
            self.on_exit = {}
        for state, objects in self.on_exit.items():
            if isinstance(objects, list):
                self.on_exit[state] = tuple(objects)  # type: ignore
            elif not isinstance(objects, (list, tuple)):
                self.on_exit[state] = (objects,)  # type: ignore
            for obj in self.on_exit[state]:  # type: ignore
                if not isinstance(obj, (FunctionType, MethodType)):
                    raise TypeError(f"on_enter accept only methods. Given type {type(obj)}.")
        self._valid = True

    def __get__(self, instance, owner) -> "BoundFSM":
        if instance is None:
            return self
        return BoundFSM(instance, self)

    def __set__(self, instance, value) -> None:
        raise AttributeError(
            "Cannot set state machine directly. It is a class level attribute and can be defined only once."
        )

    def __contains__(self, state: typing.Union[str, StrEnum]):
        if isinstance(self.states, EnumMeta) and state in self.states.__members__:
            return True
        elif isinstance(self.states, tuple) and state in self.states:
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
        raise TypeError(
            f"cannot comply state to a string: {state} which is of type {type(state)}. owner - {self.owner}."
        )

    def contains_object(self, object: typing.Union[Property, typing.Callable]) -> bool:
        """
        returns True if specified object is found in any of the state machine states.
        Supply unbound method for checking methods, as state machine is specified at class level
        when the methods are unbound.
        """
        for objects in self.machine.values():
            if object in objects:
                return True
        return False


class BoundFSM:
    """
    A FSM bound to a `Thing` instance, returned when accessed as a instance attribute (`self.state_machine`).
    There is no need to instantiate this class directly.
    """

    def __init__(self, owner: Thing, state_machine: StateMachine) -> None:
        self.descriptor = state_machine
        self.push_state_change_event = state_machine.push_state_change_event
        self.owner = owner
        # self.owner._state_machine_state = state_machine.initial_state
        # self.state_machine._prepare(owner)

    def get_state(self) -> typing.Union[str, StrEnum, None]:
        """
        return the current state. one can also access the property `current state`.

        Returns
        -------
        current state: str
        """
        try:
            return self.owner._state_machine_state
        except AttributeError:
            return self.initial_state

    def set_state(
        self, value: typing.Union[str, StrEnum, Enum], push_event: bool = True, skip_callbacks: bool = False
    ) -> None:
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
            previous_state = self.current_state
            next_state = self.descriptor._get_machine_compliant_state(value)
            self.owner._state_machine_state = next_state
            if push_event and self.push_state_change_event and hasattr(self.owner, "event_publisher"):
                self.owner.state  # just acces to trigger the observable event
            if skip_callbacks:
                return
            if previous_state in self.on_exit:
                for func in self.on_exit[previous_state]:
                    func(self.owner)
            if next_state in self.on_enter:
                for func in self.on_enter[next_state]:
                    func(self.owner)
        else:
            raise ValueError("given state '{}' not in set of allowed states : {}.".format(value, self.states))

    current_state = property(get_state, set_state, None, doc="""read and write current state of the state machine""")

    def contains_object(self, object: typing.Union[Property, typing.Callable]) -> bool:
        """
        returns True if specified object is found in any of the state machine states.
        Supply unbound method for checking methods, as state machine is specified at class level
        when the methods are unbound.
        """
        return self.descriptor.contains_object(object)

    def __hash__(self):
        return hash(
            self.owner.id
            + (str(state) for state in self.states)
            + str(self.initial_state)
            + self.owner.__class__.__name__
        )

    def __str__(self):
        return f"StateMachine(owner={self.owner.__class__.__name__} id={self.owner.id} initial_state={self.initial_state}, states={self.states})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, StateMachine):
            return False
        return (
            self.states == other.states
            and self.initial_state == other.initial_state
            and self.owner.__class__ == other.owner.__class__
            and self.owner.id == other.owner.id
        )

    def __contains__(self, state: typing.Union[str, StrEnum]) -> bool:
        return state in self.descriptor

    @property
    def initial_state(self):
        """initial state of the machine"""
        return self.descriptor.initial_state

    @property
    def states(self):
        """list of allowed states"""
        return self.descriptor.states

    @property
    def on_enter(self):
        """callbacks to execute when a certain state is entered"""
        return self.descriptor.on_enter

    @property
    def on_exit(self):
        """callbacks to execute when certain state is exited"""
        return self.descriptor.on_exit

    @property
    def machine(self):
        """the machine specification with state as key and objects as list"""
        return self.descriptor.machine


def prepare_object_FSM(instance: Thing) -> None:
    """
    prepare state machine attached to thing class
    """
    assert isinstance(instance, Thing), "state machine can only be attached to a Thing class."
    cls = instance.__class__
    if cls.state_machine and isinstance(cls.state_machine, StateMachine):
        cls.state_machine.validate(instance)
        instance.logger.debug("setup state machine")
