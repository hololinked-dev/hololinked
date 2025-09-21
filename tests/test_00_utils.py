import unittest
import typing
from pydantic import BaseModel, ValidationError

from hololinked.utils import (
    get_input_model_from_signature,
    issubklass,
    pydantic_validate_args_kwargs,
    json_schema_merge_args_to_kwargs,
)

try:
    from .utils import TestCase, TestRunner
except ImportError:
    from utils import TestCase, TestRunner


class TestUtils(TestCase):
    def test_1_pydantic_function_signature_validation(self):
        def func_without_args():
            return 1

        model = get_input_model_from_signature(func_without_args)
        self.assertTrue(model is None)

        """
        Test Sequence:
        1. Create model from function signature
        2. Check model annotations
        3. Check model fields length 
        4. Check model config (pydantic's model_config)
        5. Validation with correction and wrong invokation of function 
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
        10. func_with_positional_only_args(a, b, /):
        11. func_with_keyword_only_args(*, a, b):
        12. func_with_positional_only_args_and_kwargs(a, *args, b, **kwargs):
        """

        ####################
        ##### create model from function signature
        # 1. func_with_annotations(a: int, b: int) -> int:
        def func_with_annotations(a: int, b: int) -> int:
            return a + b

        model = get_input_model_from_signature(func_with_annotations)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["a"].annotation, int)
        self.assertEqual(model.model_fields["b"].annotation, int)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config["extra"], "forbid")
        ##### validate correct usage
        # For all the following cases, see block comment below the test case for details
        # 1. correct usage with keyword arguments
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2})
        # 2. incorrect argument types with keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": "2"})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct usage with positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(1, "2"))
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2, 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=("1", 2), kwargs={"c": 3})
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
        self.assertEqual(model.model_fields["a"].annotation, int)
        self.assertEqual(model.model_fields["b"].annotation, typing.Any)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config["extra"], "forbid")
        ##### validate correct usage
        # 1. correct usage with keyword arguments
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2})
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": "2"})
        pydantic_validate_args_kwargs(model, kwargs={"a": 2, "b": list()})
        # 2. incorrect argument types with keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": "1", "b": "2"})
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": list(), "b": dict()})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        pydantic_validate_args_kwargs(model, args=(1, "2"))
        pydantic_validate_args_kwargs(model, args=(2, list()))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=("1", "2"))
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(list(), dict()))
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2, 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": "2"})
        pydantic_validate_args_kwargs(model, args=(2,), kwargs={"b": list()})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=("1", 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        ####################

        ####################
        ##### create model from function signature
        # 3. func_with_no_annotations(a, b):
        def func_with_no_annotations(a, b):
            return a + b

        model = get_input_model_from_signature(func_with_no_annotations, model_for_empty_annotations=True)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["a"].annotation, typing.Any)
        self.assertEqual(model.model_fields["b"].annotation, typing.Any)
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config["extra"], "forbid")
        ##### validate correct usage
        # 1. correct usage
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2})
        pydantic_validate_args_kwargs(model, kwargs={"a": 1.2, "b": "2"})
        pydantic_validate_args_kwargs(model, kwargs={"a": dict(), "b": list()})
        # 2. incorrect argument types
        # typing.Any allows any type, so no ValidationError
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": list()})
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"b": dict()})
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        pydantic_validate_args_kwargs(model, args=(1, "2"))
        pydantic_validate_args_kwargs(model, args=(dict(), list()))
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        # 6. incorrect argument types with positional arguments
        # typing.Any allows any type, so no ValidationError
        # 7. too many positional arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2, 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(dict(), list(), 3))
        self.assertTrue(str(ex.exception).startswith("Too many positional arguments"))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,))
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(dict(),))
        # 9. correct usage with positional and keyword arguments
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        pydantic_validate_args_kwargs(model, args=(1.1,), kwargs={"b": "2"})
        pydantic_validate_args_kwargs(model, args=(dict(),), kwargs={"b": list()})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=("1", 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))

        model = get_input_model_from_signature(func_with_no_annotations)
        self.assertTrue(model is None)

        ####################
        ##### create model from function signature
        # 4. func_with_kwargs(a: int, b: int, **kwargs):
        def func_with_kwargs(a: int, b: int, **kwargs):
            return a + b

        model = get_input_model_from_signature(func_with_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["a"].annotation, int)
        self.assertEqual(model.model_fields["b"].annotation, int)
        self.assertEqual(len(model.model_fields), 3)
        self.assertEqual(model.model_config["extra"], "forbid")
        ##### validate correct usage
        # 1. correct usage
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2})
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3})
        pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": "3"})
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": "2"})
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": "2", "c": "3"})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        # 4. too many keyword arguments
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3, "d": 4})  # OK, not an error
        # 5. correct positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(1, "2"))
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=("1", 2))
        # 7. too many positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2, 3))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2, "c": 3})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"a": 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"b": 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        # any extra keyword argument is allowed

        ####################
        ##### create model from function signature
        # 5. func_with_annotated_kwargs(a: int, b: int, **kwargs: typing.Dict[str, int]):
        def func_with_annotated_kwargs(a: int, b: int, **kwargs: typing.Dict[str, int]):
            return a + b

        model = get_input_model_from_signature(func_with_annotated_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["a"].annotation, int)
        self.assertEqual(model.model_fields["b"].annotation, int)
        self.assertEqual(model.model_fields["kwargs"].annotation, typing.Dict[str, int])
        self.assertEqual(len(model.model_fields), 3)
        self.assertEqual(model.model_config["extra"], "forbid")
        # 1. correct usage
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2})
        pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": 3})
        pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": 3})
        # 2. incorrect argument types
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": "2"})
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": "3"})
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1, "b": 2, "c": list()})
        # 3. missing keyword arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        # 4. too many keyword arguments
        # OK, not an error
        # 5. correct positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(1, "2"))
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(dict(), 2))
        # 7. too many positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2, 3))
        # 8. missing positional arguments
        with self.assertRaises(ValidationError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,))
        # 9. correct usage with positional and keyword arguments
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2})
        pydantic_validate_args_kwargs(model, args=(1,), kwargs={"b": 2, "c": 3})
        # 10. incorrect ordering with positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"a": 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"b": 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"a": list(), "c": 3})
        self.assertTrue(str(ex.exception).startswith("Multiple values for argument"))
        # 11. incorrect usage with both positional and keyword arguments
        # any extra keyword argument is allowed so long it is of type int

        # both the following are not allowed in python - its also illogical
        # def func_with_double_args(*args1, *args2):
        #     """syntax error"""
        #     return
        # def func_with_double_kwargs(**kwargs1, **kwargs2):
        #     """syntax error"""
        #     return

        ####################
        ##### create model from function signature
        # 6. func_with_args(*args):
        def func_with_args(*args):
            return sum(args)

        model = get_input_model_from_signature(func_with_args, model_for_empty_annotations=True)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["args"].annotation, typing.Tuple)
        self.assertEqual(len(model.model_fields), 1)
        self.assertEqual(model.model_config["extra"], "forbid")
        # 1. correct usage
        pydantic_validate_args_kwargs(model, args=(1, 2))
        pydantic_validate_args_kwargs(model)
        pydantic_validate_args_kwargs(model, args=(dict()))
        # 2. incorrect argument types
        # OK, since args is a tuple of any type
        # 3. missing keyword arguments
        # OK, since args is a tuple
        # 4. too many keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct positional arguments
        pydantic_validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        # OK, since args is a tuple of any type
        # 7. too many positional arguments
        # OK, since args is a tuple of any length
        # 8. missing positional arguments
        # OK, since args is a tuple of any length
        # 9. correct usage with positional and keyword arguments
        # no keyword arguments
        # 10. incorrect ordering with positional and keyword arguments
        # OK, since args is a tuple and not keywords, no multiple values
        # 11. incorrect usage with both positional and keyword arguments
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1,), kwargs={"a": 2})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        with self.assertRaises(ValueError) as ex:
            pydantic_validate_args_kwargs(model, args=(1, 2), kwargs={"c": 3})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))

        model = get_input_model_from_signature(func_with_args)
        self.assertTrue(model is None)
        ####################

        ####################
        ##### create model from function signature
        # 7. func_with_annotated_args(*args: typing.List[int]):
        def func_with_annotated_args(*args: typing.List[int]):
            return sum(args)

        model = get_input_model_from_signature(func_with_annotated_args)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["args"].annotation, typing.List[int])
        self.assertEqual(len(model.model_fields), 1)
        self.assertEqual(model.model_config["extra"], "forbid")
        # 1. correct usage with keyword arguments
        # not possible, since args is a tuple
        # 2. incorrect argument types with keyword arguments
        # keyword arguments are not allowed
        # 3. missing keyword arguments
        # not possible
        # 4. too many keyword arguments
        with self.assertRaises(ValueError):
            pydantic_validate_args_kwargs(model, kwargs={"a": 1})
        self.assertTrue(str(ex.exception).startswith("Unexpected keyword arguments"))
        # 5. correct usage with positional arguments
        pydantic_validate_args_kwargs(model)
        pydantic_validate_args_kwargs(model, args=(1, 2))
        # 6. incorrect argument types with positional arguments
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(1, "2"))
        with self.assertRaises(ValidationError):
            pydantic_validate_args_kwargs(model, args=(dict(),))
        # 7. too many positional arguments
        # OK, since args is a list of any length
        # 8. missing positional arguments
        # OK, since args is a list of any length
        # 9. correct usage with positional and keyword arguments
        # not possible
        # 10. incorrect ordering with positional and keyword arguments
        # OK, since args is a list and not keywords, no multiple values
        # 11. incorrect usage with both positional and keyword arguments
        # not possible

        #####################
        ##### create model from function signature
        # 8. func_with_args_and_kwargs(*args, **kwargs):
        def func_with_args_and_kwargs(*args, **kwargs):
            return sum(args) + sum(kwargs.values())

        # no model
        model = get_input_model_from_signature(func_with_args_and_kwargs)
        self.assertTrue(model is None)
        # check model for empty annotations
        model = get_input_model_from_signature(func_with_args_and_kwargs, model_for_empty_annotations=True)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["args"].annotation, typing.Tuple)
        self.assertEqual(model.model_fields["kwargs"].annotation, typing.Dict[str, typing.Any])
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config["extra"], "forbid")

        def func_with_annotated_args_and_kwargs(*args: typing.List[int], **kwargs: typing.Dict[str, int]):
            return sum(args) + sum(kwargs.values())

        model = get_input_model_from_signature(func_with_annotated_args_and_kwargs)
        self.assertTrue(issubklass(model, BaseModel))
        self.assertEqual(model.model_fields["args"].annotation, typing.List[int])
        self.assertEqual(model.model_fields["kwargs"].annotation, typing.Dict[str, int])
        self.assertEqual(len(model.model_fields), 2)
        self.assertEqual(model.model_config["extra"], "forbid")


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
