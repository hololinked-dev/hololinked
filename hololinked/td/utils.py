from typing import Any, Optional


def get_summary(docs: str) -> Optional[str]:
    """Return the first line of the dosctring of an object

    :param obj: Any Python object
    :returns: str: First line of object docstring

    """
    if docs:
        return docs.partition("\n")[0].strip()
    else:
        return ""


def get_zmq_unique_identifier_from_event_affordance(affordance: Any) -> Optional[str]:
    """Return the unique identifier for a ZMQ object

    :param obj: Any Python object
    :returns: str: Unique identifier for the object

    """
    return f"{affordance.thing_id}/{affordance.name}"
