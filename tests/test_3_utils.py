
import unittest

from pydantic import BaseModel
from hololinked.utils import input_model_from_signature
try:
    from .utils import TestCase, TestRunner
except ImportError:
    from utils import TestCase, TestRunner
  



class TestUtils(TestCase):
    

    def test_1_pydantic_input_model_generator(self):
        
        def func(a: int, b: int) -> int:
            return a + b
        
        self.assertIsInstance(input_model_from_signature(func), BaseModel)


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
