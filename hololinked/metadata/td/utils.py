"""utility functions for the TD module."""

from __future__ import annotations

import re

from typing import Any


def get_summary(docs: str) -> str:
    """
    Return the first line of the docstring of an object.

    Parameters
    ----------
    docs:
        The docstring of the object

    Returns
    -------
    str:
        First line of object docstring
    """
    if docs:
        return docs.partition("\n")[0].strip()
    else:
        return ""


def a_class_name_from_title_string(title: str | None) -> str:
    """
    Name of the class `produce()` makes, the title of the Thing Model as a Python identifier.

    Parameters
    ----------
    title: str | None
        title of the Thing Model

    Returns
    -------
    str
        the title in CamelCase without other characters, `ProducedThing` if nothing is left
    """
    name = "".join(part[:1].upper() + part[1:] for part in re.split(r"\W+", title or "") if part)
    return name if name.isidentifier() else f"ProducedThing{name}"


def model_spec_has_extensions(value: Any) -> bool:
    """
    Check whether a Thing Model uses `tm:ref` or `{{placeholders}}` anywhere.

    Parameters
    ----------
    value: Any
        the Thing Model JSON, or a part of it

    Returns
    -------
    bool
        True if any `tm:ref` key or string with a placeholder is found
    """
    if isinstance(value, dict):
        return "tm:ref" in value or any(model_spec_has_extensions(item) for item in [*value, *value.values()])
    if isinstance(value, list):
        return any(model_spec_has_extensions(item) for item in value)
    return isinstance(value, str) and "{{" in value
