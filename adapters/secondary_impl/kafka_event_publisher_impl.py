#!/usr/bin/env python3
"""
Module: kafka_event_publisher_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi publisher event ke Kafka menggunakan aiokafka.
               Fully async, tidak ada fallback. Wajib dipanggil start() sebelum publish.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger(__name__)


class KafkaEventPublisher:
    """
    Adapter untuk publish event ke Kafka menggunakan aiokafka.
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        client_id: str = "erp-kafka-publisher",
        acks: str = "all",
        enable_idempotence: bool = True,
        **kwargs,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self.acks = acks
        self.enable_idempotence = enable_idempotence
        self.extra_config = kwargs
        self._producer: AIOKafkaProducer | None = None
        self._started = False

    async def start(self) -> None:
        """Start the Kafka producer."""
        if self._started:
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            client_id=self.client_id,
            acks=self.acks,
            enable_idempotence=self.enable_idempotence,
            **self.extra_config,
        )
        await self._producer.start()
        self._started = True
        logger.info(f"KafkaEventPublisher started with servers: {self.bootstrap_servers}")

    async def stop(self) -> None:
        """Stop the Kafka producer."""
        if self._producer and self._started:
            await self._producer.stop()
            self._started = False
            logger.info("KafkaEventPublisher stopped")

    async def publish(self, topic: str, event: dict[str, Any], key: str | None = None) -> None:
        """
        Publish event ke Kafka secara async.
        """
        if not self._started or self._producer is None:
            raise RuntimeError("KafkaEventPublisher not started. Call start() first.")

        try:
            value = json.dumps(event, default=str).encode("utf-8")
            key_bytes = key.encode("utf-8") if key else None
            # send_and_wait ensures message is acknowledged (blocking within async)
            await self._producer.send_and_wait(topic, value=value, key=key_bytes)
            logger.debug(f"Event published to topic {topic}")
        except KafkaError as e:
            logger.error(f"Failed to publish event to topic {topic}: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error publishing event: {e}")
            raise

    async def publish_async(
        self, topic: str, event: dict[str, Any], key: str | None = None
    ) -> None:
        """
        Alias for publish (both are async).
        """
        await self.publish(topic, event, key)

    async def flush(self, timeout: float = 10.0) -> None:
        """
        Flush pending messages (aiokafka producer has no explicit flush,
        but send_and_wait already ensures delivery. This is a no-op for compatibility.
        """
        pass

    async def close(self) -> None:
        """Alias for stop."""
        await self.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def publish_batch(self, events: list[Any]) -> None:
        for event in events:
            await self.publish(event)
            
# Untuk kompatibilitas dengan nama lama
KafkaEventPublisherImpl = KafkaEventPublisher

__all__ = ["KafkaEventPublisher", "KafkaEventPublisherImpl"]
