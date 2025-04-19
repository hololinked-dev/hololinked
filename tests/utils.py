import threading
import unittest


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
    
    def setUp(self):
        print() # dont concatenate with results printed by unit test

    @classmethod
    def tearDownClass(self):
        print(f"\n\ntear down {self.__name__}")



def print_lingering_threads(exclude_daemon=True):
    alive_threads = threading.enumerate()
    if exclude_daemon:
        alive_threads = [t for t in alive_threads if not t.daemon]
    
    for thread in alive_threads:
        print(f"Thread Name: {thread.name}, Thread ID: {thread.ident}, Is Alive: {thread.is_alive()}")
