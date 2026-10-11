"""utility functions for the TD module."""

from __future__ import annotations

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


def uses_thing_model_extensions(value: Any) -> bool:
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
        return "tm:ref" in value or any(uses_thing_model_extensions(item) for item in [*value, *value.values()])
    if isinstance(value, list):
        return any(uses_thing_model_extensions(item) for item in value)
    return isinstance(value, str) and "{{" in value
