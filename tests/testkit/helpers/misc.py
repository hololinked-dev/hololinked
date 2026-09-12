import threading
import typing

from faker import Faker


def print_lingering_threads(exclude_daemon: bool = True):
    """
    debugging helper function that prints the names and IDs of all alive threads,
    excluding daemon threads if specified.
    """
    alive_threads = threading.enumerate()
    if exclude_daemon:
        alive_threads = [t for t in alive_threads if not t.daemon]

    for thread in alive_threads:
        print(f"Thread Name: {thread.name}, Thread ID: {thread.ident}, Is Alive: {thread.is_alive()}")


class TrackingFaker:
    """A wrapper around Faker to track the last generated value."""

    def __init__(self, *args, **kwargs):
        self.gen = Faker(*args, **kwargs)
        self.last = None

    def __getattr__(self, name) -> typing.Any:
        orig = getattr(self.gen, name)
        if callable(orig):

            def wrapped(*args, **kwargs):
                result = orig(*args, **kwargs)
                self.last = result
                return result

            return wrapped
        return orig


fake = TrackingFaker()  # type: Faker
