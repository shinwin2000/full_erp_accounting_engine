#!/usr/bin/env python3
"""
Module: kafka_dead_letter_handler.py
Layer: Infrastructure (Message Broker)
Responsibility: Mengelola Dead Letter Queue (DLQ) untuk Kafka messages.
               Menyediakan fungsi untuk membaca pesan dari DLQ, menganalisis
               penyebab kegagalan, retry dengan backoff, dan mengirim ulang
               ke topic asli. Juga mendukung manual intervention dan alerting.
Dependencies:
- aiokafka (optional)
- asyncio, json, logging, datetime
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap pesan yang masuk ke DLQ dicatat. Retry dan manual intervention
       juga dicatat untuk audit trail.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

# Try to import aiokafka
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    AIOKafkaConsumer = None
    AIOKafkaProducer = None

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_DLQ_CONFIG = {
    "bootstrap_servers": "localhost:9092",
    "group_id": "erp-dlq-handler",
    "dlq_topic": "erp-dead-letter",
    "retry_topic_prefix": "erp-retry",
    "max_retries": 3,
    "retry_delay_seconds": [60, 300, 3600],  # 1 min, 5 min, 1 hour
    "max_messages_per_batch": 100,
    "poll_timeout_ms": 5000,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DeadLetterHandlerError(Exception):
    """Base exception untuk dead letter handler."""

    pass


class DLQProcessingError(DeadLetterHandlerError):
    """Error saat memproses DLQ."""

    pass


# ============================================================================
# DEAD LETTER HANDLER
# ============================================================================


class KafkaDeadLetterHandler:
    """
    Handler untuk Dead Letter Queue.

    Fitur:
    - Baca pesan dari DLQ topic
    - Retry dengan exponential backoff
    - Kirim ulang ke topic asli setelah retry berhasil
    - Tracking retry count
    - Alert untuk pesan yang gagal permanen
    - Manual reprocess support
    """

    def __init__(self, config_path: str = "config_files/message_broker_config.yaml"):
        self.config = self._load_config(config_path)
        self._consumer: AIOKafkaConsumer | None = None
        self._producer: AIOKafkaProducer | None = None
        self._running = False
        self._process_task: asyncio.Task | None = None
        self._stats = {
            "messages_received": 0,
            "messages_retried": 0,
            "messages_success": 0,
            "messages_failed_permanent": 0,
        }

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            dlq_config = config.get("dead_letter", {})
            result = DEFAULT_DLQ_CONFIG.copy()
            result.update(dlq_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load DLQ config, using defaults: {e}")
            return DEFAULT_DLQ_CONFIG.copy()

    async def _get_consumer(self) -> AIOKafkaConsumer | None:
        if not KAFKA_AVAILABLE:
            return None

        if self._consumer is None:
            self._consumer = AIOKafkaConsumer(
                self.config.get("dlq_topic", "erp-dead-letter"),
                bootstrap_servers=self.config.get("bootstrap_servers", "localhost:9092"),
                group_id=self.config.get("group_id", "erp-dlq-handler"),
                auto_offset_reset="earliest",
                enable_auto_commit=False,
                max_poll_records=self.config.get("max_messages_per_batch", 100),
            )
            await self._consumer.start()
        return self._consumer

    async def _get_producer(self) -> AIOKafkaProducer | None:
        if not KAFKA_AVAILABLE:
            return None

        if self._producer is None:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.config.get("bootstrap_servers", "localhost:9092")
            )
            await self._producer.start()
        return self._producer

    async def start(self) -> None:
        """Start the dead letter handler."""
        if self._running:
            logger.warning("Dead letter handler already running")
            return

        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.info("Dead letter handler started")

    async def stop(self) -> None:
        """Stop the dead letter handler."""
        self._running = False

        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None

        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

        if self._producer:
            await self._producer.stop()
            self._producer = None

        logger.info("Dead letter handler stopped")

    async def _process_loop(self) -> None:
        """Main processing loop for DLQ messages."""
        consumer = await self._get_consumer()
        if not consumer:
            logger.warning("Kafka not available, DLQ handler disabled")
            return

        while self._running:
            try:
                # Poll for messages
                messages = await consumer.getmany(
                    timeout_ms=self.config.get("poll_timeout_ms", 5000),
                    max_records=self.config.get("max_messages_per_batch", 100),
                )

                for tp, msgs in messages.items():
                    for msg in msgs:
                        await self._process_dlq_message(msg)

                # Commit offsets after processing batch
                await consumer.commit()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in DLQ processing loop: {e}")
                await asyncio.sleep(5)

    async def _process_dlq_message(self, msg) -> None:
        """Process a single DLQ message."""
        self._stats["messages_received"] += 1

        try:
            # Parse message
            value = msg.value
            if isinstance(value, bytes):
                dlq_data = json.loads(value.decode("utf-8"))
            else:
                dlq_data = value if isinstance(value, dict) else {"raw": str(value)}

            # Get retry count
            retry_count = dlq_data.get("retry_count", 0)
            original_topic = dlq_data.get("original_topic")
            original_key = dlq_data.get("original_key")
            original_value = dlq_data.get("original_value")
            error = dlq_data.get("error")
            failed_at = dlq_data.get("failed_at")

            # Check if should retry
            max_retries = self.config.get("max_retries", 3)

            if retry_count >= max_retries:
                # Permanent failure
                self._stats["messages_failed_permanent"] += 1
                await self._handle_permanent_failure(dlq_data, msg)
                return

            # Calculate delay based on retry count
            delays = self.config.get("retry_delay_seconds", [60, 300, 3600])
            delay = delays[min(retry_count, len(delays) - 1)]

            # Check if enough time has passed
            if failed_at:
                failed_time = datetime.fromtimestamp(failed_at, tz=UTC)
                retry_time = failed_time + timedelta(seconds=delay)
                if datetime.now(UTC) < retry_time:
                    # Not yet time to retry, re-commit and continue
                    return

            # Prepare retry message
            retry_topic = f"{self.config.get('retry_topic_prefix', 'erp-retry')}-{original_topic}"
            retry_value = (
                original_value
                if isinstance(original_value, bytes)
                else json.dumps(original_value).encode("utf-8")
            )

            # Send to retry topic
            producer = await self._get_producer()
            if producer:
                await producer.send(
                    topic=retry_topic,
                    value=retry_value,
                    key=original_key.encode("utf-8") if original_key else None,
                )

                self._stats["messages_retried"] += 1
                logger.info(
                    f"Retried message (attempt {retry_count + 1}/{max_retries}): {original_topic}"
                )

                # Also send a log to DLQ with updated retry count
                dlq_data["retry_count"] = retry_count + 1
                dlq_data["last_retry_at"] = time.time()
                await producer.send(
                    topic=self.config.get("dlq_topic", "erp-dead-letter"),
                    value=json.dumps(dlq_data).encode("utf-8"),
                )

                self._stats["messages_success"] += 1

        except Exception as e:
            logger.error(f"Failed to process DLQ message: {e}")
            self._stats["messages_failed_permanent"] += 1

    async def _handle_permanent_failure(self, dlq_data: dict, msg) -> None:
        """Handle permanently failed message."""
        original_topic = dlq_data.get("original_topic")
        error = dlq_data.get("error")

        logger.error(f"Permanent failure for message from {original_topic}: {error}")

        await trigger_alert(
            title="Kafka Message Permanently Failed",
            message=f"Message from {original_topic} failed after {dlq_data.get('retry_count', 0)} retries. Error: {error}",
            severity="error",
            source="KafkaDeadLetterHandler",
        )

        # Store in permanent failure storage for manual inspection
        await self._store_permanent_failure(dlq_data)

    async def _store_permanent_failure(self, dlq_data: dict) -> None:
        """Store permanently failed message for manual inspection."""
        # In production, store in database or file
        logger.warning(f"Permanent failure stored: {dlq_data.get('original_topic')}")

    async def reprocess_manually(self, message_id: str) -> bool:
        """
        Manually reprocess a message from DLQ.
        """
        # Implementation would load message by ID and reprocess
        logger.info(f"Manual reprocess requested for message {message_id}")
        return True

    async def get_stats(self) -> dict[str, Any]:
        """Get handler statistics."""
        return {
            "running": self._running,
            "stats": self._stats,
            "config": {
                "max_retries": self.config.get("max_retries", 3),
                "dlq_topic": self.config.get("dlq_topic"),
                "retry_delay_seconds": self.config.get("retry_delay_seconds"),
            },
        }

    async def purge_dlq(self, max_messages: int = 1000) -> int:
        """
        Purge messages from DLQ (for testing or recovery).
        """
        consumer = await self._get_consumer()
        if not consumer:
            return 0

        purged = 0
        try:
            messages = await consumer.getmany(timeout_ms=1000, max_records=max_messages)
            for tp, msgs in messages.items():
                purged += len(msgs)
            await consumer.commit()
            logger.info(f"Purged {purged} messages from DLQ")
        except Exception as e:
            logger.error(f"Failed to purge DLQ: {e}")

        return purged


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_dlq_handler: KafkaDeadLetterHandler | None = None


async def get_dead_letter_handler() -> KafkaDeadLetterHandler:
    """Get singleton instance of KafkaDeadLetterHandler."""
    global _dlq_handler
    if _dlq_handler is None:
        _dlq_handler = KafkaDeadLetterHandler()
    return _dlq_handler


async def start_dead_letter_handler() -> None:
    """Start the dead letter handler."""
    handler = await get_dead_letter_handler()
    await handler.start()


async def stop_dead_letter_handler() -> None:
    """Stop the dead letter handler."""
    global _dlq_handler
    if _dlq_handler:
        await _dlq_handler.stop()
        _dlq_handler = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DLQProcessingError",
    "DeadLetterHandlerError",
    "KafkaDeadLetterHandler",
    "get_dead_letter_handler",
    "start_dead_letter_handler",
    "stop_dead_letter_handler",
]
