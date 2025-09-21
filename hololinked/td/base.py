import inspect
import typing
from typing import ClassVar
from pydantic import BaseModel


class Schema(BaseModel):
    """
    Base dataclass for all WoT schema; Implements a custom asdict method which replaces dataclasses' asdict
    utility function
    """

    skip_keys: ClassVar = []  # override this to skip some dataclass attributes in the schema

    def model_dump(self, **kwargs) -> dict[str, typing.Any]:
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

    def json(self) -> dict[str, typing.Any]:
        """same as model_dump"""
        return self.model_dump()

    @classmethod
    def format_doc(cls, doc: str):
        """strip tabs, newlines, whitespaces etc. to format the docstring nicely"""
        # doc_as_list = doc.split('\n')
        # final_doc = []
        # for index, line in enumerate(doc_as_list):
        #     line = line.lstrip('\n').rstrip('\n')
        #     line = line.lstrip('\t').rstrip('\t')
        #     line = line.lstrip('\n').rstrip('\n')
        #     line = line.lstrip().rstrip()
        #     if index > 0:
        #         line = ' ' + line # add space to left in case of new line
        #     final_doc.append(line)
        # final_doc = ''.join(final_doc)
        doc = inspect.cleandoc(doc)
        # Remove everything after "Parameters\n-----" if present (when using numpydoc)
        marker = "Parameters\n-----"
        idx = doc.find(marker)
        if idx != -1:
            doc = doc[:idx]
        doc = doc.replace("\n", " ")
        doc = doc.replace("\t", " ")
        doc = doc.lstrip().rstrip()
        return doc
