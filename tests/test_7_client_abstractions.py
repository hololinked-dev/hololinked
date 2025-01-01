import threading
import typing
import unittest
import multiprocessing 
import logging
import zmq.asyncio

from hololinked.constants import ResourceTypes
from hololinked.server.dataklasses import ZMQResource
from hololinked.client import ObjectProxy
from hololinked.client.proxy import _Property, _Action, _Event

try:    
    from .test_3_brokers import TestBrokerMixin
    from .things.starter import run_thing_with_zmq_server
    from .things import TestThing
    from .utils import TestRunner
except ImportError:
    from test_3_brokers import TestBrokerMixin
    from things.starter import run_thing_with_zmq_server
    from things import TestThing
    from utils import TestRunner



class TestPropertyAbstraction(TestBrokerMixin):

    @classmethod    
    def setUpClass(self):
        super().setUpClass()
        print(f"test interaction affordance abstraction with {self.__name__}")
       
    
    @classmethod
    def setUpServer(self):
        pass 

    @classmethod
    def setUpThing(self):
        pass 

    @classmethod
    def startServer(self):
        multiprocessing.Process(
                            target=run_thing_with_zmq_server, 
                            args=(TestThing, self.server_id, ), 
                            kwargs=dict(done_queue=self.done_queue), 
                            daemon=True
                        ).start()
        
 
    def test_1_property_abstraction(self):
        self.client.handshake()
        test_property = _Property(
                sync_client=self.client,
                resource_info=ZMQResource(
                    what=ResourceTypes.PROPERTY,
                    class_name='TestThing',
                    id=self.server_id,
                    obj_name='test_property',
                    qualname='TestThing.test_property',
                    doc="test property",                              
                ),
                invokation_timeout=5,
                execution_timeout=5,
            )

        test_property.set(5)
        self.assertEqual(test_property.get(), 5)
        test_property.noblock_set(6)
        self.assertEqual(test_property.get(), 6)
        test_property.oneway_set(7)
        self.assertEqual(test_property.get(), 7)


    def test_2_action_abstraction(self):
        pass 


    def test_3_event_abstraction(self):
        pass
   



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
        