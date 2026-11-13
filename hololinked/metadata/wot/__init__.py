"""W3C Web of Things based Thing Descriptions (TD) and Models (TM)."""

from hololinked.core.interfaces import MetadataFormat

from .interaction_affordance import (
    ActionAffordance,
    EventAffordance,
    InteractionAffordance,
    PropertyAffordance,
)
from .tm import ThingModel


WoTMetadata = MetadataFormat(
    thing=ThingModel,
    property=PropertyAffordance,
    action=ActionAffordance,
    event=EventAffordance,
    interaction=InteractionAffordance,
)
"""The metadata classes of the W3C Web of Things Thing Description and Thing Model."""
