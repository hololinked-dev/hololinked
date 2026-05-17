"""Metadata Management Abstract Base Class."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict

from hololinked.constants import JSON, ResourceTypes


if TYPE_CHECKING:
    from hololinked.core.actions import Action
    from hololinked.core.events import Event
    from hololinked.core.property import Property
    from hololinked.core.thing import Thing, ThingMeta


class Metadata(BaseModel):
    """A base class to generate device or Thing metadata and conversely produce a Thing instance from the metadata."""

    model_config = ConfigDict(extra="allow")

    def __init__(
        self,
        thing: Thing | None = None,
        ignore_errors: bool = False,
        skip_names: Optional[list[str]] = [],
    ) -> None:
        """
        Initialize the Metadata handler.

        Parameters
        ----------
        thing: Thing | None, optional
            The `Thing` instance for which the metadata is being generated. None, if the Thing instance is to be
            produced from the metadata.
        ignore_errors: bool, optional
            Whether to ignore errors during metadata generation. Defaults to False.
        skip_names: list[str], optional
            List of property, action, or event names to skip when generating the metadata. Defaults to an empty list.
        """
        super().__init__()
        self.thing = thing
        self.ignore_errors = ignore_errors
        self.skip_names = skip_names or []

    def generate(self) -> Metadata:
        """Populate the metadata."""
        raise NotImplementedError("implement generate() in subclass")

    def produce(self) -> Thing:
        """Produce a Thing instance from the metadata."""
        raise NotImplementedError("This will be implemented in a future release for an API first approach")

    skip_properties: list[str]
    """list of default property names to skip when generating the metadata."""

    skip_actions: list[str]
    """list of default action names to skip when generating the metadata."""

    skip_events: list[str]
    """list of default event names to skip when generating the metadata."""

    def add_interactions(self) -> None:
        """Add interaction (affordances) to the metadata."""
        ...

    def json(self, **kwargs) -> dict[str, Any]:
        """
        Return the JSON string representation.

        Returns
        -------
        dict[str, Any]
            The JSON string representation.
        """
        return self.model_dump(**kwargs)


class InteractionMetadata(BaseModel):
    """
    Generate metadata for a property, action or event.

    A property, action or event is called as an interaction affordance, and the metadata generated for it
    is called as interaction metadata. This base class defines metadata methods common to all of properties,
    actions or events, and could be common to different metadata or device description standards.
    """

    _custom_schema_generators: dict

    def __init__(self):
        super().__init__()
        self._name = None
        self._objekt = None
        self._thing_id = None
        self._thing_cls = None
        self._owner = None

    @property
    def what(self) -> Enum:
        """Whether it is a property, action or event."""
        raise NotImplementedError("Unknown interaction (property, action, or event?) implement in subclass")

    @property
    def owner(self) -> Thing:
        """
        Owning `Thing` instance or `Thing` class of the interaction.

        Depending on how this object was created, returns either an instance or a class.
        """
        return self._owner

    @property
    def owner_cls(self) -> ThingMeta:
        """Return the owning `Thing` class of the interaction."""
        return self._thing_cls

    @property
    def objekt(self) -> Property | Action | Event:
        """Object instance of the interaction, instance of `Property`, `Action` or `Event`."""
        return self._objekt

    @property
    def name(self) -> str:
        """Name of the interaction that could be used as a key in the metadata."""
        return self._name

    @property
    def thing_id(self) -> str:
        """ID of the `Thing` instance owning the interaction, if available, otherwise None."""
        return self._thing_id

    @property
    def thing_cls(self) -> ThingMeta:
        """`Thing` class owning the interaction."""
        return self._thing_cls

    def build(self) -> None:
        """Populate the fields of the metadata for the specific interaction."""
        raise NotImplementedError("build must be implemented in subclass of InteractionMetadata")

    @classmethod
    def generate(
        cls,
        interaction: Property | Action | Event,
        owner: Thing | ThingMeta = None,
    ) -> PropertyMetadata | ActionMetadata | EventMetadata:
        """
        Instantitate and build the metadata for the specific interaction.

        Use the `json()` method to get the JSON representation of the metadata.

        Note that this method is different from `build()` method as its supposed to be used as a classmethod
        to create an instance. Although, it internally calls `build()`, and some additional steps can be included.

        Parameters
        ----------
        interaction: Property | Action | Event
            interaction object for which the metadata is to be built
        owner: Thing | ThingMeta
            owner of the interaction

        Returns
        -------
        PropertyMetadata | ActionMetadata | EventMetadata
            Instance of this class with the metadata fields populated.
        """
        raise NotImplementedError("generate() must be implemented in subclass of InteractionMetadata")

    @classmethod
    def from_metadata(cls, name: str, metadata: JSON) -> PropertyMetadata | ActionMetadata | EventMetadata:
        """
        Populate the metadata from the provided JSON and return it as an instance of this class.

        It is assumed that the interaction is a key in the provided JSON, so one needs to supply the name.

        Parameters
        ----------
        name: str
            name of the interaction used as key in the metadata
        metadata: JSON
            metadata JSON dictionary (the entire one, not just the component of the interaction)

        Returns
        -------
        PropertyMetadata | ActionMetadata | EventMetadata
            Instance of this class.

        Raises
        ------
        ValueError
            If the interaction type cannot be determined from the metadata.
        """
        raise NotImplementedError

    @classmethod
    def register_descriptor(
        cls,
        descriptor: Property | Action | Event,
        schema_generator: InteractionMetadata,
    ) -> None:
        """
        Register a custom schema generator for a descriptor.

        Parameters
        ----------
        descriptor: Property | Action | Event
            The descriptor class
        schema_generator: InteractionMetadata
            `InteractionMetadata` subclass that implements the custom schema generation logic for the descriptor.
            Either override the `generate()` method or the `build()` method.

        Raises
        ------
        TypeError
            If the descriptor is not an instance of `Property`, `Action` or `Event`, or if the schema generator is not an
            instance of `InteractionMetadata`.
        """
        raise NotImplementedError

    def build_non_compliant_metadata(self) -> None:
        """If there is additional non standard metadata to be added, they can be added here."""
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
        raise NotImplementedError("Implement in subclass")

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

    def json(self) -> dict[str, Any]:
        """Return the JSON representation."""
        raise NotImplementedError("json() must be implemented in subclass of InteractionMetadata")


class PropertyMetadata(InteractionMetadata):
    """Implements property affordance schema from `Property` descriptor object."""

    @property
    def what(self) -> Enum:  # noqa: D102
        return ResourceTypes.PROPERTY

    @classmethod
    def generate(cls, property: Property, owner: Thing | ThingMeta = None) -> PropertyMetadata:  # noqa: D102
        raise NotImplementedError


class ActionMetadata(InteractionMetadata):
    """Implements action affordance schema from `Action` descriptor object."""

    @property
    def what(self) -> Enum:  # noqa: D102
        return ResourceTypes.ACTION

    @classmethod
    def generate(cls, action: Action, owner: Thing | ThingMeta = None) -> ActionMetadata:  # noqa: D102
        raise NotImplementedError


class EventMetadata(InteractionMetadata):
    """Implements event affordance schema from `Event` descriptor object."""

    @property
    def what(self) -> Enum:  # noqa: D102
        return ResourceTypes.EVENT

    @classmethod
    def generate(cls, event: Event, owner: Thing | ThingMeta = None) -> EventMetadata:  # noqa: D102
        raise NotImplementedError
