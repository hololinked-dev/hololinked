

class Test:

     def _not_working_test_7_exposed_actions(self):
        """Test if actions can be invoked by a client"""
        start_thing_forked(
            thing_cls=self.thing_cls, 
            id='test-action', 
            done_queue=self.done_queue,
            log_level=logging.ERROR+10, 
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