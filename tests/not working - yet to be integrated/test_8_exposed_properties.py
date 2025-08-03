




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