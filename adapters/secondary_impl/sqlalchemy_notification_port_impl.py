#!/usr/bin/env python3
"""
Module: sqlalchemy_notification_port_impl.py
Adapter for NotificationChannel (from notification_port)
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)

Base = declarative_base()


class NotificationLogTable(Base):
    __tablename__ = "notification_logs"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(String(50), nullable=False)
    recipient = Column(String(200), nullable=False)
    subject = Column(String(200), nullable=True)
    body = Column(Text, nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    status = Column(String(50), nullable=False, default="sent")


class SQLAlchemyNotificationChannelAdapter:
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def send(self, channel: str, message: dict[str, Any]) -> dict[str, Any]:
        session = await self._get_session()
        log = NotificationLogTable(
            channel=channel,
            recipient=message.get("to", "unknown"),
            subject=message.get("subject", ""),
            body=message.get("body", ""),
            status="sent",
        )
        session.add(log)
        await session.flush()
        return {
            "id": str(log.id),
            "channel": log.channel,
            "recipient": log.recipient,
            "sent_at": log.sent_at.isoformat(),
            "status": log.status,
        }

    async def get_logs(self, channel: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        session = await self._get_session()
        stmt = select(NotificationLogTable)
        if channel:
            stmt = stmt.where(NotificationLogTable.channel == channel)
        stmt = stmt.order_by(NotificationLogTable.sent_at.desc()).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(row.id),
                "channel": row.channel,
                "recipient": row.recipient,
                "subject": row.subject,
                "body": row.body[:200],
                "sent_at": row.sent_at.isoformat(),
                "status": row.status,
            }
            for row in rows
        ]


__all__ = ["NotificationLogTable", "SQLAlchemyNotificationChannelAdapter"]