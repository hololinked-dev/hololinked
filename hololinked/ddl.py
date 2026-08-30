"""
Dependency definition layer for metadata formats/device description languages.

Please delay the import of this module as much as possible.
"""

from dataclasses import dataclass

from hololinked.core.interfaces import (
    ActionMetadata,
    EventMetadata,
    InteractionMetadata,
    Metadata,
    PropertyMetadata,
)
from hololinked.metadata.td import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
    ThingModel,
)
from hololinked.utils import MappableSingleton


@dataclass
class MetadataClasses:
    """Metadata class for each core component."""

    thing: type[Metadata]
    property: type[PropertyMetadata]
    action: type[ActionMetadata]
    event: type[EventMetadata]
    interaction: type[InteractionMetadata]


class MetadataFormats(MappableSingleton):
    """Supported metadata formats."""

    wot = MetadataClasses(
        thing=ThingModel,
        property=PropertyAffordance,
        action=ActionAffordance,
        event=EventAffordance,
        interaction=InteractionAffordance,
    )

    @classmethod
    def get(cls, format: str) -> MetadataClasses:
        """
        Get the MetadataClasses for a given format.

        Returns
        -------
        MetadataClasses
            The metadata classes for the given format, containing the thing, property, action and event classes.
        """
        if format.lower() == "wot":
            return cls.wot
        raise NotImplementedError(f"Metadata format {format} is not supported.")
