#!/usr/bin/env python3
"""
Module: sqlalchemy_outbox_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Outbox Pattern menggunakan SQLAlchemy ORM.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.message_broker.kafka_producer_wrapper import (
    KafkaProducerWrapper,
    close_kafka_producer,
    get_kafka_producer,
)
from infrastructure.persistence_orm.outbox_checkpoint_table import OutboxCheckpointTable
from infrastructure.persistence_orm.outbox_table import OutboxTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from ports.primary.outbox_repository_port import OutboxMessage, OutboxRepositoryPort

# ========================================================================
# PATCH: Add to_dict method to OutboxMessage if missing (required by P09)
# ========================================================================
if not hasattr(OutboxMessage, 'to_dict'):
    def _outbox_message_to_dict(self):
        return {
            "message_id": str(self.message_id),
            "aggregate_id": str(self.aggregate_id),
            "event_type": self.event_type,
            "payload": self.payload,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "status": self.status,
        }
    OutboxMessage.to_dict = _outbox_message_to_dict

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_DELAY_SECONDS = 30
DEFAULT_CLEANUP_DAYS = 7
DEAD_LETTER_QUEUE_TOPIC = "dead_letter_events"

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"
OUTBOX_STATUS_DEAD_LETTER = "dead_letter"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class OutboxRepositoryError(Exception):
    pass


class OutboxEventNotFoundError(OutboxRepositoryError):
    pass


class OutboxPublishError(OutboxRepositoryError):
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyOutboxRepository(OutboxRepositoryPort):
    """
    Implementasi OutboxRepositoryPort dengan SQLAlchemy.
    Mendukung dua mode:
    - Pass session eksplisit via constructor atau set_session()
    - Pass session_factory untuk auto-manage session per-operasi (mode outbox relay)
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        session_factory: async_sessionmaker | None = None,
    ):
        self._session = session
        self._session_factory = session_factory
        self._kafka_producer: KafkaProducerWrapper | None = None

    def set_session_factory(self, session_factory: async_sessionmaker) -> None:
        """Set session factory untuk auto-manage session per-batch (outbox relay mode)."""
        self._session_factory = session_factory

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise OutboxRepositoryError(
                "Session not set. Call set_session() or pass session in constructor."
            )
        return self._session

    def set_session(self, session: AsyncSession) -> None:
        """Set session untuk repository (digunakan untuk setiap batch processing)."""
        self._session = session

    async def _get_kafka_producer(self) -> KafkaProducerWrapper:
        if self._kafka_producer is None:
            self._kafka_producer = await get_kafka_producer()
        return self._kafka_producer

    async def close_kafka_producer(self) -> None:
        if self._kafka_producer:
            await close_kafka_producer()
            self._kafka_producer = None

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _serialize_event(self, event: Any) -> str:
        if hasattr(event, "to_dict"):
            data = event.to_dict()
        elif hasattr(event, "__dict__"):
            data = event.__dict__
        else:
            data = event
        return json.dumps(data, default=self._json_serializer)

    def _json_serializer(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    def _deserialize_event(self, event_type: str, payload: str) -> dict[str, Any]:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Failed to deserialize event payload for %s", event_type)
            return {"raw": payload}

    # ========================================================================
    # PORT ABSTRACT METHOD IMPLEMENTATIONS (required by OutboxRepositoryPort)
    # ========================================================================

    async def save(self, message: OutboxMessage) -> None:
        """Menyimpan pesan outbox sesuai port."""
        try:
            payload_json = json.dumps(message.payload, default=self._json_serializer)
            outbox_record = OutboxTable(
                id=message.message_id,
                event_type=message.event_type,
                aggregate_id=message.aggregate_id,
                aggregate_type="",
                payload=payload_json,
                metadata=json.dumps({}),
                status=OUTBOX_STATUS_PENDING,
                retry_count=0,
                created_at=message.occurred_at,
                updated_at=datetime.utcnow(),
            )
            self.session.add(outbox_record)
            await self.session.flush()
            logger.debug("Outbox message saved: %s", message.message_id)
        except Exception as e:
            logger.error("Failed to save outbox message: %s", e)
            raise OutboxRepositoryError(f"Failed to save: {e}") from e

    async def get_pending_messages(self, limit: int = 100) -> list[OutboxMessage]:
        """Mengambil pesan pending sesuai port."""
        try:
            stmt = (
                select(OutboxTable)
                .where(
                    OutboxTable.status == OUTBOX_STATUS_PENDING, OutboxTable.deleted_at.is_(None)
                )
                .order_by(OutboxTable.created_at)
                .limit(limit)
            )
            result = await self.session.execute(stmt)
            events = result.scalars().all()
            messages = []
            for ev in events:
                payload = self._deserialize_event(ev.event_type, ev.payload)
                msg = OutboxMessage(
                    message_id=ev.id,
                    aggregate_id=ev.aggregate_id,
                    event_type=ev.event_type,
                    payload=payload,
                    occurred_at=ev.created_at,
                    status=ev.status,
                )
                messages.append(msg)
            return messages
        except Exception as e:
            logger.error("Failed to get pending messages: %s", e)
            raise OutboxRepositoryError(f"Failed to get pending messages: {e}") from e

    async def mark_as_sent(self, message_id: UUID) -> None:
        """Menandai pesan sebagai terkirim (port required)."""
        try:
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == message_id)
                .values(
                    status=OUTBOX_STATUS_SENT,
                    sent_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()
            logger.debug("Marked message %s as sent", message_id)
        except Exception as e:
            logger.error("Failed to mark message %s as sent: %s", message_id, e)
            raise OutboxRepositoryError(f"Failed to mark as sent: {e}") from e

    async def mark_as_failed(self, message_id: UUID, error: str) -> None:
        """Menandai pesan gagal, increment retry count. Jika melebihi batas, pindah ke DLQ."""
        try:
            stmt = select(OutboxTable).where(OutboxTable.id == message_id)
            result = await self.session.execute(stmt)
            event = result.scalar_one_or_none()
            if not event:
                raise OutboxEventNotFoundError(f"Message {message_id} not found")

            retry_count = getattr(event, "retry_count", 0) + 1
            if retry_count >= DEFAULT_MAX_RETRIES:
                stmt = (
                    update(OutboxTable)
                    .where(OutboxTable.id == message_id)
                    .values(
                        status=OUTBOX_STATUS_DEAD_LETTER,
                        last_error=error,
                        updated_at=datetime.utcnow(),
                    )
                )
                await self.session.execute(stmt)
                await trigger_alert(
                    title="Outbox Message Moved to Dead Letter",
                    message=f"Message {message_id} moved to DLQ after {DEFAULT_MAX_RETRIES} retries. Error: {error[:200]}",
                    severity="warning",
                    source="OutboxRepository",
                )
            else:
                next_retry = datetime.utcnow() + timedelta(seconds=DEFAULT_RETRY_DELAY_SECONDS)
                stmt = (
                    update(OutboxTable)
                    .where(OutboxTable.id == message_id)
                    .values(
                        status=OUTBOX_STATUS_PENDING,
                        retry_count=retry_count,
                        last_error=error,
                        next_retry_at=next_retry,
                        updated_at=datetime.utcnow(),
                    )
                )
                await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            logger.error("Failed to mark message %s as failed: %s", message_id, e)
            raise OutboxRepositoryError(f"Failed to mark as failed: {e}") from e

    async def delete_sent_messages_older_than(self, cutoff_date: datetime) -> int:
        """
        Menghapus pesan yang sudah terkirim (sent_at not NULL) lebih tua dari cutoff_date.
        LOCKING: SELECT FOR UPDATE untuk mengunci baris yang akan dihapus.
        """
        try:
            if cutoff_date.tzinfo is None:
                cutoff = cutoff_date
            else:
                cutoff = cutoff_date.astimezone(UTC).replace(tzinfo=None)

            session = self.session

            # 1. Select IDs with lock
            stmt_select = (
                select(OutboxTable.id)
                .where(
                    OutboxTable.status == OUTBOX_STATUS_SENT,
                    OutboxTable.sent_at < cutoff,
                )
                .with_for_update()
            )
            result = await session.execute(stmt_select)
            ids = [row[0] for row in result.all()]

            if not ids:
                return 0

            # 2. Delete by IDs
            stmt_delete = delete(OutboxTable).where(OutboxTable.id.in_(ids))
            delete_result = await session.execute(stmt_delete)
            await session.flush()

            deleted = delete_result.rowcount
            logger.info("Deleted %d sent messages older than %s", deleted, cutoff)
            return deleted
        except Exception as e:
            logger.error("Failed to delete sent messages: %s", e)
            raise OutboxRepositoryError(f"Failed to delete sent messages: {e}") from e

    # ========================================================================
    # ADDITIONAL METHODS (for outbox relay service and internal use)
    # ========================================================================

    async def get_pending_events(
        self, limit: int, lock_timeout_seconds: int
    ) -> list[dict[str, Any]]:
        """Method untuk outbox_relay_service (mengembalikan dict, bukan OutboxMessage).

        Jika session_factory tersedia dan tidak ada session eksplisit,
        membuat session baru secara otomatis untuk operasi ini.
        """
        if self._session is None and self._session_factory is not None:
            async with self._session_factory() as auto_session:
                self._session = auto_session
                try:
                    return await self._get_pending_events_with_session(limit, lock_timeout_seconds)
                finally:
                    self._session = None
        return await self._get_pending_events_with_session(limit, lock_timeout_seconds)

    async def _get_pending_events_with_session(
        self, limit: int, lock_timeout_seconds: int
    ) -> list[dict[str, Any]]:
        """Implementasi get_pending_events menggunakan self.session yang sudah tersedia."""
        try:
            lock_for_update = lock_timeout_seconds > 0
            stmt = (
                select(OutboxTable)
                .where(
                    OutboxTable.status == OUTBOX_STATUS_PENDING,
                    OutboxTable.deleted_at.is_(None),
                )
                .order_by(OutboxTable.created_at)
                .limit(limit)
            )
            if lock_for_update:
                stmt = stmt.with_for_update(skip_locked=True)

            result = await self.session.execute(stmt)
            events = result.scalars().all()
            pending_list = []
            for ev in events:
                payload_dict = self._deserialize_event(ev.event_type, ev.payload)
                metadata_dict = {}
                if ev.metadata:
                    try:
                        metadata_dict = json.loads(ev.metadata)
                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Failed to decode metadata for event %s: %s",
                            ev.id,
                            e
                        )
                        metadata_dict = {"raw": ev.metadata}
                pending_list.append(
                    {
                        "id": ev.id,
                        "event_type": ev.event_type,
                        "aggregate_id": ev.aggregate_id,
                        "aggregate_type": ev.aggregate_type,
                        "payload": payload_dict,
                        "metadata": metadata_dict,
                        "created_at": ev.created_at,
                        "retry_count": ev.retry_count,
                        "status": ev.status,
                        "topic": getattr(ev, "topic", None),
                        "event_id": ev.id,
                        "correlation_id": getattr(ev, "correlation_id", None),
                        "idempotency_key": getattr(ev, "idempotency_key", None),
                    }
                )
            return pending_list
        except Exception as e:
            logger.error("Failed to get pending events: %s", e)
            raise OutboxRepositoryError(f"Failed to get pending events: {e}") from e

    async def mark_as_processing(self, record_id: int) -> bool:
        """Menandai event sebagai processing (digunakan oleh relay)."""
        try:
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == record_id, OutboxTable.status == OUTBOX_STATUS_PENDING)
                .values(status=OUTBOX_STATUS_PROCESSING, updated_at=datetime.utcnow())
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0
        except Exception as e:
            logger.error("Failed to mark record %d as processing: %s", record_id, e)
            raise OutboxRepositoryError(f"Failed to mark as processing: {e}") from e

    async def mark_as_published(self, record_id: int, kafka_offset: int | None = None) -> None:
        """Alias untuk mark_as_sent (digunakan oleh relay)."""
        await self.mark_as_sent(UUID(int=record_id) if isinstance(record_id, int) else record_id)

    async def mark_as_dead_letter(self, record_id: int, error_message: str) -> None:
        """Pindahkan event ke dead letter (digunakan oleh relay)."""
        try:
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == record_id)
                .values(
                    status=OUTBOX_STATUS_DEAD_LETTER,
                    last_error=error_message,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()
            await trigger_alert(
                title="Event Moved to Dead Letter Queue",
                message=f"Event {record_id} moved to DLQ after max retries. Error: {error_message[:200]}",
                severity="warning",
                source="OutboxRepository",
            )
        except Exception as e:
            logger.error("Failed to move record %d to dead letter: %s", record_id, e)
            raise OutboxRepositoryError(f"Failed to move to DLQ: {e}") from e

    async def delete_processed_records(self, older_than_hours: int = 168) -> int:
        """
        Hapus record yang sudah terkirim dan lebih tua dari older_than_hours.
        LOCKING: SELECT FOR UPDATE untuk mengunci baris yang akan dihapus.
        """
        cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
        try:
            session = self.session

            # 1. Select IDs with lock
            stmt_select = (
                select(OutboxTable.id)
                .where(
                    OutboxTable.status == OUTBOX_STATUS_SENT,
                    OutboxTable.sent_at < cutoff,
                    OutboxTable.deleted_at.is_(None),
                )
                .with_for_update()
            )
            result = await session.execute(stmt_select)
            ids = [row[0] for row in result.all()]

            if not ids:
                return 0

            # 2. Delete by IDs
            stmt_delete = delete(OutboxTable).where(OutboxTable.id.in_(ids))
            delete_result = await session.execute(stmt_delete)
            await session.flush()

            return delete_result.rowcount
        except Exception as e:
            logger.error("Failed to delete processed records: %s", e)
            raise OutboxRepositoryError(f"Failed to delete processed records: {e}") from e

    # ========================================================================
    # LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_event(
        self,
        event: Any,
        event_type: str,
        aggregate_id: UUID,
        aggregate_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Legacy method untuk menyimpan event (digunakan internal)."""
        event_id = uuid4()
        payload = self._serialize_event(event)
        metadata_json = json.dumps(metadata or {})
        outbox_record = OutboxTable(
            id=event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            metadata=metadata_json,
            status=OUTBOX_STATUS_PENDING,
            retry_count=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(outbox_record)
        await self.session.flush()
        return event_id

    async def get_checkpoint(self, relay_id: str) -> datetime | None:
        stmt = select(OutboxCheckpointTable).where(OutboxCheckpointTable.relay_id == relay_id)
        result = await self.session.execute(stmt)
        checkpoint = result.scalar_one_or_none()
        return checkpoint.last_processed_at if checkpoint else None

    async def update_checkpoint(self, relay_id: str, last_processed_at: datetime) -> None:
        """
        Update checkpoint dengan pessimistic locking.
        LOCKING: SELECT FOR UPDATE untuk mengunci baris checkpoint.
        """
        session = self.session
        try:
            # 1. Lock the row (if exists) with SELECT FOR UPDATE
            stmt_select = select(OutboxCheckpointTable).where(
                OutboxCheckpointTable.relay_id == relay_id
            ).with_for_update()
            result = await session.execute(stmt_select)
            existing = result.scalar_one_or_none()

            if existing:
                stmt = (
                    update(OutboxCheckpointTable)
                    .where(OutboxCheckpointTable.relay_id == relay_id)
                    .values(last_processed_at=last_processed_at, updated_at=datetime.utcnow())
                )
            else:
                # Insert new checkpoint (no lock needed for insert, but we could use a lock on a dummy row)
                stmt = insert(OutboxCheckpointTable).values(
                    id=uuid4(),
                    relay_id=relay_id,
                    last_processed_at=last_processed_at,
                    created_at=datetime.utcnow(),
                )
            await session.execute(stmt)
            await session.flush()
        except Exception as e:
            logger.error("Failed to update checkpoint: %s", e)
            raise OutboxRepositoryError(f"Failed to update checkpoint: {e}") from e

    # ========================================================================
    # GET OUTBOX STATS � DIPERBAIKI (tanpa query dalam loop)
    # ========================================================================

    async def get_outbox_stats(self) -> dict[str, int]:
        """
        Mengambil statistik jumlah pesan per status menggunakan satu query agregasi.
        """
        try:
            # Satu query dengan GROUP BY untuk semua status
            stmt = (
                select(OutboxTable.status, func.count())
                .where(OutboxTable.deleted_at.is_(None))
                .group_by(OutboxTable.status)
            )
            result = await self.session.execute(stmt)
            rows = result.all()

            # Inisialisasi semua status dengan 0
            stats = {
                OUTBOX_STATUS_PENDING: 0,
                OUTBOX_STATUS_PROCESSING: 0,
                OUTBOX_STATUS_SENT: 0,
                OUTBOX_STATUS_FAILED: 0,
                OUTBOX_STATUS_DEAD_LETTER: 0,
            }
            # Isi dari hasil query
            for status, count in rows:
                if status in stats:
                    stats[status] = count
            return stats
        except Exception as e:
            logger.error("Failed to get outbox stats: %s", e)
            raise OutboxRepositoryError(f"Failed to get stats: {e}") from e

    async def retry_dead_letter_event(self, event_id: UUID) -> bool:
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id == event_id, OutboxTable.status == OUTBOX_STATUS_DEAD_LETTER)
            .values(
                status=OUTBOX_STATUS_PENDING,
                retry_count=0,
                last_error=None,
                next_retry_at=None,
                updated_at=datetime.utcnow(),
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0

    async def publish_event(self, event_id: UUID, topic: str | None = None) -> bool:
        event = await self.get_event_by_id(event_id)
        if not event:
            raise OutboxEventNotFoundError(f"Event {event_id} not found")
        if event.status != OUTBOX_STATUS_PROCESSING:
            logger.warning("Event %s has status %s, cannot publish", event_id, event.status)
            return False
        producer = await self._get_kafka_producer()
        topic_name = topic or event.event_type.replace(".", "-").lower()
        success = await producer.send(
            topic=topic_name,
            key=str(event.aggregate_id),
            value=event.payload,
            headers={
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "event_id": str(event.id),
            },
        )
        if success:
            await self.mark_as_sent(event_id)
            logger.info("Event %s published to %s", event_id, topic_name)
            return True
        else:
            await self.mark_as_failed(event_id, "Producer send returned False")
            return False

    async def get_event_by_id(self, event_id: UUID) -> OutboxTable | None:
        stmt = select(OutboxTable).where(OutboxTable.id == event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


# ============================================================================
# FACTORY
# ============================================================================


async def create_outbox_repository() -> SQLAlchemyOutboxRepository:
    """Factory untuk membuat repository dengan session baru."""
    from infrastructure.database.session_factory_sqlalchemy import get_async_session

    session = await get_async_session()
    repo = SQLAlchemyOutboxRepository(session=session)
    return repo


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "OUTBOX_STATUS_DEAD_LETTER",
    "OUTBOX_STATUS_FAILED",
    "OUTBOX_STATUS_PENDING",
    "OUTBOX_STATUS_PROCESSING",
    "OUTBOX_STATUS_SENT",
    "OutboxEventNotFoundError",
    "OutboxPublishError",
    "OutboxRepositoryError",
    "SQLAlchemyOutboxRepository",
    "create_outbox_repository",
]