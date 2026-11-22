"""Unit tests for custom MQTT topic registration (Issue #134)."""

import asyncio

from unittest.mock import MagicMock, patch

import pytest

from testkit.things import TestThing

from hololinked.client.mqtt.consumed_interactions import MQTTConsumer
from hololinked.metadata.td.interaction_affordance import PropertyAffordance
from hololinked.server.mqtt.config import TopicPublisherMetadata
from hololinked.server.mqtt.handlers import TopicPublisher
from hololinked.server.mqtt.server import MQTTPublisher
from hololinked.server.mqtt.services import ThingDescriptionService
from hololinked.utils import uuid_hex


@pytest.fixture
def test_thing():
    return TestThing(id=f"test-custom-{uuid_hex()}", serial_number="simulation")


@pytest.fixture
def publisher(test_thing):
    with patch("aiomqtt.Client"):
        pub = MQTTPublisher(
            hostname="localhost",
            port=1883,
            username="test",
            password="test",
            config={
                "topic_publisher": TopicPublisher,
                "qos": 1,
            },
        )
        pub.things[test_thing.id] = test_thing
        return pub


def test_add_observable_stores_custom_topic(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_observable("observable_readonly_prop", test_thing, "custom/prop/topic")
    assert publisher.publisher_overrides[(test_thing.id, "observable_readonly_prop")].topic == "custom/prop/topic"


def test_add_observable_stores_custom_qos(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_observable("observable_readonly_prop", test_thing, "custom/prop/topic", qos=2)
    assert publisher.publisher_overrides[(test_thing.id, "observable_readonly_prop")].qos == 2


def test_add_observable_leaves_qos_unset_when_none(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_observable("observable_readonly_prop", test_thing, "custom/prop/topic")
    assert publisher.publisher_overrides[(test_thing.id, "observable_readonly_prop")].qos is None


def test_add_observable_stores_custom_publisher(publisher: MQTTPublisher, test_thing: TestThing):
    class MyPublisher(TopicPublisher):
        pass

    publisher.add_observable(
        "observable_readonly_prop",
        test_thing,
        "custom/prop/topic",
        publisher=MyPublisher,
    )
    assert publisher.publisher_overrides[(test_thing.id, "observable_readonly_prop")].publisher_class is MyPublisher


def test_add_observable_raises_type_error_for_invalid_thing(publisher: MQTTPublisher):
    with pytest.raises(TypeError):
        publisher.add_observable("observable_readonly_prop", "not-a-thing", "topic")


def test_add_observable_raises_type_error_for_non_property(publisher: MQTTPublisher, test_thing: TestThing):
    with pytest.raises(TypeError):
        publisher.add_observable("non_existent", test_thing, "topic")


def test_add_property_is_alias_for_add_observable(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_property("observable_readonly_prop", test_thing, "custom/prop/topic")
    assert publisher.publisher_overrides[(test_thing.id, "observable_readonly_prop")].topic == "custom/prop/topic"


def test_add_event_stores_custom_topic(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_event("test_event", test_thing, "custom/event/topic")
    assert publisher.publisher_overrides[(test_thing.id, "test_event")].topic == "custom/event/topic"


def test_add_event_stores_custom_qos(publisher: MQTTPublisher, test_thing: TestThing):
    publisher.add_event("test_event", test_thing, "custom/event/topic", qos=2)
    assert publisher.publisher_overrides[(test_thing.id, "test_event")].qos == 2


def test_add_event_raises_type_error_for_invalid_thing(publisher: MQTTPublisher):
    with pytest.raises(TypeError):
        publisher.add_event("test_event", "not-a-thing", "topic")


def test_generate_uses_custom_topic_for_property(test_thing: TestThing):
    """TD form.mqv_topic should use custom topic for observable properties."""
    publisher_overrides = {
        (test_thing.id, "observable_readonly_prop"): TopicPublisherMetadata(topic="custom/prop/topic")
    }

    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        publisher_overrides=publisher_overrides,
    )

    td = asyncio.run(service.generate(ignore_errors=True))

    forms = td["properties"]["observable_readonly_prop"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert "custom/prop/topic" in mqv_topics


def test_generate_uses_custom_topic_for_event(test_thing: TestThing):
    """TD form.mqv_topic should use custom topic for events."""
    publisher_overrides = {(test_thing.id, "test_event"): TopicPublisherMetadata(topic="custom/event/topic")}

    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        publisher_overrides=publisher_overrides,
    )

    td = asyncio.run(service.generate(ignore_errors=True))

    forms = td["events"]["test_event"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert "custom/event/topic" in mqv_topics


def test_generate_uses_default_topic_when_not_custom(test_thing: TestThing):
    """TD form.mqv_topic should fall back to auto-generated topic."""
    service = ThingDescriptionService(
        hostname="localhost",
        port=1883,
        logger=MagicMock(),
        thing=test_thing,
        ssl=False,
        use_websocket=False,
        publisher_overrides={},
    )

    td = asyncio.run(service.generate(ignore_errors=True))

    forms = td["properties"]["observable_readonly_prop"]["forms"]
    mqv_topics = [f.get("mqv:topic") or f.get("mqv_topic") for f in forms]
    assert f"{test_thing.id}/observable_readonly_prop" in mqv_topics


def mock_consumer(topic: str | None):
    """Helper: create MQTTConsumer with mocked clients whose form carries the given topic."""
    sync_client = MagicMock()
    async_client = MagicMock()
    logger = MagicMock()
    resource = MagicMock(spec=PropertyAffordance)
    resource.thing_id = "test-thing"
    resource.name = "custom_prop"
    resource.retrieve_form.return_value = MagicMock(mqv_topic=topic)

    consumer = MQTTConsumer(
        sync_client=sync_client,
        async_client=async_client,
        resource=resource,
        qos=1,
        logger=logger,
        owner_inst=MagicMock(),
    )
    return consumer


def test_unsubscribe_uses_form_topic():
    """unsubscribe() should use the topic from the form if available."""
    consumer = mock_consumer("custom/prop/topic")
    consumer.unsubscribe()
    consumer.sync_client.message_callback_remove.assert_called_once_with("custom/prop/topic")


def test_unsubscribe_falls_back_to_default_topic():
    """unsubscribe() should fall back to auto-generated topic when the form has no topic."""
    consumer = mock_consumer(None)
    consumer.unsubscribe()
    consumer.sync_client.message_callback_remove.assert_called_once_with("test-thing/custom_prop")
