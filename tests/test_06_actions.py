import asyncio
import unittest
import logging

from hololinked.utils import isclassmethod
from hololinked.core.actions import (
    Action,
    BoundAction,
    BoundSyncAction,
    BoundAsyncAction,
)
from hololinked.core.dataklasses import ActionInfoValidator
from hololinked.core.thing import Thing, action
from hololinked.td.interaction_affordance import ActionAffordance
from hololinked.schema_validators import JSONSchemaValidator

try:
    from .utils import TestCase, TestRunner
    from .things import TestThing
    from .things.test_thing import replace_methods_with_actions
except ImportError:
    from utils import TestCase, TestRunner
    from things import TestThing
    from things.test_thing import replace_methods_with_actions


class TestAction(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        print(f"test action with {cls.__name__}")

    def test_1_allowed_actions(self):
        """Test if methods can be decorated with action"""
        # 1. instance method can be decorated with action
        self.assertEqual(TestThing.action_echo, action()(TestThing.action_echo.obj))  # already predecorated as action
        # 2. classmethod can be decorated with action
        self.assertEqual(
            Action(TestThing.action_echo_with_classmethod),
            action()(TestThing.action_echo_with_classmethod),
        )
        self.assertTrue(isclassmethod(TestThing.action_echo_with_classmethod))
        # 3. async methods can be decorated with action
        self.assertEqual(Action(TestThing.action_echo_async), action()(TestThing.action_echo_async))
        # 4. async classmethods can be decorated with action
        self.assertEqual(
            Action(TestThing.action_echo_async_with_classmethod),
            action()(TestThing.action_echo_async_with_classmethod),
        )
        self.assertTrue(isclassmethod(TestThing.action_echo_async_with_classmethod))
        # 5. parameterized function can be decorated with action
        self.assertEqual(
            Action(TestThing.parameterized_action),
            action(safe=True)(TestThing.parameterized_action),
        )
        self.assertEqual(
            Action(TestThing.parameterized_action_without_call),
            action(idempotent=True)(TestThing.parameterized_action_without_call),
        )
        self.assertEqual(
            Action(TestThing.parameterized_action_async),
            action(synchronous=True)(TestThing.parameterized_action_async),
        )
        # 6. actions with input and output schema
        self.assertEqual(
            Action(TestThing.json_schema_validated_action),
            action(
                input_schema={
                    "val1": "integer",
                    "val2": "string",
                    "val3": "object",
                    "val4": "array",
                },
                output_schema={"val1": "int", "val3": "dict"},
            )(TestThing.json_schema_validated_action),
        )
        self.assertEqual(
            Action(TestThing.pydantic_validated_action),
            action()(TestThing.pydantic_validated_action),
        )

    def test_2_bound_method(self):
        """Test if methods decorated with action are correctly bound"""
        thing = TestThing(id="test-action", log_level=logging.ERROR)
        replace_methods_with_actions(thing_cls=TestThing)

        # 1. instance method can be decorated with action
        self.assertIsInstance(thing.action_echo, BoundAction)
        self.assertIsInstance(thing.action_echo, BoundSyncAction)
        self.assertNotIsInstance(thing.action_echo, BoundAsyncAction)
        self.assertIsInstance(TestThing.action_echo, Action)
        self.assertNotIsInstance(TestThing.action_echo, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo, BoundAction)  # type definition
        self.assertEqual(thing.action_echo.name, "action_echo")
        self.assertEqual(thing.action_echo.owner_inst, thing)
        self.assertEqual(thing.action_echo.owner, TestThing)
        self.assertEqual(thing.action_echo.execution_info, TestThing.action_echo.execution_info)
        self.assertEqual(
            str(thing.action_echo),
            f"<BoundAction({TestThing.__name__}.{thing.action_echo.name} of {thing.id})>",
        )
        self.assertNotEqual(thing.action_echo, TestThing.action_echo)
        self.assertEqual(thing.action_echo.bound_obj, thing)

        # 2. classmethod can be decorated with action
        self.assertIsInstance(thing.action_echo_with_classmethod, BoundAction)
        self.assertIsInstance(thing.action_echo_with_classmethod, BoundSyncAction)
        self.assertNotIsInstance(thing.action_echo_with_classmethod, BoundAsyncAction)
        self.assertIsInstance(TestThing.action_echo_with_classmethod, BoundAction)
        self.assertIsInstance(TestThing.action_echo_with_classmethod, BoundSyncAction)
        self.assertNotIsInstance(TestThing.action_echo_with_classmethod, Action)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_with_classmethod, BoundAction)
        self.assertEqual(thing.action_echo_with_classmethod.name, "action_echo_with_classmethod")
        self.assertEqual(thing.action_echo_with_classmethod.owner_inst, thing)
        self.assertEqual(thing.action_echo_with_classmethod.owner, TestThing)
        self.assertEqual(
            thing.action_echo_with_classmethod.execution_info,
            TestThing.action_echo_with_classmethod.execution_info,
        )
        self.assertEqual(
            str(thing.action_echo_with_classmethod),
            f"<BoundAction({TestThing.__name__}.{thing.action_echo_with_classmethod.name} of {thing.id})>",
        )
        self.assertEqual(thing.action_echo_with_classmethod, TestThing.action_echo_with_classmethod)
        self.assertEqual(thing.action_echo_with_classmethod.bound_obj, TestThing)

        # 3. async methods can be decorated with action
        self.assertIsInstance(thing.action_echo_async, BoundAction)
        self.assertNotIsInstance(thing.action_echo_async, BoundSyncAction)
        self.assertIsInstance(thing.action_echo_async, BoundAsyncAction)
        self.assertIsInstance(TestThing.action_echo_async, Action)
        self.assertNotIsInstance(TestThing.action_echo_async, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_async, BoundAction)
        self.assertEqual(thing.action_echo_async.name, "action_echo_async")
        self.assertEqual(thing.action_echo_async.owner_inst, thing)
        self.assertEqual(thing.action_echo_async.owner, TestThing)
        self.assertEqual(
            thing.action_echo_async.execution_info,
            TestThing.action_echo_async.execution_info,
        )
        self.assertEqual(
            str(thing.action_echo_async),
            f"<BoundAction({TestThing.__name__}.{thing.action_echo_async.name} of {thing.id})>",
        )
        self.assertNotEqual(thing.action_echo_async, TestThing.action_echo_async)
        self.assertEqual(thing.action_echo_async.bound_obj, thing)

        # 4. async classmethods can be decorated with action
        self.assertIsInstance(thing.action_echo_async_with_classmethod, BoundAction)
        self.assertNotIsInstance(thing.action_echo_async_with_classmethod, BoundSyncAction)
        self.assertIsInstance(thing.action_echo_async_with_classmethod, BoundAsyncAction)
        self.assertIsInstance(TestThing.action_echo_async_with_classmethod, BoundAction)
        self.assertIsInstance(TestThing.action_echo_async_with_classmethod, BoundAsyncAction)
        self.assertNotIsInstance(TestThing.action_echo_async_with_classmethod, Action)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
        self.assertEqual(
            thing.action_echo_async_with_classmethod.name,
            "action_echo_async_with_classmethod",
        )
        self.assertEqual(thing.action_echo_async_with_classmethod.owner_inst, thing)
        self.assertEqual(thing.action_echo_async_with_classmethod.owner, TestThing)
        self.assertEqual(
            thing.action_echo_async_with_classmethod.execution_info,
            TestThing.action_echo_async_with_classmethod.execution_info,
        )
        self.assertEqual(
            str(thing.action_echo_async_with_classmethod),
            f"<BoundAction({TestThing.__name__}.{thing.action_echo_async_with_classmethod.name} of {thing.id})>",
        )
        self.assertEqual(
            thing.action_echo_async_with_classmethod,
            TestThing.action_echo_async_with_classmethod,
        )
        self.assertEqual(thing.action_echo_async_with_classmethod.bound_obj, TestThing)

        # 5. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action, BoundAction)
        self.assertIsInstance(thing.parameterized_action, BoundSyncAction)
        self.assertNotIsInstance(thing.parameterized_action, BoundAsyncAction)
        self.assertIsInstance(TestThing.parameterized_action, Action)
        self.assertNotIsInstance(TestThing.parameterized_action, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action, BoundAction)
        self.assertEqual(thing.parameterized_action.name, "parameterized_action")
        self.assertEqual(thing.parameterized_action.owner_inst, thing)
        self.assertEqual(thing.parameterized_action.owner, TestThing)
        self.assertEqual(
            thing.parameterized_action.execution_info,
            TestThing.parameterized_action.execution_info,
        )
        self.assertEqual(
            str(thing.parameterized_action),
            f"<BoundAction({TestThing.__name__}.{thing.parameterized_action.name} of {thing.id})>",
        )
        self.assertNotEqual(thing.parameterized_action, TestThing.parameterized_action)
        self.assertEqual(thing.parameterized_action.bound_obj, thing)

        # 6. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action_without_call, BoundAction)
        self.assertIsInstance(thing.parameterized_action_without_call, BoundSyncAction)
        self.assertNotIsInstance(thing.parameterized_action_without_call, BoundAsyncAction)
        self.assertIsInstance(TestThing.parameterized_action_without_call, Action)
        self.assertNotIsInstance(TestThing.parameterized_action_without_call, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action_without_call, BoundAction)
        self.assertEqual(
            thing.parameterized_action_without_call.name,
            "parameterized_action_without_call",
        )
        self.assertEqual(thing.parameterized_action_without_call.owner_inst, thing)
        self.assertEqual(thing.parameterized_action_without_call.owner, TestThing)
        self.assertEqual(
            thing.parameterized_action_without_call.execution_info,
            TestThing.parameterized_action_without_call.execution_info,
        )
        self.assertEqual(
            str(thing.parameterized_action_without_call),
            f"<BoundAction({TestThing.__name__}.{thing.parameterized_action_without_call.name} of {thing.id})>",
        )
        self.assertNotEqual(
            thing.parameterized_action_without_call,
            TestThing.parameterized_action_without_call,
        )
        self.assertEqual(thing.parameterized_action_without_call.bound_obj, thing)

        # 7. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action_async, BoundAction)
        self.assertNotIsInstance(thing.parameterized_action_async, BoundSyncAction)
        self.assertIsInstance(thing.parameterized_action_async, BoundAsyncAction)
        self.assertIsInstance(TestThing.parameterized_action_async, Action)
        self.assertNotIsInstance(TestThing.parameterized_action_async, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action_async, BoundAction)
        self.assertEqual(thing.parameterized_action_async.name, "parameterized_action_async")
        self.assertEqual(thing.parameterized_action_async.owner_inst, thing)
        self.assertEqual(thing.parameterized_action_async.owner, TestThing)
        self.assertEqual(
            thing.parameterized_action_async.execution_info,
            TestThing.parameterized_action_async.execution_info,
        )
        self.assertEqual(
            str(thing.parameterized_action_async),
            f"<BoundAction({TestThing.__name__}.{thing.parameterized_action_async.name} of {thing.id})>",
        )
        self.assertNotEqual(thing.parameterized_action_async, TestThing.parameterized_action_async)
        self.assertEqual(thing.parameterized_action_async.bound_obj, thing)

        # 8. actions with input and output schema
        self.assertIsInstance(thing.json_schema_validated_action, BoundAction)
        self.assertIsInstance(thing.json_schema_validated_action, BoundSyncAction)
        self.assertNotIsInstance(thing.json_schema_validated_action, BoundAsyncAction)
        self.assertIsInstance(TestThing.json_schema_validated_action, Action)
        self.assertNotIsInstance(TestThing.json_schema_validated_action, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.json_schema_validated_action, BoundAction)
        self.assertEqual(thing.json_schema_validated_action.name, "json_schema_validated_action")
        self.assertEqual(thing.json_schema_validated_action.owner_inst, thing)
        self.assertEqual(thing.json_schema_validated_action.owner, TestThing)
        self.assertEqual(
            thing.json_schema_validated_action.execution_info,
            TestThing.json_schema_validated_action.execution_info,
        )
        self.assertEqual(
            str(thing.json_schema_validated_action),
            f"<BoundAction({TestThing.__name__}.{thing.json_schema_validated_action.name} of {thing.id})>",
        )
        self.assertNotEqual(thing.json_schema_validated_action, TestThing.json_schema_validated_action)
        self.assertEqual(thing.json_schema_validated_action.bound_obj, thing)

    def test_3_remote_info(self):
        """Test if the validator is working correctly, on which the logic of the action is based"""
        # basic check if the remote_info is correct, although this test is not necessary, not recommended and
        # neither particularly useful
        remote_info = TestThing.action_echo.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)  # type definition
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.action_echo_async.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)  # type definition
        self.assertTrue(remote_info.isaction)
        self.assertTrue(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.action_echo_with_classmethod.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)  # type definition
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.parameterized_action.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertTrue(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.parameterized_action_without_call.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertTrue(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.parameterized_action_async.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertTrue(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = TestThing.json_schema_validated_action.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)
        self.assertIsInstance(remote_info.schema_validator, JSONSchemaValidator)

    def test_4_api_and_invalid_actions(self):
        """Test if action prevents invalid objects from being named as actions and raises neat errors"""
        # done allow action decorator to be terminated without '()' on a method
        with self.assertRaises(TypeError) as ex:
            action(TestThing.incorrectly_decorated_method)
        self.assertTrue(
            str(ex.exception).startswith(
                "input schema should be a JSON or pydantic BaseModel, not a function/method, did you decorate your action wrongly?"
            )
        )

        # dunder methods cannot be decorated with action
        with self.assertRaises(ValueError) as ex:
            action()(TestThing.__internal__)
        self.assertTrue(str(ex.exception).startswith("dunder objects cannot become remote"))

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
            with self.assertRaises(TypeError) as ex:
                action()(obj)  # not an action
            self.assertTrue(str(ex.exception).startswith("target for action or is not a function/method."))

        with self.assertRaises(ValueError) as ex:
            action(safe=True, some_kw=1)
        self.assertTrue(str(ex.exception).startswith("Only 'safe', 'idempotent', 'synchronous' are allowed"))

    # TODO - rename this test
    def test_5_thing_cls_actions(self):
        """Test class and instance level action access"""
        thing = TestThing(id="test-action", log_level=logging.ERROR)
        # class level
        for name, action in TestThing.actions.descriptors.items():
            self.assertIsInstance(action, Action)
        for name in replace_methods_with_actions._exposed_actions:
            self.assertTrue(name in TestThing.actions)
        # instance level
        for name, action in thing.actions.values.items():
            self.assertIsInstance(action, BoundAction)
        for name in replace_methods_with_actions._exposed_actions:
            self.assertTrue(name in thing.actions)
        # cannot call an instance bound action at class level
        self.assertRaises(NotImplementedError, lambda: TestThing.action_echo(thing, 1))
        # but can call instance bound action with instance
        self.assertEqual(1, thing.action_echo(1))
        # can also call classmethods as usual
        self.assertEqual(2, TestThing.action_echo_with_classmethod(2))
        self.assertEqual(3, thing.action_echo_with_classmethod(3))
        # async methods behave similarly
        self.assertEqual(4, asyncio.run(thing.action_echo_async(4)))
        self.assertEqual(5, asyncio.run(TestThing.action_echo_async_with_classmethod(5)))
        self.assertRaises(NotImplementedError, lambda: asyncio.run(TestThing.action_echo(7)))
        # parameterized actions behave similarly
        self.assertEqual(
            ("test-action", 1, "hello1", 1.1),
            thing.parameterized_action(1, "hello1", 1.1),
        )
        self.assertEqual(
            ("test-action", 2, "hello2", "foo2"),
            asyncio.run(thing.parameterized_action_async(2, "hello2", "foo2")),
        )
        self.assertRaises(NotImplementedError, lambda: TestThing.parameterized_action(3, "hello3", 5))
        self.assertRaises(
            NotImplementedError,
            lambda: asyncio.run(TestThing.parameterized_action_async(4, "hello4", 5)),
        )

    def test_6_action_affordance(self):
        """Test if action affordance is correctly created"""
        thing = TestThing(id="test-action", log_level=logging.ERROR)

        assert isinstance(thing.action_echo, BoundAction)  # type definition
        affordance = thing.action_echo.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, not synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.action_echo_with_classmethod, BoundAction)  # type definition
        affordance = thing.action_echo_with_classmethod.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.action_echo_async, BoundAction)  # type definition
        affordance = thing.action_echo_async.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)  # type definition
        affordance = thing.action_echo_async_with_classmethod.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.parameterized_action, BoundAction)  # type definition
        affordance = thing.parameterized_action.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)
        self.assertTrue(affordance.synchronous)
        self.assertTrue(affordance.safe)
        self.assertIsNone(affordance.input)
        self.assertIsNone(affordance.output)
        self.assertIsNone(affordance.description)

        assert isinstance(thing.parameterized_action_without_call, BoundAction)  # type definition
        affordance = thing.parameterized_action_without_call.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.parameterized_action_async, BoundAction)  # type definition
        affordance = thing.parameterized_action_async.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, not synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsNone(affordance.input)  # no input schema
        self.assertIsNone(affordance.output)  # no output schema
        self.assertIsNone(affordance.description)  # no doc

        assert isinstance(thing.json_schema_validated_action, BoundAction)  # type definition
        affordance = thing.json_schema_validated_action.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertIsNone(affordance.idempotent)  # by default, not idempotent
        self.assertTrue(affordance.synchronous)  # by default, not synchronous
        self.assertIsNone(affordance.safe)  # by default, not safe
        self.assertIsInstance(affordance.input, dict)
        self.assertIsInstance(affordance.output, dict)
        self.assertIsNone(affordance.description)  # no doc


if __name__ == "__main__":
    unittest.main(testRunner=TestRunner())
