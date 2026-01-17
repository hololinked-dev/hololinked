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
        """Return the JSON representation of the schema"""
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

    def json(self) -> dict[str, Any]:
        """same as model_dump"""
        return self.model_dump()

    @classmethod
    def format_doc(cls, doc: str):
        """strip tabs, newlines, whitespaces etc. to format the docstring nicely"""
        doc = inspect.cleandoc(doc)
        # Remove everything after "Parameters\n-----" if present (when using numpydoc)
        marker = "Parameters\n-----"
        idx = doc.find(marker)
        if idx != -1:
            doc = doc[:idx]
        doc = doc.replace("\n", "").replace("\t", " ").lstrip().rstrip()
        return doc
