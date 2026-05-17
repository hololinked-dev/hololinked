"""Implementation of Interaction Affordances."""

from __future__ import annotations

import copy

from enum import Enum
from typing import Any, Callable, ClassVar, Optional, Self, cast  # noqa: F401

from pydantic import BaseModel, ConfigDict, RootModel

from hololinked.constants import JSON, ResourceTypes
from hololinked.core.interfaces import (
    ActionMetadata,
    EventMetadata,
    InteractionMetadata,
    PropertyMetadata,
)
from hololinked.td.base import WoTSchema
from hololinked.td.data_schema import DataSchema
from hololinked.td.forms import Form
from hololinked.td.pydantic_extensions import type_to_dataschema
from hololinked.td.utils import get_summary
from hololinked.utils import issubklass


from hololinked.core.actions import Action  # isort: skip
from hololinked.core.events import Event  # isort: skip
from hololinked.core.property import Property  # isort: skip
from hololinked.core.thing import Thing, ThingMeta  # isort: skip


class InteractionAffordance(WoTSchema, InteractionMetadata):
    """
    Implements schema fields common to all interaction affordances, property, action or event.

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

    @property
    def owner(self) -> Thing:
        """
        Owning `Thing` instance or `Thing` class of the interaction affordance.

        Depending on how this object was created, returns either an instance or a class.

        Raises
        ------
        AttributeError
            If the owner is not set, which means this affordance is not properly bound to a `Thing`
            instance or class.
        """
        if self._owner is None:
            raise AttributeError("owner is not set for this affordance")
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
        """
        Object instance of the interaction affordance, instance of `Property`, `Action` or `Event`.

        Raises
        ------
        AttributeError
            If the object is not set, which means this affordance is not properly bound to a
            `Property`, `Action` or `Event` instance.
        """
        if self._objekt is None:
            raise AttributeError("Metadata bound to unknown object (property, action or event).")
        return self._objekt

    @objekt.setter
    def objekt(self, value: Property | Action | Event) -> None:
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

    def retrieve_form(self, op: str, default: Any = None) -> Form:
        """
        Retrieve form for a certain operation, return default if not found.

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
        Retrieve and remove form for a certain operation, return default if not found.

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
    def from_metadata(cls, name: str, metadata: dict[str, Any]) -> Self:
        """
        Populate the schema from the TD and return it as an instance of this class.

        You need to supply both the TD and the name of the affordance, because the affordance definition in the TD
        does not include its name and determine its type.

        Parameters
        ----------
        name: str
            name of the interaction affordance used as key in the TD
        metadata: dict[str, Any]
            Thing Description JSON dictionary (the entire one, not just the component of the affordance)

        Returns
        -------
        PropertyAffordance | ActionAffordance | EventAffordance
            Instance of this class with the schema fields populated from the TD.

        Raises
        ------
        ValueError
            If the affordance type cannot be determined from the TD.
        """
        if cls == PropertyAffordance:
            affordance_name = "properties"
        elif cls == ActionAffordance:
            affordance_name = "actions"
        elif cls == EventAffordance:
            affordance_name = "events"
        else:
            raise ValueError(f"unknown affordance type - {cls}, cannot create object from TD")
        affordance_json = metadata[affordance_name][name]  # type: dict[str, JSON]
        affordance = cls()
        for field in cls.model_fields:
            if field in affordance_json:
                if field == "forms":
                    affordance.forms = [Form.from_TD(form) for form in affordance_json[field]]
                else:
                    setattr(affordance, field, affordance_json[field])
        affordance._name = name
        affordance._thing_id = metadata["id"]
        return affordance

    @classmethod
    def from_TD(self, name: str, TD: JSON) -> Self:
        """
        Populate the schema from the TD and return it as an instance of this class.

        You need to supply both the TD and the name of the affordance, because the affordance definition in the TD
        does not include its name and determine its type.

        Parameters
        ----------
        name: str
            name of the interaction affordance used as key in the TD
        TD: JSON
            Thing Description JSON dictionary (the entire one, not just the component of the affordance)

        Returns
        -------
        PropertyAffordance | ActionAffordance | EventAffordance
            Instance of this class with the schema fields populated from the TD.

        Raises
        ------
        ValueError
            If the affordance type cannot be determined from the TD.
        """
        return self.from_metadata(name, TD)

    @classmethod
    def register_descriptor(
        cls,
        descriptor: Property | Action | Event,
        schema_generator: type[InteractionAffordance] | type[InteractionMetadata],
    ) -> None:
        """
        Register a custom schema generator for a descriptor.

        Parameters
        ----------
        descriptor: Property | Action | Event
            The descriptor class
        schema_generator: `InteractionAffordance`
            `InteractionAffordance` subclass that implements the custom schema generation logic for the descriptor.
            Either override the `generate()` method or the `build()` method.

        Raises
        ------
        TypeError
            If the descriptor is not an instance of `Property`, `Action` or `Event`, or if the schema generator is not an
            instance of `InteractionAffordance`.
        """
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

    def __deepcopy__(self, memo):  # noqa: D105
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

    def json(self) -> dict[str, Any]:
        """
        Return the JSON representation.

        Returns
        -------
        dict[str, Any]
            JSON representation
        """
        return WoTSchema.json(self)


class PropertyAffordance(DataSchema, InteractionAffordance, PropertyMetadata):
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
    def what(self) -> Enum:  # noqa: D102
        return ResourceTypes.PROPERTY

    def build(self) -> None:  # noqa: D102
        property = cast(Property, self.objekt)
        self.ds_build_from_property(property)
        if property.observable:
            self.observable = property.observable

    @classmethod
    def generate(cls, property: Property, owner: Thing | ThingMeta):  # noqa: D102
        if not isinstance(property, Property):
            raise TypeError(f"property must be instance of Property, given type {type(property)}")
        affordance = PropertyAffordance()
        affordance.owner = owner
        affordance.objekt = property
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance


class ActionAffordance(InteractionAffordance, ActionMetadata):
    """
    creates action affordance schema from actions (or methods).

    [Schema](https://www.w3.org/TR/wot-thing-description11/#actionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    input: Optional[JSON] = None
    output: Optional[JSON] = None
    safe: Optional[bool] = None
    idempotent: Optional[bool] = None
    synchronous: Optional[bool] = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):  # noqa: D102
        return ResourceTypes.ACTION

    def build(self) -> None:  # noqa: D102
        action = cast(Action, self.objekt)
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
    def generate(cls, action: Action, owner: Thing | ThingMeta, **kwargs) -> "ActionAffordance":  # noqa: D102
        if not isinstance(action, Action):
            raise TypeError(f"action must be instance of Action, given type {type(action)}")
        affordance = ActionAffordance()
        affordance.owner = owner
        affordance.objekt = action
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance


class EventAffordance(InteractionAffordance, EventMetadata):
    """
    creates event affordance schema from events.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#eventaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    subscription: Optional[str] = None
    data: Optional[JSON] = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):  # noqa: D102
        return ResourceTypes.EVENT

    def build(self) -> None:  # noqa: D102
        event = cast(Event, self.objekt)
        doc = event.__doc__ or event.doc
        if doc:
            title = get_summary(doc)
            description = self.format_doc(doc)
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
    def generate(cls, event: Event, owner: Thing | ThingMeta, **kwargs) -> "EventAffordance":  # noqa: D102
        if not isinstance(event, Event):
            raise TypeError(f"event must be instance of Event, given type {type(event)}")
        affordance = EventAffordance()
        affordance.owner = owner
        affordance.objekt = event
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance
