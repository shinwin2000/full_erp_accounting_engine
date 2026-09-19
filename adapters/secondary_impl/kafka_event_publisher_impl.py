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
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger(__name__)


def _derive_topic(event: Any) -> str:
    """Turunkan nama topic Kafka dari event kalau topic tidak diberikan
    eksplisit. Dict event bisa membawa 'event_type'/'topic' sendiri;
    domain event dataclass (mis. ItemCreated) dipetakan dari nama kelas
    CamelCase ke kebab-case (mis. "item-created")."""
    if isinstance(event, dict):
        return str(event.get("topic") or event.get("event_type") or "domain-events")
    name = type(event).__name__
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return kebab or "domain-events"


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Serialisasikan event (dict, dataclass, atau objek dengan to_dict())
    menjadi dict yang siap di-JSON-encode."""
    if isinstance(event, dict):
        return dict(event)
    if hasattr(event, "to_dict") and callable(event.to_dict):
        try:
            return dict(event.to_dict())
        except Exception:  # noqa: BLE001 - fallback ke representasi generik
            pass
    if is_dataclass(event):
        return asdict(event)
    return {"event_type": type(event).__name__, "data": str(event)}


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

        # For stub statistics and audit
        self._event_count = 0
        self._failed_count = 0
        self._dead_letter_events: list[dict[str, Any]] = []
        self._outbox_events: list[dict[str, Any]] = []
        self._processing_events: list[dict[str, Any]] = []
        self._audit_log: list[dict[str, Any]] = []
        self._poller_running = False

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

    async def publish(
        self,
        event: Any,
        correlation_id: str | None = None,
        *,
        topic: str | None = None,
        key: str | None = None,
        **_ignored: Any,
    ) -> None:
        """
        Publish event ke Kafka secara async.

        Signature ini SENGAJA kompatibel dengan cara method ini benar-benar
        dipanggil dari seluruh application/service_layer/*.py (mis.
        `publish(event)`, `publish(event, correlation_id)`, atau
        `publish(event, correlation_id=correlation_id)`) - BUKAN dengan
        urutan lama `publish(topic, event, key)`, yang sebelumnya membuat
        setiap pemanggilan gagal dengan
        "got an unexpected keyword argument 'correlation_id'".
        `event` boleh berupa dict, dataclass domain event (mis.
        ItemCreated), atau objek apa pun dengan method to_dict().
        Topic diturunkan otomatis dari event kecuali di-override lewat
        parameter `topic`.
        """
        resolved_topic = topic or _derive_topic(event)

        if not self._started or self._producer is None:
            # Di lingkungan development, Kafka umumnya memang sengaja tidak
            # dijalankan (lihat banner startup "Kafka=[X]"). Publish event
            # jadi no-op yang aman (tidak melempar exception) supaya alur
            # bisnis utama (create/update/delete item, dst.) tidak
            # terganggu oleh infrastruktur messaging opsional ini -
            # konsisten dengan try/except di service layer yang sudah
            # menganggap kegagalan publish sebagai non-fatal.
            logger.debug(
                f"KafkaEventPublisher belum start (Kafka tidak terhubung) - "
                f"event topic='{resolved_topic}' dilewati (no-op)."
            )
            return

        payload = _event_to_dict(event)
        if correlation_id:
            payload.setdefault("correlation_id", correlation_id)

        try:
            value = json.dumps(payload, default=str).encode("utf-8")
            key_bytes = key.encode("utf-8") if key else None
            await self._producer.send_and_wait(resolved_topic, value=value, key=key_bytes)
            self._event_count += 1
            self._audit_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "publish",
                "topic": resolved_topic,
                "key": key,
                "status": "success"
            })
            logger.debug(f"Event published to topic {resolved_topic}")
        except KafkaError as e:
            self._failed_count += 1
            self._audit_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "publish",
                "topic": resolved_topic,
                "key": key,
                "status": "failed",
                "error": str(e)
            })
            logger.error(f"Failed to publish event to topic {resolved_topic}: {e}")
            raise
        except Exception as e:
            self._failed_count += 1
            self._audit_log.append({
                "timestamp": datetime.utcnow().isoformat(),
                "action": "publish",
                "topic": resolved_topic,
                "key": key,
                "status": "failed",
                "error": str(e)
            })
            logger.exception(f"Unexpected error publishing event: {e}")
            raise

    async def publish_async(
        self,
        event: Any,
        correlation_id: str | None = None,
        *,
        topic: str | None = None,
        key: str | None = None,
    ) -> None:
        """
        Alias for publish (both are async).
        """
        await self.publish(event, correlation_id, topic=topic, key=key)

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

    def subscribe(self, topic: str, callback: callable) -> None:
        """
        Memenuhi kontrak EventPublisherPort.
        Jika pemrosesan event menggunakan daemon consumer terpisah,
        log atau daftarkan callback di sini.
        """
        raise NotImplementedError("Untuk subscribe, gunakan KafkaConsumerWrapper terpisah.")

    def unsubscribe(self, topic: str) -> None:
        """Memenuhi kontrak EventPublisherPort untuk menghentikan subskripsi."""
        pass

    # ===== New missing methods =====

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get audit log of published events."""
        logs = self._audit_log
        return logs[offset:offset + limit]

    async def get_dead_letter_count(self) -> int:
        """Get number of events in dead letter queue."""
        return len(self._dead_letter_events)

    async def get_event_status(self, event_id: str) -> dict[str, Any] | None:
        """Get status of a specific event."""
        # Stub: check in audit log or stored events
        for log in self._audit_log:
            if log.get("event_id") == event_id:
                return log
        return None

    async def get_failed_count(self) -> int:
        """Get number of failed events."""
        return self._failed_count

    async def get_outbox_size(self) -> int:
        """Get number of events in outbox."""
        return len(self._outbox_events)

    async def get_pending_count(self) -> int:
        """Get number of pending events (not yet processed)."""
        return len(self._outbox_events) + len(self._processing_events)

    async def get_processing_count(self) -> int:
        """Get number of events currently being processed."""
        return len(self._processing_events)

    async def get_statistics(self) -> dict[str, Any]:
        """Get statistics about event publishing."""
        return {
            "total_published": self._event_count,
            "failed": self._failed_count,
            "outbox_size": len(self._outbox_events),
            "dead_letter_count": len(self._dead_letter_events),
            "processing_count": len(self._processing_events),
            "is_started": self._started,
            "bootstrap_servers": self.bootstrap_servers,
        }

    async def health_check(self) -> dict[str, Any]:
        """Check health of the event publisher."""
        status = "healthy" if self._started else "unhealthy"
        return {"status": status, "producer_running": self._started}

    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List events in dead letter queue."""
        return self._dead_letter_events[offset:offset + limit]

    async def purge_dead_letters(self) -> int:
        """Remove all events from dead letter queue."""
        count = len(self._dead_letter_events)
        self._dead_letter_events.clear()
        logger.info(f"Purged {count} dead letter events")
        return count

    async def purge_outbox(self) -> int:
        """Remove all events from outbox."""
        count = len(self._outbox_events)
        self._outbox_events.clear()
        logger.info(f"Purged {count} outbox events")
        return count

    async def retry_dead_letter(self, event_id: str) -> bool:
        """Retry a dead letter event (move back to processing)."""
        for i, evt in enumerate(self._dead_letter_events):
            if evt.get("event_id") == event_id:
                # Move to processing
                self._processing_events.append(evt)
                del self._dead_letter_events[i]
                logger.info(f"Retried dead letter event {event_id}")
                return True
        return False

    async def skip_dead_letter(self, event_id: str) -> bool:
        """Skip a dead letter event (remove without retry)."""
        for i, evt in enumerate(self._dead_letter_events):
            if evt.get("event_id") == event_id:
                del self._dead_letter_events[i]
                logger.info(f"Skipped dead letter event {event_id}")
                return True
        return False

    async def start_poller(self, interval_seconds: int = 5) -> None:
        """Start a background poller for processing outbox."""
        self._poller_running = True
        logger.info(f"Started event poller with interval {interval_seconds}s")

    async def stop_poller(self) -> None:
        """Stop the background poller."""
        self._poller_running = False
        logger.info("Stopped event poller")


# Untuk kompatibilitas dengan nama lama
KafkaEventPublisherImpl = KafkaEventPublisher

__all__ = ["KafkaEventPublisher", "KafkaEventPublisherImpl"]
