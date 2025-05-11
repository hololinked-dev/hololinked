import unittest, time, logging
from hololinked.server.http import HTTPServer
from hololinked.core.zmq.rpc_server import RPCServer # sets loop policy, TODO: move somewhere else
from hololinked.utils import get_current_async_loop

try:
    from .things import OceanOpticsSpectrometer
    from .utils import TestCase, TestRunner
except ImportError:
    from things import OceanOpticsSpectrometer
    from utils import TestCase, TestRunner



class TestHTTPServer(TestCase):


    def test_1_init_run_and_stop(self):
        """Test basic init, run and stop of the HTTP server."""

        # init, run and stop synchronously
        server = HTTPServer(log_level=logging.DEBUG)
        self.assertTrue(server.all_ok)
        # server.listen(forked=True)
        # time.sleep(3)
        # server.stop()

        # init, run and stop asynchronously
        server.listen(forked=True)
        time.sleep(3)
        get_current_async_loop().run_until_complete(server.async_stop())


    # def test_2_add_thing(self):
    #     """Test adding a thing to the HTTP server."""

    #     # init, run and stop synchronously
    #     server = HTTPServer(log_level=logging.ERROR+10)
    #     # self.assertTrue(server.all_ok)
    #     # server.listen(forked=True)
        
    #     # add a thing
    #     spectrometer = OceanOpticsSpectrometer()
    #     server.add_thing(spectrometer)
    #     self.assertIn(spectrometer, server.things)

    #     # remove the thing
    #     server.remove_thing(spectrometer)
    #     self.assertNotIn(spectrometer, server.things)

    #     get_current_async_loop().run_until_complete(server.async_stop())




def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestHTTPServer))
    return suite
        
if __name__ == '__main__':
    runner = TestRunner()
    runner.run(load_tests(unittest.TestLoader(), None, None))