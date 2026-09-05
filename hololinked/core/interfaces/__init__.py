"""
Interface classes for dependencies or features that are not part of the main logic.

Follows Hexagonal Architecture.
"""

# TODO once all items have base classes, dont use relative imports.
from hololinked.core.interfaces.configuration import BaseConfigurationRepository as BaseConfigurationRepository
from hololinked.core.interfaces.schema_validators import BaseSchemaValidator as BaseSchemaValidator
from hololinked.core.interfaces.serializer import BaseSerializer as BaseSerializer


from hololinked.core.interfaces.metadata import (  # isort: skip
    Metadata as Metadata,
    PropertyMetadata as PropertyMetadata,
    ActionMetadata as ActionMetadata,
    EventMetadata as EventMetadata,
    InteractionMetadata as InteractionMetadata,
    MetadataFormat as MetadataFormat,
)
