from typing import Any, Dict, List, Tuple

import pytest

from pydantic import BaseModel, ValidationError

from hololinked.utils import (
    get_input_model_from_signature,
    issubklass,
    pydantic_validate_args_kwargs,
)


def func_without_args():
    return 1


def func_with_annotations(a: int, b: int) -> int:
    return a + b


def func_with_missing_annotations(a: int, b):
    return a + b


def func_with_no_annotations(a, b):
    return a + b


def func_with_kwargs(a: int, b: int, **kwargs):
    return a + b


def func_with_annotated_kwargs(a: int, b: int, **kwargs: dict[str, int]):
    return a + b


def func_with_args(*args):
    return sum(args)


def func_with_annotated_args(*args: list[int]):
    return sum(args)


def func_with_args_and_kwargs(*args, **kwargs):
    return sum(args) + sum(kwargs.values())


def func_with_annotated_args_and_kwargs(*args: list[int], **kwargs: dict[str, int]):
    return sum(args) + sum(kwargs.values())


def test_func_without_args_model_none():
    model = get_input_model_from_signature(func_without_args)
    assert model is None


def test_01_model_func_with_annotations():
    model = get_input_model_from_signature(func_with_annotations)
    assert issubklass(model, BaseModel)
    assert model.model_fields["a"].annotation is int
    assert model.model_fields["b"].annotation is int
    assert len(model.model_fields) == 2
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1, "b": 2}, None, None),
        (None, {"a": 1, "b": "2"}, ValidationError, None),
        (None, {"a": 1}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": 3}, ValueError, "Unexpected keyword arguments"),
        ((1, 2), None, None, None),
        ((1, "2"), None, ValidationError, None),
        ((1, 2, 3), None, ValueError, "Too many positional arguments"),
        ((1,), None, ValidationError, None),
        ((1,), {"b": 2}, None, None),
        ((1,), {"a": 2}, ValueError, "Multiple values for argument"),
        ((1, 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
        (("1", 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
    ],
)
def test_01_validation_func_with_annotations(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_annotations)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_02_model_func_with_missing_annotations():
    model = get_input_model_from_signature(func_with_missing_annotations)
    assert issubklass(model, BaseModel)
    assert model.model_fields["a"].annotation is int
    assert model.model_fields["b"].annotation is Any
    assert len(model.model_fields) == 2
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1, "b": 2}, None, None),
        (None, {"a": 1, "b": "2"}, None, None),
        (None, {"a": 2, "b": list()}, None, None),
        (None, {"a": "1", "b": "2"}, ValidationError, None),
        (None, {"a": list(), "b": dict()}, ValidationError, None),
        (None, {"a": 1}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": 3}, ValueError, "Unexpected keyword arguments"),
        ((1, 2), None, None, None),
        ((1, "2"), None, None, None),
        ((2, list()), None, None, None),
        (("1", "2"), None, ValidationError, None),
        ((list(), dict()), None, ValidationError, None),
        ((1, 2, 3), None, ValueError, "Too many positional arguments"),
        ((1,), None, ValidationError, None),
        ((1,), {"b": 2}, None, None),
        ((1,), {"b": "2"}, None, None),
        ((2,), {"b": list()}, None, None),
        ((1,), {"a": 2}, ValueError, "Multiple values for argument"),
        ((1, 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
        (("1", 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
    ],
)
def test_02_validation_func_with_missing_annotations(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_missing_annotations)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_03_model_func_with_no_annotations():
    model = get_input_model_from_signature(func_with_no_annotations, model_for_empty_annotations=True)
    assert issubklass(model, BaseModel)
    assert model.model_fields["a"].annotation is Any
    assert model.model_fields["b"].annotation is Any
    assert len(model.model_fields) == 2
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1, "b": 2}, None, None),
        (None, {"a": 1.2, "b": "2"}, None, None),
        (None, {"a": dict(), "b": list()}, None, None),
        (None, {"a": list()}, ValidationError, None),
        (None, {"b": dict()}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": 3}, ValueError, "Unexpected keyword arguments"),
        ((1, 2), None, None, None),
        ((1, "2"), None, None, None),
        ((dict(), list()), None, None, None),
        ((1,), {"b": 2}, None, None),
        ((1, 2, 3), None, ValueError, "Too many positional arguments"),
        ((dict(), list(), 3), None, ValueError, "Too many positional arguments"),
        ((1,), None, ValidationError, None),
        ((dict(),), None, ValidationError, None),
        ((1,), {"b": 2}, None, None),
        ((1.1,), {"b": "2"}, None, None),
        ((dict(),), {"b": list()}, None, None),
        ((1,), {"a": 2}, ValueError, "Multiple values for argument"),
        ((1, 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
        (("1", 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
    ],
)
def test_03_validation_func_with_no_annotations(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_no_annotations, model_for_empty_annotations=True)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_03_no_model_func_with_no_annotations():
    model = get_input_model_from_signature(func_with_no_annotations)
    assert model is None


def test_04_model_func_with_kwargs():
    model = get_input_model_from_signature(func_with_kwargs)
    assert issubklass(model, BaseModel)
    assert model.model_fields["a"].annotation is int
    assert model.model_fields["b"].annotation is int
    assert len(model.model_fields) == 3
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1, "b": 2}, None, None),
        (None, {"a": 1, "b": 2, "c": 3}, None, None),
        ((1, 2), {"c": "3"}, None, None),
        (None, {"a": 1, "b": "2"}, ValidationError, None),
        (None, {"a": 1, "b": "2", "c": "3"}, ValidationError, None),
        (None, {"a": 1}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": 3, "d": 4}, None, None),
        ((1, 2), None, None, None),
        ((1, "2"), None, ValidationError, None),
        (("1", 2), None, ValidationError, None),
        ((1, 2, 3), None, ValidationError, None),
        ((1,), None, ValidationError, None),
        ((1,), {"b": 2}, None, None),
        ((1,), {"b": 2, "c": 3}, None, None),
        ((1,), {"a": 2}, ValueError, "Multiple values for argument"),
        ((1, 2), {"a": 3}, ValueError, "Multiple values for argument"),
        ((1, 2), {"b": 3}, ValueError, "Multiple values for argument"),
    ],
)
def test_04_validation_func_with_kwargs(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_kwargs)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_05_model_func_with_annotated_kwargs():
    model = get_input_model_from_signature(func_with_annotated_kwargs)
    assert issubklass(model, BaseModel)
    assert model.model_fields["a"].annotation is int
    assert model.model_fields["b"].annotation is int
    assert model.model_fields["kwargs"].annotation == dict[str, int]
    assert len(model.model_fields) == 3
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1, "b": 2}, None, None),
        (None, {"a": 1, "b": 2, "c": 3}, None, None),
        ((1, 2), {"c": 3}, None, None),
        (None, {"a": 1, "b": "2"}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": "3"}, ValidationError, None),
        (None, {"a": 1, "b": 2, "c": list()}, ValidationError, None),
        (None, {"a": 1}, ValidationError, None),
        ((1, 2), None, None, None),
        ((1, "2"), None, ValidationError, None),
        ((dict(), 2), None, ValidationError, None),
        ((1, 2, 3), None, ValidationError, None),
        ((1,), None, ValidationError, None),
        ((1,), {"b": 2}, None, None),
        ((1,), {"b": 2, "c": 3}, None, None),
        ((1,), {"a": 2}, ValueError, "Multiple values for argument"),
        ((1, 2), {"a": 3}, ValueError, "Multiple values for argument"),
        ((1, 2), {"b": 3}, ValueError, "Multiple values for argument"),
        ((1, 2), {"a": list(), "c": 3}, ValueError, "Multiple values for argument"),
    ],
)
def test_05_validation_func_with_annotated_kwargs(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_annotated_kwargs)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_06_model_func_with_args():
    model = get_input_model_from_signature(func_with_args, model_for_empty_annotations=True)
    assert issubklass(model, BaseModel)
    # assert model.model_fields["args"].annotation == tuple or model.model_fields["args"].annotation == Tuple
    assert len(model.model_fields) == 1
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        ((1, 2), None, None, None),
        (None, None, None, None),
        ((dict(),), None, None, None),
        (None, {"a": 1}, ValueError, "Unexpected keyword arguments"),
        ((1, 2), None, None, None),
        ((1,), {"a": 2}, ValueError, "Unexpected keyword arguments"),
        ((1, 2), {"c": 3}, ValueError, "Unexpected keyword arguments"),
    ],
)
def test_06_validation_func_with_args(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_args, model_for_empty_annotations=True)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_06_no_model_func_with_args():
    model = get_input_model_from_signature(func_with_args)
    assert model is None


def test_07_model_func_with_annotated_args():
    model = get_input_model_from_signature(func_with_annotated_args)
    assert issubklass(model, BaseModel)
    # assert model.model_fields["args"].annotation == list[int]
    assert len(model.model_fields) == 1
    assert model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "args,kwargs,raises,exmsg",
    [
        (None, {"a": 1}, ValueError, "Unexpected keyword arguments"),
        (None, None, None, None),
        ((1, 2), None, None, None),
        ((1, "2"), None, ValidationError, None),
        ((dict(),), None, ValidationError, None),
    ],
)
def test_07_validation_func_with_annotated_args(args, kwargs, raises, exmsg):
    model = get_input_model_from_signature(func_with_annotated_args)
    if raises:
        with pytest.raises(raises) as ex:
            pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})
        if exmsg:
            assert str(ex.value).startswith(exmsg)
    else:
        pydantic_validate_args_kwargs(model, args=args if args else (), kwargs=kwargs if kwargs else {})


def test_08_no_model_func_with_args_and_kwargs():
    model = get_input_model_from_signature(func_with_args_and_kwargs)
    assert model is None


def test_08_model_func_with_args_and_kwargs():
    model = get_input_model_from_signature(func_with_args_and_kwargs, model_for_empty_annotations=True)
    assert issubklass(model, BaseModel)
    assert model.model_fields["args"].annotation == Tuple or model.model_fields["args"].annotation is tuple
    assert model.model_fields["kwargs"].annotation == Dict[str, Any] or model.model_fields["kwargs"].annotation is dict
    assert len(model.model_fields) == 2
    assert model.model_config["extra"] == "forbid"


def test_08_model_func_with_annotated_args_and_kwargs_model():
    model = get_input_model_from_signature(func_with_annotated_args_and_kwargs)
    assert issubklass(model, BaseModel)
    assert model.model_fields["args"].annotation == List[int] or model.model_fields["args"].annotation == list[int]
    assert (
        model.model_fields["kwargs"].annotation == Dict[str, int]
        or model.model_fields["kwargs"].annotation == dict[str, int]
    )
    assert len(model.model_fields) == 2
    assert model.model_config["extra"] == "forbid"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
