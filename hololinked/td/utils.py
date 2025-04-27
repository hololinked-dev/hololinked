from typing import Any, Optional

def get_summary(obj: Any) -> Optional[str]:
    """Return the first line of the dosctring of an object

    :param obj: Any Python object
    :returns: str: First line of object docstring

    """
    docs = obj.__doc__
    if docs:
        return docs.partition("\n")[0].strip()
    else:
        return None


