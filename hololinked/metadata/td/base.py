"""Base Schema class for all WoT schema components."""

from __future__ import annotations

import inspect
import re

from typing import Any, ClassVar

from pydantic import BaseModel


class WoTSchema(BaseModel):
    """
    Base pydantic model for all WoT schema components (as in, parts within the schema).

    Call `model_dump` or `json` method to get the JSON representation of the schema (or the JSON Schema).
    """

    skip_keys: ClassVar = []  # override this to skip some dataclass attributes in the schema

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """
        Return the JSON representation of the schema.

        Returns
        -------
        dict[str, Any]
            JSON representation
        """
        # we need to override this to work with our JSON serializer
        kwargs["mode"] = "json"
        kwargs["by_alias"] = True
        kwargs["exclude_unset"] = True
        kwargs["exclude"] = [
            "instance",
            "skip_keys",
            "skip_properties",
            "skip_actions",
            "skip_events",
            "ignore_errors",
            "allow_loose_schema",
        ]
        return super().model_dump(**kwargs)

    def json(self) -> dict[str, Any]:  # ty: ignore[invalid-method-override]
        """
        Same as model_dump.

        Overrides pydantic's base class `json()` method.

        Returns
        -------
        dict[str, Any]
            JSON representation
        """
        return self.model_dump()

    @classmethod
    def format_doc(cls, doc: str) -> str:
        """
        Format a python docstring to a normal description.

        Strip tabs, newlines, whitespaces etc. to format the docstring nicely. Parameter sections are removed,
        both numpydoc (`Parameters` underlined with dashes) and Sphinx/reST field
        lists (`:param x:`, `:returns:`, `:raises:` etc.). Lines are joined with a single space.

        Returns
        -------
        str
            Formatted docstring
        """
        doc = inspect.cleandoc(doc)
        # Remove everything after "Parameters\n-----" if present (when using numpydoc)
        marker = "Parameters\n-----"
        idx = doc.find(marker)
        if idx != -1:
            doc = doc[:idx]
        # Remove everything from the first Sphinx/reST field on (:param x:, :returns:, :raises: ...)
        # (re caches compiled patterns, so this is not recompiled on every call)
        match = re.search(
            r"^:(param|parameter|arg|argument|key|keyword|type|raises?|except|exception"
            r"|var|ivar|cvar|vartype|returns?|rtype|yields?|ytype)\b[^:\n]*:",
            doc,
            flags=re.MULTILINE,
        )
        if match:
            doc = doc[: match.start()]
        # join lines with a space and collapse tabs, indentation and blank lines into single spaces
        return " ".join(doc.split())

    @staticmethod
    def declared_fields(model: type[BaseModel], skip_subclasses: tuple[type[BaseModel], ...] = ()) -> dict[str, str]:
        """
        Collect the fields declared by a schema element and all of its subclasses.

        The subclasses are included because they may declare additional fields that should be considered
        part of the schema. For example, a dataschema for a string has more fields than a generic dataschema.

        Parameters
        ----------
        model: type[BaseModel]
            the base model
        skip_subclasses: tuple[type[BaseModel], ...], optional
            subclasses to skip

        Returns
        -------
        dict[str, str]
            key of each field in the JSON document (its alias, such as `@type`, if it has one) mapped to its
            attribute name
        """
        fields = {field.alias or name: name for name, field in model.model_fields.items()}
        for subclass in model.__subclasses__():
            if issubclass(subclass, skip_subclasses):
                continue
            fields.update(WoTSchema.declared_fields(subclass, skip_subclasses=skip_subclasses))
        return fields
