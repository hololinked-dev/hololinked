from typing import Optional


def get_summary(docs: str) -> Optional[str]:
    """
    Return the first line of the dosctring of an object

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
