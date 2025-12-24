import asyncio

from copy import deepcopy

import pytest

from hololinked.core.actions import (
    Action,
    BoundAction,
    BoundAsyncAction,
    BoundSyncAction,
)
from hololinked.core.dataklasses import ActionInfoValidator
from hololinked.core.thing import action
from hololinked.schema_validators import JSONSchemaValidator
from hololinked.td.interaction_affordance import ActionAffordance
from hololinked.utils import isclassmethod


try:
    from .things import TestThing
    from .things.test_thing import replace_methods_with_actions
except ImportError:
    from things import TestThing
    from things.test_thing import replace_methods_with_actions


@pytest.fixture(scope="module")
def thing() -> TestThing:
    thing_cls = deepcopy(TestThing)
    _thing = thing_cls(id="test-action")
    replace_methods_with_actions(thing_cls=thing_cls)
    return _thing


def test_01_allowed_actions():
    """Test if methods can be decorated with action"""
    # 1. instance method can be decorated with action
    assert TestThing.action_echo == action()(TestThing.action_echo.obj)  # already predecorated as action
    # 2. classmethod can be decorated with action
    assert Action(TestThing.action_echo_with_classmethod) == action()(TestThing.action_echo_with_classmethod)
    assert isclassmethod(TestThing.action_echo_with_classmethod)
    # 3. async methods can be decorated with action
    assert Action(TestThing.action_echo_async) == action()(TestThing.action_echo_async)
    # 4. async classmethods can be decorated with action
    assert Action(TestThing.action_echo_async_with_classmethod) == action()(
        TestThing.action_echo_async_with_classmethod
    )
    assert isclassmethod(TestThing.action_echo_async_with_classmethod)
    # 5. parameterized function can be decorated with action
    assert Action(TestThing.parameterized_action) == action(safe=True)(TestThing.parameterized_action)
    assert Action(TestThing.parameterized_action_without_call) == action(idempotent=True)(
        TestThing.parameterized_action_without_call
    )
    assert Action(TestThing.parameterized_action_async) == action(synchronous=True)(
        TestThing.parameterized_action_async
    )
    # 6. actions with input and output schema
    assert Action(TestThing.json_schema_validated_action) == action(
        input_schema={
            "val1": "integer",
            "val2": "string",
            "val3": "object",
            "val4": "array",
        },
        output_schema={"val1": "int", "val3": "dict"},
    )(TestThing.json_schema_validated_action)
    assert Action(TestThing.pydantic_validated_action) == action()(TestThing.pydantic_validated_action)


def test_02_bound_method(thing: TestThing):
    """Test if methods decorated with action are correctly bound"""
    # 1. instance method can be decorated with action
    assert isinstance(thing.action_echo, BoundAction)
    assert isinstance(thing.action_echo, BoundSyncAction)
    assert not isinstance(thing.action_echo, BoundAsyncAction)
    assert isinstance(TestThing.action_echo, Action)
    assert not isinstance(TestThing.action_echo, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.action_echo, BoundAction)
    assert thing.action_echo.name == "action_echo"
    assert thing.action_echo.owner_inst == thing
    assert thing.action_echo.owner == TestThing
    assert thing.action_echo.execution_info == TestThing.action_echo.execution_info
    assert str(thing.action_echo) == f"<BoundAction({TestThing.__name__}.{thing.action_echo.name} of {thing.id})>"
    assert thing.action_echo != TestThing.action_echo
    assert thing.action_echo.bound_obj == thing

    # 2. classmethod can be decorated with action
    assert isinstance(thing.action_echo_with_classmethod, BoundAction)
    assert isinstance(thing.action_echo_with_classmethod, BoundSyncAction)
    assert not isinstance(thing.action_echo_with_classmethod, BoundAsyncAction)
    assert isinstance(TestThing.action_echo_with_classmethod, BoundAction)
    assert isinstance(TestThing.action_echo_with_classmethod, BoundSyncAction)
    assert not isinstance(TestThing.action_echo_with_classmethod, Action)
    # associated attributes of BoundAction
    assert isinstance(thing.action_echo_with_classmethod, BoundAction)
    assert thing.action_echo_with_classmethod.name == "action_echo_with_classmethod"
    assert thing.action_echo_with_classmethod.owner_inst == thing
    assert thing.action_echo_with_classmethod.owner == TestThing
    assert thing.action_echo_with_classmethod.execution_info == TestThing.action_echo_with_classmethod.execution_info
    assert (
        str(thing.action_echo_with_classmethod)
        == f"<BoundAction({TestThing.__name__}.{thing.action_echo_with_classmethod.name} of {thing.id})>"
    )
    assert thing.action_echo_with_classmethod == TestThing.action_echo_with_classmethod
    assert thing.action_echo_with_classmethod.bound_obj == TestThing

    # 3. async methods can be decorated with action
    assert isinstance(thing.action_echo_async, BoundAction)
    assert not isinstance(thing.action_echo_async, BoundSyncAction)
    assert isinstance(thing.action_echo_async, BoundAsyncAction)
    assert isinstance(TestThing.action_echo_async, Action)
    assert not isinstance(TestThing.action_echo_async, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.action_echo_async, BoundAction)
    assert thing.action_echo_async.name == "action_echo_async"
    assert thing.action_echo_async.owner_inst == thing
    assert thing.action_echo_async.owner == TestThing
    assert thing.action_echo_async.execution_info == TestThing.action_echo_async.execution_info
    assert (
        str(thing.action_echo_async)
        == f"<BoundAction({TestThing.__name__}.{thing.action_echo_async.name} of {thing.id})>"
    )
    assert thing.action_echo_async != TestThing.action_echo_async
    assert thing.action_echo_async.bound_obj == thing

    # 4. async classmethods can be decorated with action
    assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
    assert not isinstance(thing.action_echo_async_with_classmethod, BoundSyncAction)
    assert isinstance(thing.action_echo_async_with_classmethod, BoundAsyncAction)
    assert isinstance(TestThing.action_echo_async_with_classmethod, BoundAction)
    assert isinstance(TestThing.action_echo_async_with_classmethod, BoundAsyncAction)
    assert not isinstance(TestThing.action_echo_async_with_classmethod, Action)
    # associated attributes of BoundAction
    assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
    assert thing.action_echo_async_with_classmethod.name == "action_echo_async_with_classmethod"
    assert thing.action_echo_async_with_classmethod.owner_inst == thing
    assert thing.action_echo_async_with_classmethod.owner == TestThing
    assert (
        thing.action_echo_async_with_classmethod.execution_info
        == TestThing.action_echo_async_with_classmethod.execution_info
    )
    assert (
        str(thing.action_echo_async_with_classmethod)
        == f"<BoundAction({TestThing.__name__}.{thing.action_echo_async_with_classmethod.name} of {thing.id})>"
    )
    assert thing.action_echo_async_with_classmethod == TestThing.action_echo_async_with_classmethod
    assert thing.action_echo_async_with_classmethod.bound_obj == TestThing

    # 5. parameterized function can be decorated with action
    assert isinstance(thing.parameterized_action, BoundAction)
    assert isinstance(thing.parameterized_action, BoundSyncAction)
    assert not isinstance(thing.parameterized_action, BoundAsyncAction)
    assert isinstance(TestThing.parameterized_action, Action)
    assert not isinstance(TestThing.parameterized_action, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.parameterized_action, BoundAction)
    assert thing.parameterized_action.name == "parameterized_action"
    assert thing.parameterized_action.owner_inst == thing
    assert thing.parameterized_action.owner == TestThing
    assert thing.parameterized_action.execution_info == TestThing.parameterized_action.execution_info
    assert (
        str(thing.parameterized_action)
        == f"<BoundAction({TestThing.__name__}.{thing.parameterized_action.name} of {thing.id})>"
    )
    assert thing.parameterized_action != TestThing.parameterized_action
    assert thing.parameterized_action.bound_obj == thing

    # 6. parameterized function can be decorated with action
    assert isinstance(thing.parameterized_action_without_call, BoundAction)
    assert isinstance(thing.parameterized_action_without_call, BoundSyncAction)
    assert not isinstance(thing.parameterized_action_without_call, BoundAsyncAction)
    assert isinstance(TestThing.parameterized_action_without_call, Action)
    assert not isinstance(TestThing.parameterized_action_without_call, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.parameterized_action_without_call, BoundAction)
    assert thing.parameterized_action_without_call.name == "parameterized_action_without_call"
    assert thing.parameterized_action_without_call.owner_inst == thing
    assert thing.parameterized_action_without_call.owner == TestThing
    assert (
        thing.parameterized_action_without_call.execution_info
        == TestThing.parameterized_action_without_call.execution_info
    )
    assert (
        str(thing.parameterized_action_without_call)
        == f"<BoundAction({TestThing.__name__}.{thing.parameterized_action_without_call.name} of {thing.id})>"
    )
    assert thing.parameterized_action_without_call != TestThing.parameterized_action_without_call
    assert thing.parameterized_action_without_call.bound_obj == thing

    # 7. parameterized function can be decorated with action
    assert isinstance(thing.parameterized_action_async, BoundAction)
    assert not isinstance(thing.parameterized_action_async, BoundSyncAction)
    assert isinstance(thing.parameterized_action_async, BoundAsyncAction)
    assert isinstance(TestThing.parameterized_action_async, Action)
    assert not isinstance(TestThing.parameterized_action_async, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.parameterized_action_async, BoundAction)
    assert thing.parameterized_action_async.name == "parameterized_action_async"
    assert thing.parameterized_action_async.owner_inst == thing
    assert thing.parameterized_action_async.owner == TestThing
    assert thing.parameterized_action_async.execution_info == TestThing.parameterized_action_async.execution_info
    assert (
        str(thing.parameterized_action_async)
        == f"<BoundAction({TestThing.__name__}.{thing.parameterized_action_async.name} of {thing.id})>"
    )
    assert thing.parameterized_action_async != TestThing.parameterized_action_async
    assert thing.parameterized_action_async.bound_obj == thing

    # 8. actions with input and output schema
    assert isinstance(thing.json_schema_validated_action, BoundAction)
    assert isinstance(thing.json_schema_validated_action, BoundSyncAction)
    assert not isinstance(thing.json_schema_validated_action, BoundAsyncAction)
    assert isinstance(TestThing.json_schema_validated_action, Action)
    assert not isinstance(TestThing.json_schema_validated_action, BoundAction)
    # associated attributes of BoundAction
    assert isinstance(thing.json_schema_validated_action, BoundAction)
    assert thing.json_schema_validated_action.name == "json_schema_validated_action"
    assert thing.json_schema_validated_action.owner_inst == thing
    assert thing.json_schema_validated_action.owner == TestThing
    assert thing.json_schema_validated_action.execution_info == TestThing.json_schema_validated_action.execution_info
    assert (
        str(thing.json_schema_validated_action)
        == f"<BoundAction({TestThing.__name__}.{thing.json_schema_validated_action.name} of {thing.id})>"
    )
    assert thing.json_schema_validated_action != TestThing.json_schema_validated_action
    assert thing.json_schema_validated_action.bound_obj == thing


def test_03_remote_info():
    """Test if the validator is working correctly, on which the logic of the action is based"""
    remote_info = TestThing.action_echo.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert not remote_info.isproperty
    assert not remote_info.isparameterized
    assert not remote_info.iscoroutine
    assert not remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.action_echo_async.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert remote_info.iscoroutine
    assert not remote_info.isproperty
    assert not remote_info.isparameterized
    assert not remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.action_echo_with_classmethod.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert not remote_info.iscoroutine
    assert not remote_info.isproperty
    assert not remote_info.isparameterized
    assert not remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.parameterized_action.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert not remote_info.iscoroutine
    assert not remote_info.isproperty
    assert remote_info.isparameterized
    assert remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.parameterized_action_without_call.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert not remote_info.iscoroutine
    assert not remote_info.isproperty
    assert remote_info.isparameterized
    assert not remote_info.safe
    assert remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.parameterized_action_async.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert remote_info.iscoroutine
    assert not remote_info.isproperty
    assert remote_info.isparameterized
    assert not remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous

    remote_info = TestThing.json_schema_validated_action.execution_info
    assert isinstance(remote_info, ActionInfoValidator)
    assert remote_info.isaction
    assert not remote_info.iscoroutine
    assert not remote_info.isproperty
    assert not remote_info.isparameterized
    assert not remote_info.safe
    assert not remote_info.idempotent
    assert remote_info.synchronous
    assert isinstance(remote_info.schema_validator, JSONSchemaValidator)


def test_04_api_and_invalid_actions():
    """Test if action prevents invalid objects from being named as actions and raises neat errors"""
    # done allow action decorator to be terminated without '()' on a method
    with pytest.raises(TypeError) as ex:
        action(TestThing.incorrectly_decorated_method)
    assert str(ex.value).startswith(
        "input schema should be a JSON or pydantic BaseModel, not a function/method, did you decorate your action wrongly?"
    )

    # dunder methods cannot be decorated with action
    with pytest.raises(ValueError) as ex:
        action()(TestThing.__internal__)
    assert str(ex.value).startswith("dunder objects cannot become remote")

    # only functions and methods can be decorated with action
    for obj in [
        TestThing,
        str,
        1,
        1.0,
        "Str",
        True,
        None,
        object(),
        type,
        property,
    ]:
        with pytest.raises(TypeError) as ex2:
            action()(obj)
        assert str(ex2.value).startswith("target for action or is not a function/method.")

    with pytest.raises(ValueError) as ex:
        action(safe=True, some_kw=1)
    assert str(ex.value).startswith("Only 'safe', 'idempotent', 'synchronous' are allowed")


def test_05_thing_cls_actions(thing: TestThing):
    """Test class and instance level action access"""
    # class level
    for name, act in TestThing.actions.descriptors.items():
        assert isinstance(act, Action)
    for name in replace_methods_with_actions._exposed_actions:
        assert name in TestThing.actions
    # instance level
    for name, act in thing.actions.values.items():
        assert isinstance(act, BoundAction)
    for name in replace_methods_with_actions._exposed_actions:
        assert name in thing.actions
    # cannot call an instance bound action at class level
    with pytest.raises(NotImplementedError):
        TestThing.action_echo(thing, 1)
    # but can call instance bound action with instance
    assert thing.action_echo(1) == 1
    # can also call classmethods as usual
    assert TestThing.action_echo_with_classmethod(2) == 2
    assert thing.action_echo_with_classmethod(3) == 3
    # async methods behave similarly
    assert asyncio.run(thing.action_echo_async(4)) == 4
    assert asyncio.run(TestThing.action_echo_async_with_classmethod(5)) == 5
    with pytest.raises(NotImplementedError):
        asyncio.run(TestThing.action_echo(7))
    # parameterized actions behave similarly
    assert thing.parameterized_action(1, "hello1", 1.1) == ("test-action", 1, "hello1", 1.1)
    assert asyncio.run(thing.parameterized_action_async(2, "hello2", "foo2")) == ("test-action", 2, "hello2", "foo2")
    with pytest.raises(NotImplementedError):
        TestThing.parameterized_action(3, "hello3", 5)
    with pytest.raises(NotImplementedError):
        asyncio.run(TestThing.parameterized_action_async(4, "hello4", 5))


def test_06_action_affordance(thing: TestThing):
    """Test if action affordance is correctly created"""
    assert isinstance(thing.action_echo, BoundAction)
    affordance = thing.action_echo.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.action_echo_with_classmethod, BoundAction)
    affordance = thing.action_echo_with_classmethod.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.action_echo_async, BoundAction)
    affordance = thing.action_echo_async.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
    affordance = thing.action_echo_async_with_classmethod.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.parameterized_action, BoundAction)
    affordance = thing.parameterized_action.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is True
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.parameterized_action_without_call, BoundAction)
    affordance = thing.parameterized_action_without_call.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is True
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.parameterized_action_async, BoundAction)
    affordance = thing.parameterized_action_async.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert affordance.input is None
    assert affordance.output is None
    assert affordance.description is None

    assert isinstance(thing.json_schema_validated_action, BoundAction)
    affordance = thing.json_schema_validated_action.to_affordance()
    assert isinstance(affordance, ActionAffordance)
    assert affordance.idempotent is None
    assert affordance.synchronous is True
    assert affordance.safe is None
    assert isinstance(affordance.input, dict)
    assert isinstance(affordance.output, dict)
    assert affordance.description is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
