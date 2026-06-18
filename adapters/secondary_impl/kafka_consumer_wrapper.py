#!/usr/bin/env python3
"""
Module: kafka_consumer_wrapper.py
Layer: Adapters (Secondary Implementation)
Responsibility: Wrapper konkret untuk AIOKafkaConsumer. Menyediakan antarmuka
               start/stop/subscribe/poll yang diperlukan oleh application layer.
"""

from __future__ import annotations

import asyncio
import logging

from aiokafka import AIOKafkaConsumer, ConsumerRecord

logger = logging.getLogger(__name__)


class KafkaConsumerWrapper:
    """
    Wrapper untuk AIOKafkaConsumer.
    Memenuhi protokol yang diharapkan oleh application layer:
    - start()
    - stop()
    - subscribe(topics)
    - poll(timeout_ms, max_records)
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "earliest",
        enable_auto_commit: bool = False,
        auto_commit_interval_ms: int = 5000,
        max_poll_records: int = 500,
        session_timeout_ms: int = 30000,
        heartbeat_interval_ms: int = 3000,
        max_poll_interval_ms: int = 300000,
        isolation_level: str = "read_committed",
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.enable_auto_commit = enable_auto_commit
        self.auto_commit_interval_ms = auto_commit_interval_ms
        self.max_poll_records = max_poll_records
        self.session_timeout_ms = session_timeout_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.max_poll_interval_ms = max_poll_interval_ms
        self.isolation_level = isolation_level
        self._consumer: AIOKafkaConsumer | None = None
        self._subscribed_topics: set[str] = set()
        self._running = False

    async def start(self) -> None:
        """Start the Kafka consumer."""
        if self._consumer is not None:
            logger.warning("Kafka consumer already started")
            return

        self._consumer = AIOKafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=self.enable_auto_commit,
            auto_commit_interval_ms=self.auto_commit_interval_ms,
            max_poll_records=self.max_poll_records,
            session_timeout_ms=self.session_timeout_ms,
            heartbeat_interval_ms=self.heartbeat_interval_ms,
            max_poll_interval_ms=self.max_poll_interval_ms,
            isolation_level=self.isolation_level,
        )
        await self._consumer.start()
        self._running = True
        logger.info(f"Kafka consumer started for group {self.group_id}")

    async def stop(self) -> None:
        """Stop the Kafka consumer."""
        if self._consumer is None:
            logger.warning("Kafka consumer not started")
            return

        self._running = False
        await self._consumer.stop()
        self._consumer = None
        logger.info("Kafka consumer stopped")

    async def subscribe(self, topics: list[str]) -> None:
        """Subscribe to a list of topics."""
        if self._consumer is None:
            raise RuntimeError("Kafka consumer not started")
        self._consumer.subscribe(topics)
        self._subscribed_topics.update(topics)
        logger.info(f"Subscribed to topics: {topics}")

    async def poll(self, timeout_ms: int = 1000, max_records: int = 500) -> list[ConsumerRecord]:
        """
        Poll for new messages.
        Returns a list of ConsumerRecord.
        """
        if self._consumer is None:
            raise RuntimeError("Kafka consumer not started")

        try:
            # AIOKafkaConsumer.getmany() returns dict of partition -> list of records
            # We'll use getmany with timeout
            records_dict = await self._consumer.getmany(
                timeout_ms=timeout_ms, max_records=max_records
            )
            # Flatten all records into a single list
            all_records = []
            for records in records_dict.values():
                all_records.extend(records)
            return all_records
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error polling messages: {e}")
            raise

    async def commit(self) -> None:
        """Manually commit offsets (if auto_commit is disabled)."""
        if self._consumer is None:
            raise RuntimeError("Kafka consumer not started")
        await self._consumer.commit()

    async def seek_to_end(self, *topics) -> None:
        """Seek to end of partitions for given topics."""
        if self._consumer is None:
            raise RuntimeError("Kafka consumer not started")
        # Implementation may require partition assignment
        # For simplicity, we skip but can be implemented if needed
        logger.warning("seek_to_end not fully implemented")

    @property
    def running(self) -> bool:
        return self._running
