"""Base Schema class for all WoT schema components."""

import inspect

from typing import Any, ClassVar

from pydantic import BaseModel


class Schema(BaseModel):
    """
    Base pydantic model for all WoT schema components (as in, parts within the schema).

    Call `model_dump` or `json` method to get the JSON representation of the schema.
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

    def json(self) -> dict[str, Any]:  # noqa
        """
        Same as model_dump.

        Overrides pydantic's base class `json()` method.

        Returns
        -------
        dict[str, Any]
            JSON representation
        """  # noqa: D401
        return self.model_dump()

    @classmethod
    def format_doc(cls, doc: str) -> str:
        """
        Strip tabs, newlines, whitespaces etc. to format the docstring nicely.

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
        doc = doc.replace("\n", "").replace("\t", " ").lstrip().rstrip()
        return doc
