#!/usr/bin/env python3
"""
Module: outbox_relay_service.py
Layer: Infrastructure / Outbox
Responsibility: Service untuk memproses dan mengirim pesan outbox ke message broker.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, sessionmaker

from infrastructure.outbox.outbox_table import OutboxMessage, OutboxStatus

logger = logging.getLogger(__name__)


class OutboxRelayService:
    """
    Service untuk membaca pesan outbox dengan status PENDING dan mengirimkannya
    ke message broker (Kafka). Untuk keperluan test, kita cukup mengubah status
    menjadi PUBLISHED (tanpa benar-benar mengirim ke broker).
    """

    def __init__(self, session_factory: sessionmaker, kafka_broker: str | None = None):
        self.session_factory = session_factory
        self.kafka_broker = kafka_broker

    def process_pending_messages(self, batch_size: int = 100) -> int:
        """
        Memproses pesan outbox yang masih PENDING.
        Returns jumlah pesan yang berhasil diproses.
        """
        session: Session = self.session_factory()
        try:
            messages = (
                session.query(OutboxMessage)
                .filter_by(status=OutboxStatus.PENDING)
                .limit(batch_size)
                .all()
            )
            count = 0
            for msg in messages:
                try:
                    # Di sini nantinya akan ada logika publish ke Kafka
                    # Untuk test, kita hanya ubah status menjadi PUBLISHED
                    # (asumsikan sukses)
                    msg.status = OutboxStatus.PUBLISHED
                    session.add(msg)
                    count += 1
                except Exception as e:
                    logger.exception(f"Failed to publish message {msg.id}: {e}")
                    msg.status = OutboxStatus.FAILED
                    msg.last_error = str(e)
                    session.add(msg)
            session.commit()
            return count
        finally:
            session.close()
