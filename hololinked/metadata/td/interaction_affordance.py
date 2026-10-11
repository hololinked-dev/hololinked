"""Implementation of Interaction Affordances."""

from __future__ import annotations

import copy
import inspect
import warnings

from collections.abc import Callable
from enum import Enum
from inspect import Parameter
from typing import Any, ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, Field, RootModel

from hololinked import SchemaValidators
from hololinked.constants import JSON, ResourceTypes
from hololinked.core.interfaces import (
    ActionMetadata,
    BaseSchemaValidator,
    EventMetadata,
    InteractionMetadata,
    PropertyMetadata,
)
from hololinked.metadata.td.base import WoTSchema
from hololinked.metadata.td.data_schema import DataSchema
from hololinked.metadata.td.forms import Form
from hololinked.metadata.td.pydantic_extensions import dataschema_to_model, type_to_dataschema
from hololinked.metadata.td.utils import get_summary
from hololinked.schema_validators.pydantic_model import PydanticSchemaValidator
from hololinked.utils import issubklass


from hololinked.core.actions import Action, action  # isort: skip
from hololinked.core.events import Event  # isort: skip
from hololinked.core.property import Property  # isort: skip
from hololinked.core.thing import Thing, ThingMeta  # isort: skip


class InteractionAffordance(WoTSchema, InteractionMetadata):
    """
    Implements schema fields common to all interaction affordances, property, action or event.

    [Specification Definitions](https://www.w3.org/TR/wot-thing-description11/#interactionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    title: str | None = None
    titles: dict[str, str] | None = None
    description: str | None = None
    descriptions: dict[str, str] | None = None
    forms: list[Form] | None = None
    uriVariables: dict[str, JSON] | None = None
    semantic_type: str | list[str] | None = Field(default=None, alias="@type")

    _custom_metadata_generators: ClassVar = dict()
    model_config = ConfigDict(extra="allow")

    @property
    def owner(self) -> Thing:
        """
        Owning `Thing` instance or `Thing` class of the interaction affordance.

        Depending on how this object was created, returns either an instance or a class.

        Raises
        ------
        AttributeError
            If the owner is not set, which means this interaction is not properly bound to a `Thing`
            instance or class. Dont explicitly instantiate this class without the context of a `Thing` instance
            or class, or at least dont prematurely access this attribute.
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
            If the metadata is not bound to any interaction object.
            Use `Thing<instance>.<property>.to_metadata()` only method to generate this metadata
            from a property object or similarly for action and event.
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
        fields = {field.alias or name: name for name, field in cls.model_fields.items()}
        if cls is PropertyAffordance:
            fields.update(WoTSchema.declared_fields(DataSchema))
        affordance = cls()
        for key, value in affordance_json.items():
            if key == "forms":
                affordance.forms = [Form.from_TD(form) for form in value]
            elif key in fields:
                setattr(affordance, fields[key], value)
        affordance._name = name
        affordance._thing_id = metadata.get("id")  # a Thing Model has no id
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
        metadata_generator: type[InteractionAffordance | InteractionMetadata],
    ) -> None:
        """
        Register a custom schema generator for a descriptor.

        Parameters
        ----------
        descriptor: Property | Action | Event
            The descriptor class
        metadata_generator: `InteractionAffordance`
            `InteractionAffordance` subclass that implements the custom schema generation logic for the descriptor.
            Either override the `from_descriptor()` method or the `build()` method.

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
        if not isinstance(metadata_generator, InteractionAffordance):
            raise TypeError(
                "metadata generator for Property must be subclass of PropertyAfforance. "
                + f"Given type {type(metadata_generator)}"
            )
        InteractionAffordance._custom_metadata_generators[descriptor] = metadata_generator

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
    observable: bool | None = None

    def __init__(self):
        super().__init__()

    @property
    def what(self) -> Enum:  # noqa: D102
        return ResourceTypes.PROPERTY

    @property
    def event_unique_identifier(self) -> str:
        """Unique identifier for the change event of an observable property."""
        return f"{self.thing_id}/{self.name}_change_event"

    def build(self) -> None:  # noqa: D102
        property = cast(Property, self.objekt)
        self.ds_build_from_property(property)
        if property.observable:
            self.observable = property.observable

    @classmethod
    def from_descriptor(cls, property: Property, owner: Thing | ThingMeta) -> PropertyAffordance:  # noqa: D102
        if not isinstance(property, Property):
            raise TypeError(f"property must be instance of Property, given type {type(property)}")
        affordance = PropertyAffordance()
        affordance.owner = owner
        affordance.objekt = property
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance

    def to_descriptor(
        self,
        fget: Callable | None = None,
        fset: Callable | None = None,
        schema_validator: str = "pydantic",
    ) -> Property:
        """
        Create the `Property` this affordance describes.

        Parameters
        ----------
        fget: Callable, optional
            read handler, the value is stored on the `Thing` instance if not given
        fset: Callable, optional
            write handler, receives the validated value
        schema_validator: str
            name the validator of the value is registered under with `SchemaValidators`

        Returns
        -------
        Property
            the descriptor, not yet assigned to a class

        Raises
        ------
        ValueError
            if the value is stored (no `fget`) but the affordance gives no starting value, neither a `default`
            nor a `null` option
        """
        affordance = self.json()
        keywords = WoTSchema.declared_fields(DataSchema)
        # a property-level const makes the property constant instead of constraining writes
        data_schema = {key: value for key, value in affordance.items() if key in keywords and key != "const"}
        # a null option allows None, the remaining options are the schema of the value
        options = data_schema.pop("oneOf", [])
        nullable = any(option.get("type") == "null" for option in options)
        options = [option for option in options if option.get("type") != "null"]
        if len(options) == 1:
            data_schema.update(options[0])
        elif options:
            data_schema["oneOf"] = options
        default = affordance.get("default", affordance.get("const"))
        constant = "const" in affordance
        if fget is None and default is None and not (nullable or constant):
            raise ValueError(f"property {self.name} stores its value, it needs a default or a null option in its schema")
        if self.writeOnly:
            warnings.warn(f"writeOnly of property {self.name} is not supported and is ignored", UserWarning, stacklevel=2)
        model, validator = (
            schema_for_validator(data_schema, f"{self.name}_value", schema_validator) if data_schema else (None, None)
        )
        _property = Property(
            default=default,
            doc=self.description,
            label=self.title,
            constant=constant,
            readonly=bool(self.readOnly),
            allow_None=nullable,
            observable=bool(self.observable),
            model=model,
            fget=fget,
            fset=fset,
            deepcopy_default=isinstance(default, (dict, list)),
            metadata={"unit": self.unit} if self.unit is not None else None,
        )
        _property._validator = validator
        return _property


class ActionAffordance(InteractionAffordance, ActionMetadata):
    """
    creates action affordance schema from actions (or methods).

    [Schema](https://www.w3.org/TR/wot-thing-description11/#actionaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    input: JSON | None = None
    output: JSON | None = None
    safe: bool | None = None
    idempotent: bool | None = None
    synchronous: bool | None = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):  # noqa: D102
        return ResourceTypes.ACTION

    def build(self) -> None:  # noqa: D102
        action = cast(Action, self.objekt)
        doc = action.doc or action.obj.__doc__
        if doc:
            title = get_summary(doc)
            description = self.format_doc(doc)
            if title and not description.startswith(title):
                self.title = title
                self.description = description
            else:
                self.description = description
        if action.argument_schema:
            if isinstance(action.argument_schema, dict):
                self.input = action.argument_schema
            elif issubklass(action.argument_schema, (BaseModel, RootModel)):
                self.input = type_to_dataschema(action.argument_schema)
            else:
                raise ValueError(
                    f"unknown schema definition for action input, given type: {type(action.argument_schema)}"
                )
        if action.return_value_schema:
            if isinstance(action.return_value_schema, dict):
                self.output = action.return_value_schema
            elif issubklass(action.return_value_schema, (BaseModel, RootModel)):
                self.output = type_to_dataschema(action.return_value_schema)
            else:
                raise ValueError(
                    f"unknown schema definition for action output, given type: {type(action.return_value_schema)}"
                )
        if (
            not (
                hasattr(self.owner, "state_machine")
                and self.owner.state_machine is not None
                and self.owner.state_machine.contains_object(action)
            )
            and action.idempotent
        ):
            self.idempotent = action.idempotent
        if action.synchronous:
            self.synchronous = action.synchronous
        if action.safe:
            self.safe = action.safe

    @classmethod
    def from_descriptor(cls, action: Action, owner: Thing | ThingMeta, **kwargs) -> ActionAffordance:  # noqa: D102
        if not isinstance(action, Action):
            raise TypeError(f"action must be instance of Action, given type {type(action)}")
        affordance = ActionAffordance()
        affordance.owner = owner
        affordance.objekt = action
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance

    def to_descriptor(self, obj: Callable, schema_validator: str = "pydantic") -> Action:
        """
        Create the `Action` this affordance describes, invoking the given handler.

        Parameters
        ----------
        obj: Callable
            the handler, a sync or async method
        schema_validator: str
            name the validator of the input is registered under with `SchemaValidators`

        Returns
        -------
        Action
            the descriptor, not yet assigned to a class

        Raises
        ------
        TypeError
            if the parameters of the handler do not match the input, listing every mismatch
        """
        input_schema, validator = None, None
        if self.input:
            mismatches = input_signature_mismatches(obj, self.input)
            if mismatches:
                raise TypeError(
                    f"{getattr(obj, '__name__', obj)} does not match the input of action {self.name}: "
                    + "; ".join(mismatches)
                )
            input_schema, validator = schema_for_validator(self.input, f"{self.name}_input", schema_validator)
        output_schema = None
        if self.output:
            output_schema, _ = schema_for_validator(self.output, f"{self.name}_output", schema_validator)
        # flags absent from the TD keep the defaults of action(), synchronous=True decides the scheduling
        flags = {key: getattr(self, key) for key in ("safe", "idempotent", "synchronous") if getattr(self, key) is not None}
        _action = action(
            input_schema=input_schema,
            output_schema=output_schema,
            doc="\n\n".join(text for text in (self.title, self.description) if text) or None,
            **flags,
        )(obj)
        _action._schema_validator = validator
        return _action


class EventAffordance(InteractionAffordance, EventMetadata):
    """
    creates event affordance schema from events.

    [Schema](https://www.w3.org/TR/wot-thing-description11/#eventaffordance) <br>
    [UML Diagram](https://docs.hololinked.dev/UML/PDF/InteractionAffordance.pdf) <br>
    """

    # [Supported Fields]() <br>
    subscription: str | None = None
    data: JSON | None = None

    def __init__(self):
        super().__init__()

    @property
    def what(self):  # noqa: D102
        return ResourceTypes.EVENT

    @property
    def event_unique_identifier(self) -> str:
        """Identifier this event is published under, as `<thing id>/<name>`."""
        return f"{self.thing_id}/{self.name}"

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
    def from_descriptor(cls, event: Event, owner: Thing | ThingMeta, **kwargs) -> EventAffordance:  # noqa: D102
        if not isinstance(event, Event):
            raise TypeError(f"event must be instance of Event, given type {type(event)}")
        affordance = EventAffordance()
        affordance.owner = owner
        affordance.objekt = event
        affordance.build()
        affordance.build_non_compliant_metadata()
        return affordance

    def to_descriptor(self, schema_validator: str = "pydantic") -> Event:
        """
        Create the `Event` this affordance describes.

        Parameters
        ----------
        schema_validator: str
            name of the validator, registered with `SchemaValidators`, the event data schema is converted for.
            The data is not validated on push, so no validator is preset.

        Returns
        -------
        Event
            the descriptor, not yet assigned to a class
        """
        schema = None
        if self.data:
            schema, _ = schema_for_validator(self.data, f"{self.name}_data", schema_validator)
        return Event(doc=self.description, label=self.title, schema=schema)


def schema_for_validator(
    schema: dict[str, Any],
    name: str,
    schema_validator: str = "pydantic",
) -> tuple[Any, BaseSchemaValidator | None]:
    """
    Convert a DataSchema of a Thing Description into the schema a validator takes.

    Parameters
    ----------
    schema: dict[str, Any]
        the DataSchema
    name: str
        name of the model generated for a pydantic validator, for example `<action>_input`
    schema_validator: str
        name the validator is registered under with `SchemaValidators`

    Returns
    -------
    tuple[Any, BaseSchemaValidator | None]
        the schema for the descriptor, and the validator instance to preset on it. A pydantic model is left to the
        type based lookup, since a `Property` validates by calling the model rather than through a validator.
    """
    validator = getattr(SchemaValidators, schema_validator)
    if issubklass(validator, PydanticSchemaValidator):
        return dataschema_to_model(schema, name), None
    # preset, otherwise SchemaValidators.for_schema() picks the json_schema validator for any dict
    return schema, validator(schema)


def input_signature_mismatches(func: Callable, schema: dict[str, Any]) -> list[str]:
    """
    List how the parameters of an action handler do not match the input DataSchema of the action.

    The first positional parameter (`self`) and a keyword-only `request` parameter are not part of the input.
    An object input arrives as keyword arguments, any other input as a single value.

    Parameters
    ----------
    func: Callable
        the action handler
    schema: dict[str, Any]
        the input DataSchema

    Returns
    -------
    list[str]
        every mismatch found, empty if the handler matches
    """
    parameters = [
        parameter
        for parameter in list(inspect.signature(func).parameters.values())[1:]
        if not (parameter.kind is Parameter.KEYWORD_ONLY and parameter.name == "request")
    ]
    if not (schema.get("type") == "object" or "properties" in schema):
        positional = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD, Parameter.VAR_POSITIONAL)
        if len(parameters) != 1 or parameters[0].kind not in positional:
            return ["the input is a single value, so the handler takes exactly one positional parameter"]
        return []
    properties = schema.get("properties", {})
    takes_kwargs = any(parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters)
    keywords = {
        parameter.name
        for parameter in parameters
        if parameter.kind in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
    }
    mismatches = [
        f"parameter {parameter.name!r} is positional-only, an object input is given by keyword"
        for parameter in parameters
        if parameter.kind is Parameter.POSITIONAL_ONLY
    ]
    mismatches += [
        f"required parameter {parameter.name!r} is not an input property"
        for parameter in parameters
        if parameter.name in keywords and parameter.default is Parameter.empty and parameter.name not in properties
    ]
    if not takes_kwargs:
        mismatches += [
            f"input property {name!r} is not a parameter"
            for name in sorted(set(properties) | set(schema.get("required", [])))
            if name not in keywords
        ]
    additional = schema.get("additionalProperties", None)
    if additional is not None and additional is not False and not takes_kwargs:
        mismatches.append("the input allows additional properties, so the handler takes **kwargs")
    return mismatches
