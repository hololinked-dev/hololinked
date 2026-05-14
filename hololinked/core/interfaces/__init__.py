"""
Interface classes for dependencies or features that are not part of the main logic.

Follows Hexagonal Architecture.
"""

# TODO once all items have base classes, dont use relative imports.
from .schema_validators import BaseSchemaValidator as BaseSchemaValidator
from .serializer import BaseSerializer as BaseSerializer
