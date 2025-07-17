import inspect
from typing import ClassVar, Optional
import typing
from pydantic import BaseModel


class Schema(BaseModel):
    """
    Base dataclass for all WoT schema; Implements a custom asdict method which replaces dataclasses' asdict 
    utility function
    """

    skip_keys: ClassVar = [] # override this to skip some dataclass attributes in the schema

    def json(self) -> dict[str, typing.Any]:
        """Return the JSON representation of the schema"""
        return self.model_dump(
                        mode="json", 
                        by_alias=True, 
                        exclude_unset=True, 
                        exclude=[
                            "instance", 
                            "skip_properties", 
                            "skip_actions",  
                            "skip_events", 
                            "instance", 
                            "ignore_errors",
                            "allow_loose_schema"
                        ]
                    )

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
        doc = doc.replace('\n', ' ')
        doc = doc.replace('\t', ' ')
        doc = doc.lstrip().rstrip()
        return doc

