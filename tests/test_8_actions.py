import asyncio
import typing
import unittest
import logging
import multiprocessing
import jsonschema

from hololinked.utils import isclassmethod
from hololinked.param import ParameterizedFunction
from hololinked.server.actions import Action, BoundAction, BoundSyncAction, BoundAsyncAction
from hololinked.server.dataklasses import ActionInfoValidator
from hololinked.server.thing import Thing, action
from hololinked.server.properties import Number, String, ClassSelector
from hololinked.td.interaction_affordance import ActionAffordance
from hololinked.protocols.zmq import SyncZMQClient
from hololinked.protocols.zmq.message import EXIT, RequestMessage
from hololinked.protocols.zmq.client import ZMQAction
from hololinked.schema_validators import JsonSchemaValidator
try:
    from .utils import TestCase, TestRunner
    from .things import start_thing_forked 
except ImportError:
    from utils import TestCase, TestRunner
    from things import start_thing_forked 



class TestThing(Thing):

    def action_echo(self, value):
        return value

    @classmethod
    def action_echo_with_classmethod(self, value):
        return value
    
    async def action_echo_async(self, value):
        await asyncio.sleep(0.1)
        return value
    
    @classmethod
    async def action_echo_async_with_classmethod(self, value):
        await asyncio.sleep(0.1)
        return value
    
    class parameterized_action(ParameterizedFunction):

        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

        def __call__(self, instance, arg1, arg2, arg3):
            return instance.id, arg1, arg2, arg3

    class parameterized_action_without_call(ParameterizedFunction):

        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

    class parameterized_action_async(ParameterizedFunction):
            
        arg1 = Number(bounds=(0, 10), step=0.5, default=5, crop_to_bounds=True, 
                    doc='arg1 description')
        arg2 = String(default='hello', doc='arg2 description', regex='[a-z]+')
        arg3 = ClassSelector(class_=(int, float, str),
                            default=5, doc='arg3 description')

        async def __call__(self, instance, arg1, arg2, arg3):
            await asyncio.sleep(0.1)
            return instance.id, arg1, arg2, arg3

    def __internal__(self, value):
        return value

    def incorrectly_decorated_method(self, value):
        return value
    
    def not_an_action(self, value):
        return value
    
    async def not_an_async_action(self, value):
        await asyncio.sleep(0.1)
        return value
    
    def json_schema_validated_action(self, val1: int, val2: str, val3: dict, val4: list):
        return {
            'val1': val1,
            'val3': val3           
        }
    
    def pydantic_validated_action(self, val1: int, val2: str, val3: dict, val4: list) -> typing.Dict[str, typing.Union[int, dict]]:
        return {
            'val2': val2,
            'val4': val4           
        }
    
    

class TestAction(TestCase):

    @classmethod
    def setUpClass(self):
        super().setUpClass()
        print(f"test action with {self.__name__}")
        self.thing_cls = TestThing 
        self.client = SyncZMQClient(id='test-action-client', server_id='test-action', log_level=logging.ERROR, 
                                    handshake=False)
        self.done_queue = multiprocessing.Queue()


    def test_1_allowed_actions(self):
        """Test if methods can be decorated with action"""
        # 1. instance method can be decorated with action
        self.assertEqual(Action(self.thing_cls.action_echo), action()(self.thing_cls.action_echo))
        # 2. classmethod can be decorated with action
        self.assertEqual(Action(self.thing_cls.action_echo_with_classmethod), 
                        action()(self.thing_cls.action_echo_with_classmethod))
        self.assertTrue(isclassmethod(self.thing_cls.action_echo_with_classmethod))
        # 3. async methods can be decorated with action    
        self.assertEqual(Action(self.thing_cls.action_echo_async), 
                        action()(self.thing_cls.action_echo_async))
        # 4. async classmethods can be decorated with action
        self.assertEqual(Action(self.thing_cls.action_echo_async_with_classmethod), 
                        action()(self.thing_cls.action_echo_async_with_classmethod))
        self.assertTrue(isclassmethod(self.thing_cls.action_echo_async_with_classmethod))
        # 5. parameterized function can be decorated with action
        self.assertEqual(Action(self.thing_cls.parameterized_action), 
                            action(safe=True)(self.thing_cls.parameterized_action))
        self.assertEqual(Action(self.thing_cls.parameterized_action_without_call), 
                            action(idempotent=True)(self.thing_cls.parameterized_action_without_call))
        self.assertEqual(Action(self.thing_cls.parameterized_action_async), 
                            action(synchronous=True)(self.thing_cls.parameterized_action_async))
        # 6. actions with input and output schema
        self.assertEqual(Action(self.thing_cls.json_schema_validated_action),
                            action(input_schema={'val1': 'integer', 'val2': 'string', 'val3': 'object', 'val4': 'array'},
                                      output_schema={'val1': 'int', 'val3': 'dict'})(self.thing_cls.json_schema_validated_action))
        self.assertEqual(Action(self.thing_cls.pydantic_validated_action),
                            action()(self.thing_cls.pydantic_validated_action))  
        

    def test_2_bound_method(self):
        """Test if methods decorated with action are correctly bound"""
        thing = self.thing_cls(id='test-action', log_level=logging.ERROR)
        replace_methods_with_actions(thing_cls=self.thing_cls)

        # 1. instance method can be decorated with action
        self.assertIsInstance(thing.action_echo, BoundAction)
        self.assertIsInstance(thing.action_echo, BoundSyncAction)
        self.assertNotIsInstance(thing.action_echo, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.action_echo, Action)
        self.assertNotIsInstance(self.thing_cls.action_echo, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo, BoundAction) # type definition
        self.assertEqual(thing.action_echo.name, 'action_echo')
        self.assertEqual(thing.action_echo.owner_inst, thing)
        self.assertEqual(thing.action_echo.owner, self.thing_cls)
        self.assertEqual(thing.action_echo.execution_info, self.thing_cls.action_echo.execution_info)
        self.assertEqual(str(thing.action_echo), 
                        f"<BoundAction({self.thing_cls.__name__}.{thing.action_echo.name} of {thing.id})>") 
        self.assertNotEqual(thing.action_echo, self.thing_cls.action_echo)
        self.assertEqual(thing.action_echo.bound_obj, thing)
          
        # 2. classmethod can be decorated with action
        self.assertIsInstance(thing.action_echo_with_classmethod, BoundAction)
        self.assertIsInstance(thing.action_echo_with_classmethod, BoundSyncAction)
        self.assertNotIsInstance(thing.action_echo_with_classmethod, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.action_echo_with_classmethod, BoundAction)
        self.assertIsInstance(self.thing_cls.action_echo_with_classmethod, BoundSyncAction)
        self.assertNotIsInstance(self.thing_cls.action_echo_with_classmethod, Action)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_with_classmethod, BoundAction)
        self.assertEqual(thing.action_echo_with_classmethod.name, 'action_echo_with_classmethod')
        self.assertEqual(thing.action_echo_with_classmethod.owner_inst, thing)
        self.assertEqual(thing.action_echo_with_classmethod.owner, self.thing_cls)
        self.assertEqual(thing.action_echo_with_classmethod.execution_info, self.thing_cls.action_echo_with_classmethod.execution_info)
        self.assertEqual(str(thing.action_echo_with_classmethod),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.action_echo_with_classmethod.name} of {thing.id})>")
        self.assertEqual(thing.action_echo_with_classmethod, self.thing_cls.action_echo_with_classmethod)
        self.assertEqual(thing.action_echo_with_classmethod.bound_obj, self.thing_cls)
        
        # 3. async methods can be decorated with action
        self.assertIsInstance(thing.action_echo_async, BoundAction)
        self.assertNotIsInstance(thing.action_echo_async, BoundSyncAction)
        self.assertIsInstance(thing.action_echo_async, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.action_echo_async, Action)
        self.assertNotIsInstance(self.thing_cls.action_echo_async, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_async, BoundAction)
        self.assertEqual(thing.action_echo_async.name, 'action_echo_async')
        self.assertEqual(thing.action_echo_async.owner_inst, thing)
        self.assertEqual(thing.action_echo_async.owner, self.thing_cls)
        self.assertEqual(thing.action_echo_async.execution_info, self.thing_cls.action_echo_async.execution_info)
        self.assertEqual(str(thing.action_echo_async),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.action_echo_async.name} of {thing.id})>")
        self.assertNotEqual(thing.action_echo_async, self.thing_cls.action_echo_async)
        self.assertEqual(thing.action_echo_async.bound_obj, thing)
        
        # 4. async classmethods can be decorated with action
        self.assertIsInstance(thing.action_echo_async_with_classmethod, BoundAction)
        self.assertNotIsInstance(thing.action_echo_async_with_classmethod, BoundSyncAction)
        self.assertIsInstance(thing.action_echo_async_with_classmethod, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.action_echo_async_with_classmethod, BoundAction)
        self.assertIsInstance(self.thing_cls.action_echo_async_with_classmethod, BoundAsyncAction)
        self.assertNotIsInstance(self.thing_cls.action_echo_async_with_classmethod, Action)
        # associated attributes of BoundAction
        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction)
        self.assertEqual(thing.action_echo_async_with_classmethod.name, 'action_echo_async_with_classmethod')
        self.assertEqual(thing.action_echo_async_with_classmethod.owner_inst, thing)
        self.assertEqual(thing.action_echo_async_with_classmethod.owner, self.thing_cls)
        self.assertEqual(thing.action_echo_async_with_classmethod.execution_info, self.thing_cls.action_echo_async_with_classmethod.execution_info)
        self.assertEqual(str(thing.action_echo_async_with_classmethod),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.action_echo_async_with_classmethod.name} of {thing.id})>")
        self.assertEqual(thing.action_echo_async_with_classmethod, self.thing_cls.action_echo_async_with_classmethod)
        self.assertEqual(thing.action_echo_async_with_classmethod.bound_obj, self.thing_cls)

        # 5. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action, BoundAction)
        self.assertIsInstance(thing.parameterized_action, BoundSyncAction)
        self.assertNotIsInstance(thing.parameterized_action, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.parameterized_action, Action)
        self.assertNotIsInstance(self.thing_cls.parameterized_action, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action, BoundAction)
        self.assertEqual(thing.parameterized_action.name, 'parameterized_action')
        self.assertEqual(thing.parameterized_action.owner_inst, thing)
        self.assertEqual(thing.parameterized_action.owner, self.thing_cls)
        self.assertEqual(thing.parameterized_action.execution_info, self.thing_cls.parameterized_action.execution_info)
        self.assertEqual(str(thing.parameterized_action),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.parameterized_action.name} of {thing.id})>")
        self.assertNotEqual(thing.parameterized_action, self.thing_cls.parameterized_action)
        self.assertEqual(thing.parameterized_action.bound_obj, thing)

        # 6. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action_without_call, BoundAction)
        self.assertIsInstance(thing.parameterized_action_without_call, BoundSyncAction)
        self.assertNotIsInstance(thing.parameterized_action_without_call, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.parameterized_action_without_call, Action)
        self.assertNotIsInstance(self.thing_cls.parameterized_action_without_call, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action_without_call, BoundAction)
        self.assertEqual(thing.parameterized_action_without_call.name, 'parameterized_action_without_call')
        self.assertEqual(thing.parameterized_action_without_call.owner_inst, thing)
        self.assertEqual(thing.parameterized_action_without_call.owner, self.thing_cls)
        self.assertEqual(thing.parameterized_action_without_call.execution_info, self.thing_cls.parameterized_action_without_call.execution_info)
        self.assertEqual(str(thing.parameterized_action_without_call),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.parameterized_action_without_call.name} of {thing.id})>")
        self.assertNotEqual(thing.parameterized_action_without_call, self.thing_cls.parameterized_action_without_call)
        self.assertEqual(thing.parameterized_action_without_call.bound_obj, thing)

        # 7. parameterized function can be decorated with action
        self.assertIsInstance(thing.parameterized_action_async, BoundAction)
        self.assertNotIsInstance(thing.parameterized_action_async, BoundSyncAction)
        self.assertIsInstance(thing.parameterized_action_async, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.parameterized_action_async, Action)
        self.assertNotIsInstance(self.thing_cls.parameterized_action_async, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.parameterized_action_async, BoundAction)
        self.assertEqual(thing.parameterized_action_async.name, 'parameterized_action_async')
        self.assertEqual(thing.parameterized_action_async.owner_inst, thing)
        self.assertEqual(thing.parameterized_action_async.owner, self.thing_cls)
        self.assertEqual(thing.parameterized_action_async.execution_info, self.thing_cls.parameterized_action_async.execution_info)
        self.assertEqual(str(thing.parameterized_action_async),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.parameterized_action_async.name} of {thing.id})>")
        self.assertNotEqual(thing.parameterized_action_async, self.thing_cls.parameterized_action_async)
        self.assertEqual(thing.parameterized_action_async.bound_obj, thing)

        # 8. actions with input and output schema
        self.assertIsInstance(thing.json_schema_validated_action, BoundAction)
        self.assertIsInstance(thing.json_schema_validated_action, BoundSyncAction)
        self.assertNotIsInstance(thing.json_schema_validated_action, BoundAsyncAction)
        self.assertIsInstance(self.thing_cls.json_schema_validated_action, Action)
        self.assertNotIsInstance(self.thing_cls.json_schema_validated_action, BoundAction)
        # associated attributes of BoundAction
        assert isinstance(thing.json_schema_validated_action, BoundAction)
        self.assertEqual(thing.json_schema_validated_action.name, 'json_schema_validated_action')
        self.assertEqual(thing.json_schema_validated_action.owner_inst, thing)
        self.assertEqual(thing.json_schema_validated_action.owner, self.thing_cls)
        self.assertEqual(thing.json_schema_validated_action.execution_info, self.thing_cls.json_schema_validated_action.execution_info)
        self.assertEqual(str(thing.json_schema_validated_action),
                        f"<BoundAction({self.thing_cls.__name__}.{thing.json_schema_validated_action.name} of {thing.id})>")
        self.assertNotEqual(thing.json_schema_validated_action, self.thing_cls.json_schema_validated_action)
        self.assertEqual(thing.json_schema_validated_action.bound_obj, thing)


    def test_3_remote_info(self):
        """Test if the validator is working correctly, on which the logic of the action is based"""
        # basic check if the remote_info is correct, although this test is not necessary, not recommended and 
        # neither particularly useful
        remote_info = self.thing_cls.action_echo.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator) # type definition
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.safe)  
        self.assertFalse(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)

        remote_info = self.thing_cls.action_echo_async.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator) # type definition
        self.assertTrue(remote_info.isaction)
        self.assertTrue(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)

        remote_info = self.thing_cls.action_echo_with_classmethod.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator) # type definition
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)

        remote_info = self.thing_cls.parameterized_action.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertTrue(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)

        remote_info = self.thing_cls.parameterized_action_without_call.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertTrue(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)

        remote_info = self.thing_cls.parameterized_action_async.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertTrue(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertTrue(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertTrue(remote_info.synchronous)

        remote_info = self.thing_cls.json_schema_validated_action.execution_info
        self.assertIsInstance(remote_info, ActionInfoValidator)
        assert isinstance(remote_info, ActionInfoValidator)
        self.assertTrue(remote_info.isaction)
        self.assertFalse(remote_info.iscoroutine)
        self.assertFalse(remote_info.isproperty)
        self.assertFalse(remote_info.isparameterized)
        self.assertFalse(remote_info.safe)
        self.assertFalse(remote_info.idempotent)
        self.assertFalse(remote_info.synchronous)
        self.assertIsInstance(remote_info.schema_validator, JsonSchemaValidator)


    def test_4_api_and_invalid_actions(self):
        """Test if action prevents invalid objects from being named as actions and raises neat errors"""
        # done allow action decorator to be terminated without '()' on a method
        with self.assertRaises(TypeError) as ex:
           action(self.thing_cls.incorrectly_decorated_method)
        self.assertTrue(str(ex.exception).startswith("input schema should be a JSON or pydantic BaseModel, not a function/method, did you decorate your action wrongly?"))
        
        # dunder methods cannot be decorated with action
        with self.assertRaises(ValueError) as ex:
            action()(self.thing_cls.__internal__)
        self.assertTrue(str(ex.exception).startswith("dunder objects cannot become remote"))

        # only functions and methods can be decorated with action
        for obj in [self.thing_cls, str, 1, 1.0, 'Str', True, None, object(), type, property]:
            with self.assertRaises(TypeError) as ex:
                action()(obj) # not an action
            self.assertTrue(str(ex.exception).startswith("target for action or is not a function/method."))

        with self.assertRaises(ValueError) as ex:
            action(safe=True, some_kw=1)
        self.assertTrue(str(ex.exception).startswith("Only 'safe', 'idempotent', 'synchronous' are allowed"))


    def test_5_thing_cls_actions(self):
        """Test class and instance level action access"""
        thing = self.thing_cls(id='test-action', log_level=logging.ERROR)
        # class level
        for name, action in self.thing_cls.actions.items():  
            self.assertIsInstance(action, Action) 
        for name in replace_methods_with_actions._exposed_actions:
            self.assertTrue(name in self.thing_cls.actions)
        # instance level 
        for name, action in thing.actions.items(): 
            self.assertIsInstance(action, BoundAction)
        for name in replace_methods_with_actions._exposed_actions:
            self.assertTrue(name in thing.actions)
        # cannot call an instance bound action at class level
        self.assertRaises(NotImplementedError, lambda: self.thing_cls.action_echo(thing, 1))
        # but can call instance bound action with instance
        self.assertEqual(1, thing.action_echo(1))
        # can also call classmethods as usual 
        self.assertEqual(2, self.thing_cls.action_echo_with_classmethod(2))
        self.assertEqual(3, thing.action_echo_with_classmethod(3))            
        # async methods behave similarly 
        self.assertEqual(4, asyncio.run(thing.action_echo_async(4)))
        self.assertEqual(5, asyncio.run(self.thing_cls.action_echo_async_with_classmethod(5)))
        self.assertRaises(NotImplementedError, lambda: asyncio.run(self.thing_cls.action_echo(7)))
        # parameterized actions behave similarly
        self.assertEqual(('test-action', 1, 'hello1', 1.1), thing.parameterized_action(1, 'hello1', 1.1))
        self.assertEqual(('test-action', 2, 'hello2', 'foo2'), asyncio.run(thing.parameterized_action_async(2, 'hello2', 'foo2')))
        self.assertRaises(NotImplementedError, lambda: self.thing_cls.parameterized_action(3, 'hello3', 5))
        self.assertRaises(NotImplementedError, lambda: asyncio.run(self.thing_cls.parameterized_action_async(4, 'hello4', 5)))


    def test_6_action_affordance(self):
        """Test if action affordance is correctly created"""
        thing = TestThing(id='test-action', log_level=logging.ERROR)

        assert isinstance(thing.action_echo, BoundAction) # type definition
        affordance = thing.action_echo.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc
        
        assert isinstance(thing.action_echo_with_classmethod, BoundAction) # type definition
        affordance = thing.action_echo_with_classmethod.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.action_echo_async, BoundAction) # type definition
        affordance = thing.action_echo_async.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction) # type definition
        affordance = thing.action_echo_async_with_classmethod.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.parameterized_action, BoundAction) # type definition
        affordance = thing.parameterized_action.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(affordance.safe) # by default, not safe
        # self.assertIsInstance(affordance.input, dict)
        # self.assertIsInstance(affordance.output, dict)
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.parameterized_action_without_call, BoundAction) # type definition
        affordance = thing.parameterized_action_without_call.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(affordance.idempotent) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.parameterized_action_async, BoundAction) # type definition
        affordance = thing.parameterized_action_async.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(affordance.synchronous) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertTrue(not hasattr(affordance, 'input')) # no input schema
        self.assertTrue(not hasattr(affordance, 'output')) # no output schema
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        assert isinstance(thing.json_schema_validated_action, BoundAction) # type definition
        affordance = thing.json_schema_validated_action.to_affordance()
        self.assertIsInstance(affordance, ActionAffordance)
        self.assertTrue(not hasattr(affordance, 'idempotent')) # by default, not idempotent
        self.assertTrue(not hasattr(affordance, 'synchronous')) # by default, not synchronous
        self.assertTrue(not hasattr(affordance, 'safe')) # by default, not safe
        self.assertIsInstance(affordance.input, dict)
        self.assertIsInstance(affordance.output, dict)
        self.assertTrue(not hasattr(affordance, 'description')) # no doc

        
    def test_7_exposed_actions(self):
        """Test if actions can be invoked by a client"""
        start_thing_forked(
            thing_cls=self.thing_cls, 
            id='test-action', 
            done_queue=self.done_queue,
            log_level=logging.ERROR + 10, 
            prerun_callback=replace_methods_with_actions,
        )
        thing = self.thing_cls(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # thing_client = ObjectProxy('test-action', log_level=logging.ERROR) # type: TestThing
        assert isinstance(thing.action_echo, BoundAction) # type definition
        action_echo = ZMQAction(
            resource=thing.action_echo.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo(1), 1)
        
        assert isinstance(thing.action_echo_with_classmethod, BoundAction) # type definition
        action_echo_with_classmethod = ZMQAction(
            resource=thing.action_echo_with_classmethod.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_with_classmethod(2), 2)

        assert isinstance(thing.action_echo_async, BoundAction) # type definition
        action_echo_async = ZMQAction(
            resource=thing.action_echo_async.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_async("string"), "string")

        assert isinstance(thing.action_echo_async_with_classmethod, BoundAction) # type definition
        action_echo_async_with_classmethod = ZMQAction(
            resource=thing.action_echo_async_with_classmethod.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(action_echo_async_with_classmethod([1, 2]), [1, 2])

        assert isinstance(thing.parameterized_action, BoundAction) # type definition
        parameterized_action = ZMQAction(
            resource=thing.parameterized_action.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(parameterized_action(arg1=1, arg2='hello', arg3=5), ['test-action', 1, 'hello', 5])

        assert isinstance(thing.parameterized_action_async, BoundAction) # type definition
        parameterized_action_async = ZMQAction(
            resource=thing.parameterized_action_async.to_affordance(),
            sync_client=self.client
        )
        self.assertEqual(parameterized_action_async(arg1=2.5, arg2='hello', arg3='foo'), ['test-action', 2.5, 'hello', 'foo'])

        assert isinstance(thing.parameterized_action_without_call, BoundAction) # type definition
        parameterized_action_without_call = ZMQAction(
            resource=thing.parameterized_action_without_call.to_affordance(),
            sync_client=self.client
        )
        with self.assertRaises(NotImplementedError) as ex:
            parameterized_action_without_call(arg1=2, arg2='hello', arg3=5)
        self.assertTrue(str(ex.exception).startswith("Subclasses must implement __call__"))
        

    def test_8_schema_validation(self):
        """Test if schema validation is working correctly"""
        self._test_8_json_schema_validation()
        self._test_8_pydantic_validation()

    
    def _test_8_json_schema_validation(self):

        thing = self.thing_cls(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # JSON schema validation
        assert isinstance(thing.json_schema_validated_action, BoundAction) # type definition
        action_affordance = thing.json_schema_validated_action.to_affordance()
        json_schema_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=self.client
        )
        # data with invalid schema 
        with self.assertRaises(Exception) as ex1:
            json_schema_validated_action(val1='1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex1.exception).startswith("'1' is not of type 'integer'"))
        with self.assertRaises(Exception) as ex2:
            json_schema_validated_action('1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex2.exception).startswith("'1' is not of type 'integer'"))
        with self.assertRaises(Exception) as ex3:
            json_schema_validated_action(1, 2, val3={'field' : 'value'}, val4=[])
        self.assertTrue(str(ex3.exception).startswith("2 is not of type 'string'"))
        with self.assertRaises(Exception) as ex4:
            json_schema_validated_action(1, 'hello', val3='field', val4=[])
        self.assertTrue(str(ex4.exception).startswith("'field' is not of type 'object'"))
        with self.assertRaises(Exception) as ex5:
            json_schema_validated_action(1, 'hello', val3={'field' : 'value'}, val4='[]')
        self.assertTrue(str(ex5.exception).startswith("'[]' is not of type 'array'"))
        # data with valid schema
        return_value = json_schema_validated_action(val1=1, val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertEqual(return_value, {'val1': 1, 'val3': {'field': 'value'}})
        jsonschema.Draft7Validator(action_affordance.output).validate(return_value)

    
    def _test_8_pydantic_validation(self):

        thing = self.thing_cls(id='test-action', log_level=logging.ERROR)
        self.client.handshake()

        # Pydantic schema validation
        assert isinstance(thing.pydantic_validated_action, BoundAction) # type definition
        action_affordance = thing.pydantic_validated_action.to_affordance()
        pydantic_validated_action = ZMQAction(
            resource=action_affordance,
            sync_client=self.client
        )
        # data with invalid schema
        with self.assertRaises(Exception) as ex1:
            pydantic_validated_action(val1='1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex1.exception) and 
            'val1' in str(ex1.exception) and 'val2' not in str(ex1.exception) and 'val3' not in str(ex1.exception) and 
            'val4' not in str(ex1.exception)
        ) # {obj.name}_input is the pydantic model name
        with self.assertRaises(Exception) as ex2:
            pydantic_validated_action('1', val2='hello', val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex2.exception) and 
            'val1' in str(ex2.exception) and 'val2' not in str(ex2.exception) and 'val3' not in str(ex2.exception) and
            'val4' not in str(ex2.exception)
        )
        with self.assertRaises(Exception) as ex3:
            pydantic_validated_action(1, 2, val3={'field' : 'value'}, val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex3.exception) and 
            'val1' not in str(ex3.exception) and 'val2' in str(ex3.exception) and 'val3' not in str(ex3.exception) and
            'val4' not in str(ex3.exception)           
        )
        with self.assertRaises(Exception) as ex4:
            pydantic_validated_action(1, 'hello', val3='field', val4=[])
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex4.exception) and 
            'val1' not in str(ex4.exception) and 'val2' not in str(ex4.exception) and 'val3' in str(ex4.exception) and
            'val4' not in str(ex4.exception)            
        )
        with self.assertRaises(Exception) as ex5:
            pydantic_validated_action(1, 'hello', val3={'field' : 'value'}, val4='[]')
        self.assertTrue(
            "validation error for pydantic_validated_action_input" in str(ex5.exception) and 
            'val1' not in str(ex5.exception) and 'val2' not in str(ex5.exception) and 'val3' not in str(ex5.exception) and
            'val4' in str(ex5.exception)
        )
        # data with valid schema
        return_value = pydantic_validated_action(val1=1, val2='hello', val3={'field' : 'value'}, val4=[])        
        self.assertEqual(return_value, {'val2': 'hello', 'val4': []})


    def test_9_exit(self):
        exit_message = RequestMessage.craft_with_message_type(
            sender_id='test-action-client', 
            receiver_id='test-action',
            message_type=EXIT
        )
        self.client.socket.send_multipart(exit_message.byte_array)

        self.assertEqual(self.done_queue.get(), 'test-action')



def replace_methods_with_actions(thing_cls):
    thing_cls.action_echo = action()(thing_cls.action_echo)
    thing_cls.action_echo.__set_name__(thing_cls, 'action_echo')
    # classmethod can be decorated with action   
    thing_cls.action_echo_with_classmethod = action()(thing_cls.action_echo_with_classmethod)   
    # BoundAction already, cannot call __set_name__ on it, at least at the time of writing

    # async methods can be decorated with action       
    thing_cls.action_echo_async = action()(thing_cls.action_echo_async)
    thing_cls.action_echo_async.__set_name__(thing_cls, 'action_echo_async')
    # async classmethods can be decorated with action    
    thing_cls.action_echo_async_with_classmethod = action()(thing_cls.action_echo_async_with_classmethod)
    # BoundAction already, cannot call __set_name__ on it, at least at the time of writing

    # parameterized function can be decorated with action
    thing_cls.parameterized_action = action(safe=True)(thing_cls.parameterized_action)
    thing_cls.parameterized_action.__set_name__(thing_cls, 'parameterized_action')  

    thing_cls.parameterized_action_without_call = action(idempotent=True)(thing_cls.parameterized_action_without_call)
    thing_cls.parameterized_action_without_call.__set_name__(thing_cls, 'parameterized_action_without_call')

    thing_cls.parameterized_action_async = action(synchronous=True)(thing_cls.parameterized_action_async)
    thing_cls.parameterized_action_async.__set_name__(thing_cls, 'parameterized_action_async')

    # schema validated actions
    thing_cls.json_schema_validated_action = action(
        input_schema={
            'type': 'object',
            'properties': {
                'val1': {'type': 'integer'},
                'val2': {'type': 'string'},
                'val3': {'type': 'object'},
                'val4': {'type': 'array'}
            }
        },
        output_schema={
            'type': 'object',
            'properties': {
                'val1': {'type': 'integer'},
                'val3': {'type': 'object'}
            }
        }
    )(thing_cls.json_schema_validated_action)
    thing_cls.json_schema_validated_action.__set_name__(thing_cls, 'json_schema_validated_action')

    thing_cls.pydantic_validated_action = action()(thing_cls.pydantic_validated_action)
    thing_cls.pydantic_validated_action.__set_name__(thing_cls, 'pydantic_validated_action')


    replace_methods_with_actions._exposed_actions = [
                                    'action_echo', 'action_echo_with_classmethod', 'action_echo_async',
                                    'action_echo_async_with_classmethod', 'parameterized_action', 'parameterized_action_without_call',
                                    'parameterized_action_async', 'json_schema_validated_action'
                                ]



if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())