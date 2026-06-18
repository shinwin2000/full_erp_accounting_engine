from unittest.mock import AsyncMock, patch

import pytest

from adapters.secondary_impl.kafka_event_publisher_impl import KafkaEventPublisher


@pytest.mark.asyncio
async def test_publish_calls_producer_send():
    with patch(
        "adapters.secondary_impl.kafka_event_publisher_impl.AIOKafkaProducer"
    ) as MockProducer:
        mock_producer = AsyncMock()
        MockProducer.return_value = mock_producer

        publisher = KafkaEventPublisher(bootstrap_servers="localhost:9092")
        await publisher.start()
        event = {"type": "TestEvent", "data": "value"}
        await publisher.publish("test-topic", event)

        mock_producer.send_and_wait.assert_called_once_with(
            "test-topic",
            value=b'{"type": "TestEvent", "data": "value"}',
            key=None,
        )
        await publisher.stop()
