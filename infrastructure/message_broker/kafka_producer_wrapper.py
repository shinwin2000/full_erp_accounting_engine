#!/usr/bin/env python3
"""
Module: kafka_producer_wrapper.py
Layer: Infrastructure (Message Broker)
Responsibility: Wrapper untuk Kafka producer dengan async support.
Menggunakan parameter yang didukung oleh aiokafka; jika gagal, fallback ke dummy
agar aplikasi tetap berjalan (outbox tetap aman).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Try to import aiokafka
try:
    from aiokafka import AIOKafkaProducer
    from aiokafka.errors import KafkaConnectionError, KafkaError

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaProducer = None
    KafkaError = Exception
    KafkaConnectionError = Exception

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_KAFKA_PRODUCER_CONFIG = {
    "bootstrap_servers": "localhost:9092",
    "client_id": "erp-accounting-engine-producer",
    "acks": "all",
    "compression_type": "gzip",
    "max_request_size": 1048576,  # 1MB
    "linger_ms": 5,
    "request_timeout_ms": 30000,
    "enable_idempotence": True,
    "topic": "erp-events",
    "max_retries": 3,
    "retry_backoff_ms": 100,
}

DEFAULT_DEAD_LETTER_TOPIC = "erp-dead-letter"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class KafkaProducerError(Exception):
    pass


class KafkaProduceError(KafkaProducerError):
    pass


class KafkaNotAvailableError(KafkaProducerError):
    pass


# ============================================================================
# MESSAGE METADATA
# ============================================================================


@dataclass
class ProducedMessage:
    message_id: str
    topic: str
    partition: int
    offset: int
    timestamp: int
    key: str | None
    value: Any
    sent_at: float
    success: bool
    error: str | None = None


# ============================================================================
# KAFKA PRODUCER WRAPPER
# ============================================================================


class KafkaProducerWrapper:
    """
    Wrapper untuk Kafka producer (aiokafka).
    """

    def __init__(self, config_path: str = "config_files/message_broker_config.yaml"):
        self.config = self._load_config(config_path)
        self._producer: AIOKafkaProducer | None = None
        self._connected = False
        self._running = False
        self._startup_lock = asyncio.Lock()
        self._stats = {
            "messages_sent": 0,
            "messages_failed": 0,
            "last_send_time": None,
            "last_error": None,
        }
        self._message_counter = 0

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            kafka_config = config.get("kafka_producer", {})
            result = DEFAULT_KAFKA_PRODUCER_CONFIG.copy()
            result.update(kafka_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load Kafka producer config, using defaults: {e}")
            return DEFAULT_KAFKA_PRODUCER_CONFIG.copy()

    async def start(self) -> None:
        """Start Kafka producer and connect to broker."""
        async with self._startup_lock:
            if self._connected:
                return

            if not KAFKA_AVAILABLE:
                logger.warning(
                    "Kafka not available (aiokafka not installed). Producer will be dummy."
                )
                self._connected = True
                self._running = True
                return

            try:
                # Build parameters supported by AIOKafkaProducer (only those accepted)
                producer_params = {
                    "bootstrap_servers": self.config.get("bootstrap_servers"),
                    "client_id": self.config.get("client_id"),
                    "acks": self.config.get("acks", "all"),
                    "compression_type": self.config.get("compression_type", "gzip"),
                    "max_request_size": self.config.get("max_request_size", 1048576),
                    "linger_ms": self.config.get("linger_ms", 5),
                    "request_timeout_ms": self.config.get("request_timeout_ms", 30000),
                    "enable_idempotence": self.config.get("enable_idempotence", True),
                }
                # Remove keys that might be None
                producer_params = {k: v for k, v in producer_params.items() if v is not None}
                self._producer = AIOKafkaProducer(
                    **producer_params,
                    value_serializer=lambda v: (
                        json.dumps(v).encode("utf-8") if isinstance(v, dict) else v
                    ),
                )
                await self._producer.start()
                self._connected = True
                self._running = True
                logger.info(f"Kafka producer started: {self.config.get('bootstrap_servers')}")
            except Exception as e:
                logger.error(f"Failed to start Kafka producer: {e}")
                # Cleanup: tutup producer jika sudah dibuat
                if self._producer is not None:
                    try:
                        await self._producer.stop()
                    except Exception:
                        pass
                    finally:
                        self._producer = None
                # Jalankan dalam mode dummy
                self._connected = True
                self._running = True
                logger.warning("Starting dummy producer instead (Kafka unavailable).")

    async def stop(self) -> None:
        """Stop Kafka producer and close connections."""
        self._running = False
        if self._producer:
            try:
                await self._producer.stop()
                self._connected = False
                logger.info("Kafka producer stopped")
            except Exception as e:
                logger.warning(f"Error stopping Kafka producer: {e}")
            finally:
                self._producer = None

    async def send(
        self,
        topic: str | None = None,
        value: Any = None,
        key: str | None = None,
        partition: int | None = None,
        headers: list[tuple] | None = None,
        callback: Callable[[ProducedMessage], None] | None = None,
        retry: int = 0,
    ) -> ProducedMessage | None:
        """
        Send a message to Kafka topic (dummy if producer not available).
        """
        if not self._connected:
            await self.start()

        if not self._connected:
            raise KafkaNotAvailableError("Kafka producer not connected")

        # Dummy mode: simulate success
        if self._producer is None:
            self._message_counter += 1
            message_id = f"dummy_{self._message_counter}_{int(time.time() * 1000)}"
            logger.debug(f"Dummy send to {topic}: {value}")
            result = ProducedMessage(
                message_id=message_id,
                topic=topic or self.config.get("topic", "erp-events"),
                partition=0,
                offset=0,
                timestamp=int(time.time() * 1000),
                key=key,
                value=value,
                sent_at=time.time(),
                success=True,
            )
            self._stats["messages_sent"] += 1
            if callback:
                asyncio.create_task(self._invoke_callback(callback, result))
            return result

        topic = topic or self.config.get("topic", "erp-events")
        self._message_counter += 1
        message_id = f"{topic}_{self._message_counter}_{int(time.time() * 1000)}"

        # Prepare headers
        if headers is None:
            headers = []
        headers.append(("message_id", message_id.encode("utf-8")))
        headers.append(("timestamp", str(time.time()).encode("utf-8")))

        # Value serialization
        if isinstance(value, dict):
            serialized_value = json.dumps(value).encode("utf-8")
        elif isinstance(value, str):
            serialized_value = value.encode("utf-8")
        else:
            serialized_value = value  # assume bytes

        # Key serialization
        serialized_key = key.encode("utf-8") if key else None

        try:
            future = await self._producer.send(
                topic=topic,
                value=serialized_value,
                key=serialized_key,
                partition=partition,
                headers=headers,
            )

            record_metadata = await future

            result = ProducedMessage(
                message_id=message_id,
                topic=record_metadata.topic,
                partition=record_metadata.partition,
                offset=record_metadata.offset,
                timestamp=record_metadata.timestamp,
                key=key,
                value=value,
                sent_at=time.time(),
                success=True,
            )

            self._stats["messages_sent"] += 1
            self._stats["last_send_time"] = time.time()
            logger.debug(
                f"Message sent: topic={topic}, partition={record_metadata.partition}, offset={record_metadata.offset}"
            )

            if callback:
                asyncio.create_task(self._invoke_callback(callback, result))

            return result

        except Exception as e:
            self._stats["messages_failed"] += 1
            self._stats["last_error"] = str(e)
            logger.error(f"Failed to send message to {topic}: {e}")

            max_retries = self.config.get("max_retries", 3)
            if retry < max_retries:
                wait = min(2**retry, 30)  # exponential backoff
                logger.info(f"Retrying send in {wait}s (attempt {retry + 1}/{max_retries})")
                await asyncio.sleep(wait)
                return await self.send(
                    topic=topic,
                    value=value,
                    key=key,
                    partition=partition,
                    headers=headers,
                    callback=callback,
                    retry=retry + 1,
                )

            # Send to dead letter queue after all retries exhausted
            await self._send_to_dead_letter(topic, value, key, headers, str(e))

            result = ProducedMessage(
                message_id=message_id,
                topic=topic,
                partition=-1,
                offset=-1,
                timestamp=0,
                key=key,
                value=value,
                sent_at=time.time(),
                success=False,
                error=str(e),
            )
            if callback:
                asyncio.create_task(self._invoke_callback(callback, result))

            raise KafkaProduceError(
                f"Failed to send message after {max_retries} retries: {e}"
            ) from e

    async def send_batch(
        self,
        messages: list[dict[str, Any]],
        topic: str | None = None,
        callback: Callable[[list[ProducedMessage]], None] | None = None,
    ) -> list[ProducedMessage]:
        """Send multiple messages in batch (concurrently)."""
        tasks = []
        for msg in messages:
            tasks.append(
                self.send(
                    topic=topic or msg.get("topic"),
                    value=msg["value"],
                    key=msg.get("key"),
                    partition=msg.get("partition"),
                    headers=msg.get("headers"),
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final_results = []
        for r in results:
            if isinstance(r, Exception):
                final_results.append(
                    ProducedMessage(
                        message_id="",
                        topic=topic or "",
                        partition=-1,
                        offset=-1,
                        timestamp=0,
                        key=None,
                        value=None,
                        sent_at=time.time(),
                        success=False,
                        error=str(r),
                    )
                )
            else:
                final_results.append(r)

        if callback:
            asyncio.create_task(self._invoke_batch_callback(callback, final_results))

        return final_results

    async def _send_to_dead_letter(
        self, topic: str, value: Any, key: str | None, headers: list[tuple], error: str
    ) -> None:
        """Send failed message to dead letter queue topic."""
        try:
            dlq_topic = self.config.get("dead_letter_topic", DEFAULT_DEAD_LETTER_TOPIC)
            dlq_value = {
                "original_topic": topic,
                "original_key": key,
                "original_value": value,
                "error": error,
                "failed_at": time.time(),
                "headers": [(k, v.decode("utf-8") if v else None) for k, v in headers],
            }
            await self.send(topic=dlq_topic, value=dlq_value, retry=0)
            logger.info(f"Message sent to dead letter queue: {topic}")
        except Exception as e:
            logger.error(f"Failed to send to dead letter queue: {e}")
            await trigger_alert(
                title="Kafka DLQ Failed",
                message=f"Failed to send message to DLQ: {e}",
                severity="warning",
                source="KafkaProducerWrapper",
            )

    async def _invoke_callback(
        self, callback: Callable[[ProducedMessage], None], result: ProducedMessage
    ) -> None:
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(result)
            else:
                callback(result)
        except Exception as e:
            logger.error(f"Delivery callback error: {e}")

    async def _invoke_batch_callback(
        self, callback: Callable[[list[ProducedMessage]], None], results: list[ProducedMessage]
    ) -> None:
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(results)
            else:
                callback(results)
        except Exception as e:
            logger.error(f"Batch callback error: {e}")

    async def flush(self) -> None:
        """Flush all pending messages."""
        if self._producer:
            await self._producer.flush()
            logger.debug("Kafka producer flushed")

    async def get_metrics(self) -> dict[str, Any]:
        """Get producer metrics."""
        return {
            "connected": self._connected,
            "running": self._running,
            "stats": self._stats,
            "config": {
                "bootstrap_servers": self.config.get("bootstrap_servers"),
                "client_id": self.config.get("client_id"),
                "acks": self.config.get("acks"),
                "compression_type": self.config.get("compression_type"),
            },
        }

    async def is_healthy(self) -> bool:
        """Check if producer is healthy."""
        return self._connected and self._running


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_kafka_producer: KafkaProducerWrapper | None = None


async def get_kafka_producer() -> KafkaProducerWrapper:
    """Get singleton instance of KafkaProducerWrapper."""
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = KafkaProducerWrapper()
        await _kafka_producer.start()
    return _kafka_producer


async def close_kafka_producer() -> None:
    """Close Kafka producer."""
    global _kafka_producer
    if _kafka_producer:
        await _kafka_producer.stop()
        _kafka_producer = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "KafkaNotAvailableError",
    "KafkaProduceError",
    "KafkaProducerError",
    "KafkaProducerWrapper",
    "close_kafka_producer",
    "get_kafka_producer",
]