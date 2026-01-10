from ..utils import get_sanitized_filename_from_random_string


def get_sanitized_filename_from_thing_instance(instance, extension: str = "db") -> str:
    """Sanitize database filename from `Thing` instance"""
    return get_sanitized_filename_from_random_string(f"{instance.__class__.__name__}.{instance.id}", extension)
