#!/usr/bin/env python3
"""
Module: outbox_table.py
Layer: Infrastructure (Outbox)
Responsibility: Model SQLAlchemy untuk tabel transactional outbox.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import JSON, Column, DateTime, Enum, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class OutboxStatus(str, PyEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(255), nullable=False)
    aggregate_id = Column(String(255), nullable=True)
    aggregate_type = Column(String(100), nullable=True)
    payload = Column(JSON, nullable=False)
    status = Column(Enum(OutboxStatus), nullable=False, default=OutboxStatus.PENDING)
    retry_count = Column(Integer, default=0)
    last_error = Column(String(1000), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<OutboxMessage(id={self.id}, event_type={self.event_type}, status={self.status})>"
