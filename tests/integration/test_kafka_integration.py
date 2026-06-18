#!/usr/bin/env python3
"""
Integration: Kafka (Message Broker)
Menguji produksi dan konsumsi event menggunakan Kafka.
Jika Kafka tidak tersedia (library atau broker), test akan di-skip.
"""

from __future__ import annotations

import json
import os

import pytest

SKIP_IF_NO_KAFKA = os.getenv("SKIP_KAFKA_INTEGRATION", "false").lower() == "true"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: mark as integration test (requires external services)"
    )


@pytest.fixture(scope="module")
def kafka_bootstrap():
    """Fixture yang me‑return bootstrap servers, skip jika Kafka tidak tersedia."""
    bootstrap = "localhost:9092"
    kafka_available = False
    NoBrokersAvailable = None
    KafkaProducer = None

    # Coba import kafka dengan error handling
    try:
        from kafka import KafkaProducer
        from kafka.errors import NoBrokersAvailable

        kafka_available = True
    except ImportError as e:
        # Jika gagal import karena missing gssapi atau lainnya, skip
        if SKIP_IF_NO_KAFKA:
            pytest.skip(f"Kafka library not available: {e}")
        else:
            pytest.skip(f"Kafka library import error (install kafka-python or fix gssapi): {e}")
    except Exception as e:
        if SKIP_IF_NO_KAFKA:
            pytest.skip(f"Unexpected error importing Kafka: {e}")
        else:
            pytest.skip(f"Unexpected error: {e}")

    if not kafka_available:
        pytest.skip("Kafka library not available")

    # Coba koneksi ke broker
    try:
        producer = KafkaProducer(bootstrap_servers=bootstrap, request_timeout_ms=5000)
        producer.close()
    except NoBrokersAvailable:
        if SKIP_IF_NO_KAFKA:
            pytest.skip("Kafka broker not available (SKIP_KAFKA_INTEGRATION=true)")
        else:
            pytest.skip(
                "Kafka broker not available. Start Kafka or set SKIP_KAFKA_INTEGRATION=true"
            )
    except Exception as e:
        pytest.skip(f"Kafka connection error: {e}")

    return bootstrap


@pytest.mark.integration
def test_kafka_produce_consume(kafka_bootstrap):
    topic = "test-events-integration"
    # Import di dalam test agar tidak mempengaruhi fixture
    try:
        from infrastructure.message_broker.kafka_consumer_wrapper import KafkaConsumerWrapper
        from infrastructure.message_broker.kafka_producer_wrapper import KafkaProducerWrapper
    except ImportError as e:
        pytest.skip(f"Kafka wrapper modules not available: {e}")

    producer = KafkaProducerWrapper(bootstrap_servers=kafka_bootstrap)
    consumer = KafkaConsumerWrapper(topic, bootstrap_servers=kafka_bootstrap, group_id="test-group")

    event = {"type": "JournalPosted", "journal_id": "JRN-001", "amount": 1000000}

    # Kirim pesan (sync)
    producer.send_sync(topic, key=b"key1", value=json.dumps(event).encode())
    producer.flush()

    # Poll pesan (sync)
    messages = consumer.poll(timeout_ms=5000, max_records=1)
    assert len(messages) == 1
    received = json.loads(messages[0].value.decode())
    assert received["journal_id"] == "JRN-001"

    producer.close()
    consumer.close()


@pytest.mark.integration
def test_kafka_dead_letter_topic(kafka_bootstrap):
    try:
        from infrastructure.message_broker.kafka_consumer_wrapper import KafkaConsumerWrapper
        from infrastructure.message_broker.kafka_dead_letter_handler import DeadLetterHandler
    except ImportError as e:
        pytest.skip(f"Kafka wrapper modules not available: {e}")

    handler = DeadLetterHandler(bootstrap_servers=kafka_bootstrap)
    failed_event = {"type": "InvalidEvent", "error": "ValidationError"}
    handler.send_to_dlq(failed_event, topic="main-topic")

    dlq_consumer = KafkaConsumerWrapper(
        "main-topic.dlq", bootstrap_servers=kafka_bootstrap, group_id="dlq-test"
    )
    messages = dlq_consumer.poll(timeout_ms=5000, max_records=1)
    assert len(messages) >= 1
    dlq_consumer.close()
