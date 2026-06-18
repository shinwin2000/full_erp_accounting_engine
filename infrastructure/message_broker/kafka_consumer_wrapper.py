#!/usr/bin/env python3

"""
Module: kafka_consumer_wrapper.py
Layer: Infrastructure / Message Broker
Responsibility: Wrapper untuk Kafka Consumer dengan async interface.
               Mendukung subscribe, poll, commit, dan close.
               Menggunakan aiokafka jika tersedia, fallback ke kafka-python dengan thread pool.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Try to import aiokafka first (async native)
try:
    from aiokafka import AIOKafkaConsumer, ConsumerRecord
    from aiokafka.errors import KafkaConnectionError, KafkaError

    AIOKAFKA_AVAILABLE = True
except ImportError:
    AIOKAFKA_AVAILABLE = False
    AIOKafkaConsumer = None
    ConsumerRecord = None
    KafkaError = Exception

# Fallback to kafka-python (sync)
if not AIOKAFKA_AVAILABLE:
    try:
        from kafka import KafkaConsumer as SyncKafkaConsumer
        from kafka.errors import KafkaError as SyncKafkaError
        from kafka.structs import ConsumerRecord as SyncConsumerRecord

        KAFKA_PYTHON_AVAILABLE = True
    except ImportError:
        KAFKA_PYTHON_AVAILABLE = False
        SyncKafkaConsumer = None
        SyncConsumerRecord = None
        SyncKafkaError = Exception

logger = logging.getLogger(__name__)


# === 1. DATA CLASS FOR MESSAGE ===


@dataclass
class ConsumerMessage:
    """Message structure returned by poll()."""

    topic: str
    partition: int
    offset: int
    key: str | None
    value: Any
    timestamp: datetime

    @classmethod
    def from_aiokafka_record(cls, record: ConsumerRecord) -> ConsumerMessage:
        value = record.value
        if isinstance(value, bytes):
            try:
                value = json.loads(value.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass  # keep as bytes or string fallback
        key = record.key.decode("utf-8") if record.key else None
        return cls(
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            key=key,
            value=value,
            timestamp=datetime.fromtimestamp(record.timestamp / 1000.0),
        )

    @classmethod
    def from_kafka_python_record(cls, record: SyncConsumerRecord) -> ConsumerMessage:
        value = record.value
        if isinstance(value, bytes):
            try:
                value = json.loads(value.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        key = record.key.decode("utf-8") if record.key else None
        return cls(
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            key=key,
            value=value,
            timestamp=datetime.fromtimestamp(record.timestamp / 1000.0),
        )


# === 2. KAFKA CONSUMER WRAPPER (AIOKAFKA BASED) ===


class KafkaConsumerWrapper:
    """
    Async Kafka consumer wrapper.
    Prefers aiokafka if available, otherwise falls back to kafka-python with thread pool.
    Implements the interface required by subscriber_application.py.
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "erp_consumer_group",
        auto_offset_reset: str = "earliest",
        enable_auto_commit: bool = False,
        max_poll_records: int = 500,
        session_timeout_ms: int = 30000,
        heartbeat_interval_ms: int = 3000,
        max_poll_interval_ms: int = 300000,
        value_deserializer: Callable | None = None,
        **kwargs,
    ):
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.enable_auto_commit = enable_auto_commit
        self.max_poll_records = max_poll_records
        self.session_timeout_ms = session_timeout_ms
        self.heartbeat_interval_ms = heartbeat_interval_ms
        self.max_poll_interval_ms = max_poll_interval_ms
        self.value_deserializer = value_deserializer or (
            lambda v: json.loads(v.decode("utf-8")) if v else None
        )
        self._consumer = None
        self._subscribed_topics = []
        self._running = False
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the Kafka consumer."""
        if AIOKAFKA_AVAILABLE:
            await self._start_aiokafka()
        elif KAFKA_PYTHON_AVAILABLE:
            await self._start_kafka_python()
        else:
            raise RuntimeError(
                "No Kafka library installed. Please install aiokafka or kafka-python."
            )

    async def _start_aiokafka(self) -> None:
        """Start consumer using aiokafka (async native)."""
        self._consumer = AIOKafkaConsumer(
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=self.enable_auto_commit,
            max_poll_records=self.max_poll_records,
            session_timeout_ms=self.session_timeout_ms,
            heartbeat_interval_ms=self.heartbeat_interval_ms,
            max_poll_interval_ms=self.max_poll_interval_ms,
            value_deserializer=self.value_deserializer,
        )
        await self._consumer.start()
        logger.info(
            f"Kafka consumer (aiokafka) started: {self.bootstrap_servers}, group_id={self.group_id}"
        )

    async def _start_kafka_python(self) -> None:
        """Start consumer using kafka-python (sync, wrapped in thread)."""

        # kafka-python consumer creation is synchronous; run in thread
        def _create():
            return SyncKafkaConsumer(
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.group_id,
                auto_offset_reset=self.auto_offset_reset,
                enable_auto_commit=self.enable_auto_commit,
                max_poll_records=self.max_poll_records,
                session_timeout_ms=self.session_timeout_ms,
                heartbeat_interval_ms=self.heartbeat_interval_ms,
                max_poll_interval_ms=self.max_poll_interval_ms,
                value_deserializer=self.value_deserializer,
            )

        self._consumer = await asyncio.to_thread(_create)
        logger.info(
            f"Kafka consumer (kafka-python) started: {self.bootstrap_servers}, group_id={self.group_id}"
        )

    async def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics."""
        self._subscribed_topics = topics
        if AIOKAFKA_AVAILABLE:
            self._consumer.subscribe(topics)
        else:
            # kafka-python subscription must be done after creation
            # We can either create consumer with topics or subscribe later.
            # For simplicity, we will recreate consumer with topics.
            # But consumer already created in start() without topics. We'll close and recreate.
            if self._consumer:
                await self.close()

            def _create_with_topics():
                return SyncKafkaConsumer(
                    *topics,
                    bootstrap_servers=self.bootstrap_servers,
                    group_id=self.group_id,
                    auto_offset_reset=self.auto_offset_reset,
                    enable_auto_commit=self.enable_auto_commit,
                    max_poll_records=self.max_poll_records,
                    session_timeout_ms=self.session_timeout_ms,
                    heartbeat_interval_ms=self.heartbeat_interval_ms,
                    max_poll_interval_ms=self.max_poll_interval_ms,
                    value_deserializer=self.value_deserializer,
                )

            self._consumer = await asyncio.to_thread(_create_with_topics)
        logger.info(f"Subscribed to topics: {topics}")

    async def poll(
        self, timeout_ms: int = 1000, max_records: int | None = None
    ) -> list[ConsumerMessage]:
        """
        Poll for messages.
        Returns a list of ConsumerMessage.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not started. Call start() first.")

        if AIOKAFKA_AVAILABLE:
            # aiokafka's getmany returns dict of topic-partition -> list of records
            max_records = max_records or self.max_poll_records
            messages = await self._consumer.getmany(timeout_ms=timeout_ms, max_records=max_records)
            result = []
            for tp, records in messages.items():
                for record in records:
                    result.append(ConsumerMessage.from_aiokafka_record(record))
            return result
        else:
            # kafka-python poll is synchronous, run in thread
            max_records = max_records or self.max_poll_records

            def _poll():
                records_dict = self._consumer.poll(timeout_ms=timeout_ms, max_records=max_records)
                msgs = []
                for tp, recs in records_dict.items():
                    for rec in recs:
                        msgs.append(ConsumerMessage.from_kafka_python_record(rec))
                return msgs

            return await asyncio.to_thread(_poll)

    async def commit(self) -> None:
        """Commit current offsets."""
        if not self._consumer:
            return
        if AIOKAFKA_AVAILABLE:
            await self._consumer.commit()
        else:
            await asyncio.to_thread(self._consumer.commit)

    async def commit_offset(self, topic: str, partition: int, offset: int) -> None:
        """Commit specific offset for a topic-partition."""
        if not self._consumer:
            return
        if AIOKAFKA_AVAILABLE:
            from aiokafka.structs import TopicPartition

            tp = TopicPartition(topic, partition)
            await self._consumer.commit({tp: offset})
        else:
            from kafka.structs import TopicPartition as SyncTopicPartition

            tp = SyncTopicPartition(topic, partition)
            # kafka-python commit expects a dict
            await asyncio.to_thread(self._consumer.commit, {tp: offset})

    async def close(self) -> None:
        """Close the consumer."""
        if self._consumer:
            if AIOKAFKA_AVAILABLE:
                await self._consumer.stop()
            else:
                await asyncio.to_thread(self._consumer.close)
            self._consumer = None
        logger.info("Kafka consumer closed")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# === 3. FALLBACK DUMMY CONSUMER (when no library) ===

if not AIOKAFKA_AVAILABLE and not KAFKA_PYTHON_AVAILABLE:

    class KafkaConsumerWrapper:
        def __init__(self, *args, **kwargs):
            logger.error("No Kafka library installed. Kafka consumer will not work.")

        async def start(self):
            raise NotImplementedError("Kafka library not installed")

        async def subscribe(self, topics):
            raise NotImplementedError

        async def poll(self, timeout_ms=1000, max_records=None):
            return []

        async def commit(self):
            pass

        async def commit_offset(self, topic, partition, offset):
            pass

        async def close(self):
            pass


# === 4. EXPORTS ===

__all__ = ["ConsumerMessage", "KafkaConsumerWrapper"]
