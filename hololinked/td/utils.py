"""utility functions for the TD module."""

from __future__ import annotations

from typing import Optional


def get_summary(docs: str) -> Optional[str]:
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
