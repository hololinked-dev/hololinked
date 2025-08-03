




class TestThing:

   
    


    def test_3_observability(self):
        # req 1 - observable events come due to writing a property
        propective_values = [
            [1, 2, 3, 4, 5],
            ['a', 'b', 'c', 'd', 'e'],
            [1, 'a', 2, 'b', 3]
        ]
        result = []
        attempt = 0
        def cb(value):
            nonlocal attempt, result
            self.assertEqual(value, propective_values[attempt])
            result.append(value)
            attempt += 1

        self.thing_client.subscribe_event('observable_list_prop_change_event', cb)
        time.sleep(3)
        # Calm down for event publisher to connect fully as there is no handshake for events
        for value in propective_values:
            self.thing_client.observable_list_prop = value

        for i in range(20):
            if attempt == len(propective_values):
                break
            # wait for the callback to be called
            time.sleep(0.1)
        self.thing_client.unsubscribe_event('observable_list_prop_change_event')

        self.assertEqual(result, propective_values)

        # req 2 - observable events come due to reading a property
        propective_values = [1, 2, 3, 4, 5]
        result = []
        attempt = 0
        def cb(value):
            nonlocal attempt, result
            self.assertEqual(value, propective_values[attempt])
            result.append(value)
            attempt += 1

        self.thing_client.subscribe_event('observable_readonly_prop_change_event', cb)
        time.sleep(3)
        # Calm down for event publisher to connect fully as there is no handshake for events
        for _ in propective_values:
            self.thing_client.observable_readonly_prop

        for i in range(20):
            if attempt == len(propective_values):
                break
            # wait for the callback to be called
            time.sleep(0.1)

        self.thing_client.unsubscribe_event('observable_readonly_prop_change_event')
        self.assertEqual(result, propective_values)


    def test_5_json_schema_property(self):
        """Test json schema based property"""
        self.thing_client.json_schema_prop = 'hello'
        self.assertEqual(self.thing_client.json_schema_prop, 'hello')
        self.thing_client.json_schema_prop = 'world'
        self.assertEqual(self.thing_client.json_schema_prop, 'world')
        with self.assertRaises(Exception) as ex:
            self.thing_client.json_schema_prop = 'world1'
        self.assertTrue("Failed validating 'pattern' in schema:" in str(ex.exception))


    def test_6_pydantic_model_property(self):
        """Test pydantic model based property"""
        valid_value = {
            'foo': 'foo',
            'bar': 1,
            'foo_bar': 1.0
        }
        self.thing_client.pydantic_prop = valid_value
        self.assertEqual(self.thing_client.pydantic_prop, valid_value)

        invalid_value = {
            'foo': 1,
            'bar': '1',
            'foo_bar': 1.0
        }    
        with self.assertRaises(Exception) as ex:
            self.thing_client.pydantic_prop = invalid_value
        self.assertTrue("validation error for PydanticProp" in str(ex.exception))

        self.thing_client.pydantic_simple_prop = 5
        self.assertEqual(self.thing_client.pydantic_simple_prop, 5)
        with self.assertRaises(Exception) as ex:
            self.thing_client.pydantic_simple_prop = '5str'
        self.assertTrue("validation error for 'int'" in str(ex.exception))