import copy

from enum import Enum
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, RootModel

from ..constants import JSON, ResourceTypes
from ..core.actions import Action
from ..core.events import Event
from ..core.property import Property
from ..core.thing import Thing, ThingMeta
from ..utils import issubklass
from .base import Schema
from .data_schema import DataSchema
from .forms import Form
from .pydantic_extensions import type_to_dataschema
from .utils import get_summary


class InteractionAffordance(Schema):
    """
    Implements schema information common to all interaction affordances.

    [Specification Definitions](https://www.w3.org/TR/wot-thing-description11/#interactionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    title: Optional[str] = None
    titles: Optional[dict[str, str]] = None
    description: Optional[str] = None
    descriptions: Optional[dict[str, str]] = None
    forms: Optional[list[Form]] = None
    # uri variables

    _custom_schema_generators: ClassVar = dict()
    model_config = ConfigDict(extra="allow")

    def __init__(self):
        super().__init__()
        self._name = None
        self._objekt = None
        self._thing_id = None
        self._thing_cls = None
        self._owner = None

    @property
    def what(self) -> Enum:
        """Whether it is a property, action or event"""
        raise NotImplementedError("Unknown interaction affordance - implement in subclass of InteractionAffordance")

    @property
    def owner(self) -> Thing:
        """
        Owning `Thing` instance or `Thing` class of the interaction affordance.
        Depends on how this object was created, whether using an instance or a class.
        """
        return self._owner

    @owner.setter
    def owner(self, value):
        if self._owner is not None:
            raise ValueError(
                f"owner is already set for this {self.what.name.lower()} affordance, "
                + "recreate the affordance to change owner"
            )
        if not isinstance(value, (Thing, ThingMeta)):
            raise TypeError(f"owner must be instance of Thing, given type {type(value)}")
        self._owner = value
        if isinstance(value, Thing):
            self._thing_cls = value.__class__
            self._thing_id = value.id
        elif isinstance(value, ThingMeta):
            self._thing_cls = value

    @property
    def objekt(self) -> Property | Action | Event:
        """Object instance of the interaction affordance - `Property`, `Action` or `Event`"""
        return self._objekt

    @objekt.setter
    def objekt(self, value: Property | Action | Event) -> None:
        """Set the object instance of the interaction affordance - `Property`, `Action` or `Event`"""
        if self._objekt is not None:
            raise ValueError(
                f"object is already set for this {self.what.name.lower()} affordance, "
                + "recreate the affordance to change objekt"
            )
        if not (
            (self.__class__.__name__.startswith("Property") and isinstance(value, Property))
            or (self.__class__.__name__.startswith("Action") and isinstance(value, Action))
            or (self.__class__.__name__.startswith("Event") and isinstance(value, Event))
        ):
            if not isinstance(value, (Property, Action, Event)):
                raise TypeError(f"objekt must be instance of Property, Action or Event, given type {type(value)}")
            raise ValueError(
                f"provide only corresponding object for {self.__class__.__name__}, "
                + f"given object {value.__class__.__name__}"
            )
        self._objekt = value
        self._name = value.name

    @property
    def name(self) -> str:
        """Name of the interaction affordance used as key in the TD"""
        return self._name

    @property
    def thing_id(self) -> str | None:
        """ID of the `Thing` instance owning the interaction affordance, if available, otherwise None"""
        return self._thing_id

    @property
    def thing_cls(self) -> ThingMeta:
        """`Thing` class owning the interaction affordance"""
        return self._thing_cls

    def build(self) -> None:
        """populate the fields of the schema for the specific interaction affordance"""
        raise NotImplementedError("build must be implemented in subclass of InteractionAffordance")

    def retrieve_form(self, op: str, default: Any = None) -> Form:
        """
        retrieve form for a certain operation, return default if not found

        Parameters
        ----------
        op: str
            operation for which the form is to be retrieved
        default: Any, optional
            default value to return if form is not found, by default None.
            One can make use of a sensible default value for one's logic.

        Returns
        -------
        dict[str, Any]
            JSON representation of the form
        """
        if self.forms is None:
            return default
        for form in self.forms:
            if form.op == op:
                return form
        return default

    def pop_form(self, op: str, default: Any = None) -> Form:
        """
        retrieve and remove form for a certain operation, return default if not found

        Parameters
        ----------
        op: str
            operation for which the form is to be retrieved
        default: Any, optional
            default value to return if form is not found, by default None.
            One can make use of a sensible default value for one's logic.

        Returns
        -------
        dict[str, Any]
            JSON representation of the form
        """
        if self.forms is None:
            return default
        for i, form in enumerate(self.forms):
            if form.op == op:
                return self.forms.pop(i)
        return default

    @classmethod
    def generate(
        cls,
        interaction: Property | Action | Event,
        owner: Thing,
    ) -> "PropertyAffordance | ActionAffordance | EventAffordance":
        """
        build the schema for the specific interaction affordance as an instance of this class.
        Use the `json()` method to get the JSON representation of the schema.

        Note that this method is different from build() method as its supposed to be used as a classmethod
        to create an instance. Although, it internally calls build(), and some additional steps are included.

        Parameters
        ----------
        interaction: Property | Action | Event
            interaction object for which the schema is to be built
        owner: Thing
            owner of the interaction affordance

        Returns
        -------
        "PropertyAffordance | ActionAffordance | EventAffordance"
        """
        raise NotImplementedError("generate_schema must be implemented in subclass of InteractionAffordance")

    @classmethod
    def from_TD(cls, name: str, TD: JSON) -> "PropertyAffordance | ActionAffordance | EventAffordance":
        """
        populate the schema from the TD and return it as an instance of this class.

        Parameters
        ----------
        name: str
            name of the interaction affordance used as key in the TD
        TD: JSON
            Thing Description JSON dictionary (the entire one, not just the component of the affordance)

        Returns
        -------
        "PropertyAffordance | ActionAffordance | EventAffordance"
        """
        if cls == PropertyAffordance:
            affordance_name = "properties"
        elif cls == ActionAffordance:
            affordance_name = "actions"
        elif cls == EventAffordance:
            affordance_name = "events"
        else:
            raise ValueError(f"unknown affordance type - {cls}, cannot create object from TD")
        affordance_json = TD[affordance_name][name]  # type: dict[str, JSON]
        affordance = cls()
        for field in cls.model_fields:
            if field in affordance_json:
                if field == "forms":
                    affordance.forms = [Form.from_TD(form) for form in affordance_json[field]]
                else:
                    setattr(affordance, field, affordance_json[field])
        affordance._name = name
        affordance._thing_id = TD["id"]
        return affordance

    @classmethod
    def register_descriptor(
        cls,
        descriptor: Property | Action | Event,
        schema_generator: "InteractionAffordance",
    ) -> None:
        """register a custom schema generator for a descriptor"""
        if not isinstance(descriptor, (Property, Action, Event)):
            raise TypeError(
                "custom schema generator can also be registered for Property." + f" Given type {type(descriptor)}"
            )
        if not isinstance(schema_generator, InteractionAffordance):
            raise TypeError(
                "schema generator for Property must be subclass of PropertyAfforance. "
                + f"Given type {type(schema_generator)}"
            )
        InteractionAffordance._custom_schema_generators[descriptor] = schema_generator

    def build_non_compliant_metadata(self) -> None:
        """If by chance, there is additional non standard metadata to be added, they can be added here"""
        pass

    def override_defaults(self, **kwargs):
        """
        Override default values with provided keyword arguments, especially thing_id, owner name, object name etc.
        Any logic to trigger side effects while setting those values should be handled here.
        """
        for key, value in kwargs.items():
            if key == "name":
                self._name = value
            elif key == "thing_id":
                self._thing_id = value
            elif key == "owner":
                self._owner = value
            elif key == "thing_cls":
                self._thing_cls = value
            elif hasattr(self, key) or key in self.model_fields:
                setattr(self, key, value)

    def __hash__(self):
        return hash(
            self.thing_id if self.thing_id else "" + self.thing_cls.__name__ if self.thing_cls else "" + self.name
        )

    def __str__(self):
        if self.thing_cls:
            return f"{self.__class__.__name__}({self.thing_cls.__name__}({self.thing_id}).{self.name})"
        return f"{self.__class__.__name__}({self.name} of {self.thing_id})"

    def __eq__(self, value):
        if not isinstance(value, self.__class__):
            return False
        if self.thing_id is None or value.thing_id is None:
            if self.owner is None or value.owner is None:
                # cannot determine anymore
                return False
            # basically you need to have an owner for the interaction affordance
            # and a name to determine its equality. We should never check the owner
            # by the name, but by the object, otherwise the equality cannot be gauranteed
            if (self.owner == value.owner or self.thing_cls == value.thing_cls) and self.name == value.name:
                return True
            return False
        return self.thing_id == value.thing_id and self.name == value.name

    def __deepcopy__(self, memo):
        if self.__class__ == PropertyAffordance:
            result = PropertyAffordance()
        elif self.__class__ == ActionAffordance:
            result = ActionAffordance()
        elif self.__class__ == EventAffordance:
            result = EventAffordance()
        memo[id(self)] = result
        for k, v in self.__dict__.items():
            if k not in ("_owner", "_thing_cls", "_objekt"):
                setattr(result, k, copy.deepcopy(v, memo))
        return result

    def __getstate__(self):
        state = self.__dict__.copy()
        # Remove possibly unpicklable entries
        if "_owner" in state:
            del state["_owner"]
        if "_thing_cls" in state:
            del state["_thing_cls"]
        if "_objekt" in state:
            del state["_objekt"]
        return state


class PropertyAffordance(DataSchema, InteractionAffordance):
    """
    Implements property affordance schema from `Property` descriptor object.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#propertyaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    observable: Optional[bool] = None

    def __init__(self):
        super().__init__()

    @property
    def what(self) -> Enum:
        return ResourceTypes.PROPERTY

    def build(self) -> None:
        property = self.objekt
        self.ds_build_from_property(property)
        if property.observable:
            self.observable = property.observable

    @classmethod
    def generate(cls, property, owner=None):
        if not isinstance(property, Property):
            raise TypeError(f"property must be instance of Property, given type {type(property)}")
        affordance = PropertyAffordance()
        affordance.owner = owner
        affordance.objekt = property
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance


class ActionAffordance(InteractionAffordance):
    """
    creates action affordance schema from actions (or methods).

    [Schema](https://www.w3.org/TR/wot-thing-description11/#actionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    input: JSON = None
    output: JSON = None
    safe: bool = None
    idempotent: bool = None
    synchronous: bool = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):
        return ResourceTypes.ACTION

    def build(self) -> None:
        action = self.objekt  # type: Action
        if action.obj.__doc__:
            title = get_summary(action.obj.__doc__)
            description = self.format_doc(action.obj.__doc__)
            if title and not description.startswith(title):
                self.title = title
                self.description = description
            else:
                self.description = description
        if action.execution_info.argument_schema:
            if isinstance(action.execution_info.argument_schema, dict):
                self.input = action.execution_info.argument_schema
            elif issubklass(action.execution_info.argument_schema, (BaseModel, RootModel)):
                self.input = type_to_dataschema(action.execution_info.argument_schema)
            else:
                raise ValueError(
                    f"unknown schema definition for action input, given type: {type(action.execution_info.argument_schema)}"
                )
        if action.execution_info.return_value_schema:
            if isinstance(action.execution_info.return_value_schema, dict):
                self.output = action.execution_info.return_value_schema
            elif issubklass(action.execution_info.return_value_schema, (BaseModel, RootModel)):
                self.output = type_to_dataschema(action.execution_info.return_value_schema)
            else:
                raise ValueError(
                    f"unknown schema definition for action output, given type: {type(action.execution_info.return_value_schema)}"
                )
        if (
            not (
                hasattr(self.owner, "state_machine")
                and self.owner.state_machine is not None
                and self.owner.state_machine.contains_object(action)
            )
            and action.execution_info.idempotent
        ):
            self.idempotent = action.execution_info.idempotent
        if action.execution_info.synchronous:
            self.synchronous = action.execution_info.synchronous
        if action.execution_info.safe:
            self.safe = action.execution_info.safe

    @classmethod
    def generate(cls, action: Action, owner, **kwargs) -> "ActionAffordance":
        if not isinstance(action, Action):
            raise TypeError(f"action must be instance of Action, given type {type(action)}")
        affordance = ActionAffordance()
        affordance.owner = owner
        affordance.objekt = action
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance


class EventAffordance(InteractionAffordance):
    """
    creates event affordance schema from events.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#eventaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    subscription: str = None
    data: JSON = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):
        return ResourceTypes.EVENT

    def build(self) -> None:
        event = self.objekt  # type: Event
        if event.__doc__:
            title = get_summary(event.doc)
            description = self.format_doc(event.doc)
            if title and not description.startswith(title):
                self.title = title
                self.description = description
            else:
                self.description = description
        if event.schema:
            if isinstance(event.schema, dict):
                self.data = event.schema
            elif issubklass(event.schema, (BaseModel, RootModel)):
                self.data = type_to_dataschema(event.schema)
            else:
                raise ValueError(f"unknown schema definition for event data, given type: {type(event.schema)}")

    @classmethod
    def generate(cls, event: Event, owner, **kwargs) -> "EventAffordance":
        if not isinstance(event, Event):
            raise TypeError(f"event must be instance of Event, given type {type(event)}")
        affordance = EventAffordance()
        affordance.owner = owner
        affordance.objekt = event
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance
