




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


    def test_4_db_operations(self):
        # remove old file path first
        file_path = f'{BaseDB.get_temp_dir_for_class_name(TestThing.__name__)}/test-db-operations.db'
        try:
            os.remove(file_path)
        except (OSError, FileNotFoundError):
            pass
        self.assertTrue(not os.path.exists(file_path))
    	
        # test db commit property
        thing = TestThing(id='test-db-operations', use_default_db=True, log_level=logging.WARN)
        self.assertEqual(thing.db_commit_number_prop, 0) # 0 is default just for reference
        thing.db_commit_number_prop = 100
        self.assertEqual(thing.db_commit_number_prop, 100)
        self.assertEqual(thing.db_engine.get_property('db_commit_number_prop'), 100)

        # test db persist property
        self.assertEqual(thing.db_persist_selector_prop, 'a') # a is default just for reference
        thing.db_persist_selector_prop = 'c'
        self.assertEqual(thing.db_persist_selector_prop, 'c')
        self.assertEqual(thing.db_engine.get_property('db_persist_selector_prop'), 'c')

        # test db init property
        self.assertEqual(thing.db_init_int_prop, 1) # 1 is default just for reference
        thing.db_init_int_prop = 50
        self.assertEqual(thing.db_init_int_prop, 50)
        self.assertNotEqual(thing.db_engine.get_property('db_init_int_prop'), 50)
        self.assertEqual(thing.db_engine.get_property('db_init_int_prop'), TestThing.db_init_int_prop.default)
        del thing

        # delete thing and reload from database 
        thing = TestThing(id='test-db-operations', use_default_db=True, log_level=logging.WARN)
        self.assertEqual(thing.db_init_int_prop, TestThing.db_init_int_prop.default)
        self.assertEqual(thing.db_persist_selector_prop, 'c')
        self.assertNotEqual(thing.db_commit_number_prop, 100)
        self.assertEqual(thing.db_commit_number_prop, TestThing.db_commit_number_prop.default)

        # check db init prop with a different value in database apart from default
        thing.db_engine.set_property('db_init_int_prop', 101)
        del thing
        thing = TestThing(id='test-db-operations', use_default_db=True, log_level=logging.WARN)
        self.assertEqual(thing.db_init_int_prop, 101)


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


    def test_7_json_db_operations(self):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            filename = tf.name

        # test db commit property
        thing = TestThing(id="test-db-operations", use_json_file=True,
                          json_filename=filename, log_level=logging.WARN)
        self.assertEqual(thing.db_commit_number_prop, 0)
        thing.db_commit_number_prop = 100
        self.assertEqual(thing.db_commit_number_prop, 100)
        self.assertEqual(thing.db_engine.get_property('db_commit_number_prop'), 100)

        # test db persist property
        self.assertEqual(thing.db_persist_selector_prop, 'a')
        thing.db_persist_selector_prop = 'c'
        self.assertEqual(thing.db_persist_selector_prop, 'c')
        self.assertEqual(thing.db_engine.get_property('db_persist_selector_prop'), 'c')

        # test db init property
        self.assertEqual(thing.db_init_int_prop, 1)
        thing.db_init_int_prop = 50
        self.assertEqual(thing.db_init_int_prop, 50)
        self.assertNotEqual(thing.db_engine.get_property('db_init_int_prop'), 50)
        self.assertEqual(thing.db_engine.get_property('db_init_int_prop'), TestThing.db_init_int_prop.default)
        del thing

        # delete thing and reload from database
        thing = TestThing(id="test-db-operations", use_json_file=True,
                          json_filename=filename, log_level=logging.WARN)
        self.assertEqual(thing.db_init_int_prop, TestThing.db_init_int_prop.default)
        self.assertEqual(thing.db_persist_selector_prop, 'c')
        self.assertNotEqual(thing.db_commit_number_prop, 100)
        self.assertEqual(thing.db_commit_number_prop, TestThing.db_commit_number_prop.default)

        # check db init prop with a different value in database apart from default
        thing.db_engine.set_property('db_init_int_prop', 101)
        del thing
        thing = TestThing(id="test-db-operations", use_json_file=True,
                          json_filename=filename, log_level=logging.WARN)
        self.assertEqual(thing.db_init_int_prop, 101)

        os.remove(filename)



class TestClassPropertyThing(Thing):
    # Simple class property with default value
    simple_class_prop = Number(class_member=True, default=42)
    
    # Class property with custom getter/setter
    managed_class_prop = Number(class_member=True)
    
    @managed_class_prop.getter
    def get_managed_class_prop(cls):
        return getattr(cls, '_managed_value', 0)
    
    @managed_class_prop.setter
    def set_managed_class_prop(cls, value):
        if value < 0:
            raise ValueError("Value must be non-negative")
        cls._managed_value = value
        
    # Read-only class property
    readonly_class_prop = String(class_member=True, readonly=True)
    
    @readonly_class_prop.getter
    def get_readonly_class_prop(cls):
        return "read-only-value"
    
    # Deletable class property
    deletable_class_prop = Number(class_member=True, default=100)
    
    @deletable_class_prop.getter
    def get_deletable_class_prop(cls):
        return getattr(cls, '_deletable_value', 100)
    
    @deletable_class_prop.setter
    def set_deletable_class_prop(cls, value):
        cls._deletable_value = value
        
    @deletable_class_prop.deleter
    def del_deletable_class_prop(cls):
        if hasattr(cls, '_deletable_value'):
            del cls._deletable_value

    not_a_class_prop = Number(class_member=False, default=43)

    @not_a_class_prop.getter
    def get_not_a_class_prop(self):
        return getattr(self, '_not_a_class_value', 43)
    
    @not_a_class_prop.setter
    def set_not_a_class_prop(self, value):
        self._not_a_class_value = value

    @not_a_class_prop.deleter
    def del_not_a_class_prop(self):
        if hasattr(self, '_not_a_class_value'):
            del self._not_a_class_value


class TestClassProperty(TestCase):
    
    def test_1_simple_class_property(self):
        """Test basic class property functionality"""
        # Test class-level access
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 42)
        TestClassPropertyThing.simple_class_prop = 100
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 100)
        
        # Test that instance-level access reflects class value
        instance1 = TestClassPropertyThing(id='test1', log_level=logging.WARN)
        instance2 = TestClassPropertyThing(id='test2', log_level=logging.WARN)
        self.assertEqual(instance1.simple_class_prop, 100)
        self.assertEqual(instance2.simple_class_prop, 100)
        
        # Test that instance-level changes affect class value
        instance1.simple_class_prop = 200
        self.assertEqual(TestClassPropertyThing.simple_class_prop, 200)
        self.assertEqual(instance2.simple_class_prop, 200)

    def test_2_managed_class_property(self):
        """Test class property with custom getter/setter"""
        # Test initial value
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 0)
        
        # Test valid value assignment
        TestClassPropertyThing.managed_class_prop= 50
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 50)
        
        # Test validation in setter
        with self.assertRaises(ValueError):
            TestClassPropertyThing.managed_class_prop = -10
            
        # Verify value wasn't changed after failed assignment
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 50)
        
        # Test instance-level validation
        instance = TestClassPropertyThing(id='test3', log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.managed_class_prop = -20
        
        # Test that instance-level access reflects class value
        self.assertEqual(instance.managed_class_prop, 50)

        # Test that instance-level changes affects class value
        instance.managed_class_prop = 100
        self.assertEqual(TestClassPropertyThing.managed_class_prop, 100)
        self.assertEqual(instance.managed_class_prop, 100)

    def test_3_readonly_class_property(self):
        """Test read-only class property behavior"""
        # Test reading the value
        self.assertEqual(TestClassPropertyThing.readonly_class_prop, "read-only-value")
        
        # Test that setting raises an error at class level
        with self.assertRaises(ValueError):
            TestClassPropertyThing.readonly_class_prop = "new-value"
            
        # Test that setting raises an error at instance level
        instance = TestClassPropertyThing(id='test4', log_level=logging.WARN)
        with self.assertRaises(ValueError):
            instance.readonly_class_prop = "new-value"
            
        # Verify value remains unchanged
        self.assertEqual(TestClassPropertyThing.readonly_class_prop, "read-only-value")
        self.assertEqual(instance.readonly_class_prop, "read-only-value")

    def test_4_deletable_class_property(self):
        """Test class property deletion"""
        # Test initial value
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)
        
        # Test setting new value
        TestClassPropertyThing.deletable_class_prop = 150
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 150)
        
        # Test deletion
        instance = TestClassPropertyThing(id='test5', log_level=logging.WARN)
        del TestClassPropertyThing.deletable_class_prop
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)  # Should return to default
        self.assertEqual(instance.deletable_class_prop, 100)
        
        # Test instance-level deletion
        instance.deletable_class_prop = 200
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 200)
        del instance.deletable_class_prop
        self.assertEqual(TestClassPropertyThing.deletable_class_prop, 100)  # Should return to default

    def test_5_descriptor_access(self):
        """Test descriptor access for class properties"""
        # Test direct access through descriptor
        instance = TestClassPropertyThing(id='test6', log_level=logging.WARN)
        self.assertIsInstance(TestClassPropertyThing.not_a_class_prop, Number)
        self.assertEqual(instance.not_a_class_prop, 43)
        instance.not_a_class_prop = 50
        self.assertEqual(instance.not_a_class_prop, 50)

        del instance.not_a_class_prop
        # deleter deletes only an internal instance variable
        self.assertTrue(hasattr(TestClassPropertyThing, 'not_a_class_prop')) 
        self.assertEqual(instance.not_a_class_prop, 43)

        del TestClassPropertyThing.not_a_class_prop
        # descriptor itself is deleted
        self.assertFalse(hasattr(TestClassPropertyThing, 'not_a_class_prop'))
        self.assertFalse(hasattr(instance, 'not_a_class_prop'))
        with self.assertRaises(AttributeError):
            instance.not_a_class_prop
        


if __name__ == '__main__':
    unittest.main(testRunner=TestRunner())
  