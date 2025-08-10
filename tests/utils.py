import asyncio
import threading
import typing
import unittest
from faker import Faker

from hololinked.utils import get_current_async_loop



class TestResult(unittest.TextTestResult):
    """Custom test result class to format the output of test results."""

    def addSuccess(self, test):
        super().addSuccess(test)
        self.stream.write(f' {test} ✔')
        self.stream.flush()

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.stream.write(f' {test} ❌')
        self.stream.flush()

    def addError(self, test, err):
        super().addError(test, err)
        self.stream.write(f' {test} ❌ Error')
        self.stream.flush()


class TestRunner(unittest.TextTestRunner):
    """Custom test runner class to use the custom test result class."""
    resultclass = TestResult


class TestCase(unittest.TestCase):
    """Custom test case class to print some extra spaces and info about test carried out"""

    @classmethod
    def setUpClass(self):
        print(f"----------------------------------------------------------------------")
    
    @classmethod
    def tearDownClass(self):
        print(f"\n\ntear down {self.__name__}")
    
    def setUp(self):
        print() # add gaps between results printed by unit test


class AsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """Custom async test case class to print some extra spaces and info about test carried out"""

    @classmethod
    def setUpClass(self):
        print(f"----------------------------------------------------------------------")

    @classmethod
    def tearDownClass(self):
        print(f"\n\ntear down {self.__name__}")

    async def asyncSetUp(self):
        loop = asyncio.get_running_loop()
        loop.set_debug(False)
      
    def setUp(self):
        print() # add gaps between results printed by unit test
    
  



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

fake = TrackingFaker() # type: Faker

