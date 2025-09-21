import logging
import unittest

from hololinked.client import ClientFactory

try:
    from .test_11_rpc_e2e import TestRPCEndToEnd, TestRPCEndToEndAsync
    from .utils import TestRunner
    from .things import TestThing
except ImportError:
    from test_11_rpc_e2e import TestRPCEndToEnd, TestRPCEndToEndAsync
    from utils import TestRunner
    from things import TestThing


class TestZMQ_TCP(TestRPCEndToEnd):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print("Test ZMQ TCP End to End")

    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True, access_points="tcp://*:5557")
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "tcp://localhost:5557",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client


class TestZMQAsync_TCP(TestRPCEndToEndAsync):
    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True, access_points="tcp://*:6000")
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "tcp://localhost:6000",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client


class TestZMQ_INPROC(TestRPCEndToEnd):
    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True, access_points="inproc")
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "inproc",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client


class TestZMQAsync_INPROC(TestRPCEndToEndAsync):
    @classmethod
    def setUpThing(cls):
        """Set up the thing for the zmq object proxy client"""
        cls.thing = TestThing(id=cls.thing_id, log_level=logging.ERROR + 10)
        cls.thing.run_with_zmq_server(forked=True, access_points="inproc")
        cls.thing_model = cls.thing.get_thing_model(ignore_errors=True).json()

    @classmethod
    def get_client(cls):
        try:
            if cls._client is not None:
                return cls._client
            raise AttributeError()
        except AttributeError:
            cls._client = ClientFactory.zmq(
                cls.server_id,
                cls.thing_id,
                "inproc",
                log_level=logging.ERROR + 10,
                ignore_TD_errors=True,
            )
            return cls._client


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQ_TCP))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQAsync_TCP))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQ_INPROC))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestZMQAsync_INPROC))
    return suite


if __name__ == "__main__":
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))
