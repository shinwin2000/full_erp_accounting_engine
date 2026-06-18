#!/usr/bin/env python3
"""
Module: broker_exceptions.py
Layer: Infrastructure (Message Broker)
Responsibility: Mendefinisikan semua exception untuk message broker.
"""

from __future__ import annotations


class BrokerError(Exception):
    """Base exception untuk message broker."""

    pass


class KafkaProducerError(BrokerError):
    """Error pada Kafka producer."""

    pass


class KafkaSendError(KafkaProducerError):
    """Error saat mengirim pesan ke Kafka."""

    pass


class KafkaNotAvailableError(KafkaProducerError):
    """Kafka tidak tersedia."""

    pass


class KafkaConsumerError(BrokerError):
    """Error pada Kafka consumer."""

    pass


class KafkaConsumeError(KafkaConsumerError):
    """Error saat consume pesan."""

    pass


class DeadLetterHandlerError(BrokerError):
    """Error pada dead letter handler."""

    pass


class DLQProcessingError(DeadLetterHandlerError):
    """Error saat memproses DLQ."""

    pass


class OutboxPollerError(BrokerError):
    """Error pada outbox poller."""

    pass


class OutboxLockError(OutboxPollerError):
    """Error lock pada outbox poller."""

    pass


class SchemaRegistryError(BrokerError):
    """Error pada schema registry."""

    pass


class SchemaNotFoundError(SchemaRegistryError):
    """Schema tidak ditemukan."""

    pass


class SchemaCompatibilityError(SchemaRegistryError):
    """Schema tidak kompatibel."""

    pass


__all__ = [
    "BrokerError",
    "DLQProcessingError",
    "DeadLetterHandlerError",
    "KafkaConsumeError",
    "KafkaConsumerError",
    "KafkaNotAvailableError",
    "KafkaProducerError",
    "KafkaSendError",
    "OutboxLockError",
    "OutboxPollerError",
    "SchemaCompatibilityError",
    "SchemaNotFoundError",
    "SchemaRegistryError",
]
