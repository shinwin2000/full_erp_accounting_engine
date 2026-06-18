#!/usr/bin/env python3
"""
Module: kafka_producer_wrapper.py
Layer: Adapters (Secondary Implementation)
Responsibility: Wrapper konkret untuk AIOKafkaProducer. Menyembunyikan kompleksitas
               konfigurasi dan menyediakan antarmuka start/stop/send yang sederhana
               seperti yang diharapkan oleh application layer.
"""

from __future__ import annotations

import logging

from aiokafka import AIOKafkaProducer

logger = logging.getLogger(__name__)


class KafkaProducerWrapper:
    """
    Wrapper untuk AIOKafkaProducer.
    Memenuhi protokol yang diharapkan oleh application layer:
    - start()
    - stop()
    - send(topic, key, value)
    """

    def __init__(
        self,
        bootstrap_servers: str,
        client_id: str = "erp-accounting-engine-producer",
        acks: str = "all",
        enable_idempotence: bool = True,
        compression_type: str = "gzip",
        max_batch_size: int = 65536,
        linger_ms: int = 5,
        request_timeout_ms: int = 30000,
        retry_backoff_ms: int = 500,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.client_id = client_id
        self.acks = acks
        self.enable_idempotence = enable_idempotence
        self.compression_type = compression_type
        self.max_batch_size = max_batch_size
        self.linger_ms = linger_ms
        self.request_timeout_ms = request_timeout_ms
        self.retry_backoff_ms = retry_backoff_ms
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Start the Kafka producer."""
        if self._producer is not None:
            logger.warning("Kafka producer already started")
            return

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            client_id=self.client_id,
            acks=self.acks,
            enable_idempotence=self.enable_idempotence,
            compression_type=self.compression_type,
            max_batch_size=self.max_batch_size,
            linger_ms=self.linger_ms,
            request_timeout_ms=self.request_timeout_ms,
            retry_backoff_ms=self.retry_backoff_ms,
        )
        await self._producer.start()
        logger.info(f"Kafka producer started for {self.bootstrap_servers}")

    async def stop(self) -> None:
        """Stop the Kafka producer."""
        if self._producer is None:
            logger.warning("Kafka producer not started")
            return

        await self._producer.stop()
        self._producer = None
        logger.info("Kafka producer stopped")

    async def send(self, topic: str, key: bytes | None = None, value: bytes | None = None) -> None:
        """
        Send a message to a Kafka topic.
        Menyediakan antarmuka yang sinkron secara logis tapi async secara implisit.
        """
        if self._producer is None:
            raise RuntimeError("Kafka producer not started")

        try:
            await self._producer.send_and_wait(topic, value=value, key=key)
            logger.debug(f"Message sent to topic {topic}")
        except Exception as e:
            logger.error(f"Failed to send message to topic {topic}: {e}")
            raise
