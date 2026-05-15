"""Metadata Management Abstract Base Class."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional


if TYPE_CHECKING:
    from hololinked.core.thing import Thing


class Metadata:
    """A base class to generate device or Thing metadata and conversely produce a Thing instance from the metadata."""

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

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Return the JSON representation of the schema."""
        ...

    def json(self, **kwargs) -> dict[str, Any]:
        """
        Return the JSON string representation of the schema.

        Returns
        -------
        dict[str, Any]
            The JSON string representation of the schema.
        """
        return self.model_dump(**kwargs)
