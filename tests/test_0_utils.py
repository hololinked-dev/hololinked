
import unittest
import typing
from pydantic import BaseModel, ValidationError
from hololinked.utils import get_input_model_from_signature, issubklass, validate_args_kwargs
try:
    from .utils import TestCase, TestRunner
except ImportError:
    from utils import TestCase, TestRunner
  


class TestUtils(TestCase):
    

    def test_1_pydantic_input_model_generator(self):

        def func_without_args():
            return 1
        model = get_input_model_from_signature(func_without_args)
        self.assertTrue(model is None)
        
        """
        Test Sequence:
        1. Create model from function signature
        2. Check model annotations
        3. Check model fields length 
        4. Check model config
        5. Validate correct usage
        6. Always check exception strings for ValueError
        7. Use ValidationError if pydantic is supposed to raise the Error
        """

        """
        Signatures that we will validate:
        1. func_with_annotations(a: int, b: int) -> int:
        2. func_with_missing_annotations(a: int, b):
        3. func_with_no_annotations(a, b):
        4. func_with_kwargs(a: int, b: int, **kwargs):
        5. func_with_annotated_kwargs(a: int, b: int, **kwargs: typing.Dict[str, int]):
        6. func_with_args(*args):
        7. func_with_annotated_args(*args: typing.List[int]):
        8. func_with_args_and_kwargs(*args, **kwargs):
        9. func_with_annotated_args_and_kwargs(*args: typing.List[int], **kwargs: typing.Dict[str, int]):
        """

        ####################
        ##### create model from function signature
        # 1. func_with_annotations(a: int, b: int) -> int:
        def func_with_annotations(a: int, b: int) -> int:
            return a + b
        model = get_input_model_from_signature(func_with_annotations)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['a'].annotation, int)
        self.assertEqual(model.model_fields['b'].annotation, int)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config['extra'], 'forbid')
        ##### validate correct usage
        # 1. correct usage with keyword arguments
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2})
        # 2. incorrect argument types with keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1, 'b': '2'})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct usage with positional arguments
        validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=(1, '2')) 
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2, 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,), kwargs={'a': 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=('1', 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        ####################

        # 1. correct usage with keyword arguments
        # 2. incorrect argument types with keyword arguments
        # 3. missing keyword arguments
        # 4. too many keyword arguments
        # 5. correct usage with positional arguments
        # 6. incorrect argument types with positional arguments
        # 7. too many positional arguments
        # 8. missing positional arguments
        # 9. correct usage with positional and keyword arguments
        # 10. incorrect ordering with positional and keyword arguments
        # 11. additional cases of incorrect usage falling under the same categories

        ####################
        ##### create model from function signature
        # 2. func_with_missing_annotations(a: int, b):
        def func_with_missing_annotations(a: int, b):
            return a + b
        model = get_input_model_from_signature(func_with_missing_annotations)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['a'].annotation, int)
        self.assertEqual(model.model_fields['b'].annotation, typing.Any)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config['extra'], 'forbid')
        ##### validate correct usage
        # 1. correct usage
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2})
        validate_args_kwargs(model, kwargs={'a': 1, 'b': '2'})
        validate_args_kwargs(model, kwargs={'a': 2, 'b': list()})
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': '1', 'b': '2'})
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': list(), 'b': dict()})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct positional arguments
        validate_args_kwargs(model, args=(1, 2))
        validate_args_kwargs(model, args=(1, '2'))
        validate_args_kwargs(model, args=(2, list()))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=('1', '2'))
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=(list(), dict()))
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,2,3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2})
        validate_args_kwargs(model, args=(1,), kwargs={'b': '2'})
        validate_args_kwargs(model, args=(2,), kwargs={'b': list()})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,), kwargs={'a': 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=('1', 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        ####################

        ####################
        ##### create model from function signature
        # 3. func_with_no_annotations(a, b):
        def func_with_no_annotations(a, b):
            return a + b 
        model = get_input_model_from_signature(func_with_no_annotations)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['a'].annotation, typing.Any)
        self.assertEqual(model.model_fields['b'].annotation, typing.Any)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config['extra'], 'forbid')
        ##### validate correct usage
        # 1. correct usage
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2})
        validate_args_kwargs(model, kwargs={'a': 1.2, 'b': '2'})
        validate_args_kwargs(model, kwargs={'a': dict(), 'b': list()})
        # 2. incorrect argument types
        # typing.Any allows any type, so no ValidationError
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': list()})
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'b': dict()})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3})  
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct positional arguments
        validate_args_kwargs(model, args=(1, 2))
        validate_args_kwargs(model, args=(1, '2'))
        validate_args_kwargs(model, args=(dict(), list()))
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2})
        # 6. incorrect argument types with positional arguments
        # typing.Any allows any type, so no ValidationError
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,2,3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(dict(), list(), 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,))
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(dict(),))
        # 9. correct usage with positional and keyword arguments
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2})
        validate_args_kwargs(model, args=(1.1,), kwargs={'b': '2'})
        validate_args_kwargs(model, args=(dict(),), kwargs={'b': list()})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,), kwargs={'a': 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=('1', 2), kwargs={'c': 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))

        ####################
        ##### create model from function signature
        # 4. func_with_kwargs(a: int, b: int, **kwargs):
        def func_with_kwargs(a: int, b: int, **kwargs):
            return a + b
        model = get_input_model_from_signature(func_with_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['a'].annotation, int)
        self.assertEqual(model.model_fields['b'].annotation, int)
        self.assertEqual(len(model.model_fields), 3)
        self.assertEqual(model.model_config['extra'], 'forbid')
        ##### validate correct usage
        # 1. correct usage
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2})
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3})
        validate_args_kwargs(model, args=(1,2), kwargs={'c': '3'}) 
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1, 'b': '2'})
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1, 'b': '2', 'c': '3'})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1})
        # 4. too many keyword arguments
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3, 'd': 4}) # OK 
        # 5. correct positional arguments
        validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=(1, '2'))
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=('1', 2))
        # 7. too many positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1, 2, 3))        
        # 7. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,))
        # 8. correct usage with positional and keyword arguments
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2})
        validate_args_kwargs(model, args=(1,), kwargs={'b': 2, 'c': 3})
        # 9. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1,), kwargs={'a': 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2), kwargs={'a': 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            validate_args_kwargs(model, args=(1, 2), kwargs={'b': 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 10. incorrect usage with both positional and keyword arguments
        # any extra keyword argument is allowed

        ####################
        ##### create model from function signature
        # 5. func_with_annotated_kwargs(a: int, b: int, **kwargs: typing.Dict[str, int]):
        def func_with_annotated_kwargs(a: int, b: int, **kwargs: typing.Dict[str, int]):
            return a + b
        model = get_input_model_from_signature(func_with_annotated_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['a'].annotation, int)
        self.assertEqual(model.model_fields['b'].annotation, int)
        self.assertEqual(model.model_fields['kwargs'].annotation, typing.Dict[str, int])
        self.assertEqual(len(model.model_fields), 3)
        self.assertEqual(model.model_config['extra'], 'forbid')
        # 1. correct usage
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2})
        validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': 3})
        validate_args_kwargs(model, args=(1, 2), kwargs={'c': 3})
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1, 'b': '2'})
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1, 'b': 2, 'c': '3'})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, kwargs={'a': 1})
        # 4. too many keyword arguments
        # OK 
        # 5. correct positional arguments
        validate_args_kwargs(model, args=(1, 2))
        # 6. too many positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,2,3))
        # 7. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            validate_args_kwargs(model, args=(1,))
        


        # both the following are not allowed in python
        # def func_with_double_args(*args1, *args2):
        #     """syntax error"""
        #     return 
        # def func_with_double_kwargs(**kwargs1, **kwargs2):
        #     """syntax error"""
        #     return
      
        def func_with_args(*args):
            return sum(args)
        model = get_input_model_from_signature(func_with_args)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['args'].annotation, typing.Tuple)
        self.assertEqual(len(model.model_fields), 1)
        self.assertEqual(model.model_config['extra'], 'forbid')


        def func_with_annotated_args(*args: typing.List[int]):
            return sum(args)
        model = get_input_model_from_signature(func_with_annotated_args)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['args'].annotation, typing.List[int])
        self.assertEqual(len(model.model_fields), 1)
        self.assertEqual(model.model_config['extra'], 'forbid')
        # 1. correct usage
        validate_args_kwargs(model, args=(1, 2))
        validate_args_kwargs(model)
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            validate_args_kwargs(model, args=(1, '2'))
        with self.assertRaises(ValueError):
            validate_args_kwargs(model, kwargs={'a' : 1})


        def func_with_args_and_kwargs(*args, **kwargs):
            return sum(args) + sum(kwargs.values())
        model = get_input_model_from_signature(func_with_args_and_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['args'].annotation, typing.Tuple)
        self.assertEqual(model.model_fields['kwargs'].annotation, typing.Dict[str, typing.Any])
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config['extra'], 'forbid')

        def func_with_annotated_args_and_kwargs(*args: typing.List[int], **kwargs: typing.Dict[str, int]):
            return sum(args) + sum(kwargs.values())
        model = get_input_model_from_signature(func_with_annotated_args_and_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields['args'].annotation, typing.List[int])
        self.assertEqual(model.model_fields['kwargs'].annotation, typing.Dict[str, int])
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config['extra'], 'forbid')

    

if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
